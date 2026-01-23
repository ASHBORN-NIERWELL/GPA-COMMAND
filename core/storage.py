from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import streamlit as st

# ============================================================
# GLOBALS
# ============================================================

USE_FIREBASE = True  # Firebase is mandatory

_FB_INIT_DONE = False
_fb: Dict[str, Optional[object]] = {
    "admin": None,
    "firestore": None,
    "client": None,
    "storage": None,
    "bucket": None,
}


# ============================================================
# INTERNAL LOGGING
# ============================================================

def _fb_log(msg: str) -> None:
    print(f"[storage] {msg}")


# ============================================================
# FIREBASE INITIALIZATION (SINGLE SOURCE OF TRUTH)
# ============================================================

def _fb_init() -> None:
    """
    Initialize Firebase Admin SDK exactly once.
    Assumes app.py already validated secrets and env vars.
    """
    global _FB_INIT_DONE
    if _FB_INIT_DONE:
        return

    import firebase_admin
    from firebase_admin import credentials, firestore, storage

    cred_path = os.getenv("FIREBASE_CREDENTIALS")
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET")

    if not cred_path or not Path(cred_path).exists():
        raise RuntimeError("FIREBASE_CREDENTIALS missing or invalid.")

    sa = json.loads(Path(cred_path).read_text(encoding="utf-8"))
    cred = credentials.Certificate(sa)

    if not firebase_admin._apps:
        opts = {}
        if project_id:
            opts["projectId"] = project_id
        if bucket_name:
            opts["storageBucket"] = bucket_name
        firebase_admin.initialize_app(cred, opts)

    _fb["admin"] = firebase_admin
    _fb["firestore"] = firestore
    _fb["client"] = firestore.client(project=project_id) if project_id else firestore.client()
    _fb["storage"] = storage
    _fb["bucket"] = storage.bucket() if bucket_name else None

    _FB_INIT_DONE = True
    _fb_log("Firebase initialized")


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _collection_name(path: Path) -> str:
    return path.stem.lower().replace("-", "_")


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out


# ============================================================
# SETTINGS API
# ============================================================

def load_settings() -> dict:
    _fb_init()
    doc = _fb["client"].collection("settings").document("app").get()
    return doc.to_dict() or {}


def save_settings(settings: dict) -> None:
    _fb_init()
    _fb["client"].collection("settings").document("app").set(settings)


# ============================================================
# DATAFRAME API (FIRESTORE)
# ============================================================

def load_df(path: Path) -> pd.DataFrame:
    _fb_init()
    coll = _collection_name(path)
    docs = _fb["client"].collection(coll).stream()
    rows = [d.to_dict() for d in docs]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def save_df(df: pd.DataFrame, path: Path) -> None:
    _fb_init()
    coll = _collection_name(path)
    col_ref = _fb["client"].collection(coll)

    df = _normalize_dates(df)

    # 🔒 SAFE REPLACEMENT STRATEGY
    batch = _fb["client"].batch()

    for doc in col_ref.stream():
        batch.delete(doc.reference)

    for _, row in df.iterrows():
        doc_ref = col_ref.document()
        batch.set(doc_ref, row.to_dict())

    batch.commit()


# ============================================================
# BACKUPS (FIREBASE STORAGE)
# ============================================================

def zip_backup() -> str:
    _fb_init()
    if not _fb["bucket"]:
        raise RuntimeError("Firebase Storage bucket not configured.")

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.txt", "Firestore is the source of truth.")

    mem.seek(0)
    name = f"backup_{int(time.time())}.zip"
    blob = _fb["bucket"].blob(f"backups/{name}")
    blob.upload_from_file(mem, content_type="application/zip")
    return blob.public_url


# ============================================================
# AVATARS
# ============================================================

def upload_avatar(user_id: str, file_bytes: bytes) -> str:
    _fb_init()
    if not _fb["bucket"]:
        raise RuntimeError("Firebase Storage bucket not configured.")

    blob = _fb["bucket"].blob(f"avatars/{user_id}.png")
    blob.upload_from_string(file_bytes, content_type="image/png")
    return blob.public_url
