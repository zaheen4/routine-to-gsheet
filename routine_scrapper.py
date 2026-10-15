import json
import sys
import time
import asyncio
import traceback
import logging
import nodriver as nd
from bs4 import BeautifulSoup
import os
import csv
import re
import shutil
from datetime import datetime, timezone

from config import HEADLESS, CHROME_BINARY_PATH, setup_logging

setup_logging()
logger = logging.getLogger(__name__)
logger.info("Initializing routine scraper...")

# Path Configuration
CREDENTIALS_FILE = 'configs_to_edit/ucam_login_credentials.json'
TEACHER_DETAILS_FILE = 'configs_to_edit/teacher_contact_details.json'

# Output Directory Configuration
BASE_OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FORMATTED_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, "output_of_fetched_routine")
TMP_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, "tmp")

# Output Template Filenames
ATTENDANCE_DASHBOARD_HTML_FILENAME_TPL = 'attendance_dashboard_{section}.html'
ATTENDANCE_DATA_CSV_FILENAME_TPL = 'dashboard_data_{section}.csv'
ATTENDANCE_DATA_JSON_FILENAME_TPL = 'dashboard_data_{section}.json'

FINAL_ROUTINE_CSV_FILENAME = 'final_combined_routine.csv'
FINAL_ROUTINE_JSON_FILENAME = 'final_combined_routine.json'

# Retry policy for transient per-account failures (CDP node races, timeouts)
ACCOUNT_RETRY_ATTEMPTS = 2


# [Data Loading Functions]

# Roles an account can have. "primary" is the student's own section (keeps all
# courses); "lab_merge" accounts contribute their lab courses only.
USER_ROLES = ("primary", "lab_merge")


def resolve_user_roles(users):
    """
    Fills in an explicit role for every account and validates the assignment.

    ``role`` is optional and defaults to the historical positional behaviour
    (users[0] = primary, every other account = lab_merge).

    Returns:
        tuple(list | None, str | None): (accounts with ``role`` set, error).
        The list is None when the assignment is invalid.
    """
    resolved = []
    primary_count = 0
    for index, user in enumerate(users):
        role = user.get("role")
        if role is None:
            role = "primary" if index == 0 else "lab_merge"
        elif role not in USER_ROLES:
            return None, (
                f"users[{index}] has unknown role {role!r} "
                f"(expected one of: {', '.join(USER_ROLES)})"
            )
        if role == "primary":
            primary_count += 1
        resolved.append(dict(user, role=role))

    if primary_count != 1:
        return None, (
            f"exactly one account must have role 'primary', found {primary_count}"
        )
    return resolved, None


