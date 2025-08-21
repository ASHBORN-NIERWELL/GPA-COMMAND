# core/storage.py
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from typing import Optional, Tuple, Dict

import pandas as pd
import streamlit as st

from .config import (
    DEFAULT_SETTINGS, DATA_DIR, BACKUPS_DIR, LEGACY_DATA_DIR,
    SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON, USERS_CSV,
    INITIAL_SUBJECTS, AVATARS_DIR,
)
import firebase_admin
from firebase_admin import credentials

from core.config import FIREBASE_CRED_PATH

if not firebase_admin._apps:
    cred = credentials.Certificate(str(FIREBASE_CRED_PATH))
    firebase_admin.initialize_app(cred, {
        "storageBucket": "nierwell-gpa-system.appspot.com"
    })


# ===========================
# Firebase toggle & settings
# ===========================
# Turn on by setting environment variable:
#   USE_FIREBASE=1
# Required env when on:
#   FIREBASE_PROJECT_ID=your-project-id
#   FIREBASE_CREDENTIALS=/absolute/path/to/service-account.json
# Optional:
#   FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
USE_FIREBASE = str(os.getenv("USE_FIREBASE", "0")).lower() in {"1", "true", "yes"}

_FB_INIT_DONE = False
_fb = {
    "admin": None,
    "credentials": None,
    "firestore": None,   # module
    "client": None,      # firestore.Client
    "storage": None,     # module
    "bucket": None,      # Bucket (optional)
}

def _fb_log(msg: str) -> None:
    # quiet logging helper
    pass

def _fb_init() -> None:
    """Lazy init firebase_admin (idempotent)."""
    global _FB_INIT_DONE
    if _FB_INIT_DONE or not USE_FIREBASE:
        return

    creds_path = os.getenv("FIREBASE_CREDENTIALS", "").strip()
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()

    if not creds_path or not Path(creds_path).exists():
        raise RuntimeError(
            "FIREBASE_CREDENTIALS not set or file not found. "
            "Set FIREBASE_CREDENTIALS to your service-account JSON path."
        )
    if not project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID not set.")

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "firebase_admin is not installed. Run: pip install firebase-admin"
        ) from e

    cred = credentials.Certificate(creds_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"projectId": project_id, **({"storageBucket": bucket_name} if bucket_name else {})})

    _fb["admin"] = firebase_admin
    _fb["credentials"] = cred
    _fb["firestore"] = firestore
    _fb["client"] = firestore.client(project=project_id)
    _fb["storage"] = storage
    _fb["bucket"] = storage.bucket() if bucket_name else None

    _FB_INIT_DONE = True
    _fb_log("Firebase initialized")

# ------------------------------
# Local filesystem preparations
# ------------------------------
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
                df["exam_date"] = DEFAULT_SETTINGS["default_exam_date"]; changed = True
            if "user_id" not in df.columns:
                df["user_id"] = ""; changed = True
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

# ===========================
# Mapping helpers
# ===========================
# Map local filenames to Firestore collections
_COLLECTION_MAP: Dict[str, str] = {
    "subjects.csv": "subjects",
    "logs.csv": "logs",
    "tests.csv": "tests",
    "users.csv": "users",
    # settings.json handled separately as a single doc
}

def _path_to_collection(path: Path) -> Optional[str]:
    return _COLLECTION_MAP.get(path.name.lower())

# ===========================
# Firebase load/save helpers
# ===========================
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
    docs = client.collection(coll_name).stream()
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        # Prefer stable primary key name 'id'
        if "id" not in data:
            data["id"] = d.id
        rows.append(data)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)

    # Ensure date-like columns are parsed for UI logic (we'll normalize later)
    if coll_name in {"logs", "tests"} and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if coll_name == "subjects" and "exam_date" in df.columns:
        df["exam_date"] = pd.to_datetime(df["exam_date"], errors="coerce")
    return df

def _firestore_write_collection(coll_name: str, df: pd.DataFrame) -> None:
    """Upsert whole dataframe into a collection by 'id' (or autogenerated if missing)."""
    _fb_init()
    client = _fb["client"]
    col = client.collection(coll_name)
    # Normalize ID column
    out = df.copy()
    if "id" not in out.columns:
        out["id"] = ""
    # Convert date columns to ISO strings to avoid Timestamp serialization headaches
    out = _df_dates_to_iso(out, f"{coll_name}.csv")

    batch = client.batch()
    # Write in chunks of 400 to stay below Firestore batch size limit (500 ops)
    CHUNK = 400
    for i in range(0, len(out), CHUNK):
        chunk = out.iloc[i:i+CHUNK]
        for _, r in chunk.iterrows():
            data = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.to_dict().items()}
            rid = str(data.get("id") or "").strip()
            ref = col.document(rid) if rid else col.document()
            if not rid:
                # Write back generated id into data for consistency
                data["id"] = ref.id
            batch.set(ref, data)
        batch.commit()
        batch = client.batch()

