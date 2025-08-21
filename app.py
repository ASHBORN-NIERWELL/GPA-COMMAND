# app.py
from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root on path (so "core.*" and "app_pages.*" import cleanly)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st
import random

# ---------- Pages ----------
import app_pages.dashboard as dashboard
import app_pages.subjects as subjects
import app_pages.daily_log as daily_log
import app_pages.self_tests as self_tests
import app_pages.settings_backup as settings_backup
# import app_pages.leaderboard as leaderboard

# ---------- Core ----------
from core.config import SUBJECTS_CSV, LOGS_CSV, TESTS_CSV
from core.storage import ensure_store, load_df, load_settings
from core.auth import (
    load_users, get_user_by_name, create_user,
    _verify_password, claim_legacy_rows_for_user,
    get_user_avatar_path, set_user_avatar,
)
from core.gamify import compute_leaderboard

# ==============================
# Base page config
# ==============================
st.set_page_config(
    page_title="Nierwell GPA System",
    page_icon="assets/logo.png",
    layout="wide",
)

# Small CSS helper for a clean, techy look (dark, subtle neon accents)
def inject_base_css(bg_path: str = ""):
    # optional background from settings
    bg_css = f'url("file:///{bg_path.replace("\\\\","/")}"), radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)' if bg_path else 'radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)'
    st.markdown(
        f"""
        <style>
            :root {{
                --nw-bg: #0b1022;
                --nw-card: rgba(255,255,255,0.04);
                --nw-card-border: rgba(255,255,255,0.10);
                --nw-fg: #d8e1ff;
                --nw-dim: #a7b0d8;
                --nw-accent: #5eead4;   /* teal */
                --nw-accent-2: #7c3aed; /* purple */
            }}

            /* App background (with optional image) */
            .stApp {{
                background-image: {bg_css};
                background-size: cover;
                background-position: center;
                background-attachment: fixed;
                color: var(--nw-fg);
            }}

            /* Tighten content */
            .block-container {{
                padding-top: 2.2rem;
            }}

            /* Headings */
            h1, h2, h3 {{
                letter-spacing: 0.2px;
            }}
            h1 {{
                font-weight: 700;
                background: linear-gradient(90deg, var(--nw-accent), var(--nw-accent-2));
                -webkit-background-clip: text;
                background-clip: text;
                color: transparent;
                margin-bottom: 0.25rem;
            }}
            .nw-subtle {{ color: var(--nw-dim); }}

            /* Tech chips */
            .nw-chip {{
                display:inline-block; padding:7px 12px; margin:6px 8px 0 0;
                border-radius:9999px; border:1px solid var(--nw-card-border);
                background: var(--nw-card); font-size:.92rem;
            }}

            /* Glass card */
            .nw-card {{
                border-radius: 18px;
                border: 1px solid var(--nw-card-border);
                background: var(--nw-card);
                box-shadow: 0 20px 60px rgba(0,0,0,.35);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                padding: clamp(18px, 3.6vw, 28px);
            }}

            /* Logo top-right */
            .nw-logo {{
                position: fixed; top: 14px; right: 18px; z-index: 9999;
                padding: 6px 8px; border-radius: 12px;
                background: rgba(255,255,255,0.06);
                border: 1px solid var(--nw-card-border);
                backdrop-filter: blur(6px);
            }}
            .nw-logo img {{ height: 28px; }}

            /* Buttons */
            .stButton > button[kind="primary"] {{
                border-radius: 12px !important;
                background: linear-gradient(90deg, var(--nw-accent), var(--nw-accent-2)) !important;
                color: #0b1022 !important; font-weight: 700 !important;
                border: 0 !important;
            }}
            .stButton > button {{
                border-radius: 12px !important;
            }}

            /* Inputs */
            .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] > div {{
                border-radius: 12px !important;
            }}

            /* Sidebar style */
            [data-testid="stSidebar"] > div:first-child {{
                background: #0d1430;
                border-right: 1px solid rgba(255,255,255,0.08);
            }}

            /* Hide default footer */
            footer {{ visibility: hidden; }}

            /* Welcome screen: center layout */
            .nw-center {{
                min-height: calc(100vh - 120px);
                display:flex; align-items:center; justify-content:center;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def inject_welcome_chrome_hidden():
    st.markdown(
        """
        <style>
            header, [data-testid="stToolbar"], [data-testid="stSidebar"] { display:none !important; }
            .block-container { padding-top: 1.8rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ==============================
# App bootstrap
# ==============================
ensure_store()
settings = load_settings() or {}

if "user" not in st.session_state:
    st.session_state.user = None
if "nav" not in st.session_state:
    st.session_state.nav = "Dashboard"

# Global CSS (background may be overridden on welcome with branding)
inject_base_css(settings.get("welcome_bg_path", ""))

# ==============================
# WELCOME / AUTH (not signed in)
# ==============================
# ---------- WELCOME + AUTH (renovated, fast sign-in) ----------
# ---------- WELCOME + AUTH when NOT signed in ----------
if st.session_state.user is None:
    # Optional background from Settings (only on welcome screen)
    bg_path = str(settings.get("welcome_bg_path", "")).strip()

    # Techy gradient + glass card (no layout changes)
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(1200px 600px at 15% -10%, #0ea5e922, transparent 60%),
                        radial-gradient(1000px 500px at 120% 0%, #22d3ee22, transparent 60%),
                        linear-gradient(180deg, #0b1020 0%, #0e1117 100%);
            color: #e6e8ec;
        }
        .app-hero h1, .app-hero p { color: #e6e8ec !important; }
        .glass {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-radius: 16px;
            padding: 24px 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        /* tighten right column content width slightly */
        section[data-testid="stSidebar"] + div [data-testid="column"]:last-child > div:has(> .glass) {
            max-width: 520px;
            margin-left: auto;
        }
        .muted { color: #9aa4b2 !important; }
        .tip  { color: #a0f0ff !important; font-size: 0.9rem; }
        .tiny { font-size: 0.85rem; color: #93a0ad; }
        .spacer-8 { height: 8px; }
        .spacer-16 { height: 16px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Optional center graphic (user-configurable)
    if bg_path:
        css_bg = bg_path.replace("\\", "/")
        st.markdown(
            f"""
            <style>
            .stApp {{
                background-image: url("file:///{css_bg}"),
                                  radial-gradient(1200px 600px at 15% -10%, #0ea5e922, transparent 60%),
                                  radial-gradient(1000px 500px at 120% 0%, #22d3ee22, transparent 60%),
                                  linear-gradient(180deg, #0b1020 0%, #0e1117 100%);
                background-repeat: no-repeat, no-repeat, no-repeat, no-repeat;
                background-position: center top 80px, left top, right top, center;
                background-size: 420px auto, auto, auto, auto;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    users_df_all = load_users()
    usernames = users_df_all["username"].tolist()

    # Read any remembered user from settings
    remembered_user = str(settings.get("remembered_user", "")).strip()
    remembered_idx = 0
    if remembered_user and remembered_user in usernames:
        remembered_idx = ["— select —"] + usernames.index(remembered_user) * [None]  # dummy to compute
        remembered_idx = (["— select —"] + usernames).index(remembered_user)

    # Top hero (left)
    left, right = st.columns([7, 5], gap="large")

    with left:
        st.markdown('<div class="app-hero">', unsafe_allow_html=True)
        st.title("Nierwell GPA Manager")
        st.caption("Walk into exams prepared.")
        st.subheader("What you can do")
        f1, f2, f3 = st.columns(3)
        with f1:
            st.markdown("### 📚 Subjects")
            st.write("Organize courses, set exam dates, track confidence.")
        with f2:
            st.markdown("### 📝 Daily Log")
            st.write("Record hours, task types, and quick self‑ratings.")
        with f3:
            st.markdown("### 🧪 Self‑Tests")
            st.write("Add scores & difficulty; watch your curve improve.")
        st.markdown(
            '<div class="spacer-16"></div><span class="tip">Pro tip:</span> '
            '<span class="muted">Create your subjects first; everything else unlocks from there.</span>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # Auth (right) — glass card
    with right:
        
        st.subheader("Sign in")
        tab_login, tab_signup = st.tabs(["Login", "Sign up"])

        with tab_login:
            # Quick pick for remembered user (does not auto‑login)
            if remembered_user:
                st.markdown(
                    f"**Quick pick:** {remembered_user}  "
                    f"<span class='tiny'>(stored on this device)</span>", unsafe_allow_html=True
                )
                st.write("")

            # Preselect remembered user if present
            sel_user = st.selectbox(
                "User",
                ["— select —"] + usernames,
                index=remembered_idx if remembered_idx else 0,
                key="login_user_sel",
            )
            pw = st.text_input("Password", type="password", key="login_pw", placeholder="Leave empty if none")

            c1, c2 = st.columns([1, 1])
            with c1:
                remember_me = st.checkbox("Remember me", value=bool(remembered_user))
            with c2:
                st.markdown("<div class='tiny' style='text-align:right'>Press <kbd>Enter</kbd> to submit</div>", unsafe_allow_html=True)

            if st.button("Sign in", type="primary", use_container_width=True):
                if sel_user == "— select —":
                    st.error("Pick a user.")
                else:
                    row = get_user_by_name(sel_user)
                    if row is None:
                        st.error("User not found.")
                    else:
                        if _verify_password(pw, str(row.get("password_hash", ""))):
                            # Persist 'remember me' in settings.json
                            settings_live = load_settings()
                            if remember_me:
                                settings_live["remembered_user"] = sel_user
                            else:
                                settings_live.pop("remembered_user", None)
                            from core.storage import save_settings  # local import to avoid top clutter
                            save_settings(settings_live)

                            st.session_state.user = {"id": row["id"], "username": row["username"]}
                            claim_legacy_rows_for_user(row["id"])
                            st.success(f"Signed in as {row['username']}")
                            st.rerun()
                        else:
                            st.error("Wrong password.")

            st.markdown("<div class='tiny muted'>We never store your password in the browser.</div>", unsafe_allow_html=True)

        with tab_signup:
            new_user = st.text_input("New username", key="signup_user", placeholder="e.g. Aisha, Victor, Team‑Lab‑3")
            new_pw = st.text_input("Password (optional)", type="password", key="signup_pw")
            if st.button("Create account", use_container_width=True):
                if not new_user.strip():
                    st.error("Enter a username.")
                elif get_user_by_name(new_user) is not None:
                    st.error("Username already exists.")
                else:
                    uid = create_user(new_user.strip(), new_pw.strip())
                    if uid:
                        # also remember this freshly created user for convenience
                        settings_live = load_settings()
                        settings_live["remembered_user"] = new_user.strip()
                        from core.storage import save_settings
                        save_settings(settings_live)

                        st.session_state.user = {"id": uid, "username": new_user.strip()}
                        st.success(f"Account created. Welcome, {new_user.strip()}!")
                        st.rerun()
                    else:
                        st.error("Could not create user.")

        st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    st.caption("Need to import existing data? Use **Settings/Backup** after signing in.")
    st.stop()

# ==============================
# SIGNED-IN APP
# ==============================
if st.session_state.get("user"):
    username = st.session_state.user.get("username", "Student")
    st.markdown(f"## 👋 Welcome, **{username}**")

    ironman_quotes = [
        "“I am Iron Man.”",
        "“Genius, billionaire, playboy, philanthropist.”",
        "“Sometimes you gotta run before you can walk.”",
        "“If we can’t protect the Earth, you can be damn sure we’ll avenge it.”",
        "“I shouldn’t be alive, unless it was for a reason.”",
        "“It’s not about how much we lost, it’s about how much we have left.”",
        "“Sometimes you have to learn to run before you can walk.”"
    ]

    quote = random.choice(ironman_quotes)
    st.caption(f"💬 *{quote}*")


# Sidebar—clean, techy look
with st.sidebar:
    st.markdown("Account")
    st.write(f"**{st.session_state.user['username']}**")

    avatar_path = get_user_avatar_path(st.session_state.user["id"])
    if avatar_path and Path(avatar_path).exists():
        st.image(avatar_path, width=96, caption="Profile")
    else:
        st.caption("No profile picture")

    up = st.file_uploader("Update avatar", type=["png","jpg","jpeg","webp"], key="avatar_up")
    if up is not None:
        set_user_avatar(st.session_state.user["id"], up.read(), up.name)
        st.success("Profile updated."); st.rerun()

    st.divider()
    nav = st.radio(
        "Navigation",
        ["Dashboard", "Subjects", "Daily Log", "Self-Tests", "Settings & Backup"],
        label_visibility="collapsed",
        index=["Dashboard", "Subjects", "Daily Log", "Self-Tests", "Settings & Backup"].index(st.session_state.nav)
        if st.session_state.nav in ["Dashboard", "Subjects", "Daily Log", "Self-Tests", "Settings & Backup"] else 0,
    )
    st.session_state.nav = nav

    st.divider()
    if st.button("Sign out", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# Load & filter data per‑user
subjects_df_all = load_df(SUBJECTS_CSV)
logs_df_all     = load_df(LOGS_CSV)
tests_df_all    = load_df(TESTS_CSV)

for df in (logs_df_all, tests_df_all):
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()

uid = st.session_state.user["id"]
subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str) == uid].copy()
logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str) == uid].copy()
tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str) == uid].copy()

# Sidebar quick gamification (compact)
try:
    users_df_all = load_users()
    lb = compute_leaderboard(logs_df_all, tests_df_all, users_df_all)
    me = lb[lb["user_id"] == uid]
    if not me.empty:
        r = me.iloc[0]
        st.sidebar.markdown("### 🏆 Score")
        st.sidebar.metric("Rank", f"#{int(r['rank'])}/{len(lb)}")
        st.sidebar.progress(
            max(0, min(100, int(round(100 * float(r['score']) / (float(lb['score'].max()) or 1.0))))),
            text=f"Score {int(r['score'])}"
        )
except Exception:
    pass

# Router with section header styling
st.markdown("----")
if st.session_state.nav == "Dashboard":
    st.markdown("## 📊 Dashboard")
    dashboard.render(subjects_df, logs_df, tests_df, settings)

elif st.session_state.nav == "Subjects":
    st.markdown("## 📚 Subjects")
    subjects.render(subjects_df, subjects_df_all, logs_df, tests_df, settings)

elif st.session_state.nav == "Daily Log":
    st.markdown("## 📝 Daily Log")
    daily_log.render(subjects_df, logs_df, logs_df_all)

elif st.session_state.nav == "Self-Tests":
    st.markdown("## 🧪 Self‑Tests")
    self_tests.render(subjects_df, tests_df, tests_df_all)

elif st.session_state.nav == "Settings & Backup":
    st.markdown("## ⚙️ Settings & Backup")
    settings_backup.render(settings, subjects_df_all, logs_df_all, tests_df_all)
