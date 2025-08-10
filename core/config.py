from __future__ import annotations
import os, sys
from pathlib import Path

# App identity
APP_NAME = "NIERWELL GPA WIZARD"

# Defaults
DEFAULT_SETTINGS = {
    "semester": "Sem 2.2",
    "default_exam_date": "2025-09-05",
    "logs_weight": 0.70,
    "tests_weight": 0.30,
    "momentum_days": 7,
    "focus_n": 3,
    "show_upcoming_exams": True,
    "show_recent_activity": True,
}

# Seed subjects shown on first run (can edit freely)
INITIAL_SUBJECTS = [
    {"id": "chem-eng-basics", "name": "Chemical engineering basics",         "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "micro-scatter",   "name": "Microscopic & scattering techniques", "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "org-synthesis",   "name": "Organic synthesis",                    "credits": 2, "confidence": 2, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "adv-thermo",      "name": "Advanced thermodynamics",              "credits": 2, "confidence": 6, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "paint-tech",      "name": "Applied polymer — Paint tech",         "credits": 2, "confidence": 8, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "tyre-tech",       "name": "Applied polymer — Tyre tech",          "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "fibre-tech",      "name": "Applied polymer — Fibre tech",         "credits": 2, "confidence": 5, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
    {"id": "textile-fibres",  "name": "Textile & fibres",                     "credits": 2, "confidence": 7, "exam_date": DEFAULT_SETTINGS["default_exam_date"]},
]

# UI choices
TASK_TYPES = ["Read", "Problems", "Past paper", "Teaching", "Flashcards"]

def get_storage_dir() -> Path:
    """
    Persistent per-user data directory.
    Set NIERWELL_GPA_WIZARD_DATA_DIR to override (optional).
    """
    env_override = os.getenv("NIERWELL_GPA_WIZARD_DATA_DIR") or os.getenv("GPA_CC_DATA_DIR")
    if env_override:
        return Path(env_override)

    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    # Folder will be created by ensure_store()
    return base / APP_NAME

# Resolved paths
DATA_DIR        = get_storage_dir()
LEGACY_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SUBJECTS_CSV    = DATA_DIR / "subjects.csv"
LOGS_CSV        = DATA_DIR / "logs.csv"
TESTS_CSV       = DATA_DIR / "tests.csv"
SETTINGS_JSON   = DATA_DIR / "settings.json"
USERS_CSV       = DATA_DIR / "users.csv"
BACKUPS_DIR     = DATA_DIR / "backups"
AVATARS_DIR   = DATA_DIR / "avatars"
