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
    except Exception:
        pass
