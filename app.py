# =============================
# File: app.py
# =============================
#
# GPA Command Center — Streamlit app
# Reusable study tracker with per‑subject exam dates, customizable settings,
# edit/delete logs, weighted readiness, and a richer dashboard.
#
# Dev run:  streamlit run app.py
# Build EXE: use launch.py + PyInstaller
#
# Requirements (requirements.txt):
#   streamlit
#   pandas
#   numpy
#

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ----------------------
# Paths & defaults
# ----------------------
import sys
import shutil

APP_NAME = "GPACommandCenter"

# Resolve a persistent storage directory per-OS (prevents data loss with PyInstaller)

def get_storage_dir() -> Path:
    # Allow override via environment
    env_override = os.getenv("GPA_CC_DATA_DIR")
    if env_override:
        return Path(env_override)
    if os.name == "nt":  # Windows
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux & others
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME

# Legacy project-relative data folder (for migration)
LEGACY_DATA_DIR = Path(__file__).parent / "data"
DATA_DIR = get_storage_dir()
SUBJECTS_CSV = DATA_DIR / "subjects.csv"
LOGS_CSV = DATA_DIR / "logs.csv"
TESTS_CSV = DATA_DIR / "tests.csv"
SETTINGS_JSON = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "semester": "Sem 2.2",
    "default_exam_date": "2025-09-05",  # ISO date string
    # NEW: custom weights & dashboard prefs
    "logs_weight": 0.70,
    "tests_weight": 0.30,
    "momentum_days": 7,
    "focus_n": 3,
    "show_upcoming_exams": True,
    "show_recent_activity": True,
}

