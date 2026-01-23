from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional, Tuple, List, Any, Dict
import pandas as pd
import streamlit as st
from datetime import datetime

# Prevent re-initialization errors in Streamlit
import firebase_admin
from firebase_admin import credentials, firestore, storage

@st.cache_resource(show_spinner="Connecting to Firebase...")
def _init_firebase() -> Tuple[Any, Any]:
    """
    Idempotent Firebase Admin init.
    """
    # 1. Check if already initialized
    if not firebase_admin._apps:
        sa: Optional[dict] = None
        bucket_name = ""

        # 2. Try Streamlit Secrets
        if "firebase" in st.secrets:
            fb = st.secrets["firebase"]
            # Support both raw JSON string or field-by-field
            if "service_account_json" in fb:
                sa = json.loads(fb["service_account_json"])
            elif "project_id" in fb:
                sa = dict(fb)
                # Fix newline characters often broken in TOML
                if "private_key" in sa:
                    sa["private_key"] = sa["private_key"].replace("\\n", "\n")
            
            bucket_name = fb.get("storage_bucket", "")

        # 3. Fallback to Environment Variables
        if sa is None:
            sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            if sa_json:
                sa = json.loads(sa_json)
        
        if sa is None:
            raise RuntimeError("No Firebase credentials found in st.secrets or Environment Variables.")

        cred = credentials.Certificate(sa)
        firebase_admin.initialize_app(cred, {
            'storageBucket': bucket_name if bucket_name else None
        })

    db = firestore.client()
    bucket = storage.bucket() if firebase_admin.get_app().options.get('storageBucket') else None
    return db, bucket

def get_db():
    db, _ = _init_firebase()
    return db

# ---------- Analytical Utilities (The "New System" Logic) ----------

def get_prioritized_subjects_df(user_id: str) -> pd.DataFrame:
    """
    Fetches subjects and calculates Priority Score using Pandas for analysis.
    """
    db = get_db()
    docs = db.collection(f"users/{user_id}/subjects").stream()
    
    rows = []
    now = datetime.now()

    for d in docs:
        data = d.to_dict()
        data["id"] = d.id
        
        # Parse Dates
        try:
            # Handle ISO string from your previous Node.js project
            exam_dt = datetime.fromisoformat(data['examDate'].replace('Z', '+00:00'))
            days_left = (exam_dt.date() - now.date()).days
        except (KeyError, ValueError):
            days_left = 30 # Fallback

        # Analytical Formula
        conf = data.get('confidence', 5)
        credits = data.get('credits', 1)
        
        confidence_factor = 11 - conf
        urgency_factor = 100 if days_left <= 0 else (30 / max(days_left, 1))
        
        data["priority_score"] = round(confidence_factor * credits * urgency_factor, 1)
        data["days_left"] = days_left
        rows.append(data)

    df = pd.DataFrame(rows)
    if not df.empty:
        return df.sort_values(by="priority_score", ascending=False)
    return df

def log_progress(user_id: str, subject_id: str, hours: float):
    """
    Python equivalent of your logStudySession Node.js action.
    """
    db = get_db()
    ref = db.collection(f"users/{user_id}/subjects").document(subject_id)
    
    ref.update({
        "totalStudyHours": firestore.Increment(hours),
        "lastStudied": datetime.now().isoformat()
    })