def load_credentials(file_path):
    """
    Loads and validates UCAM authentication credentials from a JSON source.
    """
    logger.info("Loading credentials from: %s", file_path)
    if not os.path.isabs(file_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
        
        required_top_keys = ["users", "login_url", "attendance_dashboard_url"]
        if not all(key in credentials for key in required_top_keys):
            logger.error("Missing top-level keys in %s", file_path)
            return None
            
        if not isinstance(credentials["users"], list) or not credentials["users"]:
            logger.error("'users' array is missing or empty.")
            return None
            
        for user in credentials["users"]:
            required_user_keys = ["id", "username", "password", "section_label"]
            if not all(key in user for key in required_user_keys):
                logger.error("Missing required user keys for ID: %s", user.get('id'))
                return None

        resolved_users, role_error = resolve_user_roles(credentials["users"])
        if role_error:
            logger.error("Invalid account roles in %s: %s", file_path, role_error)
            return None
        credentials["users"] = resolved_users

        return credentials
    except Exception as e:
        logger.error("Critical error loading credentials: %s", e)
        return None

def load_teacher_details_from_file(file_path):
    """
    Loads teacher contact information from a JSON source.
    """
    if not os.path.isabs(file_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_path)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            teacher_details = json.load(f)
        if isinstance(teacher_details, dict):
            teacher_details = {
                k: v for k, v in teacher_details.items() if not k.startswith("_")
            }
        logger.info("Loaded %d teacher entries.", len(teacher_details))
        return teacher_details
    except FileNotFoundError:
        logger.warning("Teacher details file not found at '%s'.", file_path)
        return {}
    except Exception as e:
        logger.error("Unexpected error loading teacher details: %s", e)
        return {}


# [Parsing Functions]

RE_COURSE_CODE = re.compile(r"Course Code\s*:\s*(.+)", re.IGNORECASE)
RE_TITLE = re.compile(r"Title\s*:\s*(.+)", re.IGNORECASE)
RE_CREDIT = re.compile(r"Credit\s*:\s*([0-9.]+)", re.IGNORECASE)
RE_SECTION = re.compile(r"Section\s*:\s*(.+)", re.IGNORECASE)
RE_DAY = re.compile(r"Day\s*:\s*(.+)", re.IGNORECASE)
RE_TIME = re.compile(r"Time\s*:\s*(.+)", re.IGNORECASE)
RE_ROOM = re.compile(r"Room\s*:\s*(.+)", re.IGNORECASE)
RE_TEACHER = re.compile(r"Teacher\s*:\s*(\S+)", re.IGNORECASE)

def _extract(pattern, text):
    match = pattern.search(text)
    return match.group(1).strip() if match else ""

def parse_attendance_dashboard_data(html_content, user_section_label_tag):
    """
    Parses routine data from the UCAM attendance dashboard HTML.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    dashboard_entries = []

    main_table = soup.find('table', id="ctl00_MainContainer_gvCourseList")
    if not main_table:
        logger.error("Data table not found for section %s.", user_section_label_tag)
        return dashboard_entries

    rows = main_table.find_all('tr')
    if len(rows) < 2:
        return dashboard_entries

    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        entry = {"SL": cells[0].get_text(strip=True), "UserScrapedSection": user_section_label_tag}

        course_info_raw = cells[1].get_text(separator='\n', strip=True)
        entry["CourseCode"] = _extract(RE_COURSE_CODE, course_info_raw)
        entry["CourseTitle"] = _extract(RE_TITLE, course_info_raw)
        entry["Credit"] = _extract(RE_CREDIT, course_info_raw)
        entry["CourseSection"] = _extract(RE_SECTION, course_info_raw)

        schedule_one_raw = cells[2].get_text(separator='\n', strip=True)
        entry["ScheduleOne_Day"] = _extract(RE_DAY, schedule_one_raw)
        entry["ScheduleOne_Time"] = _extract(RE_TIME, schedule_one_raw)
        entry["ScheduleOne_Room"] = _extract(RE_ROOM, schedule_one_raw)
        entry["ScheduleOne_TeacherInitial"] = _extract(RE_TEACHER, schedule_one_raw)

        schedule_two_raw = cells[3].get_text(separator='\n', strip=True)
        entry["ScheduleTwo_Day"] = _extract(RE_DAY, schedule_two_raw)
        entry["ScheduleTwo_Time"] = _extract(RE_TIME, schedule_two_raw)
        entry["ScheduleTwo_Room"] = _extract(RE_ROOM, schedule_two_raw)
        entry["ScheduleTwo_TeacherInitial"] = _extract(RE_TEACHER, schedule_two_raw)

        dashboard_entries.append(entry)

    return dashboard_entries


# [Persistence Functions]

def save_data_to_file(data, output_dir, filename, file_type='csv', fieldnames=None):
    """
    Persists data to disk in the specified format.

    The write is atomic: content lands in a temporary sibling file which is
    only renamed over the target once it is fully flushed, so an interrupted
    run can never leave a truncated CSV/JSON for the next stage to read.

    Returns:
        bool: True when the file was written, False otherwise.
    """
    if not data:
        return False

    output_file_path = os.path.join(output_dir, filename)
    tmp_file_path = f"{output_file_path}.tmp"

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        logger.error("Failed to prepare output directory '%s': %s", output_dir, e)
        return False

    if file_type == 'csv':
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            logger.error("Invalid CSV data format for %s", filename)
            return False

        if fieldnames is None:
            fieldnames = list(data[0].keys())

        try:
            with open(tmp_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.error("Failed to export CSV '%s': %s", output_file_path, e)
            _discard_file(tmp_file_path)
            return False

    elif file_type == 'json':
        try:
            with open(tmp_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to export JSON '%s': %s", output_file_path, e)
            _discard_file(tmp_file_path)
            return False

    else:
        logger.error("Unsupported file type '%s' for %s", file_type, filename)
        return False

    try:
        os.replace(tmp_file_path, output_file_path)
    except OSError as e:
        logger.error("Failed to finalize '%s': %s", output_file_path, e)
        _discard_file(tmp_file_path)
        return False

    logger.info("Exported %s: %s", file_type.upper(), output_file_path)
    return True


def _discard_file(path):
    """Best-effort removal of a temporary file; never raises."""
    try:
        os.remove(path)
    except OSError:
        pass


def invalidate_previous_output(output_dir):
    """
    Removes the previous run's combined output before a new scrape starts.

    The formatter publishes whatever routine JSON it finds, so a run that dies
    before writing (SIGKILL, disk full, systemd timeout) must not leave last
    week's file on disk where it would look like this week's data. Per-section
    dumps in tmp/ are kept for post-mortem debugging.
    """
    removed = []
    for filename in (FINAL_ROUTINE_JSON_FILENAME, FINAL_ROUTINE_CSV_FILENAME):
        path = os.path.join(output_dir, filename)
        try:
            os.remove(path)
            removed.append(filename)
        except FileNotFoundError:
            continue
        except OSError as e:
            logger.error("Could not remove stale output '%s': %s", path, e)
    if removed:
        logger.info("Invalidated previous output: %s", ", ".join(removed))


# [Data Merging Functions]

def _schedule_entry(item, prefix, teacher_details):
    """
    Builds a final routine entry dict for one schedule slot of a scraped item.

    Args:
        item (dict): A scraped dashboard entry.
        prefix (str): "ScheduleOne" or "ScheduleTwo".
        teacher_details (dict): Teacher initials -> contact details.

    Returns:
        dict or None: A routine entry, or None if the slot has no day.
    """
    day = item.get(f"{prefix}_Day")
    if not day or day.lower().startswith("time :"):
        return None

    entry = {
        "CourseCode": item.get("CourseCode"),
        "CourseTitle": item.get("CourseTitle"),
        "Section": item.get("CourseSection"),
        "Day": day,
        "Room": item.get(f"{prefix}_Room"),
        "TimeSlot": item.get(f"{prefix}_Time"),
    }

    initial = item.get(f"{prefix}_TeacherInitial")
    details = teacher_details.get(initial, {})
    entry.update({
        "Teacher": details.get("FullName", initial or "N/A"),
        "TeacherPhone": details.get("Phone", ""),
        "TeacherEmail": details.get("Email", "")
    })
    return entry

def missing_teacher_initials(all_collected_data, teacher_details):
    """
    Collects teacher initials present in the scraped data but missing from
    the teacher details file.

    Returns a sorted set of unknown initials (empty when all are known).
    """
    known = set(teacher_details.keys())
    scraped = set()
    for item in all_collected_data:
        for prefix in ("ScheduleOne", "ScheduleTwo"):
            initial = item.get(f"{prefix}_TeacherInitial")
            if initial:
                scraped.add(initial)
    return sorted(initial for initial in scraped if initial not in known)


LAB_TITLE_RE = re.compile(r"\blab\b", re.IGNORECASE)


def _lab_section_set(lab_sections):
    """Normalises the lab-section argument (None | str | iterable) to a set."""
    if not lab_sections:
        return set()
    if isinstance(lab_sections, str):
        return {lab_sections}
    return {section for section in lab_sections if section}


def build_final_routine(all_collected_data, primary_section, lab_sections, teacher_details):
    """
    Merges per-section scraped data into the final deduplicated routine.

    The primary section keeps all courses; every lab_merge section contributes
    only lab courses (title contains the word "lab"). Entries are deduplicated
    by (CourseCode, Day, TimeSlot, Section).

    Args:
        lab_sections: A single section label, None, or an iterable of labels.
    """
    missing = missing_teacher_initials(all_collected_data, teacher_details)
    if missing:
        logger.warning(
            "Teacher initials not found in teacher_contact_details.json: %s",
            ", ".join(missing),
        )

    lab_section_labels = _lab_section_set(lab_sections)
    final_routine = []

    for item in all_collected_data:
        is_lab = bool(LAB_TITLE_RE.search(item.get("CourseTitle", "")))
        item_section = item.get("UserScrapedSection")

        if item_section == primary_section or (item_section in lab_section_labels and is_lab):
            for prefix in ("ScheduleOne", "ScheduleTwo"):
                entry = _schedule_entry(item, prefix, teacher_details)
                if entry:
                    final_routine.append(entry)

    unique_routine = []
    seen = set()
    for entry in final_routine:
        uid = (entry["CourseCode"], entry["Day"], entry["TimeSlot"], entry["Section"])
        if uid not in seen:
            unique_routine.append(entry)
            seen.add(uid)

    return unique_routine


# [Web Scraping Logic]

# UCAM portal DOM selector constants
MASKING_URL = "https://www.google.com"
MASKING_SETTLE_S = 3
PORTAL_GET_SETTLE_S = 15
CLOUDFLARE_COOLDOWN_S = 5
SEMESTER_SELECT_SETTLE_S = 5
PORTAL_ACCESS_ATTEMPTS = 3
LOGIN_WAIT_S = 20
LOGIN_FIELD_WAIT_S = 10
LOGIN_SUCCESS_WAIT_S = 45
SEMESTER_WAIT_S = 20
COURSE_TABLE_WAIT_S = 45
EVALUATE_POLL_S = 0.5

LOGIN_USERNAME_ID = "logMain_UserName"
LOGIN_PASSWORD_ID = "logMain_Password"
LOGIN_BUTTON_ID = "logMain_Button1"
LOGIN_SUCCESS_ID = "ctl00_lbtnUserName"
SEMESTER_DROPDOWN_ID = "ctl00_MainContainer_ddlHeldIn"
UPDATE_PANEL_ID = "ctl00_MainContainer_UpdatePanel02"
COURSE_TABLE_ID = "ctl00_MainContainer_gvCourseList"

CLOUDFLARE_TITLE_MARKERS = ("just a moment", "cloudflare", "attention required")


class ScrapeTimeoutError(TimeoutError):
    """Raised when a required page element does not appear within its wait window."""


def _is_cloudflare_blocked(page_title):
    lowered = (page_title or "").lower()
    return any(marker in lowered for marker in CLOUDFLARE_TITLE_MARKERS)


# --- nodriver evaluation helpers -------------------------------------------

def _semester_options_js():
    return (
        "(() => {"
        f" const sel = document.getElementById('{SEMESTER_DROPDOWN_ID}');"
        " if (!sel) return null;"
        " return JSON.stringify(Array.prototype.map.call(sel.options,"
        "   function (o) { return {text: o.text, value: o.value}; }));"
        "})()"
    )


def _select2_selection_js():
    """
    Opens the select2 dropdown. select2 4.x binds the single-selection toggle on
    ``mousedown`` (checking ``e.which === 1``), so a plain ``element.click()``
    never opens it. The synthesized event must carry ``button``/``buttons`` so
    ``e.which`` resolves to 1.
    """
    return (
        "(() => {"
        f" const sel = document.getElementById('{SEMESTER_DROPDOWN_ID}');"
        " const container = sel ? sel.closest('.select2-container') : null;"
        " let target = null;"
        " if (container) {"
        "   target = container.querySelector('.select2-selection') || container;"
        " } else {"
        "   target = document.querySelector('.select2-container .select2-selection')"
        "         || document.querySelector('.select2-container');"
        " }"
        " if (!target) return false;"
        " target.dispatchEvent(new MouseEvent('mousedown', {"
        "   bubbles: true, cancelable: true, view: window, button: 0, buttons: 1,"
        " }));"
        " return true;"
        "})()"
    )


def _select2_option_js(option_text):
    """
    Clicks the select2 result whose text matches ``option_text``. Result
    selection in select2 4.x is bound on ``mouseup`` over the option ``li``
    (delegated on ``.select2-results``), and the results are ``li`` elements
    under ``div.select2-results > ul.select2-results__options`` - hence the
    version-agnostic ``.select2-results li`` query plus a synthetic ``mouseup``.
    """
    target = json.dumps(option_text)
    return (
        "(() => {"
        " const items = Array.prototype.slice.call("
        "   document.querySelectorAll('.select2-results li'));"
        " for (const li of items) {"
        f"   if (li.textContent.trim() === {target}) {{"
        "     li.dispatchEvent(new MouseEvent('mouseup', {"
        "       bubbles: true, cancelable: true, view: window,"
        "       button: 0, buttons: 0,"
        "     }));"
        "     li.dispatchEvent(new MouseEvent('click', {"
        "       bubbles: true, cancelable: true, view: window,"
        "       button: 0, buttons: 0,"
        "     }));"
        "     return true;"
        "   }"
        " }"
        " return false;"
        "})()"
    )


def _dashboard_html_js():
    return (
        "(() => {"
        f" const panel = document.getElementById('{UPDATE_PANEL_ID}');"
        " if (!panel) return null;"
        " return panel.innerHTML;"
        "})()"
    )


async def _evaluate_until(tab, expression, timeout, interval=EVALUATE_POLL_S, predicate=None):
    """
    Polls ``tab.evaluate(expression)`` until ``predicate`` is satisfied or the
    timeout elapses. Returns the matching result, or None on timeout. JS errors
    (which nodriver surfaces as a value rather than an exception) simply never
    satisfy the predicate.
    """
    if predicate is None:
        predicate = lambda value: value is not None
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = await tab.evaluate(expression)
        except Exception:
            result = None
        if predicate(result):
            return result
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(interval)


async def _get_title(tab):
    """Returns the current page title, or '' when it cannot be read."""
    try:
        result = await tab.evaluate("document.title")
    except Exception:
        result = None
    return str(result) if isinstance(result, str) else ""


async def _read_semester_options(tab, timeout):
    """
    Returns the semester <option> list as [{text, value}, ...], or None when the
    dropdown never appears within ``timeout``.
    """
    result = await _evaluate_until(
        tab, _semester_options_js(), timeout, predicate=lambda value: isinstance(value, str)
    )
    if result is None:
        return None
    try:
        return json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return None


async def _click_select2_selection(tab, timeout):
    """Opens the select2 dropdown; returns True once the container was clicked."""
    result = await _evaluate_until(
        tab, _select2_selection_js(), timeout, predicate=lambda value: value is True
    )
    return result is True


async def _click_select2_option(tab, option_text, timeout):
    """Clicks the select2 result matching ``option_text``; returns True on success."""
    result = await _evaluate_until(
        tab, _select2_option_js(option_text), timeout, predicate=lambda value: value is True
    )
    return result is True


async def _read_dashboard_html(tab):
    """Returns the update panel's innerHTML, or None when the panel is absent."""
    try:
        result = await tab.evaluate(_dashboard_html_js())
    except Exception:
        result = None
    return result if isinstance(result, str) else None


async def _safe_get_content(tab):
    """Best-effort page HTML for debug logs; never raises."""
    try:
        content = await tab.get_content()
        return str(content) if content else ""
    except Exception:
        return ""


# --- browser session --------------------------------------------------------

def _session_tab(browser):
    """The browser's single session tab (what ``get`` navigates)."""
    main_tab = getattr(browser, "main_tab", None)
    return main_tab if main_tab is not None else browser


async def masking_visit(tab, url=MASKING_URL, settle_s=MASKING_SETTLE_S):
    """
    Visits a neutral site first to establish browsing context before the portal.
    """
    try:
        logger.info("Masking entry: Establishing context via Google...")
        await tab.get(url)
        await asyncio.sleep(settle_s)
    except Exception:
        logger.exception("Masking visit failed; continuing anyway.")


async def bypass_cloudflare_and_wait_for_login(tab, login_url, max_attempts=PORTAL_ACCESS_ATTEMPTS):
    """
    Opens the login page, retrying until Cloudflare lets us through and the
    UCAM login fields render. Raises ScrapeTimeoutError if blocked for good.
    """
    for attempt in range(1, max_attempts + 1):
        logger.info("Portal access attempt %d to: %s", attempt, login_url)
        await tab.get(login_url)

        await asyncio.sleep(PORTAL_GET_SETTLE_S)
        page_title = await _get_title(tab)
        logger.info("Current Page Title: '%s'", page_title)

        if _is_cloudflare_blocked(page_title):
            logger.info("Cloudflare block persisting. Refreshing session (Attempt %d)...", attempt)
            await asyncio.sleep(CLOUDFLARE_COOLDOWN_S)
            continue

        login_field = await tab.select(f"#{LOGIN_USERNAME_ID}", timeout=LOGIN_WAIT_S)
        if login_field is not None:
            logger.info("UCAM Login fields detected. Challenge likely bypassed.")
            return

        if attempt == max_attempts:
            logger.error("Critical: Failed to bypass Cloudflare after maximum retries.")
            logger.error("Page Snippet: %s", (await _safe_get_content(tab))[:500])
            raise ScrapeTimeoutError("Cloudflare challenge block.")
        logger.info("Retrying portal access...")

    raise ScrapeTimeoutError("Cloudflare challenge block.")


async def authenticate(user_creds, tab):
    """
    Fills the UCAM login form and waits for the post-login element to appear.
    """
    logger.info("Authenticating with student credentials...")
    user_field = await tab.select(f"#{LOGIN_USERNAME_ID}", timeout=LOGIN_WAIT_S)
    if user_field is None:
        raise ScrapeTimeoutError(f"Login username field not found within {LOGIN_WAIT_S}s.")
    pass_field = await tab.select(f"#{LOGIN_PASSWORD_ID}", timeout=LOGIN_FIELD_WAIT_S)
    if pass_field is None:
        raise ScrapeTimeoutError(f"Login password field not found within {LOGIN_FIELD_WAIT_S}s.")
    login_btn = await tab.select(f"#{LOGIN_BUTTON_ID}", timeout=LOGIN_FIELD_WAIT_S)
    if login_btn is None:
        raise ScrapeTimeoutError(f"Login button not found within {LOGIN_FIELD_WAIT_S}s.")

    await user_field.send_keys(user_creds['username'])
    await pass_field.send_keys(user_creds['password'])
    await login_btn.click()

    success = await tab.select(f"#{LOGIN_SUCCESS_ID}", timeout=LOGIN_SUCCESS_WAIT_S)
    if success is None:
        raise ScrapeTimeoutError(
            f"Login success indicator not found within {LOGIN_SUCCESS_WAIT_S}s."
        )
    logger.info("User %s authenticated successfully.", user_creds['id'])


async def select_semester(tab, attendance_dashboard_url, section_label):
    """
    Navigates to the dashboard and selects the first non-placeholder semester
    through the select2 control. Returns the chosen semester label.
    """
    await tab.get(attendance_dashboard_url)

    options = await _read_semester_options(tab, timeout=COURSE_TABLE_WAIT_S)
    if options is None:
        raise ScrapeTimeoutError(
            f"Semester dropdown #{SEMESTER_DROPDOWN_ID} not found for section {section_label}."
        )
    target_semester = next(
        (opt["text"] for opt in options if opt["value"] != "0"),
        None,
    )

    if not target_semester:
        raise ValueError(f"No valid semester options found for section {section_label}.")

    if not await _click_select2_selection(tab, timeout=SEMESTER_WAIT_S):
        raise ScrapeTimeoutError(
            f"Select2 dropdown could not be opened for section {section_label}."
        )

    if not await _click_select2_option(tab, target_semester, timeout=SEMESTER_WAIT_S):
        raise ScrapeTimeoutError(
            f"Select2 option '{target_semester}' not found for section {section_label}."
        )

    logger.info("Dashboard synchronized for semester: %s.", target_semester)
    await asyncio.sleep(SEMESTER_SELECT_SETTLE_S)
    return target_semester


async def extract_dashboard(tab, section_label):
    """
    Reads the course list table HTML from the dashboard panel and persists the
    parsed entries to per-section CSV/JSON files.

    When the table element is present but no rows parse, the raw panel HTML is
    dumped to tmp/ so the failure (usually portal markup drift) is diagnosable
    after the fact instead of only leaving "no valid entries" in the log.
    """
    table = await tab.select(
        f"#{UPDATE_PANEL_ID} #{COURSE_TABLE_ID}", timeout=COURSE_TABLE_WAIT_S
    )
    if table is None:
        raise ScrapeTimeoutError(
            f"Course table not found within {COURSE_TABLE_WAIT_S}s for section {section_label}."
        )

    dashboard_html = await _read_dashboard_html(tab)
    if not dashboard_html:
        logger.error(
            "Update panel '%s' returned no HTML for section %s; cannot extract the course table.",
            UPDATE_PANEL_ID,
            section_label,
        )
        return []

    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
    user_dashboard_data = parse_attendance_dashboard_data(dashboard_html, section_label)

    if not user_dashboard_data:
        failure_path = os.path.join(
            TMP_OUTPUT_DIR,
            ATTENDANCE_DASHBOARD_HTML_FILENAME_TPL.format(section=section_label),
        )
        try:
            with open(failure_path, "w", encoding="utf-8") as f:
                f.write(dashboard_html)
            logger.error(
                "Parsed 0 course rows for section %s even though table '%s' is "
                "present (likely portal markup drift). Raw panel HTML saved to %s.",
                section_label,
                COURSE_TABLE_ID,
                failure_path,
            )
        except OSError:
            logger.exception("Failed to save diagnostic HTML for section %s.", section_label)
        return []

    dash_csv = ATTENDANCE_DATA_CSV_FILENAME_TPL.format(section=section_label)
    dash_json = ATTENDANCE_DATA_JSON_FILENAME_TPL.format(section=section_label)
    save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_csv, "csv")
    save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_json, "json")

    return user_dashboard_data


