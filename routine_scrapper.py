import json
import time
import subprocess
import traceback
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from bs4 import BeautifulSoup
import os
import csv
import re

# Browser-specific imports
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

print("Initializing routine scraper...", flush=True)

# [Configuration]
# Browser Selection: "chrome" (recommended) or "firefox"
PREFERRED_BROWSER = "chrome"

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
    print(f"Loading credentials from: {file_path}", flush=True)
    if not os.path.isabs(file_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
        
        required_top_keys = ["users", "login_url", "attendance_dashboard_url"]
        if not all(key in credentials for key in required_top_keys):
            print(f"Error: Missing top-level keys in {file_path}", flush=True)
            return None
            
        if not isinstance(credentials["users"], list) or not credentials["users"]:
            print("Error: 'users' array is missing or empty.", flush=True)
            return None
            
        for user in credentials["users"]:
            required_user_keys = ["id", "username", "password", "section_label"]
            if not all(key in user for key in required_user_keys):
                print(f"Error: Missing required user keys for ID: {user.get('id')}", flush=True)
                return None
                
        return credentials
    except Exception as e:
        print(f"Critical error loading credentials: {e}", flush=True)
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
        print(f"Loaded {len(teacher_details)} teacher entries.", flush=True)
        return teacher_details
    except FileNotFoundError:
        print(f"Warning: Teacher details file not found at '{file_path}'.", flush=True)
        return {}
    except Exception as e:
        print(f"Unexpected error loading teacher details: {e}", flush=True)
        return {}


# [Parsing Functions]

def parse_attendance_dashboard_data(html_content, user_section_label_tag):
    """
    Parses routine data from the UCAM attendance dashboard HTML.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    dashboard_entries = []

    main_table = soup.find('table', id="ctl00_MainContainer_gvCourseList")
    if not main_table:
        print(f"Error: Data table not found for section {user_section_label_tag}.", flush=True)
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
        entry["CourseCode"] = (re.search(r"Course Code\s*:\s*(.+)", course_info_raw, re.IGNORECASE).group(1).replace('<b>','').replace('</b>','').strip()
                               if re.search(r"Course Code\s*:\s*(.+)", course_info_raw, re.IGNORECASE) else "")
        entry["CourseTitle"] = (re.search(r"Title\s*:\s*(.+)", course_info_raw, re.IGNORECASE).group(1).strip()
                                if re.search(r"Title\s*:\s*(.+)", course_info_raw, re.IGNORECASE) else "")
        entry["Credit"] = (re.search(r"Credit\s*:\s*([0-9.]+)", course_info_raw, re.IGNORECASE).group(1).strip()
                           if re.search(r"Credit\s*:\s*([0-9.]+)", course_info_raw, re.IGNORECASE) else "")
        entry["CourseSection"] = (re.search(r"Section\s*:\s*(.+)", course_info_raw, re.IGNORECASE).group(1).strip()
                            if re.search(r"Section\s*:\s*(.+)", course_info_raw, re.IGNORECASE) else "")

        schedule_one_raw = cells[2].get_text(separator='\n', strip=True)
        entry["ScheduleOne_Day"] = (re.search(r"Day\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE).group(1).replace('<b>','').replace('</b>','').strip()
                                   if re.search(r"Day\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE) else "")
        entry["ScheduleOne_Time"] = (re.search(r"Time\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE).group(1).strip()
                                    if re.search(r"Time\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE) else "")
        entry["ScheduleOne_Room"] = (re.search(r"Room\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE).group(1).strip()
                                    if re.search(r"Room\s*:\s*(.+)", schedule_one_raw, re.IGNORECASE) else "")
        entry["ScheduleOne_TeacherInitial"] = (re.search(r"Teacher\s*:\s*(\S+)", schedule_one_raw, re.IGNORECASE).group(1).strip()
                                             if re.search(r"Teacher\s*:\s*(\S+)", schedule_one_raw, re.IGNORECASE) else "")

        schedule_two_raw = cells[3].get_text(separator='\n', strip=True)
        entry["ScheduleTwo_Day"] = (re.search(r"Day\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE).group(1).replace('<b>','').replace('</b>','').strip()
                                   if re.search(r"Day\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE) else "")
        entry["ScheduleTwo_Time"] = (re.search(r"Time\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE).group(1).strip()
                                    if re.search(r"Time\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE) else "")
        entry["ScheduleTwo_Room"] = (re.search(r"Room\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE).group(1).strip()
                                    if re.search(r"Room\s*:\s*(.+)", schedule_two_raw, re.IGNORECASE) else "")
        entry["ScheduleTwo_TeacherInitial"] = (re.search(r"Teacher\s*:\s*(\S+)", schedule_two_raw, re.IGNORECASE).group(1).strip()
                                             if re.search(r"Teacher\s*:\s*(\S+)", schedule_two_raw, re.IGNORECASE) else "")

        dashboard_entries.append(entry)

    return dashboard_entries


# [Persistence Functions]

def save_data_to_file(data, output_dir, filename, file_type='csv'):
    """
    Persists data to disk in the specified format.
    """
    if not data: return
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, filename)

    if file_type == 'csv':
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            print(f"Error: Invalid CSV data format for {filename}", flush=True)
            return
            
        if "final_combined_routine" in filename:
             fieldnames = ["CourseCode", "CourseTitle", "Teacher", "TeacherPhone", "TeacherEmail", "Day", "Room", "TimeSlot", "Section"]
        else:
            fieldnames = list(data[0].keys())

        try:
            with open(output_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(data)
            print(f"Exported CSV: {output_file_path}", flush=True)
        except Exception as e:
            print(f"Failed to export CSV: {e}", flush=True)
            
    elif file_type == 'json':
        try:
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"Exported JSON: {output_file_path}", flush=True)
        except Exception as e:
            print(f"Failed to export JSON: {e}", flush=True)


# [Web Scraping Logic]

def scrape_dashboard_for_user(driver, user_creds, common_urls):
    """
    Executes the scraping workflow for a specific user profile.
    """
    user_dashboard_data = []
    section_label = user_creds['section_label']

    print(f"\n--- Processing User Profile: {user_creds['id']} ({section_label}) ---", flush=True)
    
    # 1. Establish context by visiting a neutral site first
    try:
        print("Masking entry: Establishing context via Google...", flush=True)
        driver.get("https://www.google.com")
        time.sleep(3)
    except: pass

    # 2. Portal Authentication
    try:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            print(f"Portal access attempt {attempt} to: {common_urls['login_url']}", flush=True)
            driver.get(common_urls['login_url'])
            
            # Allow extended time for Cloudflare background checks
            time.sleep(15) 
            page_title = driver.title
            print(f"Current Page Title: '{page_title}'", flush=True)
            
            if "Just a moment" in page_title or "Cloudflare" in page_title or "Attention Required" in page_title:
                print(f"Cloudflare block persisting. Refreshing session (Attempt {attempt})...", flush=True)
                time.sleep(5)
                continue
            
            try:
                WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "logMain_UserName")))
                print("UCAM Login fields detected. Challenge likely bypassed.", flush=True)
                break
            except TimeoutException:
                if attempt == max_attempts:
                    print("Critical: Failed to bypass Cloudflare after maximum retries.", flush=True)
                    print("Page Snippet:", driver.page_source[:500], flush=True)
                    raise TimeoutException("Cloudflare challenge block.")
                print("Retrying portal access...", flush=True)

        print("Authenticating with student credentials...", flush=True)
        user_field = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "logMain_UserName")))
        pass_field = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Password")))
        login_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Button1")))
        
        user_field.send_keys(user_creds['username'])
        pass_field.send_keys(user_creds['password'])
        login_btn.click()
        
        WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.ID, "ctl00_lbtnUserName")))
        print(f"User {user_creds['id']} authenticated successfully.", flush=True)
    except Exception as e:
        print(f"Authentication Failure: {type(e).__name__} | URL: {driver.current_url}", flush=True)
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

    print(f"Dashboard synchronized for semester: {target_semester}.", flush=True)
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
                print(f"System Chrome Version: {major_version} (via '{binary}')", flush=True)
                return major_version
        except:
            continue
    return None


# [Main Workflow]

def main():
    print("Executing scraper workflow...", flush=True)
    
    credentials = load_credentials(CREDENTIALS_FILE)
    if not credentials:
        print("Termination: Missing configuration.", flush=True)
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
            print(f"\n--- Initializing Session: {profile['id']} ---", flush=True)

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
                driver = uc.Chrome(options=options, version_main=major_v)

            elif PREFERRED_BROWSER.lower() == "firefox":
                options = FirefoxOptions()
                service = FirefoxService(GeckoDriverManager().install())
                driver = webdriver.Firefox(service=service, options=options)

            if not driver:
                print(f"Error: Driver initialization failure for {profile['id']}.", flush=True)
                continue

            driver.implicitly_wait(15)
            user_data = scrape_dashboard_for_user(driver, profile, common_urls)
            all_collected_data.extend(user_data)

        except Exception as e:
            print(f"Workflow Exception for {profile['id']}: {e}", flush=True)
            if driver:
                try:
                    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
                    log_path = os.path.join(TMP_OUTPUT_DIR, f"error_log_{profile['id']}.html")
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    print(f"Debug log saved: {log_path}", flush=True)
                except: pass
        finally:
            if driver:
                driver.quit()
                print(f"Session closed for {profile['id']}.", flush=True)

    if not all_collected_data:
        print("Data collection yielded zero results. Aborting export.", flush=True)
        return

    print("\n--- Processing Combined Results ---", flush=True)
    final_routine = []
    
    primary_section = credentials["users"][0]["section_label"]
    secondary_section = credentials["users"][1]["section_label"] if len(credentials["users"]) > 1 else None

    for item in all_collected_data:
        is_lab = "lab" in item.get("CourseTitle", "").lower()
        item_section = item.get("UserScrapedSection")

        if item_section == primary_section or (item_section == secondary_section and is_lab):
            
            if item.get("ScheduleOne_Day") and not item.get("ScheduleOne_Day","").lower().startswith("time :"):
                entry1 = {
                    "CourseCode": item.get("CourseCode"), 
                    "CourseTitle": item.get("CourseTitle"),
                    "Section": item.get("CourseSection"), 
                    "Day": item.get("ScheduleOne_Day"),
                    "Room": item.get("ScheduleOne_Room"), 
                    "TimeSlot": item.get("ScheduleOne_Time")
                }
                initial = item.get("ScheduleOne_TeacherInitial")
                details = teacher_details.get(initial, {})
                entry1.update({
                    "Teacher": details.get("FullName", initial or "N/A"),
                    "TeacherPhone": details.get("Phone", ""),
                    "TeacherEmail": details.get("Email", "")
                })
                final_routine.append(entry1)

            if item.get("ScheduleTwo_Day") and not item.get("ScheduleTwo_Day","").lower().startswith("time :"):
                entry2 = {
                    "CourseCode": item.get("CourseCode"), 
                    "CourseTitle": item.get("CourseTitle"),
                    "Section": item.get("CourseSection"),
                    "Day": item.get("ScheduleTwo_Day"),
                    "Room": item.get("ScheduleTwo_Room"), 
                    "TimeSlot": item.get("ScheduleTwo_Time")
                }
                initial = item.get("ScheduleTwo_TeacherInitial")
                details = teacher_details.get(initial, {})
                entry2.update({
                    "Teacher": details.get("FullName", initial or "N/A"),
                    "TeacherPhone": details.get("Phone", ""),
                    "TeacherEmail": details.get("Email", "")
                })
                final_routine.append(entry2)

    if final_routine:
        unique_routine = []
        seen = set()
        for entry in final_routine:
            uid = (entry["CourseCode"], entry["Day"], entry["TimeSlot"], entry["Section"])
            if uid not in seen:
                unique_routine.append(entry)
                seen.add(uid)

        print(f"Exporting {len(unique_routine)} unique entries.", flush=True)
        save_data_to_file(unique_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_CSV_FILENAME, "csv")
        save_data_to_file(unique_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_JSON_FILENAME, "json")
    else:
        print("Warning: No valid routine entries filtered.", flush=True)

    print("\nScraper workflow finished.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal global error: {e}", flush=True)
        traceback.print_exc()