INITIAL_SUBJECTS = [
    {"id": "chem-eng-basics", "name": "Chemical engineering basics", "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "micro-scatter", "name": "Microscopic & scattering techniques", "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "org-synthesis", "name": "Organic synthesis", "credits": 2, "confidence": 2, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "adv-thermo", "name": "Advanced thermodynamics", "credits": 2, "confidence": 6, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "paint-tech", "name": "Applied polymer — Paint tech", "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "tyre-tech", "name": "Applied polymer — Tyre tech", "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "fibre-tech", "name": "Applied polymer — Fibre tech", "credits": 2, "confidence": 5, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "textile-fibres", "name": "Textile & fibres", "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
]

TASK_TYPES = ["Read", "Problems", "Past paper", "Teaching", "Flashcards"]

st.set_page_config(page_title="GPA Command Center", page_icon="🎯", layout="wide")

# ----------------------
# Helpers
# ----------------------

def ensure_store():
    # Create persistent dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # One-time migration from legacy ./data next to script (use newest files)
    try:
        if LEGACY_DATA_DIR.exists() and any(LEGACY_DATA_DIR.iterdir()):
            for fname in ["subjects.csv", "logs.csv", "tests.csv", "settings.json"]:
                legacy = LEGACY_DATA_DIR / fname
                target = DATA_DIR / fname
                if legacy.exists() and not target.exists():
                    shutil.copy2(legacy, target)
    except Exception:
        pass

    # Create settings if missing
    if not SETTINGS_JSON.exists():
        SETTINGS_JSON.write_text(json.dumps(DEFAULT_SETTINGS, indent=2))

    # Create CSVs if missing (do NOT overwrite existing)
    if not SUBJECTS_CSV.exists():
        pd.DataFrame(INITIAL_SUBJECTS).to_csv(SUBJECTS_CSV, index=False)
    else:
        # migrate existing subjects.csv to include exam_date if missing
        try:
            df = pd.read_csv(SUBJECTS_CSV)
            if "exam_date" not in df.columns:
                df["exam_date"] = DEFAULT_SETTINGS["default_exam_date"]
                df.to_csv(SUBJECTS_CSV, index=False)
        except Exception:
            pass
    if not LOGS_CSV.exists():
        pd.DataFrame(columns=["id", "date", "subject_id", "hours", "task", "score", "notes"]).to_csv(LOGS_CSV, index=False)
    if not TESTS_CSV.exists():
        pd.DataFrame(columns=["id", "date", "subject_id", "score", "difficulty", "notes"]).to_csv(TESTS_CSV, index=False)

def load_settings() -> dict:
    try:
        s = json.loads(SETTINGS_JSON.read_text())
    except Exception:
        s = DEFAULT_SETTINGS.copy()
    # Backfill new keys
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s



def save_settings(s: dict):
    SETTINGS_JSON.write_text(json.dumps(s, indent=2))


@st.cache_data(show_spinner=False)
def load_df(path: Path) -> pd.DataFrame:
    """Read CSVs; parse date columns where relevant."""
    name = Path(path).name.lower()
    if name in {"logs.csv", "tests.csv"}:
        try:
            return pd.read_csv(path, parse_dates=["date"], dayfirst=False)
        except Exception:
            return pd.read_csv(path)
    if name == "subjects.csv":
        try:
            return pd.read_csv(path, parse_dates=["exam_date"], dayfirst=False)
        except Exception:
            return pd.read_csv(path)
    return pd.read_csv(path)


def save_df(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False)
    load_df.clear()  # invalidate cache


def days_between(d1, d2) -> int:
    d1 = pd.to_datetime(d1).date()
    d2 = pd.to_datetime(d2).date()
    return (d2 - d1).days


def calc_priority(credits, confidence) -> float:
    return (10 - float(confidence)) * float(credits)


def compute_metrics(subjects: pd.DataFrame, logs: pd.DataFrame, tests: pd.DataFrame) -> pd.DataFrame:
    """Compute per‑subject metrics with customizable weighting for avg_score."""
    settings = load_settings()
    w_logs = float(settings.get("logs_weight", 0.70))
    w_tests = float(settings.get("tests_weight", max(0.0, 1.0 - w_logs)))

    # Aggregate inputs
    hours = logs.groupby("subject_id")["hours"].sum().rename("hours").reset_index()
    tests_avg = tests.groupby("subject_id")["score"].mean().rename("tests_avg").reset_index()
    logs_avg  = logs.groupby("subject_id")["score"].mean().rename("logs_avg").reset_index()

    df = subjects.copy()
    df["exam_date"] = pd.to_datetime(df.get("exam_date"), errors="coerce")
    df["priority"]  = df.apply(lambda r: calc_priority(r["credits"], r["confidence"]), axis=1)

    # Merge aggregates
    df = df.merge(hours,     left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"])  # hours
    df = df.merge(tests_avg, left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"])  # tests_avg
    df = df.merge(logs_avg,  left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"])  # logs_avg

    # Coerce and fill
    df["hours"]     = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["tests_avg"] = pd.to_numeric(df["tests_avg"], errors="coerce")
    df["logs_avg"]  = pd.to_numeric(df["logs_avg"],  errors="coerce")

    # Weighted average: w_logs logs, w_tests tests; fallback to whichever exists
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

    # Days left per subject
    default_exam = pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]))
    today = date.today()
    df["days_left"] = df["exam_date"].apply(lambda d: max(0, days_between(today, d if pd.notnull(d) else default_exam)))

    # Priority gap
    df["priority_gap"] = df["priority"] * (1 - (df["avg_score"] / 100.0))
    return df


def weighted_readiness(df_metrics: pd.DataFrame) -> float:
    if df_metrics.empty:
        return 0.0
    num = (df_metrics["priority"] * (df_metrics["avg_score"] / 100.0)).sum()
    den = df_metrics["priority"].sum()
    if den == 0:
        return 0.0
    return float(num / den)


# ----------------------
# UI — Sidebar
# ----------------------
ensure_store()
settings = load_settings()
subjects_df = load_df(SUBJECTS_CSV)
logs_df = load_df(LOGS_CSV)
tests_df = load_df(TESTS_CSV)

page = st.sidebar.radio(
    "Navigate",
    ["📊 Dashboard", "📚 Subjects", "📝 Daily Log", "🧪 Self‑Tests", "⚙️ Settings/Backup"],
)

# sidebar summary text (triple‑quoted f-string)
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

# ----------------------
# Dashboard
# ----------------------
if page == "📊 Dashboard":
    st.title(f"GPA Command Center — {settings.get('semester','Sem')}")
    metrics = compute_metrics(subjects_df, logs_df, tests_df)

    # Top summary cards
    col1, col2, col3 = st.columns(3)
    with col1:
        if not metrics.empty:
            focus_row = metrics.sort_values("priority_gap", ascending=False).iloc[0]
            st.metric(label="Focus today on", value=focus_row["name"], delta=f"Gap {focus_row['priority_gap']:.2f}")
        else:
            st.info("Add subjects to get a focus suggestion.")
    with col2:
        ready = weighted_readiness(metrics)
        st.metric(label="Overall readiness (weighted)", value=f"{round(ready*100):d}%")
    with col3:
        st.metric(label="Study momentum", value=f"{len(logs_df)} logs • {len(tests_df)} tests")

    # Focus list (Top N by gap)
    focus_n = int(settings.get("focus_n", 3))
    st.subheader(f"Top {focus_n} focus areas (by priority gap)")
    if len(metrics):
        topn = metrics.sort_values("priority_gap", ascending=False).head(focus_n)[["name", "priority_gap", "avg_score", "hours", "days_left"]]
        st.dataframe(topn.set_index("name"), use_container_width=True)
    else:
        st.caption("No subjects yet.")

    # Hours by subject (bar)
    st.subheader("Hours by subject")
    hb = metrics[["name", "hours"]].set_index("name")
    st.bar_chart(hb)

    # Momentum (last X days)
    momentum_days = int(settings.get("momentum_days", 7))
    st.subheader(f"Study momentum (last {momentum_days} days)")
    if len(logs_df):
        logs = logs_df.copy()
        logs["date"] = pd.to_datetime(logs["date"]).dt.date
        cutoff = date.today() - timedelta(days=momentum_days-1)
        recent = logs[logs["date"] >= cutoff]
        daily = recent.groupby("date")["hours"].sum().reset_index().set_index("date")
        st.line_chart(daily)
    else:
        st.caption("No logs yet.")

    # Knowledge curve from tests (optional)
    st.subheader("Knowledge curve (tests average by date)")
    if len(tests_df):
        curve = tests_df.copy()
        curve["date"] = pd.to_datetime(curve["date"]).dt.date
        curve = curve.groupby("date")["score"].mean().reset_index().set_index("date")
        st.line_chart(curve)
    else:
        st.caption("No test scores yet.")

    # Upcoming exams
    if settings.get("show_upcoming_exams", True):
        st.subheader("Upcoming exams")
        if len(metrics):
            upcoming = metrics.sort_values(["days_left", "priority_gap"]).loc[:, ["name", "exam_date", "days_left", "priority_gap", "avg_score"]]
            st.dataframe(upcoming.set_index("name"), use_container_width=True)
        else:
            st.caption("No subjects yet.")

    # Recent activity
    if settings.get("show_recent_activity", True):
        st.subheader("Recent activity")
        if len(logs_df):
            ra = logs_df.copy()
            ra["date"] = pd.to_datetime(ra["date"]).dt.strftime("%Y-%m-%d")
            st.dataframe(ra.sort_values("date", ascending=False).head(10), use_container_width=True)
        else:
            st.caption("No recent logs.")

# ----------------------
# Subjects
# ----------------------
elif page == "📚 Subjects":
    st.title("Subjects & Priorities")
    st.caption("Tip: Keep credits accurate; adjust confidence weekly. Lower confidence ⇒ higher priority. Also set exam date per subject here.")

    # Ensure the column exists for safety
    if "exam_date" not in subjects_df.columns:
        subjects_df["exam_date"] = load_settings().get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"])

    edited = st.data_editor(
        subjects_df,
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

    c1, c2 = st.columns([1,1])
    with c1:
        if st.button("➕ Add subject"):
            s = load_settings()
            new = {
                "id": str(uuid.uuid4()),
                "name": "New subject",
                "credits": 2,
                "confidence": 5,
                "exam_date": s.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]),
            }
            edited = pd.concat([edited, pd.DataFrame([new])], ignore_index=True)
            save_df(edited, SUBJECTS_CSV)
            st.rerun()

    with c2:
        if st.button("💾 Save changes"):
            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            save_df(edited, SUBJECTS_CSV)
            st.success("Saved.")
            st.rerun()

    st.divider()
    st.subheader("Computed metrics")
    metrics = compute_metrics(edited, logs_df, tests_df)
    st.dataframe(metrics[["name", "credits", "confidence", "exam_date", "priority", "hours", "avg_score", "days_left", "priority_gap"]], use_container_width=True)