async def scrape_dashboard_for_user(tab, user_creds, common_urls):
    """
    Executes the scraping workflow for a specific user profile.

    Returns:
        tuple(list, str): the parsed dashboard entries and the semester label
        that was selected on the portal.
    """
    section_label = user_creds['section_label']
    logger.info("--- Processing User Profile: %s (%s) ---", user_creds['id'], section_label)

    await masking_visit(tab)

    try:
        await bypass_cloudflare_and_wait_for_login(tab, common_urls['login_url'])
        await authenticate(user_creds, tab)
    except Exception as e:
        logger.error("Authentication Failure: %s", type(e).__name__)
        raise

    semester = await select_semester(
        tab, common_urls['attendance_dashboard_url'], section_label
    )
    entries = await extract_dashboard(tab, section_label)
    return entries, semester

CHROME_BINARY_NAMES = ["google-chrome-stable", "google-chrome", "chromium-browser", "chromium"]

def _platform_chrome_candidates():
    """
    Well-known Chrome/Chromium install paths, by platform.

    macOS .app bundles and Windows Program Files installs are not on PATH,
    so `shutil.which` cannot find them. Returns deduplicated candidate paths
    (empty on Linux, where PATH-scan names above are the only option).
    """
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif os.name == "nt":
        bases = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramW6432"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for base in bases:
            if not base:
                continue
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
            candidates.append(os.path.join(base, "Chromium", "Application", "chrome.exe"))
    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]

