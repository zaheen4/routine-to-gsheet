#!/usr/bin/env python3
"""Scaffold and validate the routine pipeline's local configuration.

Copies template files to their real names if missing, checks that the
required Google Cloud key files and .env are present, and validates the
config JSON. Safe to run repeatedly (never overwrites existing files).

Usage:
    python scripts/setup.py
"""
import json
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Real file -> template it is copied from (only when the real file is missing).
TEMPLATE_MAP = {
    "configs_to_edit/ucam_login_credentials.json":
        "configs_to_edit/ucam_login_credentials.json.example.txt",
    "configs_to_edit/teacher_contact_details.json":
        "configs_to_edit/teacher_contact_details.json.example.txt",
    ".env": ".env.example",
}

# Files that MUST be obtained from Google Cloud (never scaffolded from
# templates - the templates are invalid placeholders).
GOOGLE_KEY_FILES = [
    "google_cloud_keys/service_account_key.json",
    "google_cloud_keys/oauth_client_secret.json",
]

REQUIRED_CREDENTIALS_KEYS = ["users", "login_url", "attendance_dashboard_url"]
REQUIRED_USER_KEYS = ["id", "username", "password", "section_label"]

# Browser binaries considered, in order of preference. Matches the scraper's
# auto-detection so setup can warn early if none are installed.
CHROME_CANDIDATES = [
    "google-chrome-stable",
    "google-chrome",
    "chromium-browser",
    "chromium",
    "chrome",
]

ENV_PLACEHOLDER_IDS = {"your_app_script_id", "YOUR_APP_SCRIPT_ID_GOES_HERE", ""}


def resolve_path(rel_path):
    """Resolve a project-relative path to an absolute path."""
    return os.path.join(PROJECT_ROOT, rel_path)


def scaffold_files(root=PROJECT_ROOT):
    """Copy missing templates to their real names.

    Returns a list of human-readable status lines.
    """
    lines = []
    for real_rel, template_rel in TEMPLATE_MAP.items():
        real_path = os.path.join(root, real_rel)
        if os.path.exists(real_path):
            lines.append("exists: %s" % real_rel)
            continue
        template_path = os.path.join(root, template_rel)
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        shutil.copy2(template_path, real_path)
        lines.append("created: %s (edit it)" % real_rel)
    return lines


def validate_credentials_json(path):
    """Validate the UCAM credentials JSON structure.

    Returns (ok, errors) where errors is a list of strings.
    """
    errors = []
    if not os.path.exists(path):
        return False, ["%s is missing" % path]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, ["%s is not valid JSON: %s" % (path, e)]

    missing = [k for k in REQUIRED_CREDENTIALS_KEYS if k not in data]
    if missing:
        errors.append("missing top-level key(s): %s" % ", ".join(missing))
    if not isinstance(data.get("users"), list) or not data["users"]:
        errors.append("'users' must be a non-empty list")
    else:
        for i, user in enumerate(data["users"]):
            user_missing = [k for k in REQUIRED_USER_KEYS if k not in user]
            if user_missing:
                errors.append("users[%d] missing key(s): %s" % (i, ", ".join(user_missing)))
    return not errors, errors


def validate_teacher_details(path):
    """Validate the teacher contacts JSON (optional file, may be absent)."""
    if not os.path.exists(path):
        return True, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, ["%s is not valid JSON: %s" % (path, e)]
    if not isinstance(data, dict):
        return False, ["%s must be a JSON object" % path]
    return True, []


def _env_value(env_lines, key):
    for line in env_lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        if k.strip() == key:
            return v.strip()
    return None


def validate_env(path):
    """Check .env for the values the pipeline needs.

    APP_SCRIPT_ID is the only value with no working default (config.py uses a
    placeholder), so it is the one required in .env. SPREADSHEET_NAME and
    TARGET_SHEET_NAME fall back to sensible defaults in config.py.

    Returns (ok, errors).
    """
    errors = []
    if not os.path.exists(path):
        return False, ["%s is missing (run setup.py to create it)" % path]
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    app_script_id = _env_value(lines, "APP_SCRIPT_ID")
    if not app_script_id or app_script_id in ENV_PLACEHOLDER_IDS:
        errors.append("APP_SCRIPT_ID is unset or still a placeholder (see SETUP.md Phase A6)")
    return not errors, errors


def find_browser():
    """Return the first installed Chrome/Chromium binary name, or None."""
    for name in CHROME_CANDIDATES:
        if shutil.which(name):
            return name
    return None


def main():
    root = PROJECT_ROOT
    lines = scaffold_files(root)

    print("\n[1/5] Scaffolded config files")
    for line in lines:
        print("  -", line)

    print("\n[2/5] Google Cloud key files")
    ok = True
    for rel in GOOGLE_KEY_FILES:
        present = os.path.exists(resolve_path(rel))
        print("  - %s: %s" % (rel, "present" if present else "MISSING"))
        if not present:
            ok = False
    if not ok:
        print("  -> Download these from Google Cloud Console (SETUP.md Phase A3/A5).")

    print("\n[3/5] Browser detection")
    browser = find_browser()
    if browser:
        print("  - found:", browser)
    else:
        print("  - none found: install Chrome or Chromium (SETUP.md Phase B2)")
        ok = False

    print("\n[4/5] Configuration validation")
    env_lines = None
    env_path = resolve_path(".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.readlines()
    spreadsheet = _env_value(env_lines, "SPREADSHEET_NAME") or "CSE-03_B_ClassRoutine"
    print("  - SPREADSHEET_NAME resolves to:", spreadsheet)
    cred_ok, cred_errors = validate_credentials_json(
        resolve_path("configs_to_edit/ucam_login_credentials.json"))
    for err in cred_errors:
        print("  - ERROR:", err)
    teacher_ok, teacher_errors = validate_teacher_details(
        resolve_path("configs_to_edit/teacher_contact_details.json"))
    for err in teacher_errors:
        print("  - ERROR:", err)
    env_ok, env_errors = validate_env(env_path)
    for err in env_errors:
        print("  - ERROR:", err)
    if not (cred_ok and teacher_ok and env_ok):
        ok = False

    print("\n[5/5] Next steps")
    print("  1. Edit configs_to_edit/ucam_login_credentials.json with your UCAM login (SETUP.md Phase B4).")
    print("  2. Set SPREADSHEET_NAME and APP_SCRIPT_ID in .env (SETUP.md Phase B4).")
    print("  3. Run: .venv/bin/python scripts/check_setup.py  (preflight check)")
    print("  4. Run: .venv/bin/python routine_scrapper.py")
    print("  5. Run: .venv/bin/python gsheet_formatter.py   (first run opens OAuth)")

    print()
    if ok:
        print("OK - setup looks ready. See SETUP.md for the next steps.")
        return 0
    print("ISSUES FOUND - see the messages above and SETUP.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