# ----------------------
# Daily Log (add + edit/delete)
# ----------------------
elif page == "📝 Daily Log":
    st.title("Daily Log")

    # Quick add
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
            score = st.number_input("Quick self‑test % (optional)", min_value=0, max_value=100, step=1, value=0)
        with t3:
            notes = st.text_input("Notes", value="")

        submitted = st.form_submit_button("Add entry")
        if submitted:
            new_row = {
                "id": str(uuid.uuid4()),
                "date": log_date.strftime("%Y-%m-%d"),
                "subject_id": subj_id,
                "hours": float(hours),
                "task": task,
                "score": int(score) if score else np.nan,
                "notes": notes,
            }
            logs_df = pd.concat([logs_df, pd.DataFrame([new_row])], ignore_index=True)
            save_df(logs_df, LOGS_CSV)
            st.success("Log added.")
            st.rerun()

    st.subheader("Edit or delete logs")

    editable = logs_df.copy()
    # Ensure types for editor
    if "date" in editable.columns:
        editable["date"] = pd.to_datetime(editable["date"], errors="coerce").dt.date
    editable["subject_id"] = editable.get("subject_id").astype("string") if "subject_id" in editable.columns else ""
    editable["task"] = editable.get("task").astype("string") if "task" in editable.columns else ""
    editable["notes"] = editable.get("notes").astype("string") if "notes" in editable.columns else ""
    editable["hours"] = pd.to_numeric(editable.get("hours"), errors="coerce") if "hours" in editable.columns else 0.0
    editable["score"] = pd.to_numeric(editable.get("score"), errors="coerce") if "score" in editable.columns else np.nan

    if "delete" not in editable.columns:
        editable["delete"] = False

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

    csave, cdel = st.columns([1,1])
    with csave:
        if st.button("💾 Save edits"):
            edited_view["id"] = edited_view["id"].fillna("")
            mask_new = edited_view["id"] == ""
            edited_view.loc[mask_new, "id"] = [str(uuid.uuid4()) for _ in range(mask_new.sum())]

            # Coerce types again before saving
            edited_view["hours"] = pd.to_numeric(edited_view.get("hours"), errors="coerce").fillna(0.0)
            if "score" in edited_view.columns:
                edited_view["score"] = pd.to_numeric(edited_view["score"], errors="coerce")
            for col in ["subject_id", "task", "notes"]:
                if col in edited_view.columns:
                    edited_view[col] = edited_view[col].astype("string").fillna("")

            to_save = edited_view.drop(columns=["delete"], errors="ignore")
            save_df(to_save, LOGS_CSV)
            logs_df = to_save
            st.success("Edits saved.")
            st.rerun()

    with cdel:
        if st.button("🗑️ Delete checked rows"):
            remaining = edited_view[edited_view.get("delete", False) != True].drop(columns=["delete"], errors="ignore")
            save_df(remaining, LOGS_CSV)
            logs_df = remaining
            st.success("Selected logs deleted.")
            st.rerun()

    st.caption("Subject ID → Name map:")
    if len(subjects_df):
        map_df = subjects_df[["id", "name"]].rename(columns={"id": "Subject ID", "name": "Subject name"})
        st.dataframe(map_df, use_container_width=True, hide_index=True)