def get_chrome_executable():
    """
    Resolve the exact Chrome binary to launch.

    Precedence: CHROME_BINARY_PATH env override, then a deterministic PATH scan,
    then well-known per-platform install paths. Passed to nodriver as
    browser_executable_path so the launched browser always matches what was
    detected (nodriver has no chromedriver to version-match).
    """
    if CHROME_BINARY_PATH:
        if os.path.isfile(CHROME_BINARY_PATH):
            logger.info("Using Chrome binary from CHROME_BINARY_PATH: %s", CHROME_BINARY_PATH)
            return CHROME_BINARY_PATH
        logger.warning("CHROME_BINARY_PATH set but not found: %s", CHROME_BINARY_PATH)
    for binary in CHROME_BINARY_NAMES:
        path = shutil.which(binary)
        if path:
            return path
    for candidate in _platform_chrome_candidates():
        if os.path.isfile(candidate):
            logger.info("Found Chrome binary at well-known path: %s", candidate)
            return candidate
    return None


async def launch_browser():
    """
    Starts a fresh Chrome session via nodriver (CDP directly - no chromedriver).

    On headless Linux, HEADLESS should be False so Chrome renders on the Xvfb
    virtual display rather than being challenged by Cloudflare's headless
    detection; scripts/run_routine.sh already wraps the scraper in xvfb-run.
    """
    chrome_path = get_chrome_executable()
    if not chrome_path:
        logger.error(
            "No Chrome binary found on this system. Install Chrome/Chromium or "
            "set CHROME_BINARY_PATH."
        )
        raise RuntimeError("No Chrome binary found on this system.")

    browser_args = [
        "--window-size=1920,1080",
        "--disable-gpu",
        "--disable-blink-features=AutomationControlled",
        "--profile-directory=Default",
    ]
    if not HEADLESS and sys.platform.startswith("linux"):
        browser_args.append("--ozone-platform=x11")
        browser_args.append("--ozone-platform-hint=x11")

    logger.info("Launching Chrome: %s (headless=%s)", chrome_path, HEADLESS)
    return await nd.start(
        headless=HEADLESS,
        browser_executable_path=chrome_path,
        browser_args=browser_args,
        sandbox=False,
    )


