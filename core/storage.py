# storage.py
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

# ==============================
# CONFIG
# ==============================

USE_FIREBASE = True  # <-- single switch

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"          # cache only
BACKUPS_DIR = BASE_DIR / "backups"    # cache only
AVATARS_DIR = BASE_DIR / "avatars"    # cache only

# ==============================
# FIREBASE INIT (lazy)
# ==============================

_fb = {
    "app": None,
    "db": None,
    "bucket": None,
}


def _fb_init():
    if _fb["app"] is not None:
        return

    import firebase_admin
    from firebase_admin import credentials, firestore, storage

    cred = credentials.ApplicationDefault()
    _fb["app"] = firebase_admin.initialize_app(
        cred,
        {"storageBucket": "<YOUR_BUCKET_NAME>.appspot.com"},
    )
    _fb["db"] = firestore.client()
    _fb["bucket"] = storage.bucket()


# ==============================
# UTILS
# ==============================

def ensure_store() -> None:
    """Local directories are cache-only when Firebase is enabled."""
    if USE_FIREBASE:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)


def _df_dates_to_iso(df: pd.DataFrame, name: str) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out


def _path_to_collection(path: Path) -> Optional[str]:
    """Maps CSV filename → Firestore collection"""
    return path.stem.lower().replace("-", "_")


# ==============================
# FIRESTORE HELPERS
# ==============================

def _firestore_fetch_collection(collection: str) -> pd.DataFrame:
    _fb_init()
    docs = _fb["db"].collection(collection).stream()
    rows = [d.to_dict() for d in docs]
    return pd.DataFrame(rows)


def _firestore_write_collection(collection: str, df: pd.DataFrame) -> None:
    _fb_init()
    col_ref = _fb["db"].collection(collection)

    # destructive replace (source of truth)
    for doc in col_ref.stream():
        doc.reference.delete()

    for _, row in df.iterrows():
        col_ref.add(row.to_dict())


# ==============================
# PUBLIC API
# ==============================

def load_df(path: Path) -> pd.DataFrame:
    name = path.name.lower()

    if USE_FIREBASE:
        coll = _path_to_collection(path)
        try:
            df = _firestore_fetch_collection(coll)
            return df if not df.empty else pd.DataFrame()
        except Exception:
            pass  # fallback to cache

    # ---- CACHE FALLBACK ----
    if path.exists():
        return pd.read_csv(path)

    return pd.DataFrame()


def save_df(df: pd.DataFrame, path: Path) -> None:
    name = path.name.lower()
    to_save = _df_dates_to_iso(df, name)

    if USE_FIREBASE:
        coll = _path_to_collection(path)
        _firestore_write_collection(coll, to_save)

    # ---- CACHE WRITE (NON-AUTHORITATIVE) ----
    if not USE_FIREBASE:
        tmp = path.with_suffix(".tmp")
        to_save.to_csv(tmp, index=False, encoding="utf-8")
        for _ in range(5):
            try:
                tmp.replace(path)
                break
            except PermissionError:
                time.sleep(0.2)


# ==============================
# SETTINGS (JSON → FIRESTORE)
# ==============================

DEFAULT_SETTINGS_PATH = DATA_DIR / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    path = path or DEFAULT_SETTINGS_PATH

    if USE_FIREBASE:
        _fb_init()
        doc = _fb["db"].collection("settings").document("app").get()
        return doc.to_dict() or {}

    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    return {}


def save_settings(settings: dict, path: Path | None = None) -> None:
    path = path or DEFAULT_SETTINGS_PATH

    if USE_FIREBASE:
        _fb_init()
        _fb["db"].collection("settings").document("app").set(settings)
        return

    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# ==============================
# BACKUPS → FIREBASE STORAGE
# ==============================

def zip_backup() -> Optional[str]:
    if not USE_FIREBASE:
        return None

    _fb_init()

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.txt", "Firestore is the source of truth.")

    mem.seek(0)
    name = f"backup_{int(time.time())}.zip"
    blob = _fb["bucket"].blob(f"backups/{name}")
    blob.upload_from_file(mem, content_type="application/zip")

    return blob.public_url


# ==============================
# AVATARS → FIREBASE STORAGE
# ==============================

def upload_avatar(user_id: str, file_bytes: bytes) -> str:
    _fb_init()
    blob = _fb["bucket"].blob(f"avatars/{user_id}.png")
    blob.upload_from_string(file_bytes, content_type="image/png")
    return blob.public_url
