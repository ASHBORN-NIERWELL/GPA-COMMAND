from __future__ import annotations

import os
import sys
import json
import random
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

# ============================================================
# Ensure project root is on PYTHONPATH
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# Firebase bootstrap (MANDATORY, FAIL-FAST)
# ============================================================
def bootstrap_firebase_or_die() -> None:
    """
    Enforce Firebase availability.
    - Reads credentials ONLY from st.secrets
    - Writes service account JSON to /tmp
    - Sets required env vars
    - Stops app immediately if anything is missing
    """
    try:
        cfg = st.secrets["FIREBASE"]
    except Exception:
        st.error("❌ FIREBASE secrets not found. Deployment is misconfigured.")
        st.stop()

    # ---- Service account JSON ----
    sa = cfg.get("service_account_json")
    if not sa:
        st.error("❌ FIREBASE.service_account_json is missing.")
        st.stop()

    sa_path = Path(tempfile.gettempdir()) / "firebase_service_account.json"
    try:
        if isinstance(sa, dict):
            sa_path.write_text(json.dumps(sa), encoding="utf-8")
        else:
            sa_path.write_text(sa, encoding="utf-8")
    except Exception as e:
        st.error(f"❌ Failed to materialize Firebase credentials: {e}")
        st.stop()

    os.environ["FIREBASE_CREDENTIALS"] = str(sa_path)

    # ---- Required metadata ----
    project_id = cfg.get("project_id")
    bucket = cfg.get("storage_bucket")

    if not project_id:
        st.error("❌ FIREBASE.project_id is missing.")
        st.stop()
    if not bucket:
        st.error("❌ FIREBASE.storage_bucket is missing.")
        st.stop()

    os.environ["FIREBASE_PROJECT_ID"] = project_id
    os.environ["FIREBASE_STORAGE_BUCKET"] = bucket
    os.environ["USE_FIREBASE"] = "1"


# 🔒 MUST run before importing core.storage
bootstrap_firebase_or_die()


# ============================================================
# Core imports (Firebase already guaranteed)
# ============================================================
from core.config import SUBJECTS_CSV, LOGS_CSV, TESTS_CSV
from core.storage import (
    load_df,
    save_df,
    load_settings,
    save_settings,
)

from core.auth import (
    load_users,
    get_user_by_name,
    create_user,
    _verify_password,
    claim_legacy_rows_for_user,
    get_user_avatar_path,
    set_user_avatar,
)
from core.gamify import compute_leaderboard


# ============================================================
# App pages
# ============================================================
import app_pages.dashboard as dashboard
import app_pages.subjects as subjects
import app_pages.daily_log as daily_log
import app_pages.self_tests as self_tests
import app_pages.settings_backup as settings_backup

try:
    import app_pages.firebase_check as firebase_check
except Exception:
    firebase_check = None


# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="Nierwell GPA System",
    page_icon="assets/logo.png",
    layout="wide",
)


# ============================================================
# Global CSS
# ============================================================
def inject_base_css(bg_path: str = "") -> None:
    bg_css = bg_path.replace("\\", "/") if bg_path else ""

    bg = (
        f'url("file:///{bg_css}"), radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)'
        if bg_css
        else "radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)"
    )

    st.markdown(
        f"""
        <style>
        :root {{
            --fg: #d8e1ff;
            --accent: #5eead4;
            --accent2: #7c3aed;
        }}
        .stApp {{
            background-image: {bg};
            background-size: cover;
            background-attachment: fixed;
            color: var(--fg);
        }}
        h1 {{
            font-weight: 700;
            background: linear-gradient(90deg, var(--accent), var(--accent2));
            -webkit-background-clip: text;
            color: transparent;
        }}
        footer {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# App bootstrap
# ============================================================

try:
    settings = load_settings() or {}
except Exception as e:
    st.error(f"❌ Firebase storage unavailable: {e}")
    st.stop()

inject_base_css(settings.get("welcome_bg_path", ""))

if "user" not in st.session_state:
    st.session_state.user = None
if "nav" not in st.session_state:
    st.session_state.nav = "Dashboard"


# ============================================================
# AUTH / WELCOME
# ============================================================
if st.session_state.user is None:
    st.title("Nierwell GPA Manager")
    st.caption("Walk into exams prepared.")

    users_df = load_users()
    usernames = users_df["username"].tolist()

    tab_login, tab_signup = st.tabs(["Login", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            sel_user = st.selectbox("User", ["— select —"] + usernames)
            pw = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")

        if submitted:
            if sel_user == "— select —":
                st.error("Pick a user.")
            else:
                row = get_user_by_name(sel_user)
                if row and _verify_password(pw, str(row.get("password_hash", ""))):
                    st.session_state.user = {
                        "id": row["id"],
                        "username": row["username"],
                    }
                    claim_legacy_rows_for_user(row["id"])
                    st.success("Signed in.")
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

    with tab_signup:
        with st.form("signup_form"):
            uname = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            create = st.form_submit_button("Create account")

        if create:
            if not uname:
                st.error("Username required.")
            else:
                create_user(uname, pw)
                st.success("Account created. You may now sign in.")
                st.rerun()

    st.stop()


# ============================================================
# SIGNED-IN APP
# ============================================================
uid = st.session_state.user["id"]
username = st.session_state.user["username"]

st.markdown(f"## 👋 Welcome, **{username}**")

quotes = [
    "Sometimes you gotta run before you can walk.",
    "Focus. Build. Execute.",
    "Discipline beats motivation.",
]
st.caption(f"💬 *{random.choice(quotes)}*")


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.markdown("### Account")
    st.write(f"**{username}**")

    avatar = get_user_avatar_path(uid)
    if avatar and Path(avatar).exists():
        st.image(avatar, width=96)

    up = st.file_uploader("Update avatar", type=["png", "jpg", "jpeg", "webp"])
    if up:
        set_user_avatar(uid, up.read(), up.name)
        st.success("Updated.")
        st.rerun()

    st.divider()
    nav_items = [
        "Dashboard",
        "Subjects",
        "Daily Log",
        "Self-Tests",
        "Settings & Backup",
        "🔍 Firebase Check",
    ]
    st.session_state.nav = st.radio(
        "Navigation",
        nav_items,
        index=nav_items.index(st.session_state.nav),
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("Sign out", use_container_width=True):
        st.session_state.user = None
        st.rerun()


# ============================================================
# Data loading
# ============================================================
subjects_all = load_df(SUBJECTS_CSV)
logs_all = load_df(LOGS_CSV)
tests_all = load_df(TESTS_CSV)

subjects_df = subjects_all[subjects_all["user_id"] == uid]
logs_df = logs_all[logs_all["user_id"] == uid]
tests_df = tests_all[tests_all["user_id"] == uid]


# ============================================================
# Router
# ============================================================
st.markdown("---")

if st.session_state.nav == "Dashboard":
    dashboard.render(subjects_df, logs_df, tests_df, settings)

elif st.session_state.nav == "Subjects":
    subjects.render(subjects_df, subjects_all, logs_df, tests_df, settings)

elif st.session_state.nav == "Daily Log":
    daily_log.render(subjects_df, logs_df, logs_all)

elif st.session_state.nav == "Self-Tests":
    self_tests.render(subjects_df, tests_df, tests_all)

elif st.session_state.nav == "Settings & Backup":
    settings_backup.render(settings, subjects_all, logs_all, tests_all)

else:
    if firebase_check and hasattr(firebase_check, "render"):
        firebase_check.render()
    else:
        st.info("Firebase diagnostics unavailable.")
