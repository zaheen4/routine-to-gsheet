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

# Browser Selection: "chrome" (recommended) or "firefox"
PREFERRED_BROWSER = os.getenv("PREFERRED_BROWSER", "chrome")

# Headless Mode: True to run without a visible window
HEADLESS = _env_bool("HEADLESS", False)

# Chrome binary path override (else auto-detected). Lets you pin the exact
# browser whose major version is matched against the downloaded chromedriver.
CHROME_BINARY_PATH = os.getenv("CHROME_BINARY_PATH")

# Google Spreadsheet & Apps Script configuration
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "CSE-03_B_ClassRoutine")
APP_SCRIPT_ID = os.getenv(
    "APP_SCRIPT_ID",
    "AKfycbxEHGHqGrOQkLOpyikkjGLZ1cf-g0YfUW1dXmqWX6PUOoFxEPIr7FoeQ8e74-euTg",
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )