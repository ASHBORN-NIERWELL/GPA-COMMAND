# core/storage.py
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from typing import Optional, Dict

import pandas as pd
import streamlit as st

from .config import (
    DEFAULT_SETTINGS, DATA_DIR, BACKUPS_DIR, LEGACY_DATA_DIR,
    SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON, USERS_CSV,
    INITIAL_SUBJECTS, AVATARS_DIR,
)

# -------------------------------------------------------------
# Firebase usage toggle
# -------------------------------------------------------------
# We auto-enable Firebase if Streamlit Secrets contains a [firebase]
# section OR if the USE_FIREBASE env var is set to 1/true/yes.
USE_FIREBASE = (
    ("firebase" in st.secrets) or
    (str(os.getenv("USE_FIREBASE", "0")).lower() in {"1", "true", "yes"})
)

_FB_INIT_DONE = False
_fb: Dict[str, object] = {
    "admin": None,      # firebase_admin module
    "credentials": None,# firebase_admin.credentials.Certificate
    "firestore": None,  # firebase_admin.firestore module
    "client": None,     # firestore.Client
    "storage": None,    # firebase_admin.storage module
    "bucket": None,     # storage.Bucket (optional)
}


def _fb_log(msg: str) -> None:
    # Quiet helper for debugging; uncomment to surface logs in UI
    # st.write(f"[firebase] {msg}")
    pass


# -------------------------------------------------------------
# Firebase credentials loading (Streamlit Secrets first)
# -------------------------------------------------------------

def _service_account_from_secrets() -> Optional[dict]:
    """Return a service-account dict from st.secrets if present, else None."""
    if "firebase" not in st.secrets:
        return None
    fb = st.secrets["firebase"]

    # Option B: raw JSON as a string under key `service_account`
    if "service_account" in fb:
        sa = fb["service_account"]
        return json.loads(sa) if isinstance(sa, str) else dict(sa)

    # Option A: field-by-field in TOML
    required = [
        "project_id", "private_key_id", "private_key", "client_email",
        "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url",
    ]
    for k in required:
        if k not in fb:
            raise RuntimeError(f"[firebase] Missing field in secrets: {k}")

    return {
        "type": fb.get("type", "service_account"),
        "project_id": fb["project_id"],
        "private_key_id": fb["private_key_id"],
        # Convert escaped newlines to real newlines
        "private_key": str(fb["private_key"]).replace("\\n", "\n"),
        "client_email": fb["client_email"],
        "client_id": fb["client_id"],
        "auth_uri": fb["auth_uri"],
        "token_uri": fb["token_uri"],
        "auth_provider_x509_cert_url": fb["auth_provider_x509_cert_url"],
        "client_x509_cert_url": fb["client_x509_cert_url"],
    }


def _bucket_from_secrets() -> str:
    if "firebase" in st.secrets:
        return str(st.secrets["firebase"].get("storage_bucket", "")).strip()
    return ""


def _fb_init() -> None:
    """Lazy-init Firebase Admin SDK (idempotent). Prefers Streamlit Secrets, then env vars."""
    global _FB_INIT_DONE
    if _FB_INIT_DONE or not USE_FIREBASE:
        return

    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials as _credentials  # type: ignore
        from firebase_admin import firestore as _firestore  # type: ignore
        from firebase_admin import storage as _storage  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "firebase_admin is not installed. Add it to requirements.txt: 'firebase-admin'"
        ) from e

    # Prefer secrets
    sa = _service_account_from_secrets()
    bucket_name = _bucket_from_secrets()
    project_id = (sa or {}).get("project_id", "")

    # Env fallbacks
    if sa is None:
        sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        sa_path = os.getenv("FIREBASE_CREDENTIALS", "").strip()
        if sa_json:
            sa = json.loads(sa_json)
            project_id = sa.get("project_id", project_id)
        elif sa_path and Path(sa_path).exists():
            sa = json.loads(Path(sa_path).read_text(encoding="utf-8"))
            project_id = sa.get("project_id", project_id)
        else:
            raise RuntimeError(
                "No Firebase credentials found. Add [firebase] to Streamlit Secrets or set FIREBASE_SERVICE_ACCOUNT_JSON/FIREBASE_CREDENTIALS."
            )
        bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", bucket_name)

    cred = _credentials.Certificate(sa)

    if not firebase_admin._apps:  # type: ignore
        opts: Dict[str, str] = {}
        if bucket_name:
            opts["storageBucket"] = bucket_name
        if project_id:
            opts["projectId"] = project_id
        firebase_admin.initialize_app(cred, opts)  # type: ignore

    # Stash handles
    _fb["admin"] = firebase_admin
    _fb["credentials"] = cred
    _fb["firestore"] = _firestore
    _fb["client"] = _firestore.client(project=project_id) if project_id else _firestore.client()
    _fb["storage"] = _storage
    _fb["bucket"] = _storage.bucket() if bucket_name else None

    _FB_INIT_DONE = True
    _fb_log("Firebase initialized")


# -------------------------------------------------------------
# Local filesystem preparations
# -------------------------------------------------------------

def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # one-time migration from ./data
    try:
        if LEGACY_DATA_DIR.exists() and any(LEGACY_DATA_DIR.iterdir()):
            for fname in ["subjects.csv", "logs.csv", "tests.csv", "settings.json", "users.csv"]:
                src, dst = LEGACY_DATA_DIR / fname, DATA_DIR / fname
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
    except Exception:
        pass

    # settings.json
    if not SETTINGS_JSON.exists():
        SETTINGS_JSON.write_text(json.dumps(DEFAULT_SETTINGS, indent=2), encoding="utf-8")

    # users.csv (ensure avatar_path exists)
    if not USERS_CSV.exists():
        pd.DataFrame(
            columns=["id", "username", "password_hash", "created_at", "avatar_path"]
        ).to_csv(USERS_CSV, index=False, encoding="utf-8")
    else:
        try:
            df = pd.read_csv(USERS_CSV)
            changed = False
            if "avatar_path" not in df.columns:
                df["avatar_path"] = ""
                changed = True
            if changed:
                df.to_csv(USERS_CSV, index=False, encoding="utf-8")
        except Exception:
            pass

    # subjects.csv
    if not SUBJECTS_CSV.exists():
        df = pd.DataFrame(INITIAL_SUBJECTS)
        df["user_id"] = ""
        df.to_csv(SUBJECTS_CSV, index=False, encoding="utf-8")
    else:
        try:
            df = pd.read_csv(SUBJECTS_CSV)
            changed = False
            if "exam_date" not in df.columns:
                df["exam_date"] = DEFAULT_SETTINGS.get("default_exam_date")
                changed = True
            if "user_id" not in df.columns:
                df["user_id"] = ""
                changed = True
            if changed:
                df.to_csv(SUBJECTS_CSV, index=False, encoding="utf-8")
        except Exception:
            pass

    # logs/tests — backfill missing columns if needed
    needed_logs  = ["id", "date", "subject_id", "hours", "task", "score", "notes", "user_id"]
    needed_tests = ["id", "date", "subject_id", "score", "difficulty", "notes", "user_id"]
    for p, needed in [(LOGS_CSV, needed_logs), (TESTS_CSV, needed_tests)]:
        if not p.exists():
            pd.DataFrame(columns=needed).to_csv(p, index=False, encoding="utf-8")
        else:
            try:
                df = pd.read_csv(p)
                changed = False
                for col in needed:
                    if col not in df.columns:
                        df[col] = "" if col in ["id", "date", "subject_id", "task", "notes", "user_id"] else pd.NA
                        changed = True
                if changed:
                    df.to_csv(p, index=False, encoding="utf-8")
            except Exception:
                pass


