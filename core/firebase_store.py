# core/firebase_store.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

import streamlit as st

# Lazy imports inside init
firebase_admin = None  # type: ignore

@st.cache_resource(show_spinner=False)
def _init_firebase():
    """
    Idempotent Firebase Admin init using:
    1) Streamlit Secrets [firebase]  (recommended)
       - either field-by-field TOML or raw JSON under `service_account`
       - optional: storage_bucket
    2) Env fallback FIREBASE_SERVICE_ACCOUNT_JSON / FIREBASE_CREDENTIALS (if you use them)
    Returns: (firestore_client, storage_bucket_or_None)
    """
    global firebase_admin
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials as _credentials  # type: ignore
        from firebase_admin import firestore as _firestore  # type: ignore
        from firebase_admin import storage as _storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "firebase_admin is not installed. Add to requirements.txt: firebase-admin"
        ) from e

    # ---- Build service account from secrets (preferred) ----
    sa: Optional[dict] = None
    bucket_name = ""
    if "firebase" in st.secrets:
        fb = st.secrets["firebase"]
        # Option B: raw JSON in a single key
        if "service_account" in fb:
            sa_raw = fb["service_account"]
            sa = json.loads(sa_raw) if isinstance(sa_raw, str) else dict(sa_raw)
        else:
            # Option A: field-by-field
            required = [
                "project_id", "private_key_id", "private_key", "client_email",
                "client_id", "auth_uri", "token_uri",
                "auth_provider_x509_cert_url", "client_x509_cert_url",
            ]
            for k in required:
                if k not in fb:
                    raise RuntimeError(f"[firebase] Missing field in secrets: {k}")
            sa = {
                "type": fb.get("type", "service_account"),
                "project_id": fb["project_id"],
                "private_key_id": fb["private_key_id"],
                "private_key": str(fb["private_key"]).replace("\\n", "\n"),
                "client_email": fb["client_email"],
                "client_id": fb["client_id"],
                "auth_uri": fb["auth_uri"],
                "token_uri": fb["token_uri"],
                "auth_provider_x509_cert_url": fb["auth_provider_x509_cert_url"],
                "client_x509_cert_url": fb["client_x509_cert_url"],
            }
        bucket_name = str(fb.get("storage_bucket", "")).strip()

    # (Optional) Env fallbacks if you use them locally
    if sa is None:
        import os
        sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        sa_path = os.getenv("FIREBASE_CREDENTIALS", "").strip()
        if sa_json:
            sa = json.loads(sa_json)
        elif sa_path and Path(sa_path).exists():
            sa = json.loads(Path(sa_path).read_text(encoding="utf-8"))
        else:
            raise RuntimeError(
                "Missing Firebase credentials. Add them under [firebase] in Streamlit Secrets."
            )
        bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", bucket_name) or ""

    cred = _credentials.Certificate(sa)
    project_id = sa.get("project_id", "")

    if not firebase_admin._apps:  # type: ignore
        opts = {}
        if bucket_name:
            opts["storageBucket"] = bucket_name
        if project_id:
            opts["projectId"] = project_id
        firebase_admin.initialize_app(cred, opts)  # type: ignore

    db = _firestore.client(project=project_id) if project_id else _firestore.client()  # type: ignore
    bucket = _storage.bucket() if bucket_name else None  # type: ignore
    return db, bucket


def get_db_and_bucket():
    """Public accessor for Firestore client and Storage bucket."""
    return _init_firebase()


def upload_bytes(path_in_bucket: str, file_bytes: bytes, content_type: str | None = None) -> str:
    """
    Uploads bytes to Firebase Storage (if bucket configured).
    Returns a public URL if the blob is made public; otherwise the gs:// URL.
    """
    db, bucket = get_db_and_bucket()
    if bucket is None:
        raise RuntimeError("Firebase Storage bucket not configured. Set storage_bucket in [firebase] secrets.")

    blob = bucket.blob(path_in_bucket)
    blob.upload_from_string(file_bytes, content_type=content_type)

    # make it public so avatars can render without signed URLs
    try:
        blob.make_public()
        return blob.public_url
    except Exception:
        return f"gs://{bucket.name}/{path_in_bucket}"


