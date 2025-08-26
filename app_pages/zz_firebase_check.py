# pages/zz_firebase_check.py
from __future__ import annotations
import time
import uuid
import json
import pandas as pd
import streamlit as st

# Try to use your project's helper first
try:
    from core.firebase_store import get_db_and_bucket
    have_helper = True
except Exception:
    have_helper = False

# Fallbacks if the helper isn't available / configured
def _fallback_db_bucket():
    import os
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
    # These environment variables must be set for the fallback
    # FIREBASE_CREDENTIALS, FIREBASE_PROJECT_ID, FIREBASE_STORAGE_BUCKET
    cred_path = os.getenv("FIREBASE_CREDENTIALS", "").strip()
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()

    if not cred_path or not project_id or not bucket_name:
        raise RuntimeError("Fallback requires FIREBASE_* env vars (CREDENTIALS, PROJECT_ID, STORAGE_BUCKET).")

    cred = credentials.Certificate(cred_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"projectId": project_id, "storageBucket": bucket_name})
    return firestore.client(project=project_id), storage.bucket(bucket_name)

st.title("Firebase Update Diagnostic")

# ---- Bootstrap clients ----
db = bucket = None
errors = []

try:
    if have_helper:
        db, bucket = get_db_and_bucket()
    else:
        db, bucket = _fallback_db_bucket()
except Exception as e:
    errors.append(f"Init error: {e}")

with st.expander("Environment / Setup"):
    st.write({
        "using_helper": have_helper,
        "db_ok": db is not None,
        "bucket_ok": bucket is not None,
    })
    if errors:
        st.error("\n".join(errors))

if not db or not bucket:
    st.stop()

# ---- Firestore round-trip test ----
st.subheader("1) Firestore write → read")
fs_result = {}
try:
    from firebase_admin import firestore as _fs
    token = str(uuid.uuid4())
    doc_ref = db.collection("diag").document(token)
    payload = {
        "kind": "ping",
        "token": token,
        "client_time": time.time(),
        "server_time": _fs.SERVER_TIMESTAMP,
    }
    # write
    doc_ref.set(payload, merge=True)
    time.sleep(0.5)  # small delay so server timestamp populates
    snap = doc_ref.get()
    fs_result = snap.to_dict() or {}

    ok = snap.exists and fs_result.get("token") == token
    st.success(f"Firestore OK: wrote and read back doc diag/{token}") if ok else st.error("Firestore read-back failed.")
    st.code(json.dumps(fs_result, indent=2), language="json")

except Exception as e:
    st.error(f"Firestore test error: {e}")

# ---- Storage round-trip test ----
st.subheader("2) Storage upload → fetch metadata (generation/size)")
storage_result = {}
try:
    token2 = str(uuid.uuid4())
    path = f"diag/{token2}.txt"
    blob = bucket.blob(path)
    content1 = f"hello-from-diagnostic {token2} t={time.time()}\n"
    blob.upload_from_string(content1, content_type="text/plain")

    # metadata after first upload
    blob.reload()
    gen1 = getattr(blob, "generation", None)
    size1 = getattr(blob, "size", None)

    # write again to confirm generation increases
    time.sleep(0.3)
    content2 = f"second-write {token2} t={time.time()}\n"
    blob.upload_from_string(content2, content_type="text/plain")
    blob.reload()
    gen2 = getattr(blob, "generation", None)
    size2 = getattr(blob, "size", None)

    # try to make it public (optional; depends on your rules)
    public_url = None
    try:
        blob.make_public()
        public_url = blob.public_url
    except Exception:
        public_url = "(not public / rules disabled)"

    storage_result = {
        "path": path,
        "generation_before": gen1,
        "size_before": size1,
        "generation_after": gen2,
        "size_after": size2,
        "public_url": public_url,
    }
    st.code(json.dumps(storage_result, indent=2), language="json")

    # Verdicts
    if gen1 and gen2 and str(gen2) != str(gen1):
        st.success("Storage OK: generation changed after second write.")
    else:
        st.error("Storage generation did not change — upload may have failed.")

    if size2 and int(size2) >= len(content2):
        st.info("Storage size looks correct for the latest content.")
    else:
        st.warning("Storage size looks suspiciously small.")

except Exception as e:
    st.error(f"Storage test error: {e}")

# ---- Optional: list recent diag files (helps verify visually in Console) ----
with st.expander("List recent diag/ files (up to 20)"):
    try:
        # Uses Google Cloud Storage list API via admin sdk
        from google.cloud import storage as gcs
        # The admin bucket object is compatible with gcs listing
        client = gcs.Client()  # will pick creds from admin sdk env
        # NOTE: if this raises auth error, it's fine; listing is optional
        blobs = list(client.list_blobs(bucket.name, prefix="diag/", max_results=20))
        rows = [{
            "name": b.name,
            "size": b.size,
            "updated": getattr(b, "updated", None),
            "generation": getattr(b, "generation", None),
        } for b in blobs]
        df = pd.DataFrame(rows)
        if len(df):
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No diag/ blobs found (yet).")
    except Exception as e:
        st.caption(f"(Skipping list — {e})")
