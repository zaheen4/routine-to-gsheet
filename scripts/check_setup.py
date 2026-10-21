#!/usr/bin/env python3
"""Online preflight check for the routine pipeline.

Verifies local config files are present and valid, and that the spreadsheet can
be opened with the service account (catches the "not shared" mistake).

Usage:
    python scripts/check_setup.py

Exits 0 when everything looks ready, 1 otherwise.
"""
import json
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from browser_lookup import get_chrome_executable
from config import CHROME_BINARY_PATH, HEADLESS, SPREADSHEET_NAME, setup_logging
from gsheet_formatter import (
    GOOGLE_SERVICE_ACCOUNT_KEY_FILE,
    authenticate_gsheet,
)

setup_logging()

problems = []


def check(description, condition, detail=""):
    """Report a single check; record it as a problem when it fails."""
    if condition:
        print("  [OK]     %s" % description)
        return True
    print("  [FAIL]   %s" % description)
    if detail:
        print("            %s" % detail)
    problems.append(description)
    return False


def warn(description, detail=""):
    """Report an informational check. Warnings never block the run."""
    print("  [WARN]   %s" % description)
    if detail:
        print("            %s" % detail)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": str(e)}


def main():
    print("Routine pipeline preflight\n")

    print("Local files")
    key = load_json(GOOGLE_SERVICE_ACCOUNT_KEY_FILE)
    if "__error__" in key:
        check("service account key is valid JSON",
              False, "%s: %s" % (GOOGLE_SERVICE_ACCOUNT_KEY_FILE, key["__error__"]))
        client_email = None
    else:
        check("service account key is valid JSON", True)
        client_email = key.get("client_email")
        check("service account key has client_email",
              bool(client_email), "share the spreadsheet with this email (SETUP.md Phase A3)")

    print("\nGoogle connection")
    gc = None
    if not any("service account key" in p for p in problems):
        gc = authenticate_gsheet(GOOGLE_SERVICE_ACCOUNT_KEY_FILE)
        check("service account authentication", gc is not None)

    if gc is not None:
        try:
            gc.open(SPREADSHEET_NAME)
            check("spreadsheet '%s' opens with service account" % SPREADSHEET_NAME, True)
        except Exception as e:
            check("spreadsheet '%s' opens with service account" % SPREADSHEET_NAME,
                  False,
                  "%s — make sure the sheet exists, the name in .env is exact, and the "
                  "sheet is shared (Editor) with %s" % (e, client_email))

    print("\nScraper environment (informational - warnings never block)")
    chrome = get_chrome_executable(CHROME_BINARY_PATH)
    if chrome:
        print("  [OK]     Chrome binary detected: %s" % chrome)
    else:
        warn("Chrome/Chromium binary not detected",
             "the scraper will abort; install Chrome/Chromium or set "
             "CHROME_BINARY_PATH in .env")

    if sys.platform.startswith("linux"):
        if shutil.which("xvfb-run"):
            print("  [OK]     xvfb-run available (needed by scripts/run_routine.sh)")
        else:
            warn("xvfb-run not found",
                 "scripts/run_routine.sh will refuse to run on Linux without it; "
                 "install e.g. Debian/Ubuntu: sudo apt install xvfb")
        if HEADLESS:
            warn("HEADLESS=true on Linux",
                 "true headless Chrome tends to be challenged by Cloudflare; "
                 "prefer HEADLESS=false under xvfb-run for scheduled runs")

    print()
    if problems:
        print("Found %d issue(s). See SETUP.md troubleshooting table." % len(problems))
        return 1
    print("All checks passed. You're ready to run extract_ucam.py, "
          "gsheet_formatter.py and ics_exporter.py (or scripts/run_routine.sh).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
