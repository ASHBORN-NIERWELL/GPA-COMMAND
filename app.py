# =============================
# File: app.py
# =============================
#
# GPA Command Center — Streamlit app
# Multi-user profiles (optional passwords), per-subject exam dates,
# customizable weights, edit/delete logs, backups, and a richer dashboard.
#
# Dev run:  streamlit run app.py
#
# Requirements (requirements.txt):
#   streamlit==1.48.0
#   pandas==2.3.1
#   numpy==2.3.2
#   pyarrow==21.0.0
#   (optional) bcrypt
#

from __future__ import annotations

import json
import os
import sys
import uuid
import shutil
import hashlib
from typing import Optional, Tuple
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import streamlit as st

# ----------------------
# App identity & storage
# ----------------------
APP_NAME = "GPACommandCenter"

def sanitize_subjects_for_editor(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    out = df.copy()

    # Ensure required columns exist
    if "exam_date" not in out.columns:
        out["exam_date"] = settings.get("default_exam_date", "2025-09-05")
    if "credits" not in out.columns:
        out["credits"] = 2
    if "confidence" not in out.columns:
        out["confidence"] = 5

    # Coerce dtypes for editor
    for col in ["id", "name", "user_id"]:
        if col in out.columns:
            out[col] = out[col].astype("string")

    out["credits"] = pd.to_numeric(out.get("credits"), errors="coerce").fillna(1).astype(int)
    out["confidence"] = pd.to_numeric(out.get("confidence"), errors="coerce").fillna(5).round().clip(0, 10).astype(int)

    # IMPORTANT: DateColumn needs datetime.date dtype
    out["exam_date"] = pd.to_datetime(out.get("exam_date"), errors="coerce")\
                          .dt.date

    # If any remain missing, fill with default exam date as date
    default_date = pd.to_datetime(settings.get("default_exam_date", "2025-09-05"), errors="coerce")
    default_date = default_date.date() if pd.notnull(default_date) else date.today()
    out["exam_date"] = out["exam_date"].apply(lambda d: default_date if pd.isna(d) else d)

    return out


def get_storage_dir() -> Path:
    """A persistent user data dir (works in EXE, avoids temp loss)."""
    env_override = os.getenv("GPA_CC_DATA_DIR")
    if env_override:
        return Path(env_override)

    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME

# Paths
LEGACY_DATA_DIR = Path(__file__).parent / "data"
DATA_DIR        = get_storage_dir()
SUBJECTS_CSV    = DATA_DIR / "subjects.csv"
LOGS_CSV        = DATA_DIR / "logs.csv"
TESTS_CSV       = DATA_DIR / "tests.csv"
SETTINGS_JSON   = DATA_DIR / "settings.json"
USERS_CSV       = DATA_DIR / "users.csv"
BACKUPS_DIR     = DATA_DIR / "backups"

DEFAULT_SETTINGS = {
    "semester": "Sem 2.2",
    "default_exam_date": "2025-09-05",
    "logs_weight": 0.70,
    "tests_weight": 0.30,
    "momentum_days": 7,
    "focus_n": 3,
    "show_upcoming_exams": True,
    "show_recent_activity": True,
}

INITIAL_SUBJECTS = [
    {"id": "chem-eng-basics", "name": "Chemical engineering basics",            "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "micro-scatter",   "name": "Microscopic & scattering techniques",    "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "org-synthesis",   "name": "Organic synthesis",                       "credits": 2, "confidence": 2, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "adv-thermo",      "name": "Advanced thermodynamics",                 "credits": 2, "confidence": 6, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "paint-tech",      "name": "Applied polymer — Paint tech",            "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "tyre-tech",       "name": "Applied polymer — Tyre tech",             "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "fibre-tech",      "name": "Applied polymer — Fibre tech",            "credits": 2, "confidence": 5, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "textile-fibres",  "name": "Textile & fibres",                        "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
]

TASK_TYPES = ["Read", "Problems", "Past paper", "Teaching", "Flashcards"]

# Optional strong hashing
try:
    import bcrypt  # type: ignore
    HAVE_BCRYPT = True
except Exception:
    HAVE_BCRYPT = False

# ----------------------
# Streamlit page config
# ----------------------
st.set_page_config(page_title="GPA Command Center", page_icon="🎯", layout="wide")

# ----------------------
# Storage helpers
# ----------------------
def ensure_store() -> None:
    """Create data folder, migrate legacy, and ensure files/columns exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    # One-time migration from ./data
    try:
        if LEGACY_DATA_DIR.exists() and any(LEGACY_DATA_DIR.iterdir()):
            for fname in ["subjects.csv", "logs.csv", "tests.csv", "settings.json", "users.csv"]:
                src = LEGACY_DATA_DIR / fname
                dst = DATA_DIR / fname
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
    except Exception:
        pass

    if not SETTINGS_JSON.exists():
        SETTINGS_JSON.write_text(json.dumps(DEFAULT_SETTINGS, indent=2))

    if not USERS_CSV.exists():
        pd.DataFrame(columns=["id", "username", "password_hash", "created_at"]).to_csv(USERS_CSV, index=False)

    if not SUBJECTS_CSV.exists():
        df = pd.DataFrame(INITIAL_SUBJECTS)
        df["user_id"] = ""  # unclaimed legacy/global
        df.to_csv(SUBJECTS_CSV, index=False)
    else:
        try:
            df = pd.read_csv(SUBJECTS_CSV)
            changed = False
            if "exam_date" not in df.columns:
                df["exam_date"] = DEFAULT_SETTINGS["default_exam_date"]; changed = True
            if "user_id" not in df.columns:
                df["user_id"] = ""; changed = True
            if changed:
                df.to_csv(SUBJECTS_CSV, index=False)
        except Exception:
            pass

    if not LOGS_CSV.exists():
        pd.DataFrame(columns=["id", "date", "subject_id", "hours", "task", "score", "notes", "user_id"]).to_csv(LOGS_CSV, index=False)
    else:
        try:
            df = pd.read_csv(LOGS_CSV)
            if "user_id" not in df.columns:
                df["user_id"] = ""
                df.to_csv(LOGS_CSV, index=False)
        except Exception:
            pass

    if not TESTS_CSV.exists():
        pd.DataFrame(columns=["id", "date", "subject_id", "score", "difficulty", "notes", "user_id"]).to_csv(TESTS_CSV, index=False)
    else:
        try:
            df = pd.read_csv(TESTS_CSV)
            if "user_id" not in df.columns:
                df["user_id"] = ""
                df.to_csv(TESTS_CSV, index=False)
        except Exception:
            pass

def zip_backup() -> Path:
    """Create a timestamped zip of all CSV/JSON files."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath = BACKUPS_DIR / f"backup_{ts}.zip"
    with ZipFile(zpath, "w", ZIP_DEFLATED) as zf:
        for p in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON, USERS_CSV]:
            if p.exists():
                zf.write(p, arcname=p.name)
    return zpath

@st.cache_data(show_spinner=False)
def load_df(path: Path) -> pd.DataFrame:
    """CSV loader with date parsing for relevant files."""
    name = path.name.lower()
    try:
        if name in {"logs.csv", "tests.csv"}:
            return pd.read_csv(path, parse_dates=["date"], dayfirst=False)
        if name == "subjects.csv":
            return pd.read_csv(path, parse_dates=["exam_date"], dayfirst=False)
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path)

def save_df(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)
    load_df.clear()

def load_settings() -> dict:
    try:
        s = json.loads(SETTINGS_JSON.read_text())
    except Exception:
        s = DEFAULT_SETTINGS.copy()
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s

def save_settings(s: dict) -> None:
    SETTINGS_JSON.write_text(json.dumps(s, indent=2))

# ----------------------
# User management
# ----------------------
def _hash_password(pw: str) -> str:
    if not pw:
        return ""
    if HAVE_BCRYPT:
        return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return "sha256:" + hashlib.sha256(pw.encode("utf-8")).hexdigest()

def _verify_password(pw: str, hashed: str) -> bool:
    if hashed == "" and pw == "":
        return True
    if HAVE_BCRYPT and hashed and not hashed.startswith("sha256:"):
        try:
            return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    return ("sha256:" + hashlib.sha256(pw.encode("utf-8")).hexdigest()) == hashed

@st.cache_data(show_spinner=False)
def load_users() -> pd.DataFrame:
    if USERS_CSV.exists():
        try:
            return pd.read_csv(USERS_CSV)
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "username", "password_hash", "created_at"])

def save_users(df: pd.DataFrame) -> None:
    df.to_csv(USERS_CSV, index=False)
    load_users.clear()

def get_user_by_name(username: str) -> Optional[pd.Series]:
    df = load_users()
    m = df["username"].str.lower() == username.strip().lower()
    return df[m].iloc[0] if m.any() else None

def create_user(username: str, password: str = "") -> Optional[str]:
    username = username.strip()
    if not username:
        return None
    users = load_users()
    if (users["username"].str.lower() == username.lower()).any():
        return None
    uid = str(uuid.uuid4())
    row = {
        "id": uid,
        "username": username,
        "password_hash": _hash_password(password),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    users = pd.concat([users, pd.DataFrame([row])], ignore_index=True)
    save_users(users)
    return uid

def rename_user(user_id: str, new_name: str) -> bool:
    users = load_users()
    if (users["username"].str.lower() == new_name.strip().lower()).any():
        return False
    idx = users.index[users["id"] == user_id]
    if len(idx) == 0:
        return False
    users.loc[idx[0], "username"] = new_name.strip()
    save_users(users)
    return True

def set_user_password(user_id: str, new_password: str) -> None:
    users = load_users()
    idx = users.index[users["id"] == user_id]
    if len(idx):
        users.loc[idx[0], "password_hash"] = _hash_password(new_password)
        save_users(users)

def delete_user(user_id: str, reassign_to: Optional[str]) -> None:
    """Delete a user; optionally reassign their rows to another user_id."""
    users = load_users()
    users = users[users["id"] != user_id]
    save_users(users)

    for path in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV]:
        df = load_df(path)
        if "user_id" in df.columns:
            if reassign_to:
                df.loc[df["user_id"] == user_id, "user_id"] = reassign_to
            else:
                df = df[df["user_id"] != user_id]
            save_df(df, path)

def claim_legacy_rows_for_user(user_id: str) -> None:
    """Rows without user_id belong to first user that logs in (soft migration)."""
    for path in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV]:
        df = load_df(path)
        if "user_id" in df.columns:
            mask = df["user_id"].astype(str).fillna("") == ""
            if mask.any():
                df.loc[mask, "user_id"] = user_id
                save_df(df, path)

# ----------------------
# Metrics
# ----------------------
def days_between(d1, d2) -> int:
    d1 = pd.to_datetime(d1).date()
    d2 = pd.to_datetime(d2).date()
    return (d2 - d1).days

def calc_priority(credits, confidence) -> float:
    return (10 - float(confidence)) * float(credits)

def compute_metrics(subjects: pd.DataFrame, logs: pd.DataFrame, tests: pd.DataFrame) -> pd.DataFrame:
    settings = load_settings()
    w_logs = float(settings.get("logs_weight", 0.70))
    w_tests = float(settings.get("tests_weight", max(0.0, 1.0 - w_logs)))

    hours = logs.groupby("subject_id")["hours"].sum().rename("hours").reset_index()
    tests_avg = tests.groupby("subject_id")["score"].mean().rename("tests_avg").reset_index()
    logs_avg  = logs.groupby("subject_id")["score"].mean().rename("logs_avg").reset_index()

    df = subjects.copy()
    df["exam_date"] = pd.to_datetime(df.get("exam_date"), errors="coerce")
    df["priority"]  = df.apply(lambda r: calc_priority(r["credits"], r["confidence"]), axis=1)

    for agg in [(hours, "hours"), (tests_avg, "tests_avg"), (logs_avg, "logs_avg")]:
        df = df.merge(agg[0], left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"])

    df["hours"]     = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["tests_avg"] = pd.to_numeric(df["tests_avg"], errors="coerce")
    df["logs_avg"]  = pd.to_numeric(df["logs_avg"],  errors="coerce")

    def weighted_avg(row):
        has_logs  = pd.notna(row.get("logs_avg"))
        has_tests = pd.notna(row.get("tests_avg"))
        if has_logs and has_tests:
            return row["logs_avg"] * w_logs + row["tests_avg"] * w_tests
        if has_logs:
            return row["logs_avg"]
        if has_tests:
            return row["tests_avg"]
        return 0.0

    df["avg_score"] = df.apply(weighted_avg, axis=1)

    default_exam = pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]))
    today = date.today()
    df["days_left"] = df["exam_date"].apply(lambda d: max(0, days_between(today, d if pd.notnull(d) else default_exam)))

    df["priority_gap"] = df["priority"] * (1 - (df["avg_score"] / 100.0))
    return df

def weighted_readiness(df_metrics: pd.DataFrame) -> float:
    if df_metrics.empty:
        return 0.0
    num = (df_metrics["priority"] * (df_metrics["avg_score"] / 100.0)).sum()
    den = df_metrics["priority"].sum()
    return float(num / den) if den else 0.0

# ----------------------
# Boot & auth UI
# ----------------------
ensure_store()
settings = load_settings()

if "user" not in st.session_state:
    st.session_state.user = None  # dict: id, username

st.sidebar.subheader("Account")

# Login / Sign up
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
                    # Soft-claim legacy rows (first user)
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

if st.session_state.user:
    st.sidebar.write(f"**Signed in:** {st.session_state.user['username']}")
    if st.button("Sign out"):
        st.session_state.user = None
        st.rerun()
else:
    st.sidebar.info("Not signed in — you can browse, but edits require sign-in.")

# ----------------------
# Load and isolate user data
# ----------------------
subjects_df_all = load_df(SUBJECTS_CSV)
logs_df_all     = load_df(LOGS_CSV)
tests_df_all    = load_df(TESTS_CSV)

if st.session_state.user:
    uid = st.session_state.user["id"]
    subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str) == uid].copy()
    logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str) == uid].copy()
    tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str) == uid].copy()
else:
    # show unclaimed rows only
    blank = ["", "nan", "NaN"]
    subjects_df = subjects_df_all[subjects_df_all.get("user_id", "").astype(str).isin(blank)].copy()
    logs_df     = logs_df_all[logs_df_all.get("user_id", "").astype(str).isin(blank)].copy()
    tests_df    = tests_df_all[tests_df_all.get("user_id", "").astype(str).isin(blank)].copy()

# ----------------------
# Sidebar nav
# ----------------------
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

page = st.sidebar.radio(
    "Navigate",
    ["📊 Dashboard", "📚 Subjects", "📝 Daily Log", "🧪 Self-Tests", "⚙️ Settings/Backup"],
)
# ===== Import / Export helpers =====
def to_date_safe(series: pd.Series) -> pd.Series:
    # Accepts strings, datetimes, NaN; returns datetime.date or NaT
    s = pd.to_datetime(series, errors="coerce")               # parse anything ISO-like
    # if tz-aware, strip timezone without erroring
    try:
        s = s.dt.tz_localize(None)                            # ignore if not tz-aware
    except Exception:
        pass
    return s.dt.date


def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out

