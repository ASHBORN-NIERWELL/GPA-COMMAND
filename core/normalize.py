# core/normalize.py
from __future__ import annotations
import uuid
from typing import Optional, Tuple
import numpy as np
import pandas as pd

# ---- small helpers ----
def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out

def _align_columns(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = sorted(set(a.columns).union(set(b.columns)))
    return _ensure_columns(a, cols)[cols], _ensure_columns(b, cols)[cols]

# ---- normalizers ----
def normalize_subjects_df(df: pd.DataFrame, default_exam: str, user_id: str | None) -> pd.DataFrame:
    out = df.copy()

    need = ["id", "name", "credits", "confidence", "exam_date", "user_id"]
    out = _ensure_columns(out, need)

    # ids
    out["id"] = out["id"].astype("string").fillna("")
    mask_blank = out["id"].str.strip() == ""
    out.loc[mask_blank, "id"] = [str(uuid.uuid4()) for _ in range(mask_blank.sum())]

    # strings
    for col in ["name", "user_id"]:
        out[col] = out[col].astype("string").fillna("")

    # numerics
    out["credits"] = pd.to_numeric(out["credits"], errors="coerce").fillna(1).astype(int)
    out["confidence"] = (
        pd.to_numeric(out["confidence"], errors="coerce")
        .fillna(5).round().clip(0, 10).astype(int)
    )

    # dates
    def_exam = pd.to_datetime(default_exam, errors="coerce")
    out["exam_date"] = pd.to_datetime(out["exam_date"], errors="coerce")
    out["exam_date"] = out["exam_date"].fillna(def_exam).dt.strftime("%Y-%m-%d")

    # force user id if provided
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

    for col in ["subject_id", "task", "notes"]:
        out[col] = out[col].astype("string").fillna("")

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
        .fillna(3).round().clip(1, 5).astype(int)
    )

    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    if user_id is not None:
        out["user_id"] = str(user_id)

    return out[need]

# ---- merge helpers ----
def _merge_replace_current_user(existing: pd.DataFrame, incoming: pd.DataFrame, uid: str | None) -> pd.DataFrame:
    if uid is None:
        ex_aligned, inc_aligned = _align_columns(existing, incoming)
        return inc_aligned

    existing, incoming = _align_columns(existing, incoming)
    incoming["user_id"] = str(uid)

    others = existing[existing.get("user_id", "").astype(str) != str(uid)]
    cur    = existing[existing.get("user_id", "").astype(str) == str(uid)]

    merged_cur = (
        pd.concat([cur, incoming], ignore_index=True)
        .drop_duplicates(subset=["id"], keep="last")
    )
    return pd.concat([others, merged_cur], ignore_index=True)

def _append_current_user(existing: pd.DataFrame, incoming: pd.DataFrame, uid: str | None) -> pd.DataFrame:
    if uid is None:
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
    return pd.concat([others, merged_cur], ignore_index=True)
