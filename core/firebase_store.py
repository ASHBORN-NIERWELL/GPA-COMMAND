# core/firebase_store.py
from __future__ import annotations
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
