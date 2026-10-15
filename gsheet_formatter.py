import json
import logging
import os
import pickle
import sys
import traceback
from datetime import datetime, timezone

import gspread
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    APP_SCRIPT_ID,
    MAX_DATA_AGE_HOURS,
    SPREADSHEET_NAME,
    TARGET_SHEET_NAME,
    setup_logging,
)
from routine_format import (
    SHEET_HEADERS,
    build_sheet_data,
    contact_column_letter,
)

setup_logging()
logger = logging.getLogger(__name__)
logger.info("gsheet_formatter.py starting...")

# [Configuration]
NEW_MAIN_SHEET_NAME = 'NewMain'
FUNCTION_NAME = 'triggerSortFromPython'

# [Path Constants]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPED_DATA_JSON_PATH = os.path.join(BASE_DIR, "output_of_fetched_routine", "final_combined_routine.json")

# [Google Cloud Platform Configuration]
# Anchored to BASE_DIR: the formatter is run from the project root by
# run_routine.sh and by the scheduler units, but a relative path here would
# silently point at a *different* (missing) credential file if it were ever run
# from elsewhere.
GOOGLE_KEYS_DIR = "google_cloud_keys"
GOOGLE_SERVICE_ACCOUNT_KEY_FILE = os.path.join(BASE_DIR, GOOGLE_KEYS_DIR, "service_account_key.json")
GOOGLE_OAUTH_CLIENT_SECRET_FILE = os.path.join(BASE_DIR, GOOGLE_KEYS_DIR, "oauth_client_secret.json")

# Scopes for Apps Script and Spreadsheet API access
APP_SCRIPT_SCOPES = [
    'https://www.googleapis.com/auth/script.projects',
    'https://www.googleapis.com/auth/script.external_request',
    'https://www.googleapis.com/auth/spreadsheets'
]
TOKEN_PICKLE_FILE = os.path.join(BASE_DIR, "token.pickle")

# Credential files are created owner-readable/writable only.
PRIVATE_FILE_MODE = 0o600


def restrict_secret_file_mode(path):
    """Best-effort chmod 600 on a credential file; never raises.

    token.pickle is a refresh token in the clear, so it should not be left
    group/world readable (the default umask on most Linux systems is 022).
    """
    try:
        os.chmod(path, PRIVATE_FILE_MODE)
    except OSError:
        logger.debug("Could not restrict permissions on '%s'.", path)


# [Helper Functions]

