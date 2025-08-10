# core/storage.py
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd
import streamlit as st

from .config import (
    DEFAULT_SETTINGS, DATA_DIR, BACKUPS_DIR, LEGACY_DATA_DIR,
    SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, SETTINGS_JSON, USERS_CSV,
    INITIAL_SUBJECTS, AVATARS_DIR,
)


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # one-time migration from ./data
    try:
        if LEGACY_DATA_DIR.exists() and any(LEGACY_DATA_DIR.iterdir()):
            for fname in ["subjects.csv", "logs.csv", "tests.csv", "settings.json", "users.csv"]:
                src, dst = LEGACY_DATA_DIR / fname, DATA_DIR / fname
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
    except Exception:
        pass

    # settings.json
    if not SETTINGS_JSON.exists():
        SETTINGS_JSON.write_text(json.dumps(DEFAULT_SETTINGS, indent=2), encoding="utf-8")

    # users.csv (ensure avatar_path exists)
    if not USERS_CSV.exists():
        pd.DataFrame(
            columns=["id", "username", "password_hash", "created_at", "avatar_path"]
        ).to_csv(USERS_CSV, index=False, encoding="utf-8")
    else:
        try:
            df = pd.read_csv(USERS_CSV)
            changed = False
            if "avatar_path" not in df.columns:
                df["avatar_path"] = ""
                changed = True
            if changed:
                df.to_csv(USERS_CSV, index=False, encoding="utf-8")
        except Exception:
            pass

    # subjects.csv
    if not SUBJECTS_CSV.exists():
        df = pd.DataFrame(INITIAL_SUBJECTS)
        df["user_id"] = ""
        df.to_csv(SUBJECTS_CSV, index=False, encoding="utf-8")
    else:
        try:
            df = pd.read_csv(SUBJECTS_CSV)
            changed = False
            if "exam_date" not in df.columns:
                df["exam_date"] = DEFAULT_SETTINGS["default_exam_date"]; changed = True
            if "user_id" not in df.columns:
                df["user_id"] = ""; changed = True
            if changed:
                df.to_csv(SUBJECTS_CSV, index=False, encoding="utf-8")
        except Exception:
            pass

    # logs/tests — backfill missing columns if needed
    needed_logs  = ["id", "date", "subject_id", "hours", "task", "score", "notes", "user_id"]
    needed_tests = ["id", "date", "subject_id", "score", "difficulty", "notes", "user_id"]
    for p, needed in [(LOGS_CSV, needed_logs), (TESTS_CSV, needed_tests)]:
        if not p.exists():
            pd.DataFrame(columns=needed).to_csv(p, index=False, encoding="utf-8")
        else:
            try:
                df = pd.read_csv(p)
                changed = False
                for col in needed:
                    if col not in df.columns:
                        df[col] = "" if col in ["id", "date", "subject_id", "task", "notes", "user_id"] else pd.NA
                        changed = True
                if changed:
                    df.to_csv(p, index=False, encoding="utf-8")
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
    """
    Cached CSV loader with date parsing. Clears via load_df.clear()
    """
    name = path.name.lower()
    try:
        if name in {"logs.csv", "tests.csv"}:
            return pd.read_csv(path, parse_dates=["date"], dayfirst=False, encoding="utf-8")
        if name == "subjects.csv":
            return pd.read_csv(path, parse_dates=["exam_date"], dayfirst=False, encoding="utf-8")
        return pd.read_csv(path, encoding="utf-8")
    except Exception:
        # fallback if pandas chokes on encoding/engine
        return pd.read_csv(path, engine="python", encoding_errors="ignore")


def save_df(df: pd.DataFrame, path: Path) -> None:
    """Atomic write with small retry for Windows file locks; busts load_df cache."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8")
    for _ in range(5):
        try:
            tmp.replace(path)  # atomic on most OSes
            break
        except PermissionError:
            time.sleep(0.2)
    load_df.clear()  # invalidate cache for next read


def load_settings() -> dict:
    try:
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        s = DEFAULT_SETTINGS.copy()
    # backfill any new defaults
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s


def save_settings(s: dict) -> None:
    SETTINGS_JSON.write_text(json.dumps(s, indent=2), encoding="utf-8")
