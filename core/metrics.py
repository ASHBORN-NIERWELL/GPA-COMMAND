# core/metrics.py
from __future__ import annotations

from datetime import date
from typing import Tuple

import numpy as np
import pandas as pd

from .storage import load_settings
from .config import DEFAULT_SETTINGS


# -------------------------------
# Editor helpers
# -------------------------------
def sanitize_subjects_for_editor(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """
    Make subjects DF safe for Streamlit's data_editor:
      - Ensure exam_date/credits/confidence exist with sane defaults
      - Cast ids/names to string
      - Normalize exam_date -> datetime.date (editor-friendly)
      - If a 'completed' column exists, coerce to bool (do not create it here)
    """
    out = df.copy()

    # Required fields for editor UX
    if "exam_date" not in out.columns:
        out["exam_date"] = settings.get("default_exam_date", "2025-09-05")
    if "credits" not in out.columns:
        out["credits"] = 2
    if "confidence" not in out.columns:
        out["confidence"] = 5

    for col in ["id", "name", "user_id"]:
        if col in out.columns:
            out[col] = out[col].astype("string")

    # Numeric normalizations
    out["credits"] = pd.to_numeric(out.get("credits"), errors="coerce").fillna(1).clip(1).astype(int)
    out["confidence"] = (
        pd.to_numeric(out.get("confidence"), errors="coerce")
        .fillna(5).round().clip(0, 10).astype(int)
    )

    # Date normalization for exam_date
    out["exam_date"] = pd.to_datetime(out.get("exam_date"), errors="coerce").dt.date
    default_date = pd.to_datetime(settings.get("default_exam_date", "2025-09-05"), errors="coerce")
    default_date = default_date.date() if pd.notnull(default_date) else date.today()
    out["exam_date"] = out["exam_date"].apply(lambda d: default_date if pd.isna(d) else d)

    # If 'completed' exists already, normalize type (do not create here)
    if "completed" in out.columns:
        out["completed"] = out["completed"].astype(str).str.lower().isin(["true", "1", "yes"])

    return out


# -------------------------------
# Core computations
# -------------------------------
def days_between(d1, d2) -> int:
    d1 = pd.to_datetime(d1).date()
    d2 = pd.to_datetime(d2).date()
    return (d2 - d1).days


def calc_priority(credits, confidence) -> float:
    # Higher credits + lower confidence => higher priority
    return (10.0 - float(confidence)) * float(max(1, credits))


def _safe_aggregates(logs: pd.DataFrame, tests: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns (hours_by_subject, tests_avg_by_subject, logs_avg_by_subject),
    gracefully handling missing columns / empty frames.
    """
    # Normalize shapes
    logs = logs.copy() if logs is not None else pd.DataFrame()
    tests = tests.copy() if tests is not None else pd.DataFrame()

    # Ensure required columns
    for col in ["subject_id", "hours", "score"]:
        if col not in logs.columns:
            logs[col] = pd.NA
    for col in ["subject_id", "score"]:
        if col not in tests.columns:
            tests[col] = pd.NA

    # Cast numerics
    logs["hours"] = pd.to_numeric(logs["hours"], errors="coerce")
    logs["score"] = pd.to_numeric(logs["score"], errors="coerce")
    tests["score"] = pd.to_numeric(tests["score"], errors="coerce")

    # Groupbys (drop NaN subject_ids first)
    h = pd.DataFrame(columns=["subject_id", "hours"])
    if not logs.empty:
        h = (
            logs.dropna(subset=["subject_id"])
            .groupby("subject_id", as_index=False)["hours"]
            .sum()
            .rename(columns={"hours": "hours"})
        )

    tavg = pd.DataFrame(columns=["subject_id", "tests_avg"])
    if not tests.empty:
        tavg = (
            tests.dropna(subset=["subject_id"])
            .groupby("subject_id", as_index=False)["score"]
            .mean()
            .rename(columns={"score": "tests_avg"})
        )

    lavg = pd.DataFrame(columns=["subject_id", "logs_avg"])
    if not logs.empty:
        lavg = (
            logs.dropna(subset=["subject_id"])
            .groupby("subject_id", as_index=False)["score"]
            .mean()
            .rename(columns={"score": "logs_avg"})
        )

    return h, tavg, lavg


def compute_metrics(subjects: pd.DataFrame, logs: pd.DataFrame, tests: pd.DataFrame) -> pd.DataFrame:
    """
    Returns per-subject metrics:
      - priority, hours, tests_avg, logs_avg, avg_score (weighted), days_left, priority_gap
    Notes:
      * This function does NOT filter out completed subjects; the caller/UI decides.
      * Robust to empty logs/tests.
    """
    # Settings for averaging
    settings = load_settings()
    w_logs = float(settings.get("logs_weight", 0.70))
    w_tests = float(settings.get("tests_weight", max(0.0, 1.0 - w_logs)))

    # Aggregate inputs safely
    hours_by, testsavg_by, logsavg_by = _safe_aggregates(logs, tests)

    df = subjects.copy()
    # Normalize dates
    df["exam_date"] = pd.to_datetime(df.get("exam_date"), errors="coerce")
    # Priority
    df["priority"] = df.apply(lambda r: calc_priority(r.get("credits", 1), r.get("confidence", 5)), axis=1)

    # Merge aggregates on "id" (subjects) == "subject_id" (logs/tests)
    for agg, col in [(hours_by, "hours"), (testsavg_by, "tests_avg"), (logsavg_by, "logs_avg")]:
        if not agg.empty:
            df = df.merge(agg, left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"], errors="ignore")
        else:
            df[col] = np.nan

    # Clean numerics
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["tests_avg"] = pd.to_numeric(df["tests_avg"], errors="coerce")
    df["logs_avg"] = pd.to_numeric(df["logs_avg"], errors="coerce")

    # Weighted average rule
    def weighted_avg(row):
        has_logs = pd.notna(row.get("logs_avg"))
        has_tests = pd.notna(row.get("tests_avg"))
        if has_logs and has_tests:
            return float(row["logs_avg"]) * w_logs + float(row["tests_avg"]) * w_tests
        if has_logs:
            return float(row["logs_avg"])
        if has_tests:
            return float(row["tests_avg"])
        return 0.0

    df["avg_score"] = df.apply(weighted_avg, axis=1)

    # Time to exam
    default_exam = pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]))
    today = date.today()
    df["days_left"] = df["exam_date"].apply(
        lambda d: max(0, days_between(today, d if pd.notnull(d) else default_exam))
    )

    # Gap to ideal (priority-scaled) — lower avg_score => larger gap
    df["priority_gap"] = df["priority"] * (1 - (df["avg_score"] / 100.0))

    return df


def weighted_readiness(df_metrics: pd.DataFrame) -> float:
    """
    Returns a single readiness score in [0,1] using a priority-weighted average of avg_score.
    If priorities sum to 0, returns 0.0.
    """
    if df_metrics is None or df_metrics.empty:
        return 0.0
    num = (df_metrics["priority"] * (df_metrics["avg_score"] / 100.0)).sum()
    den = df_metrics["priority"].sum()
    return float(num / den) if den else 0.0
