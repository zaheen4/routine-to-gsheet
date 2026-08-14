import logging
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")

# Headless Mode: True to run without a visible window. Keep False on Linux even
# for scheduled runs: scripts/run_routine.sh wraps the scraper in xvfb-run so
# Chrome renders on the virtual X display (real headless gets challenged by
# Cloudflare).
HEADLESS = _env_bool("HEADLESS", False)

# Chrome binary path override (else auto-detected: PATH scan on Linux, plus
# well-known .app bundle on macOS and Program Files installs on Windows).
CHROME_BINARY_PATH = os.getenv("CHROME_BINARY_PATH")

# Google Spreadsheet & Apps Script configuration
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "CSE-03_B_ClassRoutine")
TARGET_SHEET_NAME = os.getenv("TARGET_SHEET_NAME", "backend")
APP_SCRIPT_ID = os.getenv("APP_SCRIPT_ID", "YOUR_APP_SCRIPT_ID_GOES_HERE")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )