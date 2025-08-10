from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd
from .storage import load_settings
from .config import DEFAULT_SETTINGS

def sanitize_subjects_for_editor(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    out = df.copy()
    for need in ["exam_date","credits","confidence"]: 
        if need not in out.columns:
            if need == "exam_date":
                out["exam_date"] = settings.get("default_exam_date", "2025-09-05")
            if need == "credits": out["credits"] = 2
            if need == "confidence": out["confidence"] = 5
    for col in ["id","name","user_id"]:
        if col in out.columns: out[col] = out[col].astype("string")
    out["credits"] = pd.to_numeric(out.get("credits"), errors="coerce").fillna(1).astype(int)
    out["confidence"] = pd.to_numeric(out.get("confidence"), errors="coerce").fillna(5).round().clip(0,10).astype(int)
    out["exam_date"] = pd.to_datetime(out.get("exam_date"), errors="coerce").dt.date
    default_date = pd.to_datetime(settings.get("default_exam_date", "2025-09-05"), errors="coerce")
    default_date = default_date.date() if pd.notnull(default_date) else date.today()
    out["exam_date"] = out["exam_date"].apply(lambda d: default_date if pd.isna(d) else d)
    return out

def days_between(d1, d2) -> int:
    d1 = pd.to_datetime(d1).date(); d2 = pd.to_datetime(d2).date()
    return (d2 - d1).days

def calc_priority(credits, confidence) -> float:
    return (10 - float(confidence)) * float(credits)

def compute_metrics(subjects: pd.DataFrame, logs: pd.DataFrame, tests: pd.DataFrame) -> pd.DataFrame:
    settings = load_settings()
    w_logs = float(settings.get("logs_weight", 0.70))
    w_tests = float(settings.get("tests_weight", max(0.0, 1.0 - w_logs)))

    hours    = logs.groupby("subject_id")["hours"].sum().rename("hours").reset_index()
    testsavg = tests.groupby("subject_id")["score"].mean().rename("tests_avg").reset_index()
    logsavg  = logs.groupby("subject_id")["score"].mean().rename("logs_avg").reset_index()

    df = subjects.copy()
    df["exam_date"] = pd.to_datetime(df.get("exam_date"), errors="coerce")
    df["priority"]  = df.apply(lambda r: calc_priority(r["credits"], r["confidence"]), axis=1)

    for agg, col in [(hours,"hours"), (testsavg,"tests_avg"), (logsavg,"logs_avg")]:
        df = df.merge(agg, left_on="id", right_on="subject_id", how="left").drop(columns=["subject_id"])

    df["hours"]     = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0)
    df["tests_avg"] = pd.to_numeric(df["tests_avg"], errors="coerce")
    df["logs_avg"]  = pd.to_numeric(df["logs_avg"],  errors="coerce")

    def weighted_avg(row):
        has_logs, has_tests = pd.notna(row.get("logs_avg")), pd.notna(row.get("tests_avg"))
        if has_logs and has_tests: return row["logs_avg"]*w_logs + row["tests_avg"]*w_tests
        if has_logs: return row["logs_avg"]
        if has_tests: return row["tests_avg"]
        return 0.0

    df["avg_score"] = df.apply(weighted_avg, axis=1)

    default_exam = pd.to_datetime(settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]))
    today = date.today()
    df["days_left"] = df["exam_date"].apply(lambda d: max(0, days_between(today, d if pd.notnull(d) else default_exam)))
    df["priority_gap"] = df["priority"] * (1 - (df["avg_score"]/100.0))
    return df

def weighted_readiness(df_metrics: pd.DataFrame) -> float:
    if df_metrics.empty: return 0.0
    num = (df_metrics["priority"] * (df_metrics["avg_score"]/100.0)).sum()
    den = df_metrics["priority"].sum()
    return float(num/den) if den else 0.0
