import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

import gspread

from config import (
    MAX_DATA_AGE_HOURS,
    SPREADSHEET_NAME,
    TARGET_SHEET_NAME,
    setup_logging,
)
from routine_format import (
    DATA_START_COL,
    DATA_START_ROW,
    DATA_WIDTH,
    NO_DATA_MESSAGE,
    SHEET_HEADERS,
    SIGNATURE,
    build_newmain_rows,
    build_sheet_data,
    contact_column_letter,
    format_stamp,
    stamp_row_for,
)

setup_logging()
logger = logging.getLogger(__name__)
logger.info("gsheet_formatter.py starting...")

# [Configuration]
NEW_MAIN_SHEET_NAME = 'NewMain'

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

# The 'NewMain' block spans B..I; a worksheet needs at least this many columns
# before anything can be written into it.
NEW_MAIN_LAST_COL = DATA_START_COL + DATA_WIDTH - 1


# [Helper Functions]



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

def get_or_create_worksheet(spreadsheet, sheet_name, rows=100, cols=20, seed_headers=False,
                            min_rows=None, min_cols=None):
    """
    Retrieves a worksheet by name, creating it if it does not exist.

    Args:
        spreadsheet (gspread.Spreadsheet): The target spreadsheet object.
        sheet_name (str): Name of the worksheet to retrieve or create.
        rows (str): Initial row count for new worksheet.
        cols (str): Initial column count for new worksheet.
        seed_headers (bool): If True, write SHEET_HEADERS to B3:I3 when a new
            worksheet is created (matches the data block at B4).
        min_rows (int): Grow an existing worksheet to at least this many rows.
        min_cols (int): Grow an existing worksheet to at least this many columns.

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
    grow_worksheet(worksheet, min_rows=min_rows, min_cols=min_cols)
    return worksheet


def grow_worksheet(worksheet, min_rows=None, min_cols=None):
    """
    Grow a worksheet when the required extent exceeds its current grid.

    Worksheets used to be sized only when they were created, so a routine that
    later grew past that size failed with "Range exceeds grid limits" - a
    routine that grew from 25 to 40 rows hit it on both the 'backend' write and
    the 'NewMain' write. Growth only: an existing sheet may deliberately carry
    more rows or columns than the routine needs, so this never shrinks.
    """
    current_rows = getattr(worksheet, "row_count", None) or 0
    current_cols = getattr(worksheet, "col_count", None) or 0
    target_rows = max(current_rows, min_rows or 0)
    target_cols = max(current_cols, min_cols or 0)
    if target_rows > current_rows or target_cols > current_cols:
        worksheet.resize(rows=target_rows, cols=target_cols)
        logger.info(
            "Grew '%s' from %dx%d to %dx%d to fit the routine.",
            worksheet.title, current_rows, current_cols, target_rows, target_cols,
        )


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

def write_newmain_sheet(worksheet, entries, now=None):
    """
    Render the sorted routine into the 'NewMain' worksheet.

    'NewMain' is built from the same in-memory entry list that was written to
    'backend' rather than reading 'backend' back out, so there is one source of
    truth and a serialisation surprise in the 'backend' write cannot leak into
    the sorted output.

    Args:
        worksheet (gspread.Worksheet): The 'NewMain' worksheet.
        entries (list): Routine entry dicts, as loaded from the scraper JSON.
        now (datetime | None): Timestamp for the footer; defaults to UTC now.

    Returns:
        bool: True when the sheet was fully updated, False otherwise.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        rows = build_newmain_rows(entries)

        # Content only: a manual styling pass on the sheet survives.
        worksheet.batch_clear([f"B{DATA_START_ROW}:I{worksheet.row_count}"])

        if rows:
            # RAW matches how 'backend' is written, so the two sheets agree
            # instead of 'NewMain' inheriting Sheets' typed coercion.
            worksheet.update(values=rows, range_name="B4", value_input_option="RAW")
            last_data_row = DATA_START_ROW - 1 + len(rows)
        else:
            worksheet.update(values=[[NO_DATA_MESSAGE]], range_name="B4")
            last_data_row = DATA_START_ROW

        stamp_row = stamp_row_for(last_data_row)
        worksheet.update([[format_stamp(now)]], f"B{stamp_row}")
        worksheet.update([[SIGNATURE]], f"B{stamp_row + 1}")
        worksheet.format(f"B{stamp_row}", {"horizontalAlignment": "LEFT"})
        worksheet.format(f"B{stamp_row + 1}", {"horizontalAlignment": "RIGHT"})

        logger.info("Wrote %d rows to '%s' (stamp at B%d).", len(rows), worksheet.title, stamp_row)
        return True
    except Exception as e:
        logger.error("Error writing to worksheet '%s': %s", worksheet.title, e)
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
            min_rows=len(routine_data) + 1,
            min_cols=DATA_WIDTH,
        )

        if target_ws:
            if write_data_to_sheet(target_ws, routine_data):
                logger.info("Spreadsheet synchronization successful.")
            else:
                # Bail out before touching NewMain: continuing would leave the
                # previous run's sorted rows on the sheet looking fresh.
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

        # 3b. Ensure the 'NewMain' worksheet exists, and is big enough for the
        # block plus the two footer rows.
        new_main_ws = get_or_create_worksheet(
            spreadsheet,
            NEW_MAIN_SHEET_NAME,
            rows=max(30, len(routine_data) + 5),
            cols=10,
            seed_headers=True,
            min_rows=len(routine_data) + 6,
            min_cols=NEW_MAIN_LAST_COL,
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

    # 4. Render the sorted output into 'NewMain'
    logger.info("\nWriting sorted output to '%s'...", NEW_MAIN_SHEET_NAME)
    if write_newmain_sheet(new_main_ws, routine_data):
        logger.info("Post-processing complete. Sheets updated.")
    else:
        logger.error("Writing '%s' failed.", NEW_MAIN_SHEET_NAME)
        exit_code = 1

    if exit_code == 0:
        # One line that answers "did last night's run do anything?" from the
        # journal, without opening the spreadsheet.
        logger.info(
            "Run summary: %d entries (%.1f h old) | '%s' -> '%s' on '%s'",
            len(routine_data),
            age_hours,
            TARGET_SHEET_NAME,
            NEW_MAIN_SHEET_NAME,
            SPREADSHEET_NAME,
        )
        logger.info("Workflow execution finished.")
    else:
        logger.error("Workflow execution finished with errors (exit %d).", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
