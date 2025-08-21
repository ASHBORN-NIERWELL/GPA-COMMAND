import pandas as pd
from pathlib import Path
import streamlit as st  # only to reuse secrets loader
from core.config import SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, USERS_CSV, DEFAULT_SETTINGS
from core.firebase_store import upsert_dataframe, load_settings_dict, save_settings_dict

def read_csv_if_exists(p: Path) -> pd.DataFrame:
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

def main():
    subs  = read_csv_if_exists(SUBJECTS_CSV)
    logs  = read_csv_if_exists(LOGS_CSV)
    tests = read_csv_if_exists(TESTS_CSV)
    users = read_csv_if_exists(USERS_CSV)

    if len(subs):  upsert_dataframe("subjects", subs)
    if len(logs):  upsert_dataframe("logs", logs)
    if len(tests): upsert_dataframe("tests", tests)
    if len(users): upsert_dataframe("users", users)

    # settings.json → settings/app_settings
    # if you have a local file, just load via your existing load_settings()
    from core.storage import load_settings
    current = load_settings()
    save_settings_dict(current)
    print("Migration complete.")

if __name__ == "__main__":
    main()