# ----------------------
# Self‑Tests
# ----------------------
elif page == "🧪 Self‑Tests":
    st.title("Self‑Test Tracker")

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
            new_row = {
                "id": str(uuid.uuid4()),
                "date": test_date.strftime("%Y-%m-%d"),
                "subject_id": subj_id,
                "score": int(score),
                "difficulty": int(difficulty),
                "notes": notes,
            }
            tests_df = pd.concat([tests_df, pd.DataFrame([new_row])], ignore_index=True)
            save_df(tests_df, TESTS_CSV)
            st.success("Test added.")
            st.rerun()

    st.subheader("Your test history")
    st.dataframe(tests_df.sort_values("date", ascending=False), use_container_width=True)

# ----------------------
# Settings / Backup (semester & default exam date + weights)
# ----------------------
elif page == "⚙️ Settings/Backup":
    st.title("Settings & Backup")
    st.caption("Set global options, weights, and export/import data.")
    st.info(f"Data folder: {DATA_DIR}")

    with st.form("settings"):
        colA, colB = st.columns([1,1])
        with colA:
            semester = st.text_input("Semester label", value=settings.get("semester", DEFAULT_SETTINGS["semester"]))
            focus_n = st.number_input("Top N focus subjects on dashboard", min_value=1, max_value=10, value=int(settings.get("focus_n", 3)))
            momentum_days = st.number_input("Momentum window (days)", min_value=3, max_value=30, value=int(settings.get("momentum_days", 7)))
        with colB:
            default_exam = st.date_input(
                "Default exam date (for new subjects & fallback)",
                value=pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]).strip()).date(),
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

    st.subheader("Export")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download subjects.csv", data=subjects_df.to_csv(index=False), file_name="subjects.csv")
    with c2:
        st.download_button("Download logs.csv", data=logs_df.to_csv(index=False), file_name="logs.csv")
    with c3:
        st.download_button("Download tests.csv", data=tests_df.to_csv(index=False), file_name="tests.csv")

    st.subheader("Import")
    up1, up2, up3 = st.columns(3)
    with up1:
        f1 = st.file_uploader("subjects.csv", type=["csv"], key="u1")
        if f1 is not None:
            df = pd.read_csv(f1)
            save_df(df, SUBJECTS_CSV)
            st.success("subjects.csv imported. Reloading…")
            st.rerun()
    with up2:
        f2 = st.file_uploader("logs.csv", type=["csv"], key="u2")
        if f2 is not None:
            df = pd.read_csv(f2)
            save_df(df, LOGS_CSV)
            st.success("logs.csv imported. Reloading…")
            st.rerun()
    with up3:
        f3 = st.file_uploader("tests.csv", type=["csv"], key="u3")
        if f3 is not None:
            df = pd.read_csv(f3)
            save_df(df, TESTS_CSV)
            st.success("tests.csv imported. Reloading…")
            st.rerun()

    st.divider()
    if st.button("Reset to defaults (clears data folder)"):
        for p in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON]:
            if Path(p).exists():
                Path(p).unlink()
        ensure_store()
        st.success("Data reset.")
        st.rerun()