def zip_backup() -> Path:
    """Create a timestamped zip of all CSV/JSON files."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath = BACKUPS_DIR / f"backup_{ts}.zip"
    with ZipFile(zpath, "w", ZIP_DEFLATED) as zf:
        for p in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON, USERS_CSV]:
            if p.exists():
                zf.write(p, arcname=p.name)
    return zpath


# -------------------------------------------------------------
# Mapping helpers (filename <-> collection)
# -------------------------------------------------------------
_COLLECTION_MAP: Dict[str, str] = {
    "subjects.csv": "subjects",
    "logs.csv": "logs",
    "tests.csv": "tests",
    "users.csv": "users",
    # settings.json handled separately as a single doc
}


def _path_to_collection(path: Path) -> Optional[str]:
    return _COLLECTION_MAP.get(path.name.lower())


# -------------------------------------------------------------
# Firebase load/save helpers
# -------------------------------------------------------------

def _df_dates_to_iso(df: pd.DataFrame, file_name_lower: str) -> pd.DataFrame:
    out = df.copy()
    try:
        if file_name_lower in {"logs.csv", "tests.csv"} and "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        if file_name_lower == "subjects.csv" and "exam_date" in out.columns:
            out["exam_date"] = pd.to_datetime(out["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return out


def _firestore_fetch_collection(coll_name: str) -> pd.DataFrame:
    _fb_init()
    client = _fb["client"]
    assert client is not None, "Firestore client unavailable"
    docs = client.collection(coll_name).stream()  # type: ignore
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        if "id" not in data:
            data["id"] = d.id
        rows.append(data)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Parse dates for UI use
    if coll_name in {"logs", "tests"} and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if coll_name == "subjects" and "exam_date" in df.columns:
        df["exam_date"] = pd.to_datetime(df["exam_date"], errors="coerce")
    return df


def _firestore_write_collection(coll_name: str, df: pd.DataFrame) -> None:
    """Upsert whole dataframe into a collection by 'id' (or autogenerated if missing)."""
    _fb_init()
    client = _fb["client"]
    assert client is not None, "Firestore client unavailable"
    col = client.collection(coll_name)  # type: ignore

    out = df.copy()
    if "id" not in out.columns:
        out["id"] = ""
    out = _df_dates_to_iso(out, f"{coll_name}.csv")

    batch = client.batch()  # type: ignore
    CHUNK = 400  # below Firestore's 500 op limit
    for i in range(0, len(out), CHUNK):
        chunk = out.iloc[i:i+CHUNK]
        for _, r in chunk.iterrows():
            data = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.to_dict().items()}
            rid = str(data.get("id") or "").strip()
            ref = col.document(rid) if rid else col.document()
            if not rid:
                data["id"] = ref.id
            batch.set(ref, data)
        batch.commit()
        batch = client.batch()


def _firestore_load_settings() -> dict:
    _fb_init()
    client = _fb["client"]
    assert client is not None, "Firestore client unavailable"
    ref = client.collection("app_settings").document("default")  # type: ignore
    snap = ref.get()
    if not snap.exists:
        ref.set(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    data = snap.to_dict() or {}
    return {**DEFAULT_SETTINGS, **data}


def _firestore_save_settings(s: dict) -> None:
    _fb_init()
    client = _fb["client"]
    assert client is not None, "Firestore client unavailable"
    ref = client.collection("app_settings").document("default")  # type: ignore
    ref.set(dict(s))


# -------------------------------------------------------------
# Public load/save API
# -------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_df(path: Path) -> pd.DataFrame:
    """
    Cached loader returning a pandas DataFrame.
    If Firebase is enabled and the path maps to a collection, read from Firestore;
    otherwise read from the local CSV.
    """
    name = path.name.lower()

    if USE_FIREBASE:
        coll = _path_to_collection(path)
        if coll:
            try:
                df = _firestore_fetch_collection(coll)
                # Write local cache copy (normalized) for convenience
                try:
                    df_cache = _df_dates_to_iso(df, name)
                    df_cache.to_csv(path, index=False, encoding="utf-8")
                except Exception:
                    pass
                # Ensure parsed dates for UI
                if name in {"logs.csv", "tests.csv"} and "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                if name == "subjects.csv" and "exam_date" in df.columns:
                    df["exam_date"] = pd.to_datetime(df["exam_date"], errors="coerce")
                return df
            except Exception as e:
                _fb_log(f"Firestore load failure for {coll}: {e}")
                # fall back to local

    # Local CSV loader (original behavior)
    try:
        if name in {"logs.csv", "tests.csv"}:
            return pd.read_csv(path, parse_dates=["date"], dayfirst=False, encoding="utf-8")
        if name == "subjects.csv":
            return pd.read_csv(path, parse_dates=["exam_date"], dayfirst=False, encoding="utf-8")
        return pd.read_csv(path, encoding="utf-8")
    except Exception:
        return pd.read_csv(path, engine="python", encoding_errors="ignore")


def save_df(df: pd.DataFrame, path: Path) -> None:
    """Atomic write to local CSV + optional Firestore upsert (when enabled)."""
    name = path.name.lower()

    # Always write local CSV (acts as cache/backup)
    tmp = path.with_suffix(path.suffix + ".tmp")
    to_save = _df_dates_to_iso(df, name)
    to_save.to_csv(tmp, index=False, encoding="utf-8")
    for _ in range(5):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            time.sleep(0.2)

    # Firestore sync (best-effort)
    if USE_FIREBASE:
        coll = _path_to_collection(path)
        if coll:
            try:
                _firestore_write_collection(coll, to_save)
            except Exception as e:
                _fb_log(f"Firestore save failure for {coll}: {e}")

    load_df.clear()  # invalidate cache


def load_settings() -> dict:
    """
    Load app-wide settings. When Firebase is enabled, fetch from
    Firestore (app_settings/default) with default backfill; otherwise
    read from local settings.json.
    """
    if USE_FIREBASE:
        try:
            s = _firestore_load_settings()
            try:
                SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")
            except Exception:
                pass
            return s
        except Exception as e:
            _fb_log(f"Firestore load_settings failed: {e}")

    # Local JSON
    try:
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        s = DEFAULT_SETTINGS.copy()
    # Backfill new defaults
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s


def save_settings(s: dict) -> None:
    """Save settings to local JSON and Firestore (if enabled)."""
    SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")

    if USE_FIREBASE:
        try:
            _firestore_save_settings(s)
        except Exception as e:
            _fb_log(f"Firestore save_settings failed: {e}")
