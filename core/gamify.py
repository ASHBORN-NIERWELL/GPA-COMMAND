# core/gamify.py
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Dict, Tuple

import numpy as np
import pandas as pd


# -----------------------------
# Streak helpers
# -----------------------------
def _streak_days(dates: pd.Series) -> int:
    """Longest streak of consecutive days with any activity."""
    if dates is None or len(dates) == 0:
        return 0
    days = pd.to_datetime(dates, errors="coerce").dt.date.dropna().unique()
    if len(days) == 0:
        return 0
    days = sorted(days)
    longest = cur = 1
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            cur += 1
        else:
            longest = max(longest, cur)
            cur = 1
    return max(longest, cur)


def _recent_streak(dates: pd.Series) -> int:
    """Current ongoing streak up to today."""
    if dates is None or len(dates) == 0:
        return 0
    s = set(pd.to_datetime(dates, errors="coerce").dt.date.dropna().tolist())
    streak = 0
    d = date.today()
    while d in s:
        streak += 1
        d -= timedelta(days=1)
    return streak


# -----------------------------
# Defensive column prep
# -----------------------------
def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out


# -----------------------------
# Leaderboard
# -----------------------------
def compute_leaderboard(
    logs_all: pd.DataFrame,
    tests_all: pd.DataFrame,
    users_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Scoring:
      +10 pts per study hour
      +2  pts per test % (avg)
      +2  * difficulty per test entry
      +2  pts per day in current streak
      +1  pt  per day in best streak
    """
    logs = _ensure_cols(logs_all, ["user_id", "hours", "date"]).copy()
    tests = _ensure_cols(tests_all, ["user_id", "score", "difficulty", "date"]).copy()

    # dtypes
    logs["hours"] = pd.to_numeric(logs["hours"], errors="coerce").fillna(0.0)
    logs["date"] = pd.to_datetime(logs["date"], errors="coerce")

    tests["score"] = pd.to_numeric(tests["score"], errors="coerce")
    tests["difficulty"] = pd.to_numeric(tests["difficulty"], errors="coerce").fillna(0.0)
    tests["date"] = pd.to_datetime(tests["date"], errors="coerce")

    # aggregates
    hours = logs.groupby("user_id", as_index=True)["hours"].sum(min_count=1)
    tests_avg = tests.groupby("user_id", as_index=True)["score"].mean()
    tests_bonus = tests.groupby("user_id", as_index=True)["difficulty"].sum(min_count=1) * 2.0

    # streaks (using logs dates)
    streak_cur_series = logs.groupby("user_id", as_index=True)["date"].apply(_recent_streak)
    streak_best_series = logs.groupby("user_id", as_index=True)["date"].apply(_streak_days)

    # users base
    users = users_df.copy()
    if "id" not in users.columns:
        users["id"] = ""
    if "username" not in users.columns:
        users["username"] = "(user)"
    users["user_id"] = users["id"].astype(str)

    # map aggregates to users list (ensures all users appear)
    uid = users["user_id"]
    lb = pd.DataFrame({
        "user_id": uid,
        "username": users["username"],
        "hours": uid.map(hours).fillna(0.0).astype(float),
        "tests_avg": uid.map(tests_avg).fillna(0.0).astype(float),
        "test_bonus": uid.map(tests_bonus).fillna(0.0).astype(float),
        "streak_cur": pd.to_numeric(uid.map(streak_cur_series), errors="coerce").fillna(0.0).astype(float),
        "streak_best": pd.to_numeric(uid.map(streak_best_series), errors="coerce").fillna(0.0).astype(float),
    })

    lb["score"] = (
        (lb["hours"] * 10.0)
        + (lb["tests_avg"] * 2.0)
        + lb["test_bonus"]
        + (lb["streak_cur"] * 2.0)
        + (lb["streak_best"] * 1.0)
    )

    lb = lb.sort_values(["score", "hours", "tests_avg"], ascending=False).reset_index(drop=True)
    lb["rank"] = lb.index + 1
    return lb[["rank", "username", "score", "hours", "tests_avg", "streak_cur", "streak_best", "user_id"]]


# -----------------------------
# Recent highlights
# -----------------------------
def recent_highlights(logs_all: pd.DataFrame, tests_all: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """Recent long sessions (>=2h) and high scores (>=80%) in the last N days."""
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days - 1)
    items: List[Dict] = []

    logs = _ensure_cols(logs_all, ["user_id", "hours", "date"]).copy()
    logs["hours"] = pd.to_numeric(logs["hours"], errors="coerce").fillna(0.0)
    logs["date"] = pd.to_datetime(logs["date"], errors="coerce")
    long_logs = logs[(logs["date"] >= cutoff) & (logs["hours"] >= 2.0)]
    for _, r in long_logs.iterrows():
        if pd.notna(r["date"]):
            items.append({
                "when": r["date"].date(),
                "user_id": r["user_id"],
                "type": "study",
                "detail": f"{r['hours']:.1f}h session"
            })

    tests = _ensure_cols(tests_all, ["user_id", "score", "date"]).copy()
    tests["score"] = pd.to_numeric(tests["score"], errors="coerce")
    tests["date"] = pd.to_datetime(tests["date"], errors="coerce")
    great = tests[(tests["date"] >= cutoff) & (tests["score"] >= 80)]
    for _, r in great.iterrows():
        if pd.notna(r["date"]):
            items.append({
                "when": r["date"].date(),
                "user_id": r["user_id"],
                "type": "test",
                "detail": f"Scored {int(r['score'])}%"
            })

    if not items:
        return pd.DataFrame(columns=["when", "user_id", "type", "detail"])
    return pd.DataFrame(items).sort_values("when", ascending=False)


# -----------------------------
# Achievements (for dashboard bar)
# -----------------------------
def _count_completed(subjects_df: pd.DataFrame) -> int:
    if subjects_df is None or subjects_df.empty:
        return 0
    if "completed" not in subjects_df.columns:
        return 0
    return int(subjects_df["completed"].astype(str).str.lower().isin(["true", "1", "yes"]).sum())


def _any_perfect(subjects_df: pd.DataFrame, tests_df: pd.DataFrame, logs_df: pd.DataFrame) -> bool:
    """
    "Perfect 100" — proxy: any subject with avg score >= 100, or
    if you compute a combined score elsewhere, you can pass a merged frame.
    Here we check tests/logs averages by subject_id if available.
    """
    try:
        # Prefer tests
        t = _ensure_cols(tests_df, ["subject_id", "score"]).copy()
        t["score"] = pd.to_numeric(t["score"], errors="coerce")
        by = t.dropna(subset=["subject_id"]).groupby("subject_id")["score"].mean()
        if len(by) and (by >= 100).any():
            return True

        # Fallback to logs score if present
        l = _ensure_cols(logs_df, ["subject_id", "score"]).copy()
        l["score"] = pd.to_numeric(l["score"], errors="coerce")
        by2 = l.dropna(subset=["subject_id"]).groupby("subject_id")["score"].mean()
        if len(by2) and (by2 >= 100).any():
            return True
    except Exception:
        pass
    return False


def _total_hours(logs_df: pd.DataFrame) -> float:
    if logs_df is None or logs_df.empty:
        return 0.0
    logs = _ensure_cols(logs_df, ["hours"]).copy()
    return float(pd.to_numeric(logs["hours"], errors="coerce").fillna(0.0).sum())


def _current_streak(logs_df: pd.DataFrame) -> int:
    if logs_df is None or logs_df.empty:
        return 0
    return _recent_streak(pd.to_datetime(logs_df.get("date"), errors="coerce"))


def get_achievement_states(
    subjects_df: pd.DataFrame,
    logs_df: pd.DataFrame,
    tests_df: pd.DataFrame
) -> List[Dict[str, object]]:
    """
    Returns a list of achievement state dicts:
      { id, label, description, unlocked (bool), progress (0..1) }
    Progress gives a fill level for a radial/progress bar.
    """
    subjects_df = subjects_df.copy() if subjects_df is not None else pd.DataFrame()
    logs_df = logs_df.copy() if logs_df is not None else pd.DataFrame()
    tests_df = tests_df.copy() if tests_df is not None else pd.DataFrame()

    completed_cnt = _count_completed(subjects_df)
    hours_total = _total_hours(logs_df)
    cur_streak = _current_streak(logs_df)
    any_perfect = _any_perfect(subjects_df, tests_df, logs_df)

    ach: List[Dict[str, object]] = []

    # 1) First Finish
    unlocked = completed_cnt >= 1
    ach.append({
        "id": "first_finish",
        "label": "First Finish",
        "description": "Mark any subject as complete.",
        "unlocked": unlocked,
        "progress": min(1.0, completed_cnt / 1.0),
    })

    # 2) 5 Done
    unlocked = completed_cnt >= 5
    ach.append({
        "id": "five_finishes",
        "label": "5 Done",
        "description": "Complete 5 subjects.",
        "unlocked": unlocked,
        "progress": min(1.0, completed_cnt / 5.0),
    })

    # 3) Perfect 100
    ach.append({
        "id": "perfect_subject",
        "label": "Perfect 100",
        "description": "Reach a perfect 100 score on any subject.",
        "unlocked": bool(any_perfect),
        "progress": 1.0 if any_perfect else 0.0,
    })

    # 4) 7-Day Streak
    ach.append({
        "id": "streak_7",
        "label": "7-Day Streak",
        "description": "Study 7 days in a row.",
        "unlocked": cur_streak >= 7,
        "progress": min(1.0, cur_streak / 7.0),
    })

    # 5) 20 Study Hours (lifetime)
    ach.append({
        "id": "hours_20",
        "label": "20 Hours",
        "description": "Accumulate 20 hours of study.",
        "unlocked": hours_total >= 20.0,
        "progress": min(1.0, hours_total / 20.0),
    })

    return ach
