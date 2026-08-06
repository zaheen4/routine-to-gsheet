import json
import time
import subprocess
import traceback
import logging
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import os
import csv
import re
import shutil

from config import PREFERRED_BROWSER, HEADLESS, CHROME_BINARY_PATH, setup_logging

# Browser-specific imports
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.firefox import GeckoDriverManager

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


# [Data Loading Functions]

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
    """
    if not data: return
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, filename)

    if file_type == 'csv':
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            logger.error("Invalid CSV data format for %s", filename)
            return

        if fieldnames is None:
            fieldnames = list(data[0].keys())

        try:
            with open(output_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(data)
            logger.info("Exported CSV: %s", output_file_path)
        except Exception as e:
            logger.error("Failed to export CSV: %s", e)
            
    elif file_type == 'json':
        try:
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.info("Exported JSON: %s", output_file_path)
        except Exception as e:
            logger.error("Failed to export JSON: %s", e)


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


def build_final_routine(all_collected_data, primary_section, secondary_section, teacher_details):
    """
    Merges per-section scraped data into the final deduplicated routine.

    The primary section keeps all courses; the secondary section contributes
    only lab courses (title contains "lab"). Entries are deduplicated by
    (CourseCode, Day, TimeSlot, Section).
    """
    missing = missing_teacher_initials(all_collected_data, teacher_details)
    if missing:
        logger.warning(
            "Teacher initials not found in teacher_contact_details.json: %s",
            ", ".join(missing),
        )

    final_routine = []

    for item in all_collected_data:
        is_lab = "lab" in item.get("CourseTitle", "").lower()
        item_section = item.get("UserScrapedSection")

        if item_section == primary_section or (item_section == secondary_section and is_lab):
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

LOGIN_USERNAME_ID = "logMain_UserName"
LOGIN_PASSWORD_ID = "logMain_Password"
LOGIN_BUTTON_ID = "logMain_Button1"
LOGIN_SUCCESS_ID = "ctl00_lbtnUserName"
SEMESTER_DROPDOWN_ID = "ctl00_MainContainer_ddlHeldIn"
UPDATE_PANEL_ID = "ctl00_MainContainer_UpdatePanel02"
COURSE_TABLE_ID = "ctl00_MainContainer_gvCourseList"

CLOUDFLARE_TITLE_MARKERS = ("just a moment", "cloudflare", "attention required")


def _is_cloudflare_blocked(page_title):
    lowered = (page_title or "").lower()
    return any(marker in lowered for marker in CLOUDFLARE_TITLE_MARKERS)


def masking_visit(driver, url=MASKING_URL, settle_s=MASKING_SETTLE_S):
    """
    Visits a neutral site first to establish browsing context before the portal.
    """
    try:
        logger.info("Masking entry: Establishing context via Google...")
        driver.get(url)
        time.sleep(settle_s)
    except Exception:
        logger.exception("Masking visit failed; continuing anyway.")


def bypass_cloudflare_and_wait_for_login(driver, login_url, max_attempts=PORTAL_ACCESS_ATTEMPTS):
    """
    Opens the login page, retrying until Cloudflare lets us through and the
    UCAM login fields render. Raises TimeoutException if blocked for good.
    """
    for attempt in range(1, max_attempts + 1):
        logger.info("Portal access attempt %d to: %s", attempt, login_url)
        driver.get(login_url)

        time.sleep(PORTAL_GET_SETTLE_S)
        page_title = driver.title
        logger.info("Current Page Title: '%s'", page_title)

        if _is_cloudflare_blocked(page_title):
            logger.info("Cloudflare block persisting. Refreshing session (Attempt %d)...", attempt)
            time.sleep(CLOUDFLARE_COOLDOWN_S)
            continue

        try:
            WebDriverWait(driver, LOGIN_WAIT_S).until(
                EC.presence_of_element_located((By.ID, LOGIN_USERNAME_ID))
            )
            logger.info("UCAM Login fields detected. Challenge likely bypassed.")
            return
        except TimeoutException:
            if attempt == max_attempts:
                logger.error("Critical: Failed to bypass Cloudflare after maximum retries.")
                logger.error("Page Snippet: %s", driver.page_source[:500])
                raise TimeoutException("Cloudflare challenge block.") from None
            logger.info("Retrying portal access...")


def authenticate(user_creds, driver):
    """
    Fills the UCAM login form and waits for the post-login element to appear.
    """
    logger.info("Authenticating with student credentials...")
    user_field = WebDriverWait(driver, LOGIN_WAIT_S).until(
        EC.element_to_be_clickable((By.ID, LOGIN_USERNAME_ID))
    )
    pass_field = WebDriverWait(driver, LOGIN_FIELD_WAIT_S).until(
        EC.element_to_be_clickable((By.ID, LOGIN_PASSWORD_ID))
    )
    login_btn = WebDriverWait(driver, LOGIN_FIELD_WAIT_S).until(
        EC.element_to_be_clickable((By.ID, LOGIN_BUTTON_ID))
    )

    user_field.send_keys(user_creds['username'])
    pass_field.send_keys(user_creds['password'])
    login_btn.click()

    WebDriverWait(driver, LOGIN_SUCCESS_WAIT_S).until(
        EC.presence_of_element_located((By.ID, LOGIN_SUCCESS_ID))
    )
    logger.info("User %s authenticated successfully.", user_creds['id'])


def select_semester(driver, attendance_dashboard_url, section_label):
    """
    Navigates to the dashboard and selects the first non-placeholder semester
    through the select2 control. Returns the chosen semester label.
    """
    driver.get(attendance_dashboard_url)
    WebDriverWait(driver, COURSE_TABLE_WAIT_S).until(
        EC.presence_of_element_located((By.ID, SEMESTER_DROPDOWN_ID))
    )

    original_select = WebDriverWait(driver, SEMESTER_WAIT_S).until(
        EC.presence_of_element_located((By.ID, SEMESTER_DROPDOWN_ID))
    )
    options = original_select.find_elements(By.TAG_NAME, "option")
    target_semester = next(
        (opt.text for opt in options if opt.get_attribute("value") != "0"),
        None,
    )

    if not target_semester:
        raise ValueError(f"No valid semester options found for section {section_label}.")

    s2_container = (
        f"//select[@id='{SEMESTER_DROPDOWN_ID}']/"
        f"following-sibling::span[contains(@class,'select2-container')]"
    )
    WebDriverWait(driver, SEMESTER_WAIT_S).until(
        EC.element_to_be_clickable((By.XPATH, s2_container))
    ).click()

    s2_option = f"//span[contains(@class, 'select2-results')]//li[text()=\"{target_semester}\"]"
    WebDriverWait(driver, SEMESTER_WAIT_S).until(
        EC.element_to_be_clickable((By.XPATH, s2_option))
    ).click()

    logger.info("Dashboard synchronized for semester: %s.", target_semester)
    time.sleep(SEMESTER_SELECT_SETTLE_S)
    return target_semester


def extract_dashboard(driver, section_label):
    """
    Reads the course list table HTML from the dashboard panel and persists the
    parsed entries to per-section CSV/JSON files.
    """
    WebDriverWait(driver, COURSE_TABLE_WAIT_S).until(
        EC.presence_of_element_located(
            (By.XPATH, f"//div[@id='{UPDATE_PANEL_ID}']//table[@id='{COURSE_TABLE_ID}']")
        )
    )

    dashboard_html = driver.find_element(By.ID, UPDATE_PANEL_ID).get_attribute('innerHTML')
    user_dashboard_data = []

    if dashboard_html:
        os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
        user_dashboard_data = parse_attendance_dashboard_data(dashboard_html, section_label)

        if user_dashboard_data:
            dash_csv = ATTENDANCE_DATA_CSV_FILENAME_TPL.format(section=section_label)
            dash_json = ATTENDANCE_DATA_JSON_FILENAME_TPL.format(section=section_label)
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_csv, "csv")
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_json, "json")

    return user_dashboard_data


def scrape_dashboard_for_user(driver, user_creds, common_urls):
    """
    Executes the scraping workflow for a specific user profile.
    """
    section_label = user_creds['section_label']
    logger.info("--- Processing User Profile: %s (%s) ---", user_creds['id'], section_label)

    masking_visit(driver)

    try:
        bypass_cloudflare_and_wait_for_login(driver, common_urls['login_url'])
        authenticate(user_creds, driver)
    except Exception as e:
        logger.error("Authentication Failure: %s | URL: %s", type(e).__name__, driver.current_url)
        raise

    select_semester(driver, common_urls['attendance_dashboard_url'], section_label)
    return extract_dashboard(driver, section_label)

CHROME_BINARY_NAMES = ["google-chrome-stable", "google-chrome", "chromium-browser", "chromium"]

def get_chrome_executable():
    """
    Resolve the exact Chrome binary to launch and match chromedriver against.

    Precedence: CHROME_BINARY_PATH env override, then a deterministic PATH scan.
    Unlike undetected-chromedriver's own lookup (a set, order not guaranteed),
    this keeps the browser choice consistent between version detection and launch.
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
    return None