async def scrape_account_with_retries(profile, common_urls):
    """
    Runs the full scraping workflow for one account, retrying transient
    failures (CDP node races, network blips, timeouts) with a fresh browser
    session per attempt.

    Returns:
        tuple(list, str): the collected dashboard entries and the selected
        semester label. Re-raises the last error once all attempts are
        exhausted.
    """
    last_exc = None
    for attempt in range(1, ACCOUNT_RETRY_ATTEMPTS + 1):
        browser = None
        tab = None
        logger.info(
            "--- Initializing Session: %s (attempt %d/%d) ---",
            profile['id'], attempt, ACCOUNT_RETRY_ATTEMPTS,
        )
        try:
            browser = await launch_browser()
            tab = _session_tab(browser)
            return await scrape_dashboard_for_user(tab, profile, common_urls)
        except Exception as e:
            last_exc = e
            logger.error(
                "Workflow Exception for %s (attempt %d/%d): %s",
                profile['id'], attempt, ACCOUNT_RETRY_ATTEMPTS, e,
            )
            if tab is not None:
                try:
                    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
                    log_path = os.path.join(
                        TMP_OUTPUT_DIR, f"error_log_{profile['id']}.html"
                    )
                    content = await _safe_get_content(tab)
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    logger.info("Debug log saved: %s", log_path)
                except Exception:
                    logger.exception("Failed to save debug log for %s.", profile['id'])
            if attempt < ACCOUNT_RETRY_ATTEMPTS:
                logger.warning(
                    "Retrying %s with a fresh browser session...", profile['id']
                )
        finally:
            if browser is not None:
                try:
                    browser.stop()
                except Exception:
                    logger.exception("Failed to stop browser for %s.", profile['id'])
                logger.info("Session closed for %s.", profile['id'])
    raise last_exc or RuntimeError("no scrape attempts were made")