def load_routine_data(json_file_path):
    """
    Loads the processed routine data from the generated JSON file.

    Two payload shapes are accepted so the two pipeline stages can be upgraded
    independently: the current run manifest
    ({"generated_at", "semester", "accounts", "entries"}) and the legacy bare
    list of routine entries.

    Returns:
        tuple(list, str | None): (entries, generated_at). Returns ([], None)
        when the file is missing, unreadable, or malformed; a legacy list
        payload also yields generated_at=None because its age is unknowable.
    """
    logger.info("Loading routine data from: %s", json_file_path)
    try:
        with open(json_file_path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("Error: Source file '%s' not found.", json_file_path)
        return [], None
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in '%s'.", json_file_path)
        return [], None
    except Exception as e:
        logger.error("Unexpected error in load_routine_data: %s", e)
        return [], None

    if isinstance(data, dict):
        entries = data.get("entries")
        generated_at = data.get("generated_at")
        if not isinstance(entries, list):
            logger.error("'%s' has no 'entries' list.", json_file_path)
            return [], None
        logger.info(
            "Successfully loaded %d routine entries (generated_at=%s, semester=%s).",
            len(entries), generated_at, data.get("semester"),
        )
        return entries, generated_at

    if isinstance(data, list):
        logger.info("Successfully loaded %d routine entries (legacy list payload).", len(data))
        return data, None

    logger.error("Unsupported JSON payload in '%s'.", json_file_path)
    return [], None


def data_age_hours(generated_at):
    """
    Returns the age of a run manifest in hours, or None when unusable.

    Args:
        generated_at (str | None): ISO-8601 UTC stamp as written by the scraper.
    """
    if not generated_at:
        return None
    try:
        stamp = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        logger.error("Unparseable 'generated_at' value: %r", generated_at)
        return None
    return (datetime.now(timezone.utc) - stamp.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0


def authenticate_gsheet(service_account_json_path):
    """
    Authenticates with the Google Sheets API using a service account.

    Args:
        service_account_json_path (str): Path to the service account JSON key.

    Returns:
        gspread.Client: Authenticated gspread client or None if authentication fails.
    """
    logger.info("Authenticating with Google Sheets API...")
    try:
        if not os.path.isabs(service_account_json_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            service_account_json_path = os.path.join(script_dir, service_account_json_path)

        if not os.path.exists(service_account_json_path):
            logger.error("Service account key not found at '%s'.", service_account_json_path)
            return None

        gc = gspread.service_account(filename=service_account_json_path)
        logger.info("Google Sheets authentication successful.")
        return gc
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        return None

def get_or_create_worksheet(spreadsheet, sheet_name, rows=100, cols=20, seed_headers=False):
    """
    Retrieves a worksheet by name, creating it if it does not exist.

    Args:
        spreadsheet (gspread.Spreadsheet): The target spreadsheet object.
        sheet_name (str): Name of the worksheet to retrieve or create.
        rows (str): Initial row count for new worksheet.
        cols (str): Initial column count for new worksheet.
        seed_headers (bool): If True, write SHEET_HEADERS to B3:I3 when a new
            worksheet is created (matches the Apps Script data block at B4).

    Returns:
        gspread.Worksheet: The requested worksheet object or None if retrieval fails.
    """
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        logger.info("Found existing worksheet: '%s'", sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("Worksheet '%s' not found. Initializing new worksheet...", sheet_name)
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)
        logger.info("Created worksheet: '%s'", sheet_name)
        if seed_headers:
            worksheet.update(values=[SHEET_HEADERS], range_name='B3')
            worksheet.format("B3:I3", {'textFormat': {'bold': True}})
            logger.info("Seeded headers to 'B3:I3' on '%s'.", sheet_name)
    except Exception as e:
        logger.error("Error accessing worksheet '%s': %s", sheet_name, e)
        return None
    return worksheet


def write_data_to_sheet(worksheet, data_to_write):
    """
    Writes routine data to the worksheet with formatted headers and contact information.

    Args:
        worksheet (gspread.Worksheet): The worksheet to update.
        data_to_write (list): List of routine entry dictionaries.

    Returns:
        bool: True if writing was successful, False otherwise.
    """
    if not data_to_write:
        logger.warning("No data available to write to '%s'.", worksheet.title)
        return False
    try:
        worksheet.clear()
        logger.info("Cleared existing content in '%s'.", worksheet.title)

        all_rows = build_sheet_data(data_to_write)
        if all_rows is None:
            logger.error("Invalid data format. Expected a list of dictionaries.")
            return False

        # Bulk update worksheet starting from A1
        worksheet.update(values=all_rows, range_name='A1')

        # Apply WRAP strategy to the contact column (Column H)
        contact_col_letter = contact_column_letter()
        if contact_col_letter:
            worksheet.format(
                f"{contact_col_letter}2:{contact_col_letter}{len(all_rows)}",
                {'wrapStrategy': 'WRAP'}
            )
            logger.info("Applied text wrapping to contact column (%s).", contact_col_letter)

        logger.info("Wrote %d rows to '%s'.", len(data_to_write), worksheet.title)
        return True
    except Exception as e:
        logger.error("Error writing to worksheet '%s': %s", worksheet.title, e)
        traceback.print_exc()
        return False

def _headless_environment():
    """Return True when no display/Wayland session is available.

    Used to fail fast instead of hanging when a token re-auth is needed:
    under the systemd timer there is no DISPLAY/WAYLAND_DISPLAY and no
    browser can open the OAuth consent page, so run_local_server() would
    wait until the service timeout.

    Windows and macOS always have a GUI session available to the user
    (macOS uses WindowServer, not X11, so DISPLAY is never set there) -
    only Linux/BSD rely on the DISPLAY/WAYLAND_DISPLAY env vars.
    """
    if os.name == "nt" or sys.platform == "darwin":
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def call_apps_script_function(script_id, function_name, client_secrets_file, token_pickle_file, scopes):
    """
    Authenticates and executes a Google Apps Script function via the API.

    Args:
        script_id (str): The unique Script ID for the Apps Script project.
        function_name (str): The name of the function to execute.
        client_secrets_file (str): Path to the OAuth 2.0 client secret.
        token_pickle_file (str): Path to the cached authentication token.
        scopes (list): Required API scopes.

    Returns:
        bool: True if execution succeeded, False otherwise.
    """
    creds = None
    if os.path.exists(token_pickle_file):
        with open(token_pickle_file, 'rb') as token:
            creds = pickle.load(token)

    # Refresh or obtain new credentials if necessary
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing API credentials...")
            creds.refresh(Request())
        else:
            if _headless_environment():
                logger.error(
                    "Cached token is missing or expired with no refresh token. "
                    "Re-authentication requires a browser session: run "
                    "'gsheet_formatter.py' interactively once (with a DISPLAY) to "
                    "complete the OAuth flow and refresh '%s'.",
                    token_pickle_file,
                )
                return False
            logger.info("Authenticating with Google OAuth...")
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes)
            creds = flow.run_local_server(port=0)

        with open(token_pickle_file, 'wb') as token:
            pickle.dump(creds, token)
        restrict_secret_file_mode(token_pickle_file)
        logger.info("API credentials cached successfully.")

    try:
        service = build('script', 'v1', credentials=creds)
        logger.info("Executing Apps Script: %s...", function_name)

        request_body = {"function": function_name}
        response = service.scripts().run(scriptId=script_id, body=request_body).execute()

        if 'error' in response:
            error_msg = response['error'].get('errorMessage', 'Execution error')
            logger.error("Apps Script Error: %s", error_msg)
            return False

        logger.info("Apps Script execution completed successfully.")
        return True

    except Exception as e:
        logger.error("Failed to execute Apps Script: %s", e)
        traceback.print_exc()
        return False


# [Main Execution]

def main():
    """
    Run the sheet sync workflow.

    Returns:
        int: Process exit code - 0 only when the sheet was fully updated,
        non-zero otherwise. Every caller (scripts/run_routine.sh, the systemd
        unit's Restart=on-failure, Task Scheduler) relies on this to tell a
        real sync apart from a no-op; every failure path used to return None
        and exit 0, so a broken sync looked identical to a good one.
    """
    logger.info("Initializing Google Sheets formatting workflow...")

    # 1. Load data source
    routine_data, generated_at = load_routine_data(SCRAPED_DATA_JSON_PATH)
    if not routine_data:
        logger.error("Data source empty. Aborting sync.")
        return 1

    # 1b. Refuse to publish data that is not provably fresh: a scrape that died
    # before writing must not let the previous run's rows reach the sheet.
    age_hours = data_age_hours(generated_at)
    if age_hours is None:
        logger.error(
            "Data source has no usable 'generated_at' timestamp, so its freshness "
            "cannot be verified. Re-run routine_scrapper.py to regenerate '%s'.",
            SCRAPED_DATA_JSON_PATH,
        )
        return 1
    if MAX_DATA_AGE_HOURS > 0 and age_hours > MAX_DATA_AGE_HOURS:
        logger.error(
            "Refusing to publish stale data: generated %.1f hours ago (limit %d). "
            "Run routine_scrapper.py first.",
            age_hours,
            MAX_DATA_AGE_HOURS,
        )
        return 1
    if MAX_DATA_AGE_HOURS > 0:
        logger.info("Data is %.1f hours old (limit %d).", age_hours, MAX_DATA_AGE_HOURS)
    else:
        logger.warning("Data age check disabled (MAX_DATA_AGE_HOURS=0).")

    # 2. Authenticate and establish connection
    gc = authenticate_gsheet(GOOGLE_SERVICE_ACCOUNT_KEY_FILE)
    if not gc:
        logger.error("Authentication failure. Exiting.")
        return 1

    exit_code = 0

    try:
        logger.info("Opening spreadsheet: '%s'", SPREADSHEET_NAME)
        spreadsheet = gc.open(SPREADSHEET_NAME)

        # 3. Synchronize data with the 'backend' worksheet
        target_ws = get_or_create_worksheet(
            spreadsheet,
            TARGET_SHEET_NAME,
            rows=len(routine_data) + 5,
            cols=10,
        )

        if target_ws:
            if write_data_to_sheet(target_ws, routine_data):
                logger.info("Spreadsheet synchronization successful.")
            else:
                # Bail out before creating/updating NewMain or triggering the Apps
                # Script: the sort step reads 'backend' directly, so continuing here
                # would republish the PREVIOUS run's rows as if they were fresh.
                logger.error(
                    "Synchronization failed. Skipping post-processing; '%s' and '%s' "
                    "were left untouched.",
                    TARGET_SHEET_NAME,
                    NEW_MAIN_SHEET_NAME,
                )
                return 1
        else:
            logger.error("Target worksheet unreachable. Exiting.")
            return 1

        # 3b. Ensure the 'NewMain' worksheet exists for Apps Script post-processing
        new_main_ws = get_or_create_worksheet(
            spreadsheet,
            NEW_MAIN_SHEET_NAME,
            rows=max(30, len(routine_data) + 5),
            cols=10,
            seed_headers=True,
        )
        if not new_main_ws:
            logger.error("NewMain worksheet unreachable. Exiting.")
            return 1

    except gspread.exceptions.SpreadsheetNotFound:
        logger.error("Spreadsheet '%s' not found.", SPREADSHEET_NAME)
        return 1
    except Exception as e:
        logger.error("Critical error during synchronization: %s", e)
        traceback.print_exc()
        return 1

    # 4. Trigger post-processing via Apps Script
    logger.info("\nTriggering post-processing workflow...")
    if APP_SCRIPT_ID == 'YOUR_APP_SCRIPT_ID_GOES_HERE':
        logger.error(
            "APP_SCRIPT_ID is not configured; '%s' was not re-sorted.",
            NEW_MAIN_SHEET_NAME,
        )
        exit_code = 1
    else:
        call_success = call_apps_script_function(
            script_id=APP_SCRIPT_ID,
            function_name=FUNCTION_NAME,
            client_secrets_file=GOOGLE_OAUTH_CLIENT_SECRET_FILE,
            token_pickle_file=TOKEN_PICKLE_FILE,
            scopes=APP_SCRIPT_SCOPES,
        )
        if call_success:
            logger.info("Post-processing complete. Sheets updated.")
        else:
            logger.error("Post-processing trigger failed.")
            exit_code = 1

    if exit_code == 0:
        # One line that answers "did last night's run do anything?" from the
        # journal, without opening the spreadsheet.
        logger.info(
            "Run summary: %d entries (%.1f h old) | '%s' -> %s('%s') -> '%s'",
            len(routine_data),
            age_hours,
            TARGET_SHEET_NAME,
            FUNCTION_NAME,
            NEW_MAIN_SHEET_NAME,
            SPREADSHEET_NAME,
        )
        logger.info("Workflow execution finished.")
    else:
        logger.error("Workflow execution finished with errors (exit %d).", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
