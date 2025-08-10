# core/utils.py
from __future__ import annotations

import uuid
from typing import Iterable, Tuple, Optional
import pandas as pd
import numpy as np


def safe_uuid(n: int = 1) -> list[str] | str:
    """Generate n UUID4 strings (list if n>1, single str if n==1)."""
    vals = [str(uuid.uuid4()) for _ in range(max(1, n))]
    return vals[0] if n == 1 else vals


def ensure_string_cols(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    """Cast selected columns to pandas 'string' dtype if present."""
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = out[c].astype("string")
    return out


def coerce_date_col(
    df: pd.DataFrame,
    col: str,
    out: str = "date",
    fmt: str = "%Y-%m-%d"
) -> pd.DataFrame:
    """
    Coerce a date-like column:
      out='date' -> python datetime.date
      out='str'  -> ISO string using fmt
    """
    out_df = df.copy()
    if col not in out_df.columns:
        return out_df
    s = pd.to_datetime(out_df[col], errors="coerce")
    # strip timezone if present
    try:
        s = s.dt.tz_localize(None)
    except Exception:
        pass
    if out == "date":
        out_df[col] = s.dt.date
    else:
        out_df[col] = s.dt.strftime(fmt)
    return out_df


def add_delete_flag(df: pd.DataFrame, col: str = "delete") -> pd.DataFrame:
    """Ensure a boolean 'delete' column exists for editor-based deletes."""
    out = df.copy()
    if col not in out.columns:
        out[col] = False
    return out


def split_by_user(df_all: pd.DataFrame, uid: Optional[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return (current_user_rows, others_rows) using 'user_id' column.
    If uid is None, current_user_rows == df_all and others_rows is empty.
    """
    if uid is None or "user_id" not in df_all.columns:
        return df_all.copy(), df_all.iloc[0:0].copy()
    mask = df_all.get("user_id", "").astype(str) == str(uid)
    return df_all[mask].copy(), df_all[~mask].copy()


def ensure_numeric(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    """Coerce listed columns to numeric (NaN on failure)."""
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out
