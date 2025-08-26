# app.py
from __future__ import annotations
import sys, os, json, random
from pathlib import Path

# Ensure project root on path (so "core.*" and "app_pages.*" import cleanly)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

# ==============================
# Bootstrap Firebase (prod-safe)
# ==============================
def _bootstrap_firebase_env_from_secrets():
    """
    If FIREBASE env vars aren't set, populate them from st.secrets["FIREBASE"].
    This lets core.storage connect to Firestore/Storage in production.
    """
    try:
        cfg = st.secrets.get("FIREBASE", {})
    except Exception:
        cfg = {}

    if not cfg:
        return

    # Materialize service account JSON to a temp file
    sa_raw = cfg.get("service_account_json", "")
    if sa_raw:
        p = Path("/tmp/firebase_sa.json")
        try:
            if isinstance(sa_raw, dict):
                p.write_text(json.dumps(sa_raw), encoding="utf-8")
            else:
                p.write_text(sa_raw, encoding="utf-8")
            os.environ.setdefault("FIREBASE_CREDENTIALS", str(p))
        except Exception:
            pass

    if cfg.get("project_id"):
        os.environ.setdefault("FIREBASE_PROJECT_ID", str(cfg["project_id"]))
    if cfg.get("storage_bucket"):
        os.environ.setdefault("FIREBASE_STORAGE_BUCKET", str(cfg["storage_bucket"]))
    # Prefer ON in prod unless explicitly disabled
    os.environ.setdefault("USE_FIREBASE", "1")

_bootstrap_firebase_env_from_secrets()

# ---------- Pages ----------
import app_pages.dashboard as dashboard
import app_pages.subjects as subjects
import app_pages.daily_log as daily_log
import app_pages.self_tests as self_tests
import app_pages.settings_backup as settings_backup
# import app_pages.leaderboard as leaderboard  # optional

# Optional diagnostics page (use if present)
try:
    import app_pages.firebase_check as firebase_check  # your layout
except Exception:
    firebase_check = None

# ---------- Core ----------
from core.config import SUBJECTS_CSV, LOGS_CSV, TESTS_CSV
from core.storage import ensure_store, load_df, load_settings, save_df
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
    bg_css = (
        f'url("file:///{bg_path.replace("\\\\","/")}"), radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)'
        if bg_path else
        'radial-gradient(80% 120% at 100% 0%, #0f172a 10%, #0b1022 70%)'
    )
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
if st.session_state.user is None:
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
        .muted {{ color: #9aa4b2 !important; }}
        .tip  {{ color: #a0f0ff !important; font-size: 0.9rem; }}
        .tiny {{ font-size: 0.85rem; color: #93a0ad; }}
        .spacer-8 {{ height: 8px; }}
        .spacer-16 {{ height: 16px; }}
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

    # Read any remembered user from settings (preselect if present)
    remembered_user = str(settings.get("remembered_user", "")).strip()
    remembered_idx = (["— select —"] + usernames).index(remembered_user) if remembered_user in usernames else 0

    left, right = st.columns([7, 5], gap="large")

    # ---------- Left: marketing / features ----------
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
            st.write("Record hours, task types, and quick self-ratings.")
        with f3:
            st.markdown("### 🧪 Self-Tests")
            st.write("Add scores & difficulty; watch your curve improve.")
        st.markdown(
            '<div class="spacer-16"></div><span class="tip">Pro tip:</span> '
            '<span class="muted">Create your subjects first; everything else unlocks from there.</span>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

        # ---------- Restore (ALL users) block lives INSIDE the welcome screen ----------
        from core.storage import restore_from_zip_all_users, SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, USERS_CSV
        with st.expander("🔧 Restore data from backup (all users)"):
            st.caption("Upload a ZIP created by the app’s Backup page. This restores subjects, logs, tests, users, and optionally settings for **all** users.")
            mode = st.radio("Restore mode", ["Merge (safe, default)", "Replace ALL (danger)"], horizontal=True, index=0)
            up = st.file_uploader("Backup ZIP", type=["zip"], accept_multiple_files=False, key="welcome_restore_zip")
            col1, col2 = st.columns([1,1])
            with col1:
                if st.button("Run restore", type="primary", use_container_width=True, disabled=up is None):
                    if up is None:
                        st.warning("Please choose a ZIP.")
                    else:
                        rep = restore_from_zip_all_users(up.read(), mode=("merge" if mode.startswith("Merge") else "replace_all"))
                        st.success("Restore complete.")
                        st.json(rep)  # or render a compact summary
                        st.toast("Data restored. You can now sign in.", icon="✅")
                        # Force fresh reads for load_users(), load_df(), etc.
                        st.cache_data.clear()
                        st.rerun()
            with col2:
                st.caption("CSV files used by the app:")
                st.code(f"{SUBJECTS_CSV}\n{LOGS_CSV}\n{TESTS_CSV}\n{USERS_CSV}")

    # ---------- Right: auth ----------
    with right:
        st.subheader("Sign in")
        tab_login, tab_signup = st.tabs(["Login", "Sign up"])

        with tab_login:
            # Quick pick for remembered user (does not auto-login)
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
                index=remembered_idx,
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
            new_user = st.text_input("New username", key="signup_user", placeholder="e.g. Aisha, Victor, Team-Lab-3")
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
    st.caption(f"💬 *{random.choice(ironman_quotes)}*")

# Sidebar — account + nav
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
    nav_items = ["Dashboard", "Subjects", "Daily Log", "Self-Tests", "Settings & Backup", "🔍 Firebase Check"]
    nav = st.radio(
        "Navigation",
        nav_items,
        label_visibility="collapsed",
        index=nav_items.index(st.session_state.nav) if st.session_state.nav in nav_items else 0,
    )
    st.session_state.nav = nav

    st.divider()
    if st.button("Sign out", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# Load & filter data per-user
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
    st.markdown("## 🧪 Self-Tests")
    self_tests.render(subjects_df, tests_df, tests_df_all)

elif st.session_state.nav == "Settings & Backup":
    st.markdown("## ⚙️ Settings & Backup")
    settings_backup.render(settings, subjects_df_all, logs_df_all, tests_df_all)

else:
    # 🔍 Firebase Check
    if firebase_check and hasattr(firebase_check, "render"):
        firebase_check.render()
    else:
        # Built-in minimal checker exercising your normal save/load path
        st.markdown("## 🔍 Firebase Check")
        st.caption("This writes a tiny row to logs and immediately reads it back via your storage layer.")
        from datetime import datetime
        import uuid
        if st.button("Write test row"):
            try:
                df_all = load_df(LOGS_CSV)
                row = pd.DataFrame([{
                    "id": str(uuid.uuid4()),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "subject_id": "firebase-check",
                    "hours": 0.1,
                    "task": "check",
                    "score": None,
                    "notes": "Firebase test row",
                    "user_id": st.session_state.user["id"],
                }])
                updated = pd.concat([df_all, row], ignore_index=True)
                updated["date"] = pd.to_datetime(updated["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                save_df(updated, LOGS_CSV)
                st.success("✅ Wrote a test row. Reloading…")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Write failed: {e}")

        try:
            df = load_df(LOGS_CSV)
            view = df.sort_values("date", ascending=False).head(12)
            st.dataframe(view, use_container_width=True, hide_index=True)
            if (view.get("subject_id") == "firebase-check").any():
                st.success("Firestore/Storage path looks healthy — test row is visible.")
            else:
                st.info("No diagnostic row yet. Click “Write test row”.")
        except Exception as e:
            st.error(f"❌ Read failed: {e}")
