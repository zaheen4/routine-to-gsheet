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


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default

# Headless Mode: True to run without a visible window. Keep False on Linux even
# for scheduled runs: scripts/run_routine.sh wraps the scraper in xvfb-run so
# Chrome renders on the virtual X display (real headless gets challenged by
# Cloudflare).
HEADLESS = _env_bool("HEADLESS", False)

# Chrome binary path override (else auto-detected: PATH scan on Linux, plus
# well-known .app bundle on macOS and Program Files installs on Windows).
CHROME_BINARY_PATH = os.getenv("CHROME_BINARY_PATH")

# Official UCAM Student Class Routine Report - the source the scraper reads.
# The `mmi` token is issued by the portal; override it in .env if it rotates.
LOGIN_URL = os.getenv("LOGIN_URL", "https://ucam.niter.edu.bd/Security/LogIn.aspx")
ROUTINE_REPORT_URL = os.getenv(
    "ROUTINE_REPORT_URL",
    "https://ucam.niter.edu.bd/Module/schedular/Report/"
    "RptStudentClassRoutine.aspx?mmi=40545e1e42555f594e63",
)

# Every generated artifact (routine JSON, ICS) lands here. Relative values are
# anchored to the project root by the consumers, so a run from another cwd still
# writes next to the code.
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

# Calendar export settings. Asia/Dhaka is a fixed +0600 offset (no DST), which
# is also what the portal's schedule times mean.
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "Asia/Dhaka")
# Optional ISO date (YYYY-MM-DD) that ends the recurring events. When unset, the
# exporter derives it from the semester label (e.g. "January-July 2026").
SEMESTER_END = os.getenv("SEMESTER_END") or None

# Google Spreadsheet configuration
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "CSE-03_B_ClassRoutine")
TARGET_SHEET_NAME = os.getenv("TARGET_SHEET_NAME", "backend")

# Maximum age (hours) of the scraper's output that the formatter will publish.
# Guards against a crashed or killed scrape leaving the previous run's JSON on
# disk and the formatter republishing it as if it were fresh. 0 disables the
# check (not recommended).
MAX_DATA_AGE_HOURS = _env_int("MAX_DATA_AGE_HOURS", 48)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
