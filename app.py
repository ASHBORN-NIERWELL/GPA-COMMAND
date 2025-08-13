from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import pandas as pd

# Pages
import app_pages.dashboard as dashboard
import app_pages.subjects as subjects
import app_pages.daily_log as daily_log
import app_pages.self_tests as self_tests
import app_pages.settings_backup as settings_backup
# import app_pages.leaderboard as leaderboard

# Core
from core.config import SUBJECTS_CSV, LOGS_CSV, TESTS_CSV
from core.storage import ensure_store, load_df, load_settings
from core.auth import (
    load_users, get_user_by_name, create_user,
    _verify_password, claim_legacy_rows_for_user,
    get_user_avatar_path, set_user_avatar,
)
from core.metrics import compute_metrics
from core.gamify import compute_leaderboard

st.set_page_config(page_title="NIERWELL GPA System", page_icon="🎯", layout="wide")
ensure_store()
settings = load_settings()

# --- Session bootstrap ---
if "user" not in st.session_state:
    st.session_state.user = None

# ---------- WELCOME + AUTH when NOT signed in ----------
if st.session_state.user is None:
    # Optional background from Settings (only on welcome screen)
    bg_path = str(settings.get("welcome_bg_path", "")).strip()
    if bg_path:
        css_bg = bg_path.replace("\\", "/")
        st.markdown(
            f"""
            <style>
            .stApp {{
                background-image: url("file:///{css_bg}");
                background-attachment: fixed;
                background-size: contain;
                background-repeat: no-repeat;
                background-position: center;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    users_df_all = load_users()
    usernames = users_df_all["username"].tolist()

    # Top hero
    st.title("Welcome to Nierwell GPA Manager 🎯")
    st.caption("Plan smarter, track consistently, and walk into exams prepared.")

    # Load data once for preview (anonymous rows only)
    try:
        subjects_df_all = load_df(SUBJECTS_CSV)
        logs_df_all     = load_df(LOGS_CSV)
        tests_df_all    = load_df(TESTS_CSV)
    except Exception:
        subjects_df_all = pd.DataFrame()
        logs_df_all     = pd.DataFrame()
        tests_df_all    = pd.DataFrame()

    blanks = ["", "nan", "NaN"]
    preview_subjects = subjects_df_all[subjects_df_all.get("user_id", "").astype(str).isin(blanks)].copy()
    preview_tests    = tests_df_all[tests_df_all.get("user_id", "").astype(str).isin(blanks)].copy()

    # Quick preview metrics (NO total hours – multi-user safe)
    colA, colC = st.columns(2)
    with colA:
        st.metric("Subjects (sample space)", f"{len(preview_subjects):,}")
    with colC:
        mean_score = pd.to_numeric(preview_tests.get("score"), errors="coerce").mean() if not preview_tests.empty else float("nan")
        st.metric("Avg self‑test score", f"{0 if pd.isna(mean_score) else round(mean_score):d}%")

    st.divider()

    # Feature + Auth columns
    left, right = st.columns([7, 5], gap="large")

    with left:
        st.subheader("What you can do here")
        f1, f2, f3 = st.columns(3)
        with f1:
            st.markdown("### 📚 Subjects")
            st.write("Organize courses, set exam dates, and track confidence per subject.")
        with f2:
            st.markdown("### 📝 Daily Log")
            st.write("Record study sessions with hours, tasks, and quick self‑ratings.")
        with f3:
            st.markdown("### 🧪 Self‑Tests")
            st.write("Add quiz/test entries, difficulty, and notes to see progress.")

        with st.expander("Tips to get the most out of Nierwell", expanded=False):
            st.markdown(
                "- Add **subjects** first (exam dates & credits help prioritization).\n"
                "- Log **every study session** with realistic hours and a short note.\n"
                "- Use **Self‑Tests** weekly; trends matter more than single scores.\n"
                "- Check the **Dashboard** to see priorities and readiness evolve."
            )

    with right:
        st.subheader("Sign in or create an account")

        tab_login, tab_signup = st.tabs(["Login", "Sign up"])

        with tab_login:
            sel_user = st.selectbox("User", ["— select —"] + usernames, index=0, key="login_user_sel")
            pw = st.text_input("Password (leave empty if none)", type="password", key="login_pw")
            if st.button("Sign in", type="primary", use_container_width=True):
                if sel_user == "— select —":
                    st.error("Pick a user.")
                else:
                    row = get_user_by_name(sel_user)
                    if row is None:
                        st.error("User not found.")
                    else:
                        if _verify_password(pw, str(row.get("password_hash", ""))):
                            st.session_state.user = {"id": row["id"], "username": row["username"]}
                            claim_legacy_rows_for_user(row["id"])
                            st.success(f"Signed in as {row['username']}")
                            st.rerun()
                        else:
                            st.error("Wrong password.")

        with tab_signup:
            new_user = st.text_input("New username", key="signup_user")
            new_pw = st.text_input("Password (optional)", type="password", key="signup_pw")
            if st.button("Create account", use_container_width=True):
                if not new_user.strip():
                    st.error("Enter a username.")
                elif get_user_by_name(new_user) is not None:
                    st.error("Username already exists.")
                else:
                    uid = create_user(new_user.strip(), new_pw.strip())
                    if uid:
                        st.session_state.user = {"id": uid, "username": new_user.strip()}
                        st.success(f"Account created. Welcome, {new_user.strip()}!")
                        st.rerun()
                    else:
                        st.error("Could not create user.")

    st.divider()
    st.caption("Need to import existing data? Use **Settings/Backup** after signing in.")
    st.stop()

# ========== SIGNED-IN APP BELOW ==========

# --- Sidebar: Account (avatar + sign out) ---
st.sidebar.subheader("Account")
st.sidebar.write(f"**Signed in:** {st.session_state.user['username']}")

avatar_path = get_user_avatar_path(st.session_state.user["id"])
if avatar_path and Path(avatar_path).exists():
    st.sidebar.image(avatar_path, width=96, caption="Profile")
else:
    st.sidebar.markdown("🧑‍🎓 *(no profile picture)*")

avatar_file = st.sidebar.file_uploader("Upload profile picture", type=["png","jpg","jpeg","webp"], key="avatar_up")
if avatar_file is not None:
    set_user_avatar(st.session_state.user["id"], avatar_file.read(), avatar_file.name)
    st.sidebar.success("Profile picture updated.")
    st.rerun()

if st.sidebar.button("Sign out"):
    st.session_state.user = None
    st.rerun()

# --- Load data & filter by user ---
subjects_df_all = load_df(SUBJECTS_CSV)
logs_df_all     = load_df(LOGS_CSV)
tests_df_all    = load_df(TESTS_CSV)

uid = st.session_state.user["id"]
subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str) == uid].copy()
logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str) == uid].copy()
tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str) == uid].copy()

# --- Sidebar quick stats ---
try:
    min_days = int(compute_metrics(subjects_df, logs_df, tests_df)["days_left"].min())
except Exception:
    min_days = None

st.sidebar.markdown(
    f"""**Semester:** {settings.get('semester','N/A')}  
**Default exam date:** {settings.get('default_exam_date')}  
**Weights:** logs {int(settings.get('logs_weight',0.7)*100)}% / tests {int(settings.get('tests_weight',0.3)*100)}%  
**Nearest exam in:** {min_days if min_days is not None else '—'} days"""
)

# --- Sidebar: Gamification ---
try:
    users_df_all = load_users()
    lb = compute_leaderboard(logs_df_all, tests_df_all, users_df_all)
    if len(lb):
        st.sidebar.subheader("🏆 Gamification")
        me = lb[lb["user_id"] == st.session_state.user["id"]]
        if not me.empty:
            r = me.iloc[0]
            st.sidebar.metric("Rank", f"#{int(r['rank'])}/{len(lb)}")
            max_score = float(lb["score"].max()) or 1.0
            pct = int(round(100 * float(r["score"]) / max_score))
            try:
                st.sidebar.progress(pct, text=f"Score {int(r['score'])}")
            except TypeError:
                st.sidebar.progress(pct)
                st.sidebar.caption(f"Score {int(r['score'])}")
            st.sidebar.caption(
                f"Hours {r['hours']:.1f} • Tests avg {int(round(r['tests_avg']))}% • Streak {int(r['streak_cur'])}🔥"
            )
        else:
            st.sidebar.info("Add a log or test to join the board.")
except Exception as e:
    st.sidebar.caption(f"Gamification unavailable: {e}")

# --- Navigation + routing ---
page = st.sidebar.radio(
    "Navigate",
    ["📊 Dashboard", "📚 Subjects", "📝 Daily Log", "🧪 Self‑Tests", "⚙️ Settings/Backup"]
    # + ["🏆 Leaderboard"]
)

if page == "📊 Dashboard":
    dashboard.render(subjects_df, logs_df, tests_df, settings)
elif page == "📚 Subjects":
    subjects.render(subjects_df, subjects_df_all, logs_df, tests_df, settings)
elif page == "📝 Daily Log":
    daily_log.render(subjects_df, logs_df, logs_df_all)
elif page == "🧪 Self‑Tests":
    self_tests.render(subjects_df, tests_df, tests_df_all)
else:
    settings_backup.render(settings, subjects_df_all, logs_df_all, tests_df_all)
