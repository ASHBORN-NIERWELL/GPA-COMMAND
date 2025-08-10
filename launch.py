# launch.py — robust launcher for Streamlit when frozen with PyInstaller
import os, sys, webbrowser

# Force production mode so we can fix the port
os.environ["STREAMLIT_GLOBAL_DEVELOPMENTMODE"] = "false"

# Support both dev & PyInstaller builds
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)  # keep data next to the exe

# Locate the app file
CANDIDATES = ["app.py", "gpa_command_center_python_app.py"]
APP_PATH = next((os.path.join(BASE_DIR, n) for n in CANDIDATES if os.path.exists(os.path.join(BASE_DIR, n))), None)
if not APP_PATH:
    print(f"ERROR: Could not find any of: {CANDIDATES} in {BASE_DIR}", file=sys.stderr)
    sys.exit(2)

try:
    from streamlit.web import cli as stcli
except Exception as e:
    print("Streamlit missing. Install deps in your venv: pip install streamlit pandas numpy", file=sys.stderr)
    print(e, file=sys.stderr)
    sys.exit(1)

# CLI args: explicitly disable dev mode, fix port/address, no file watcher in _MEIPASS
sys.argv = [
    "streamlit", "run", APP_PATH,
    "--global.developmentMode", "false",
    "--server.headless", "false",
    "--server.port", "8501",
    "--server.address", "127.0.0.1",
    "--server.fileWatcherType", "none",
    "--browser.gatherUsageStats", "false",
]

# Best effort: open browser
try:
    webbrowser.open_new("http://127.0.0.1:8501")
except Exception:
    pass

sys.exit(stcli.main())
