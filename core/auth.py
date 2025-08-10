from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from .config import (
    USERS_CSV,
    SUBJECTS_CSV,
    LOGS_CSV,
    TESTS_CSV,
    AVATARS_DIR,
)
from .storage import load_df, save_df

# Optional strong hashing
try:
    import bcrypt  # type: ignore
    HAVE_BCRYPT = True
except Exception:
    HAVE_BCRYPT = False


# -----------------------
# Avatar helpers
# -----------------------
def set_user_avatar(user_id: str, file_bytes: bytes, filename: str) -> str:
    """
    Save avatar to AVATARS_DIR/{user_id}.ext and update users.csv (avatar_path).
    Returns the stored path as string.
    """
    ext = (Path(filename).suffix or ".png").lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    out_path = AVATARS_DIR / f"{user_id}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)  # ensure folder exists

    # Remove any previous avatar with a different extension to avoid clutter
    for old in AVATARS_DIR.glob(f"{user_id}.*"):
        if old.suffix.lower() != ext:
            try:
                old.unlink()
            except Exception:
                pass

    with open(out_path, "wb") as f:
        f.write(file_bytes)

    users = load_users()
    idx = users.index[users["id"] == user_id]
    if len(idx):
        users.loc[idx[0], "avatar_path"] = str(out_path)
        save_users(users)

    return str(out_path)


def get_user_avatar_path(user_id: str) -> str:
    users = load_users()
    row = users[users["id"] == user_id]
    if len(row):
        p = str(row.iloc[0].get("avatar_path", "")).strip()
        if p and Path(p).exists():
            return p
    return ""  # caller can fall back to a placeholder


# -----------------------
# Password helpers
# -----------------------
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


# Optional public alias (nicer import)
def verify_password(pw: str, hashed: str) -> bool:
    return _verify_password(pw, hashed)


# -----------------------
# Users CRUD
# -----------------------
@st.cache_data(show_spinner=False)
def load_users() -> pd.DataFrame:
    try:
        df = pd.read_csv(USERS_CSV)
    except Exception:
        df = pd.DataFrame(columns=["id", "username", "password_hash", "created_at", "avatar_path"])

    # Backfill missing columns (e.g., avatar_path added later)
    for col, default in [
        ("id", ""),
        ("username", ""),
        ("password_hash", ""),
        ("created_at", ""),
        ("avatar_path", ""),
    ]:
        if col not in df.columns:
            df[col] = default
    return df


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
        "avatar_path": "",
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
    for path in [SUBJECTS_CSV, LOGS_CSV, TESTS_CSV]:
        df = load_df(path)
        if "user_id" in df.columns:
            mask = df["user_id"].astype(str).fillna("") == ""
            if mask.any():
                df.loc[mask, "user_id"] = user_id
                save_df(df, path)
