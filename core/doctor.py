from __future__ import annotations
from pathlib import Path
import pandas as pd
from .config import DATA_DIR, BACKUPS_DIR, AVATARS_DIR, SUBJECTS_CSV, LOGS_CSV, TESTS_CSV, USERS_CSV
from .storage import ensure_store

def run_health_check() -> dict:
    ensure_store()
    report = {}

    # Paths
    report["paths_exist"] = {
        "DATA_DIR": DATA_DIR.exists(),
        "BACKUPS_DIR": BACKUPS_DIR.exists(),
        "AVATARS_DIR": AVATARS_DIR.exists(),
    }

    # Files present
    report["files_exist"] = {
        "subjects": SUBJECTS_CSV.exists(),
        "logs": LOGS_CSV.exists(),
        "tests": TESTS_CSV.exists(),
        "users": USERS_CSV.exists(),
    }

    # Schema minimal checks
    def cols(p):
        try: return set(pd.read_csv(p, nrows=0).columns.tolist())
        except Exception: return set()
    report["schemas"] = {
        "subjects": cols(SUBJECTS_CSV).issuperset({"id","name","exam_date","user_id"}),
        "logs": cols(LOGS_CSV).issuperset({"id","date","subject_id","hours","user_id"}),
        "tests": cols(TESTS_CSV).issuperset({"id","date","subject_id","score","user_id"}),
        "users": cols(USERS_CSV).issuperset({"id","username","password_hash","created_at","avatar_path"}),
    }

    # Write test
    try:
        probe = DATA_DIR / "_write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        report["write_ok"] = True
    except Exception:
        report["write_ok"] = False

    return report