def delete_blob(path_in_bucket: str) -> None:
    """Deletes a blob from Storage; no-op if it doesn't exist."""
    _, bucket = get_db_and_bucket()
    if bucket is None:
        return
    blob = bucket.blob(path_in_bucket)
    try:
        blob.delete()
=======
import io, json
from typing import List, Dict, Any, Optional
import pandas as pd
import streamlit as st

from firebase_admin import credentials, firestore, initialize_app, storage as fb_storage
from google.cloud import storage as gcs

# ---------- bootstrap ----------
@st.cache_resource(show_spinner=False)
def _init_firebase():
    # read from Streamlit secrets
    cfg = st.secrets.get("FIREBASE", {})
    project_id = cfg.get("project_id")
    sa_json_str = cfg.get("service_account_json", "")
    bucket_name = cfg.get("storage_bucket")

    if not project_id or not sa_json_str or not bucket_name:
        raise RuntimeError("Missing FIREBASE settings in .streamlit/secrets.toml")

    cred = credentials.Certificate(json.loads(sa_json_str))
    app = initialize_app(cred, {"storageBucket": bucket_name})
    db = firestore.client()
    bucket = fb_storage.bucket()  # default = bucket_name above
    return db, bucket

def get_db_and_bucket():
    return _init_firebase()

# ---------- Firestore <-> pandas ----------
def df_from_collection(collection: str, where: Optional[List]=None) -> pd.DataFrame:
    """
    Load a whole collection (optionally with simple where filters).
    where = [("field", "==", value), ...]
    """
    db, _ = get_db_and_bucket()
    q = db.collection(collection)
    if where:
        for f, op, val in where:
            q = q.where(f, op, val)
    docs = q.stream()
    rows = []
    for d in docs:
        r = d.to_dict()
        r["id"] = d.id if "id" not in r else r["id"]
        rows.append(r)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def upsert_dataframe(collection: str, df: pd.DataFrame, id_field: str = "id") -> None:
    """
    Upsert each row in df into Firestore collection by id_field.
    """
    db, _ = get_db_and_bucket()
    for _, row in df.iterrows():
        data = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        doc_id = str(data.get(id_field) or "")
        if not doc_id:
            # fall back: Firestore auto id
            db.collection(collection).add(data)
        else:
            db.collection(collection).document(doc_id).set(data, merge=True)

def delete_by_ids(collection: str, ids: List[str], id_field: str = "id") -> None:
    db, _ = get_db_and_bucket()
    for doc_id in ids:
        db.collection(collection).document(str(doc_id)).delete()

# ---------- settings ----------
SETTINGS_DOC = ("settings", "app_settings")

def load_settings_dict(defaults: dict) -> dict:
    db, _ = get_db_and_bucket()
    ref = db.collection(SETTINGS_DOC[0]).document(SETTINGS_DOC[1])
    snap = ref.get()
    data = snap.to_dict() if snap.exists else {}
    out = defaults.copy()
    out.update(data or {})
    return out

def save_settings_dict(s: dict) -> None:
    db, _ = get_db_and_bucket()
    ref = db.collection(SETTINGS_DOC[0]).document(SETTINGS_DOC[1])
    ref.set(s, merge=True)

# ---------- storage (avatars, backgrounds) ----------
def upload_bytes(path_in_bucket: str, content: bytes, content_type: str = "application/octet-stream") -> str:
    """
    Upload bytes to Firebase Storage and return the gs:// URL.
    """
    _, bucket = get_db_and_bucket()
    blob = bucket.blob(path_in_bucket)
    blob.upload_from_string(content, content_type=content_type)
    # You can also generate a signed URL if you want a public HTTP URL
    return f"gs://{bucket.name}/{path_in_bucket}"

def delete_blob(path_in_bucket: str) -> None:
    _, bucket = get_db_and_bucket()
    try:
        bucket.blob(path_in_bucket).delete()
    except Exception:
        pass