def _align_columns(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Make both frames have the union of columns (order-insensitive)."""
    cols = sorted(set(a.columns).union(set(b.columns)))
    return _ensure_columns(a, cols)[cols], _ensure_columns(b, cols)[cols]

def normalize_subjects_df(df: pd.DataFrame, default_exam: str, user_id: str | None) -> pd.DataFrame:
    out = df.copy()

    # required columns
    need = ["id", "name", "credits", "confidence", "exam_date", "user_id"]
    out = _ensure_columns(out, need)

    # ids
    out["id"] = out["id"].astype("string").fillna("")
    mask_blank = out["id"].str.strip() == ""
    out.loc[mask_blank, "id"] = [str(uuid.uuid4()) for _ in range(mask_blank.sum())]

    # strings
    for col in ["name", "user_id"]:
        out[col] = out[col].astype("string").fillna("")

    # numeric ranges
    out["credits"] = pd.to_numeric(out["credits"], errors="coerce").fillna(1).astype(int)
    out["confidence"] = (
        pd.to_numeric(out["confidence"], errors="coerce")
        .fillna(5)
        .round()
        .clip(0, 10)
        .astype(int)
    )

    # dates
    def_exam = pd.to_datetime(default_exam, errors="coerce")
    out["exam_date"] = pd.to_datetime(out["exam_date"], errors="coerce")
    out["exam_date"] = out["exam_date"].fillna(def_exam).dt.strftime("%Y-%m-%d")

    # user_id override
    if user_id is not None:
        out["user_id"] = str(user_id)

    return out[need]

def normalize_logs_df(df: pd.DataFrame, user_id: str | None) -> pd.DataFrame:
    out = df.copy()
    need = ["id", "date", "subject_id", "hours", "task", "score", "notes", "user_id"]
    out = _ensure_columns(out, need)

    out["id"] = out["id"].astype("string").fillna("")
    mask_blank = out["id"].str.strip() == ""
    out.loc[mask_blank, "id"] = [str(uuid.uuid4()) for _ in range(mask_blank.sum())]

    out["subject_id"] = out["subject_id"].astype("string").fillna("")
    out["task"] = out["task"].astype("string").fillna("")
    out["notes"] = out["notes"].astype("string").fillna("")

    out["hours"] = pd.to_numeric(out["hours"], errors="coerce").fillna(0.0)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    out.loc[(out["score"] < 0) | (out["score"] > 100), "score"] = np.nan

    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    if user_id is not None:
        out["user_id"] = str(user_id)

    return out[need]

def normalize_tests_df(df: pd.DataFrame, user_id: str | None) -> pd.DataFrame:
    out = df.copy()
    need = ["id", "date", "subject_id", "score", "difficulty", "notes", "user_id"]
    out = _ensure_columns(out, need)

    out["id"] = out["id"].astype("string").fillna("")
    mask_blank = out["id"].str.strip() == ""
    out.loc[mask_blank, "id"] = [str(uuid.uuid4()) for _ in range(mask_blank.sum())]

    out["subject_id"] = out["subject_id"].astype("string").fillna("")
    out["notes"] = out["notes"].astype("string").fillna("")

    out["score"] = pd.to_numeric(out["score"], errors="coerce").clip(0, 100)
    out["difficulty"] = (
        pd.to_numeric(out["difficulty"], errors="coerce")
        .fillna(3)
        .round()
        .clip(1, 5)
        .astype(int)
    )

    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    if user_id is not None:
        out["user_id"] = str(user_id)

    return out[need]

def _merge_replace_current_user(existing: pd.DataFrame, incoming: pd.DataFrame, uid: str | None) -> pd.DataFrame:
    """Replace ONLY the current user's rows in 'existing' with 'incoming'."""
    if uid is None:
        # admin mode: replace file
        ex_aligned, inc_aligned = _align_columns(existing, incoming)
        return inc_aligned

    # ensure both have same columns
    existing, incoming = _align_columns(existing, incoming)

    # force user_id on incoming
    incoming["user_id"] = str(uid)

    others = existing[existing.get("user_id", "").astype(str) != str(uid)]
    # keep last occurrence by id (incoming rows override)
    cur = incoming.copy()
    merged_cur = (
        pd.concat([existing[existing.get("user_id", "").astype(str) == str(uid)], cur], ignore_index=True)
        .drop_duplicates(subset=["id"], keep="last")
    )
    out = pd.concat([others, merged_cur], ignore_index=True)
    return out

def _append_current_user(existing: pd.DataFrame, incoming: pd.DataFrame, uid: str | None) -> pd.DataFrame:
    """Append/overwrite by id ONLY for current user; keep everyone else intact."""
    if uid is None:
        # admin mode: append all and drop dup IDs (last wins)
        existing, incoming = _align_columns(existing, incoming)
        out = pd.concat([existing, incoming], ignore_index=True)
        if "id" in out.columns:
            out = out.drop_duplicates(subset=["id"], keep="last")
        return out

    existing, incoming = _align_columns(existing, incoming)
    incoming["user_id"] = str(uid)

    others = existing[existing.get("user_id", "").astype(str) != str(uid)]
    current = existing[existing.get("user_id", "").astype(str) == str(uid)]

    merged_cur = (
        pd.concat([current, incoming], ignore_index=True)
        .drop_duplicates(subset=["id"], keep="last")
    )
    out = pd.concat([others, merged_cur], ignore_index=True)
    return out

# ----------------------
# Pages
# ----------------------
if page == "📊 Dashboard":
    st.title(f"GPA Command Center — {settings.get('semester','Sem')}")
    metrics = compute_metrics(subjects_df, logs_df, tests_df)

    c1, c2, c3 = st.columns(3)
    with c1:
        if not metrics.empty:
            focus_row = metrics.sort_values("priority_gap", ascending=False).iloc[0]
            st.metric("Focus today on", focus_row["name"], delta=f"Gap {focus_row['priority_gap']:.2f}")
        else:
            st.info("Add subjects to get a focus suggestion.")
    with c2:
        ready = weighted_readiness(metrics)
        st.metric("Overall readiness (weighted)", f"{round(ready*100):d}%")
    with c3:
        st.metric("Study momentum", f"{len(logs_df)} logs • {len(tests_df)} tests")

    focus_n = int(settings.get("focus_n", 3))
    st.subheader(f"Top {focus_n} focus areas (by priority gap)")
    if len(metrics):
        topn = metrics.sort_values("priority_gap", ascending=False).head(focus_n)[["name", "priority_gap", "avg_score", "hours", "days_left"]]
        st.dataframe(topn.set_index("name"), use_container_width=True)
    else:
        st.caption("No subjects yet.")

    st.subheader("Hours by subject")
    hb = metrics[["name", "hours"]].set_index("name")
    st.bar_chart(hb)

    momentum_days = int(settings.get("momentum_days", 7))
    st.subheader(f"Study momentum (last {momentum_days} days)")
    if len(logs_df):
        logs = logs_df.copy()
        logs["date"] = pd.to_datetime(logs["date"], errors="coerce", format="mixed").dt.date
        logs = logs.dropna(subset=["date"])

        cutoff = date.today() - timedelta(days=momentum_days - 1)
        recent = logs[logs["date"] >= cutoff]
        daily = recent.groupby("date")["hours"].sum().reset_index().set_index("date")
        st.line_chart(daily)
    else:
        st.caption("No logs yet.")

    st.subheader("Knowledge curve (tests average by date)")
        
    
    if len(tests_df):
        curve = tests_df.copy()
        curve["date"] = pd.to_datetime(curve["date"], errors="coerce", format="mixed").dt.date
        curve = curve.dropna(subset=["date"])

        curve = curve.groupby("date")["score"].mean().reset_index().set_index("date")
        st.line_chart(curve)
    else:
        st.caption("No test scores yet.")

    if settings.get("show_upcoming_exams", True):
        st.subheader("Upcoming exams")
        if len(metrics):
            upcoming = metrics.sort_values(["days_left", "priority_gap"]).loc[:, ["name", "exam_date", "days_left", "priority_gap", "avg_score"]]
            st.dataframe(upcoming.set_index("name"), use_container_width=True)
        else:
            st.caption("No subjects yet.")

    if settings.get("show_recent_activity", True):
        st.subheader("Recent activity")
        if len(logs_df):
            ra = logs_df.copy()
            ra["date"] = pd.to_datetime(ra["date"]).dt.strftime("%Y-%m-%d")
            st.dataframe(ra.sort_values("date", ascending=False).head(10), use_container_width=True)
        else:
            st.caption("No recent logs.")
            

elif page == "📚 Subjects":
    st.title("Subjects & Priorities")
    st.caption("Keep credits accurate; adjust confidence weekly. Set exam date per subject.")

    # Make the dataframe editor-safe (especially exam_date -> datetime.date)
    subjects_editor_df = sanitize_subjects_for_editor(subjects_df, settings)

    edited = st.data_editor(
        subjects_editor_df,
        column_config={
            "id": st.column_config.TextColumn(disabled=True),
            "name": st.column_config.TextColumn(label="Subject"),
            "credits": st.column_config.NumberColumn(min_value=1, step=1),
            "confidence": st.column_config.NumberColumn(min_value=0, max_value=10, step=1),
            "exam_date": st.column_config.DateColumn(label="Exam date", format="YYYY-MM-DD"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="subjects_editor",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("➕ Add subject"):
            s = settings
            new = {
                "id": str(uuid.uuid4()),
                "name": "New subject",
                "credits": 2,
                "confidence": 5,
                "exam_date": s.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]),
                "user_id": st.session_state.user["id"] if st.session_state.user else "",
            }
            # append and save
            edited = pd.concat([edited, pd.DataFrame([new])], ignore_index=True)
            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

            if st.session_state.user:
                uid = st.session_state.user["id"]
                others = subjects_df_all[subjects_df_all.get("user_id", "") != uid]
                edited["user_id"] = uid
                save_df(pd.concat([others, edited], ignore_index=True), SUBJECTS_CSV)
            else:
                save_df(edited, SUBJECTS_CSV)
            st.rerun()

    with c2:
        if st.button("💾 Save changes"):
            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

            if st.session_state.user:
                uid = st.session_state.user["id"]
                others = subjects_df_all[subjects_df_all.get("user_id", "") != uid]
                edited["user_id"] = uid
                save_df(pd.concat([others, edited], ignore_index=True), SUBJECTS_CSV)
            else:
                save_df(edited, SUBJECTS_CSV)

            st.success("Saved.")
            st.rerun()

    st.divider()
    st.subheader("Computed metrics")
    metrics = compute_metrics(edited, logs_df, tests_df)
    st.dataframe(
        metrics[["name", "credits", "confidence", "exam_date", "priority", "hours", "avg_score", "days_left", "priority_gap"]],
        use_container_width=True,
    )


elif page == "📝 Daily Log":
    st.title("Daily Log")

    with st.form("add_log"):
        c1, c2, c3 = st.columns(3)
        with c1:
            log_date = st.date_input("Date", value=date.today())
        with c2:
            subj_opts = {row["name"]: row["id"] for _, row in subjects_df.iterrows()}
            subj_name = st.selectbox("Subject", list(subj_opts.keys()))
            subj_id = subj_opts[subj_name]
        with c3:
            hours = st.number_input("Hours", min_value=0.0, step=0.25, value=1.5)
        t1, t2, t3 = st.columns(3)
        with t1:
            task = st.selectbox("Task type", TASK_TYPES)
        with t2:
            score = st.number_input("Quick self-test % (optional)", min_value=0, max_value=100, step=1, value=0)
        with t3:
            notes = st.text_input("Notes", value="")
        submitted = st.form_submit_button("Add entry")

        if submitted:
            if not st.session_state.user:
                st.warning("Please sign in to add logs.")
            else:
                new_row = {
                    "id": str(uuid.uuid4()),
                    "date": log_date.strftime("%Y-%m-%d"),
                    "subject_id": subj_id,
                    "hours": float(hours),
                    "task": task,
                    "score": int(score) if score else np.nan,
                    "notes": notes,
                    "user_id": st.session_state.user["id"],
                }
                updated = pd.concat([logs_df_all, pd.DataFrame([new_row])], ignore_index=True)
                save_df(updated, LOGS_CSV)
                st.success("Log added.")
                st.rerun()

    st.subheader("Edit or delete logs")
    editable = logs_df.copy()
    if "date" in editable.columns:
        editable["date"] = pd.to_datetime(editable["date"], errors="coerce").dt.date
    if "delete" not in editable.columns:
        editable["delete"] = False
    # enforce dtypes for editor
    for col in ["subject_id", "task", "notes"]:
        if col in editable.columns:
            editable[col] = editable[col].astype("string")
    for col in ["hours", "score"]:
        if col in editable.columns:
            editable[col] = pd.to_numeric(editable[col], errors="coerce")

    subject_ids = subjects_df["id"].tolist() if len(subjects_df) else []

    edited_view = st.data_editor(
        editable,
        column_config={
            "id": st.column_config.TextColumn(help="Unique log ID", disabled=True),
            "date": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "subject_id": st.column_config.SelectboxColumn(label="Subject", options=subject_ids),
            "hours": st.column_config.NumberColumn(step=0.25, min_value=0.0),
            "task": st.column_config.SelectboxColumn(options=TASK_TYPES),
            "score": st.column_config.NumberColumn(min_value=0, max_value=100, step=1),
            "notes": st.column_config.TextColumn(),
            "delete": st.column_config.CheckboxColumn(help="Tick to delete"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="logs_editor",
    )

    csave, cdel = st.columns([1, 1])
    with csave:
        if st.button("💾 Save edits"):
            if not st.session_state.user:
                st.warning("Please sign in to save.")
            else:
                edited_view["id"] = edited_view["id"].fillna("")
                mask_new = edited_view["id"] == ""
                edited_view.loc[mask_new, "id"] = [str(uuid.uuid4()) for _ in range(mask_new.sum())]
                edited_view["hours"] = pd.to_numeric(edited_view.get("hours"), errors="coerce").fillna(0.0)
                if "score" in edited_view.columns:
                    edited_view["score"] = pd.to_numeric(edited_view["score"], errors="coerce")
                for col in ["subject_id", "task", "notes"]:
                    if col in edited_view.columns:
                        edited_view[col] = edited_view[col].astype("string").fillna("")
                edited_view["user_id"] = st.session_state.user["id"]

                uid = st.session_state.user["id"]
                others = logs_df_all[logs_df_all.get("user_id", "") != uid]
                to_save_all = pd.concat([others, edited_view.drop(columns=["delete"], errors="ignore")], ignore_index=True)
                save_df(to_save_all, LOGS_CSV)
                st.success("Edits saved.")
                st.rerun()

    with cdel:
        if st.button("🗑️ Delete checked rows"):
            if not st.session_state.user:
                st.warning("Please sign in to delete.")
            else:
                uid = st.session_state.user["id"]
                keep_current = edited_view[edited_view.get("delete", False) != True].drop(columns=["delete"], errors="ignore")
                keep_current["user_id"] = uid
                others = logs_df_all[logs_df_all.get("user_id", "") != uid]
                remaining_all = pd.concat([others, keep_current], ignore_index=True)
                save_df(remaining_all, LOGS_CSV)
                st.success("Selected logs deleted.")
                st.rerun()

    st.caption("Subject ID → Name map:")
    if len(subjects_df):
        map_df = subjects_df[["id", "name"]].rename(columns={"id": "Subject ID", "name": "Subject name"})
        st.dataframe(map_df, use_container_width=True, hide_index=True)

elif page == "🧪 Self-Tests":
    st.title("Self-Test Tracker")

    with st.form("add_test"):
        c1, c2, c3 = st.columns(3)
        with c1:
            test_date = st.date_input("Date", value=date.today(), key="test_date")
        with c2:
            subj_opts = {row["name"]: row["id"] for _, row in subjects_df.iterrows()}
            subj_name = st.selectbox("Subject", list(subj_opts.keys()), key="test_subject")
            subj_id = subj_opts[subj_name]
        with c3:
            score = st.number_input("Score (%)", min_value=0, max_value=100, step=1, value=60)
        d1, d2 = st.columns(2)
        with d1:
            difficulty = st.slider("Difficulty (1–5)", min_value=1, max_value=5, value=3)
        with d2:
            notes = st.text_input("Notes", value="")
        submitted = st.form_submit_button("Add test")

        if submitted:
            if not st.session_state.user:
                st.warning("Please sign in to add tests.")
            else:
                new_row = {
                    "id": str(uuid.uuid4()),
                    "date": test_date.strftime("%Y-%m-%d"),
                    "subject_id": subj_id,
                    "score": int(score),
                    "difficulty": int(difficulty),
                    "notes": notes,
                    "user_id": st.session_state.user["id"],
                }
                updated = pd.concat([tests_df_all, pd.DataFrame([new_row])], ignore_index=True)
                save_df(updated, TESTS_CSV)
                st.success("Test added.")
                st.rerun()

    st.subheader("Your test history")
    st.dataframe(tests_df.sort_values("date", ascending=False), use_container_width=True)

elif page == "⚙️ Settings/Backup":
    st.title("Settings & Backup")
    st.caption("Global options, weights, users, and import/export.")
    st.info(f"Data folder: {DATA_DIR}")

    # Always create tabs first
    tabs = st.tabs(["App settings", "Manage users", "Backup/Export/Import"])

    # ---- App settings
    with tabs[0]:
        with st.form("settings"):
            colA, colB = st.columns([1, 1])
            with colA:
                semester = st.text_input("Semester label", value=settings.get("semester", DEFAULT_SETTINGS["semester"]))
                focus_n = st.number_input("Top N focus subjects on dashboard", min_value=1, max_value=10, value=int(settings.get("focus_n", 3)))
                momentum_days = st.number_input("Momentum window (days)", min_value=3, max_value=30, value=int(settings.get("momentum_days", 7)))
            with colB:
                default_exam = st.date_input(
                    "Default exam date (for new subjects & fallback)",
                    value=pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]), errors="coerce").date(),
                )
                logs_weight = st.slider("Logs weight (avg score)", min_value=0.0, max_value=1.0, step=0.05, value=float(settings.get("logs_weight", 0.70)))
                tests_weight = round(1.0 - logs_weight, 2)
                st.write(f"Tests weight auto-set to **{int(tests_weight*100)}%**")
                show_upcoming = st.checkbox("Show Upcoming exams", value=bool(settings.get("show_upcoming_exams", True)))
                show_recent = st.checkbox("Show Recent activity", value=bool(settings.get("show_recent_activity", True)))

            apply_to_empty = st.checkbox("Apply default exam date to subjects with empty exam_date", value=False)
            submitted = st.form_submit_button("💾 Save settings")
            if submitted:
                settings.update({
                    "semester": semester,
                    "default_exam_date": default_exam.strftime("%Y-%m-%d"),
                    "focus_n": int(focus_n),
                    "momentum_days": int(momentum_days),
                    "logs_weight": float(logs_weight),
                    "tests_weight": float(tests_weight),
                    "show_upcoming_exams": bool(show_upcoming),
                    "show_recent_activity": bool(show_recent),
                })
                save_settings(settings)
                if apply_to_empty:
                    s = load_df(SUBJECTS_CSV)
                    s["exam_date"] = pd.to_datetime(s.get("exam_date"), errors="coerce")
                    mask = s["exam_date"].isna()
                    s.loc[mask, "exam_date"] = pd.to_datetime(settings["default_exam_date"])
                    s["exam_date"] = pd.to_datetime(s["exam_date"]).dt.strftime("%Y-%m-%d")
                    save_df(s, SUBJECTS_CSV)
                st.success("Settings saved.")
                st.rerun()

    # ---- Manage users
    with tabs[1]:
        st.subheader("Users")
        users = load_users().copy()
        if len(users) == 0:
            st.info("No users yet. Create one from the sidebar → Sign up.")
        else:
            st.dataframe(users[["id", "username", "created_at"]], hide_index=True, use_container_width=True)

        st.markdown("### Edit user")
        if len(users):
            user_labels = [f"{r['username']} ({r['id'][:8]})" for _, r in users.iterrows()]
            choice = st.selectbox("Select user", options=["— select —"] + user_labels, index=0)
            if choice != "— select —":
                idx = user_labels.index(choice)
                row = users.iloc[idx]
                target_id = str(row["id"])

                new_name = st.text_input("Rename (optional)", value=row["username"])
                new_pw   = st.text_input("Set/Reset password (optional)", type="password", help="Leave blank to keep existing/none.")
                colx, coly, colz = st.columns(3)
                with colx:
                    if st.button("Save user changes"):
                        ok = True
                        if new_name.strip() and new_name.strip().lower() != str(row["username"]).lower():
                            ok = rename_user(target_id, new_name.strip())
                            if not ok:
                                st.error("Username already exists.")
                        if ok and new_pw.strip():
                            set_user_password(target_id, new_pw.strip())
                        if ok:
                            st.success("User updated.")
                            st.rerun()
                with coly:
                    other_users = users[users["id"] != target_id]
                    reassign_to = None
                    if len(other_users):
                        lab = [f"{r['username']} ({r['id'][:8]})" for _, r in other_users.iterrows()]
                        sel = st.selectbox("Reassign data to (optional)", ["— none —"] + lab)
                        if sel != "— none —":
                            reassign_to = str(other_users.iloc[lab.index(sel)]["id"])
                    if st.button("Delete user"):
                        if st.session_state.user and st.session_state.user["id"] == target_id:
                            st.error("Can't delete the currently signed-in user.")
                        else:
                            delete_user(target_id, reassign_to)
                            st.success("User deleted.")
                            st.rerun()
                with colz:
                    if st.button("Claim legacy rows for this user"):
                        claim_legacy_rows_for_user(target_id)
                        st.success("Unowned rows assigned.")
                        st.rerun()

    # ---- Backup/Export/Import
    with tabs[2]:
        st.subheader("Backups")
        colb1, colb2 = st.columns(2)
        with colb1:
            if st.button("Create backup ZIP"):
                z = zip_backup()
                st.success(f"Backup created: {z.name}")
                with open(z, "rb") as f:
                    st.download_button("Download latest backup", data=f.read(), file_name=z.name, key="dl_backup_zip")
        with colb2:
            uploaded_zip = st.file_uploader("Restore from backup (ZIP)", type=["zip"])
            if uploaded_zip is not None:
                tmp = BACKUPS_DIR / f"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                with open(tmp, "wb") as f:
                    f.write(uploaded_zip.read())
                from zipfile import ZipFile
                with ZipFile(tmp, "r") as zf:
                    zf.extractall(DATA_DIR)
                load_df.clear(); load_users.clear()
                st.success("Backup restored.")
                st.rerun()

        st.divider()
        st.subheader("Export CSVs")

        export_scope = st.radio(
            "What to export?",
            ["Current user only", "All data (admin)"],
            horizontal=True,
            key="export_scope",
        )

        # Build export frames
        if export_scope == "Current user only" and st.session_state.user:
            uid = st.session_state.user["id"]
            subj_exp = subjects_df_all[subjects_df_all.get("user_id", "") == uid]
            logs_exp = logs_df_all[logs_df_all.get("user_id", "") == uid]
            tests_exp = tests_df_all[tests_df_all.get("user_id", "") == uid]
        else:
            subj_exp = subjects_df_all
            logs_exp = logs_df_all
            tests_exp = tests_df_all

        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button("Download subjects.csv", data=subj_exp.to_csv(index=False), file_name="subjects.csv", key="exp_sub")
        with c2:
            st.download_button("Download logs.csv", data=logs_exp.to_csv(index=False), file_name="logs.csv", key="exp_logs")
        with c3:
            st.download_button("Download tests.csv", data=tests_exp.to_csv(index=False), file_name="tests.csv", key="exp_tests")

        st.divider()
        st.subheader("Import CSVs")

        st.caption("Choose how imported rows should be applied. Dates and IDs will be normalized automatically.")
        import_mode = st.selectbox(
            "Import mode",
            [
                "Append to current user (recommended)",
                "Replace current user's data",
                "Replace entire file (admin)",
            ],
            index=0,
            help="Append = keep existing rows and add/overwrite by id. Replace current user = only your rows are replaced. Replace entire file = admin-level overwrite.",
        )

        # Normalizers + merges (helpers defined right here to avoid NameError)
        def _ensure_id_strings(df):
            if "id" in df.columns:
                df["id"] = df["id"].astype(str)
            return df

        def normalize_subjects_df(df, default_exam, uid_or_none):
            df = df.copy()
            for c in ["id", "name"]:
                if c not in df.columns:
                    df[c] = ""
            if "credits" not in df.columns: df["credits"] = 2
            if "confidence" not in df.columns: df["confidence"] = 5
            df["credits"] = pd.to_numeric(df["credits"], errors="coerce").fillna(1).astype(int)
            df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(5).clip(0,10).astype(int)
            df["exam_date"] = pd.to_datetime(df.get("exam_date"), errors="coerce")
            df["exam_date"] = df["exam_date"].fillna(pd.to_datetime(default_exam))
            df["exam_date"] = df["exam_date"].dt.strftime("%Y-%m-%d")
            if uid_or_none is not None:
                df["user_id"] = uid_or_none
            df = _ensure_id_strings(df)
            return df

        def normalize_logs_df(df, uid_or_none):
            df = df.copy()
            for c in ["id","date","subject_id","hours","task","score","notes"]:
                if c not in df.columns: df[c] = np.nan if c in ["hours","score"] else ""
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
            if uid_or_none is not None:
                df["user_id"] = uid_or_none
            df = _ensure_id_strings(df)
            return df

        def normalize_tests_df(df, uid_or_none):
            df = df.copy()
            for c in ["id","date","subject_id","score","difficulty","notes"]:
                if c not in df.columns: df[c] = np.nan if c in ["score","difficulty"] else ""
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
            df["difficulty"] = pd.to_numeric(df["difficulty"], errors="coerce").fillna(3).clip(1,5).astype(int)
            if uid_or_none is not None:
                df["user_id"] = uid_or_none
            df = _ensure_id_strings(df)
            return df

        def _merge_replace_current_user(existing, incoming, uid):
            existing = existing.copy()
            # drop current user's rows and add incoming
            left = existing[existing.get("user_id","") != uid]
            return pd.concat([left, incoming], ignore_index=True)

        def _append_current_user(existing, incoming, uid):
            existing = existing.copy()
            # Upsert by 'id' for current user
            if "id" not in incoming.columns:
                incoming["id"] = [str(uuid.uuid4()) for _ in range(len(incoming))]
            mask = existing.get("user_id","") == uid
            cur = existing[mask]
            others = existing[~mask]
            # Remove any incoming ids from current, then append
            cur = cur[~cur["id"].isin(incoming["id"])]
            cur = pd.concat([cur, incoming], ignore_index=True)
            return pd.concat([others, cur], ignore_index=True)

        coli1, coli2, coli3 = st.columns(3)
        with coli1:
            f1 = st.file_uploader("subjects.csv", type=["csv"], key="imp_sub")
        with coli2:
            f2 = st.file_uploader("logs.csv", type=["csv"], key="imp_logs")
        with coli3:
            f3 = st.file_uploader("tests.csv", type=["csv"], key="imp_tests")

        if st.button("Run import"):
            if import_mode != "Replace entire file (admin)" and not st.session_state.user:
                st.warning("Sign in to import for a specific user.")
            else:
                uid = st.session_state.user["id"] if st.session_state.user else None
                default_exam = settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"])

                if f1 is not None:
                    try:
                        incoming = pd.read_csv(f1)
                        incoming = normalize_subjects_df(incoming, default_exam, uid if import_mode != "Replace entire file (admin)" else None)
                        if import_mode == "Replace entire file (admin)":
                            save_df(incoming, SUBJECTS_CSV)
                        elif import_mode == "Replace current user's data":
                            merged = _merge_replace_current_user(load_df(SUBJECTS_CSV), incoming, uid)
                            save_df(merged, SUBJECTS_CSV)
                        else:
                            merged = _append_current_user(load_df(SUBJECTS_CSV), incoming, uid)
                            save_df(merged, SUBJECTS_CSV)
                        st.success("subjects.csv imported.")
                    except Exception as e:
                        st.error(f"subjects.csv import failed: {e}")

                if f2 is not None:
                    try:
                        incoming = pd.read_csv(f2)
                        incoming = normalize_logs_df(incoming, uid if import_mode != "Replace entire file (admin)" else None)
                        if import_mode == "Replace entire file (admin)":
                            save_df(incoming, LOGS_CSV)
                        elif import_mode == "Replace current user's data":
                            merged = _merge_replace_current_user(load_df(LOGS_CSV), incoming, uid)
                            save_df(merged, LOGS_CSV)
                        else:
                            merged = _append_current_user(load_df(LOGS_CSV), incoming, uid)
                            save_df(merged, LOGS_CSV)
                        st.success("logs.csv imported.")
                    except Exception as e:
                        st.error(f"logs.csv import failed: {e}")

                if f3 is not None:
                    try:
                        incoming = pd.read_csv(f3)
                        incoming = normalize_tests_df(incoming, uid if import_mode != "Replace entire file (admin)" else None)
                        if import_mode == "Replace entire file (admin)":
                            save_df(incoming, TESTS_CSV)
                        elif import_mode == "Replace current user's data":
                            merged = _merge_replace_current_user(load_df(TESTS_CSV), incoming, uid)
                            save_df(merged, TESTS_CSV)
                        else:
                            merged = _append_current_user(load_df(TESTS_CSV), incoming, uid)
                            save_df(merged, TESTS_CSV)
                        st.success("tests.csv imported.")
                    except Exception as e:
                        st.error(f"tests.csv import failed: {e}")

                load_df.clear()
                st.info("Import complete.")
                st.rerun()
