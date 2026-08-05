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

from config import PREFERRED_BROWSER, HEADLESS, setup_logging

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

def build_final_routine(all_collected_data, primary_section, secondary_section, teacher_details):
    """
    Merges per-section scraped data into the final deduplicated routine.

    The primary section keeps all courses; the secondary section contributes
    only lab courses (title contains "lab"). Entries are deduplicated by
    (CourseCode, Day, TimeSlot, Section).
    """
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

def scrape_dashboard_for_user(driver, user_creds, common_urls):
    """
    Executes the scraping workflow for a specific user profile.
    """
    user_dashboard_data = []
    section_label = user_creds['section_label']

    logger.info("--- Processing User Profile: %s (%s) ---", user_creds['id'], section_label)
    
    # 1. Establish context by visiting a neutral site first
    try:
        logger.info("Masking entry: Establishing context via Google...")
        driver.get("https://www.google.com")
        time.sleep(3)
    except: pass

    # 2. Portal Authentication
    try:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            logger.info("Portal access attempt %d to: %s", attempt, common_urls['login_url'])
            driver.get(common_urls['login_url'])
            
            # Allow extended time for Cloudflare background checks
            time.sleep(15) 
            page_title = driver.title
            logger.info("Current Page Title: '%s'", page_title)
            
            if "Just a moment" in page_title or "Cloudflare" in page_title or "Attention Required" in page_title:
                logger.info("Cloudflare block persisting. Refreshing session (Attempt %d)...", attempt)
                time.sleep(5)
                continue
            
            try:
                WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "logMain_UserName")))
                logger.info("UCAM Login fields detected. Challenge likely bypassed.")
                break
            except TimeoutException:
                if attempt == max_attempts:
                    logger.error("Critical: Failed to bypass Cloudflare after maximum retries.")
                    logger.error("Page Snippet: %s", driver.page_source[:500])
                    raise TimeoutException("Cloudflare challenge block.")
                logger.info("Retrying portal access...")

        logger.info("Authenticating with student credentials...")
        user_field = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "logMain_UserName")))
        pass_field = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Password")))
        login_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Button1")))
        
        user_field.send_keys(user_creds['username'])
        pass_field.send_keys(user_creds['password'])
        login_btn.click()
        
        WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.ID, "ctl00_lbtnUserName")))
        logger.info("User %s authenticated successfully.", user_creds['id'])
    except Exception as e:
        logger.error("Authentication Failure: %s | URL: %s", type(e).__name__, driver.current_url)
        raise e

    # 3. Navigation to Dashboard
    driver.get(common_urls['attendance_dashboard_url'])
    semester_dropdown_id = "ctl00_MainContainer_ddlHeldIn"
    WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.ID, semester_dropdown_id)))

    original_select = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, semester_dropdown_id)))
    options = original_select.find_elements(By.TAG_NAME, "option")
    target_semester = next((opt.text for opt in options if opt.get_attribute("value") != "0"), None)

    if not target_semester:
        raise Exception(f"No valid semester options found for section {section_label}.")

    s2_container = f"//select[@id='{semester_dropdown_id}']/following-sibling::span[contains(@class,'select2-container')]"
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, s2_container))).click()

    s2_option = f"//span[contains(@class, 'select2-results')]//li[text()=\"{target_semester}\"]"
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, s2_option))).click()

    logger.info("Dashboard synchronized for semester: %s.", target_semester)
    time.sleep(5) 

    # 4. Content Extraction
    update_panel_id = "ctl00_MainContainer_UpdatePanel02"
    WebDriverWait(driver, 45).until(
        EC.presence_of_element_located((By.XPATH, f"//div[@id='{update_panel_id}']//table[@id='ctl00_MainContainer_gvCourseList']"))
    )
    
    dashboard_html = driver.find_element(By.ID, update_panel_id).get_attribute('innerHTML')

    if dashboard_html:
        os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
        user_dashboard_data = parse_attendance_dashboard_data(dashboard_html, section_label)
        
        if user_dashboard_data:
            dash_csv = ATTENDANCE_DATA_CSV_FILENAME_TPL.format(section=section_label)
            dash_json = ATTENDANCE_DATA_JSON_FILENAME_TPL.format(section=section_label)
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_csv, "csv")
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_json, "json")

    return user_dashboard_data

def get_chrome_major_version():
    """
    Attempts to retrieve the installed Chrome version.
    """
    for binary in ["google-chrome-stable", "google-chrome", "chromium-browser", "chromium"]:
        try:
            output = subprocess.check_output([binary, "--version"], stderr=subprocess.STDOUT).decode("utf-8")
            version_match = re.search(r"(\d+)\.\d+\.\d+\.\d+", output)
            if version_match:
                major_version = int(version_match.group(1))
                logger.info("System Chrome Version: %d (via '%s')", major_version, binary)
                return major_version
        except:
            continue
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
                
                major_v = get_chrome_major_version()
                driver = uc.Chrome(options=options, version_main=major_v, headless=HEADLESS)

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