def build_run_output(entries, account_summaries, primary_semester, generated_at=None):
    """
    Builds the run manifest written to FINAL_ROUTINE_JSON_FILENAME.

    The manifest carries provenance (when, from which semester, which accounts)
    so the formatter can refuse to publish stale data and so a "wrong semester"
    run is diagnosable after the fact.
    """
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "semester": primary_semester,
        "accounts": account_summaries,
        "entries": entries,
    }


# [Main Workflow]

async def main():
    logger.info("Executing scraper workflow...")
    
    credentials = load_credentials(CREDENTIALS_FILE)
    if not credentials:
        logger.error(
            "Termination: %s is missing or invalid (needs 'users', 'login_url' and "
            "'attendance_dashboard_url'). See SETUP.md Phase A4.",
            CREDENTIALS_FILE,
        )
        sys.exit(1)

    # Drop the previous run's output now: if this run dies before writing (kill,
    # disk full, timeout), the formatter must not find last week's data and
    # republish it as this week's routine.
    invalidate_previous_output(FORMATTED_OUTPUT_DIR)

    teacher_details = load_teacher_details_from_file(TEACHER_DETAILS_FILE)
    all_collected_data = []
    failed_accounts = []
    account_summaries = []
    primary_semester = None

    common_urls = {
        "login_url": credentials["login_url"],
        "attendance_dashboard_url": credentials["attendance_dashboard_url"]
    }

    for profile in credentials["users"]:
        try:
            user_data, semester = await scrape_account_with_retries(profile, common_urls)
        except Exception as e:
            logger.error(
                "Account %s failed after %d attempt(s): %s",
                profile['id'], ACCOUNT_RETRY_ATTEMPTS, e,
            )
            failed_accounts.append(profile['id'])
            continue

        all_collected_data.extend(user_data)
        account_summaries.append({
            "id": profile["id"],
            "section_label": profile.get("section_label"),
            "role": profile.get("role"),
            "semester": semester,
            "entries": len(user_data),
        })
        if profile.get("role") == "primary":
            primary_semester = semester

    if failed_accounts:
        logger.error(
            "Aborting export due to failed account(s): %s. Partial data will not be published.",
            ", ".join(str(f) for f in failed_accounts),
        )
        sys.exit(1)

    if not all_collected_data:
        logger.error("Data collection yielded zero results. Aborting export.")
        sys.exit(1)

    logger.info("--- Processing Combined Results ---")
    primary_section = next(
        user["section_label"]
        for user in credentials["users"]
        if user.get("role") == "primary"
    )
    lab_sections = [
        user["section_label"]
        for user in credentials["users"]
        if user.get("role") == "lab_merge"
    ]

    unique_routine = build_final_routine(all_collected_data, primary_section, lab_sections, teacher_details)

    if not unique_routine:
        logger.error(
            "No valid routine entries left after merging: %d raw entries collected, "
            "primary section '%s', lab section(s) %s. If the portal has published the "
            "schedule, check the raw panel HTML in %s.",
            len(all_collected_data),
            primary_section,
            lab_sections or "none",
            TMP_OUTPUT_DIR,
        )
        sys.exit(1)

    logger.info("Exporting %d unique entries.", len(unique_routine))
    if not save_data_to_file(
        unique_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_CSV_FILENAME, "csv",
        fieldnames=["CourseCode", "CourseTitle", "Teacher", "TeacherPhone", "TeacherEmail", "Day", "Room", "TimeSlot", "Section"],
    ):
        # The CSV is a human-readable convenience artifact; the JSON is the
        # contract the formatter consumes, so a CSV failure is not fatal.
        logger.warning("Could not write %s (non-fatal).", FINAL_ROUTINE_CSV_FILENAME)

    run_output = build_run_output(
        unique_routine, account_summaries, primary_semester
    )
    if not save_data_to_file(
        run_output, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_JSON_FILENAME, "json"
    ):
        logger.error(
            "Failed to write %s. Aborting so the formatter cannot re-sync stale data.",
            FINAL_ROUTINE_JSON_FILENAME,
        )
        sys.exit(1)

    logger.info("Scraper workflow finished.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as e:
        logger.error("Fatal global error: %s", e)
        traceback.print_exc()
        sys.exit(1)
