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
from core.gamify import compute_leaderboard   # <-- import here

st.set_page_config(page_title="GPA Command Center", page_icon="🎯", layout="wide")
ensure_store()
settings = load_settings()

# --- Session bootstrap ---
if "user" not in st.session_state:
    st.session_state.user = None

# --- Sidebar: Account ---
st.sidebar.subheader("Account")
users_df_all = load_users()
usernames = users_df_all["username"].tolist()

tab_login, tab_signup = st.sidebar.tabs(["Login", "Sign up"])

with tab_login:
    sel_user = st.selectbox("User", ["— select —"] + usernames, index=0, key="login_user_sel")
    pw = st.text_input("Password (leave empty if none)", type="password", key="login_pw")
    if st.button("Sign in"):
        if sel_user == "— select —":
            st.sidebar.error("Pick a user.")
        else:
            row = get_user_by_name(sel_user)
            if row is None:
                st.sidebar.error("User not found.")
            else:
                if _verify_password(pw, str(row.get("password_hash", ""))):
                    st.session_state.user = {"id": row["id"], "username": row["username"]}
                    claim_legacy_rows_for_user(row["id"])
                    st.sidebar.success(f"Signed in as {row['username']}")
                    st.rerun()
                else:
                    st.sidebar.error("Wrong password.")

with tab_signup:
    new_user = st.text_input("New username", key="signup_user")
    new_pw = st.text_input("Password (optional)", type="password", key="signup_pw")
    if st.button("Create account"):
        if not new_user.strip():
            st.sidebar.error("Enter a username.")
        elif get_user_by_name(new_user) is not None:
            st.sidebar.error("Username already exists.")
        else:
            uid = create_user(new_user.strip(), new_pw.strip())
            if uid:
                st.session_state.user = {"id": uid, "username": new_user.strip()}
                st.sidebar.success(f"Account created. Welcome, {new_user.strip()}!")
                st.rerun()
            else:
                st.sidebar.error("Could not create user.")

# --- Sidebar: Signed-in area (avatar + sign out) ---
if st.session_state.user:
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
else:
    st.sidebar.info("Not signed in — you can browse, but edits require sign-in.")

# --- Load data & filter by user ---
subjects_df_all = load_df(SUBJECTS_CSV)
logs_df_all     = load_df(LOGS_CSV)
tests_df_all    = load_df(TESTS_CSV)

# Normalize date columns globally to datetime64[ns]
for df in (logs_df_all, tests_df_all):
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()

if st.session_state.user:
    uid = st.session_state.user["id"]
    subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str) == uid].copy()
    logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str) == uid].copy()
    tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str) == uid].copy()
else:
    blanks = ["", "nan", "NaN"]
    subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str).isin(blanks)].copy()
    logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str).isin(blanks)].copy()
    tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str).isin(blanks)].copy()

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
    lb = compute_leaderboard(logs_df_all, tests_df_all, users_df_all)
    if len(lb):
        st.sidebar.subheader("🏆 Gamification")
        if st.session_state.user:
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
        else:
            top = lb.iloc[0]
            st.sidebar.metric("Leader", top["username"], delta=f"Score {int(top['score'])}")
            st.sidebar.caption("Sign in to see your rank.")
except Exception as e:
    st.sidebar.caption(f"Gamification unavailable: {e}")

# --- Navigation + routing ---
page = st.sidebar.radio(
    "Navigate",
    ["📊 Dashboard", "📚 Subjects", "📝 Daily Log", "🧪 Self-Tests", "⚙️ Settings/Backup"]
    # + ["🏆 Leaderboard"]
)

if page == "📊 Dashboard":
    dashboard.render(subjects_df, logs_df, tests_df, settings)
elif page == "📚 Subjects":
    subjects.render(subjects_df, subjects_df_all, logs_df, tests_df, settings)
elif page == "📝 Daily Log":
    daily_log.render(subjects_df, logs_df, logs_df_all)
elif page == "🧪 Self-Tests":
    self_tests.render(subjects_df, tests_df, tests_df_all)
# elif page == "🏆 Leaderboard":
#     leaderboard.render(logs_df_all, tests_df_all)
else:
    settings_backup.render(settings, subjects_df_all, logs_df_all, tests_df_all)