def _firestore_load_settings() -> dict:
    _fb_init()
    client = _fb["client"]
    # Single document for app settings
    ref = client.collection("app_settings").document("default")
    snap = ref.get()
    if not snap.exists:
        # initialize with defaults
        ref.set(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    data = snap.to_dict() or {}
    # backfill new defaults
    s = {**DEFAULT_SETTINGS, **data}
    return s

def _firestore_save_settings(s: dict) -> None:
    _fb_init()
    client = _fb["client"]
    ref = client.collection("app_settings").document("default")
    # Simple overwrite; callers pass a fully merged dict
    ref.set(dict(s))

# ===========================
# Public load/save API
# ===========================
@st.cache_data(show_spinner=False)
def load_df(path: Path) -> pd.DataFrame:
    """
    Cached loader returning a pandas DataFrame.
    If USE_FIREBASE=1 and the path maps to a Firestore collection,
    it reads from Firestore; otherwise it reads the local CSV.
    """
    name = path.name.lower()

    # ---- Firebase path
    if USE_FIREBASE:
        coll = _path_to_collection(path)
        if coll:
            try:
                df = _firestore_fetch_collection(coll)
                # Keep local cache for offline/backup convenience
                try:
                    # Normalize date fields before writing to CSV cache
                    df_cache = _df_dates_to_iso(df, name)
                    df_cache.to_csv(path, index=False, encoding="utf-8")
                except Exception:
                    pass
                # For UI, parse dates like original code
                if name in {"logs.csv", "tests.csv"} and "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                if name == "subjects.csv" and "exam_date" in df.columns:
                    df["exam_date"] = pd.to_datetime(df["exam_date"], errors="coerce")
                return df
            except Exception as e:
                # If Firestore fails, fall back to local CSV
                _fb_log(f"Firestore load failure for {coll}: {e}")

    # ---- Original CSV loader
    try:
        if name in {"logs.csv", "tests.csv"}:
            return pd.read_csv(path, parse_dates=["date"], dayfirst=False, encoding="utf-8")
        if name == "subjects.csv":
            return pd.read_csv(path, parse_dates=["exam_date"], dayfirst=False, encoding="utf-8")
        return pd.read_csv(path, encoding="utf-8")
    except Exception:
        # fallback if pandas chokes on encoding/engine
        return pd.read_csv(path, engine="python", encoding_errors="ignore")

def save_df(df: pd.DataFrame, path: Path) -> None:
    """
    Atomic write to local CSV + optional Firestore upsert (when enabled).
    Busts load_df cache after saving.
    """
    name = path.name.lower()
    # Always write local CSV (acts as cache/backup)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Ensure date columns are serializable
    to_save = _df_dates_to_iso(df, name)
    to_save.to_csv(tmp, index=False, encoding="utf-8")
    for _ in range(5):
        try:
            tmp.replace(path)  # atomic on most OSes
            break
        except PermissionError:
            time.sleep(0.2)

    # Write to Firestore if enabled and path maps to a collection
    if USE_FIREBASE:
        coll = _path_to_collection(path)
        if coll:
            try:
                _firestore_write_collection(coll, to_save)
            except Exception as e:
                _fb_log(f"Firestore save failure for {coll}: {e}")

    load_df.clear()  # invalidate cache for next read

def load_settings() -> dict:
    """
    Load app-wide settings.
    When USE_FIREBASE=1, reads from Firestore doc app_settings/default.
    Otherwise, from local settings.json (with default backfill).
    """
    if USE_FIREBASE:
        try:
            s = _firestore_load_settings()
            # also refresh local JSON cache for convenience
            try:
                SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")
            except Exception:
                pass
            return s
        except Exception as e:
            _fb_log(f"Firestore load_settings failed: {e}")

    # local JSON
    try:
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        s = DEFAULT_SETTINGS.copy()
    # backfill any new defaults
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s

def save_settings(s: dict) -> None:
    """
    Save app-wide settings to local JSON and, if enabled, to Firestore.
    """
    # Write local JSON
    SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")

    # Firestore (best effort)
    if USE_FIREBASE:
        try:
            _firestore_save_settings(s)
        except Exception as e:
            _fb_log(f"Firestore save_settings failed: {e}")