def get_chrome_major_version(chrome_path=None):
    """
    Attempts to retrieve the major version of the Chrome binary to be launched.
    """
    binary = chrome_path or get_chrome_executable()
    if not binary:
        logger.error("No Chrome binary found on this system.")
        return None
    try:
        output = subprocess.check_output([binary, "--version"], stderr=subprocess.STDOUT).decode("utf-8")
        version_match = re.search(r"(\d+)\.\d+\.\d+\.\d+", output)
        if version_match:
            major_version = int(version_match.group(1))
            logger.info("System Chrome Version: %d (via '%s')", major_version, binary)
            return major_version
    except Exception as e:
        logger.error("Failed to detect Chrome version from %s: %s", binary, e)
    return None


# [Main Workflow]

def main():
    logger.info("Executing scraper workflow...")
    
    credentials = load_credentials(CREDENTIALS_FILE)
    if not credentials:
        logger.error("Termination: Missing configuration.")
        return

    teacher_details = load_teacher_details_from_file(TEACHER_DETAILS_FILE)
    all_collected_data = []

    common_urls = {
        "login_url": credentials["login_url"],
        "attendance_dashboard_url": credentials["attendance_dashboard_url"]
    }

    for profile in credentials["users"]:
        driver = None 
        try:
            logger.info("--- Initializing Session: %s ---", profile['id'])

            if PREFERRED_BROWSER.lower() == "chrome":
                options = uc.ChromeOptions()
                options.add_argument("--window-size=1920,1080")
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                
                # Enhanced stealth flags
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--profile-directory=Default")
                
                chrome_path = get_chrome_executable()
                if not chrome_path:
                    logger.error("No Chrome binary found for %s. Install Chrome/Chromium or set CHROME_BINARY_PATH.", profile['id'])
                    continue
                major_v = get_chrome_major_version(chrome_path)
                driver = uc.Chrome(options=options, version_main=major_v,
                                   browser_executable_path=chrome_path, headless=HEADLESS)

            elif PREFERRED_BROWSER.lower() == "firefox":
                options = FirefoxOptions()
                if HEADLESS:
                    options.headless = True
                service = FirefoxService(GeckoDriverManager().install())
                driver = webdriver.Firefox(service=service, options=options)

            if not driver:
                logger.error("Driver initialization failure for %s.", profile['id'])
                continue

            driver.implicitly_wait(15)
            user_data = scrape_dashboard_for_user(driver, profile, common_urls)
            all_collected_data.extend(user_data)

        except Exception as e:
            logger.error("Workflow Exception for %s: %s", profile['id'], e)
            if driver:
                try:
                    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
                    log_path = os.path.join(TMP_OUTPUT_DIR, f"error_log_{profile['id']}.html")
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info("Debug log saved: %s", log_path)
                except: pass
        finally:
            if driver:
                driver.quit()
                logger.info("Session closed for %s.", profile['id'])

    if not all_collected_data:
        logger.error("Data collection yielded zero results. Aborting export.")
        return

    logger.info("--- Processing Combined Results ---")
    primary_section = credentials["users"][0]["section_label"]
    secondary_section = credentials["users"][1]["section_label"] if len(credentials["users"]) > 1 else None

    unique_routine = build_final_routine(all_collected_data, primary_section, secondary_section, teacher_details)

    if unique_routine:
        logger.info("Exporting %d unique entries.", len(unique_routine))
        save_data_to_file(unique_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_CSV_FILENAME, "csv",
                          fieldnames=["CourseCode", "CourseTitle", "Teacher", "TeacherPhone", "TeacherEmail", "Day", "Room", "TimeSlot", "Section"])
        save_data_to_file(unique_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_JSON_FILENAME, "json")
    else:
        logger.warning("No valid routine entries filtered.")

    logger.info("Scraper workflow finished.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error("Fatal global error: %s", e)
        traceback.print_exc()