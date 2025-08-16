# core/gamify.py
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import numpy as np

def _streak_days(dates: pd.Series) -> int:
    """Longest streak of consecutive days with any activity."""
    if dates is None or len(dates) == 0:
        return 0
    days = sorted(pd.to_datetime(dates, errors="coerce").dt.date.dropna().unique())
    if not days:
        return 0
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

def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out

def compute_leaderboard(logs_all: pd.DataFrame, tests_all: pd.DataFrame, users_df: pd.DataFrame) -> pd.DataFrame:
    """
    Scoring:
      +10 pts per study hour
      +2 pts per test % (avg)
      +2 * difficulty per test entry
      +2 pts per day in current streak, +1 per day in best streak
    """
    logs  = _ensure_cols(logs_all,  ["user_id", "hours", "date"]).copy()
    tests = _ensure_cols(tests_all, ["user_id", "score", "difficulty", "date"]).copy()

    # dtypes
    logs["hours"] = pd.to_numeric(logs["hours"], errors="coerce").fillna(0.0)
    logs["date"]  = pd.to_datetime(logs["date"],  errors="coerce")
    tests["score"] = pd.to_numeric(tests["score"], errors="coerce")
    tests["difficulty"] = pd.to_numeric(tests["difficulty"], errors="coerce").fillna(0.0)
    tests["date"]  = pd.to_datetime(tests["date"], errors="coerce")

    # aggregates
    hours       = logs.groupby("user_id")["hours"].sum(min_count=1)
    tests_avg   = tests.groupby("user_id")["score"].mean()               # no min_count arg for mean
    tests_bonus = tests.groupby("user_id")["difficulty"].sum(min_count=1) * 2.0

    # streaks
    streak_cur  = logs.groupby("user_id")["date"].apply(_recent_streak)
    streak_best = logs.groupby("user_id")["date"].apply(_streak_days)

    # assemble
    users = users_df.copy()
    if "id" not in users.columns:
        users["id"] = ""
    if "username" not in users.columns:
        users["username"] = "(user)"

    users["user_id"] = users["id"].astype(str)

    lb = pd.DataFrame({
        "user_id":    users["user_id"],
        "username":   users["username"],
        "hours":      users["user_id"].map(hours).fillna(0.0),
        "tests_avg":  users["user_id"].map(tests_avg).fillna(0.0),
        "test_bonus": users["user_id"].map(tests_bonus).fillna(0.0),
        "streak_cur": users["user_id"].map(streak_cur).fillna(0.0),
        "streak_cur":  users["user_id"].map(streak_cur).fillna(0.0),
        "streak_cur":  pd.to_numeric(users["user_id"].map(streak_cur), errors="coerce").fillna(0.0).astype(float),
        "streak_best": pd.to_numeric(users["user_id"].map(streak_best), errors="coerce").fillna(0.0).astype(float),
        "streak_best": users["user_id"].map(streak_best).fillna(0.0),
        "streak_best":users["user_id"].map(streak_best).fillna(0.0),
    })

    lb["score"] = (lb["hours"] * 10.0) + (lb["tests_avg"] * 2.0) + lb["test_bonus"] + (lb["streak_cur"] * 2.0) + (lb["streak_best"] * 1.0)
    lb = lb.sort_values(["score", "hours", "tests_avg"], ascending=False).reset_index(drop=True)
    lb["rank"] = lb.index + 1
    return lb[["rank", "username", "score", "hours", "tests_avg", "streak_cur", "streak_best", "user_id"]]

def recent_highlights(logs_all: pd.DataFrame, tests_all: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """Recent long sessions (>=2h) and high scores (>=80%) in the last N days."""
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days - 1)
    items: list[dict] = []

    logs = _ensure_cols(logs_all, ["user_id", "hours", "date"]).copy()
    logs["hours"] = pd.to_numeric(logs["hours"], errors="coerce").fillna(0.0)
    logs["date"]  = pd.to_datetime(logs["date"], errors="coerce")
    long_logs = logs[(logs["date"] >= cutoff) & (logs["hours"] >= 2.0)]
    for _, r in long_logs.iterrows():
        if pd.notna(r["date"]):
            items.append({"when": r["date"].date(), "user_id": r["user_id"], "type": "study", "detail": f"{r['hours']:.1f}h session"})

    tests = _ensure_cols(tests_all, ["user_id", "score", "date"]).copy()
    tests["score"] = pd.to_numeric(tests["score"], errors="coerce")
    tests["date"]  = pd.to_datetime(tests["date"], errors="coerce")
    great = tests[(tests["date"] >= cutoff) & (tests["score"] >= 80)]
    for _, r in great.iterrows():
        if pd.notna(r["date"]):
            items.append({"when": r["date"].date(), "user_id": r["user_id"], "type": "test", "detail": f"Scored {int(r['score'])}%"})

    if not items:
        return pd.DataFrame(columns=["when", "user_id", "type", "detail"])
    return pd.DataFrame(items).sort_values("when", ascending=False)
