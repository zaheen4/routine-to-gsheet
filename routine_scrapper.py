import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from bs4 import BeautifulSoup
import os
import csv
import re

# Firefox-specific imports
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.firefox import GeckoDriverManager
# Chrome-specific imports
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

print("Script starting: Imports successful.", flush=True)

# --- Configuration ---
# Browser Choice: "firefox" or "chrome"
# Ensure the corresponding WebDriver (GeckoDriver for Firefox, ChromeDriver for Chrome) is set up.
PREFERRED_BROWSER = "firefox"  # Or "chrome"



CREDENTIALS_FILE = 'configs_to_edit/ucam_login_credentials.json'
TEACHER_DETAILS_FILE = 'configs_to_edit/teacher_contact_details.json'

# Output Folder Configuration
BASE_OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FORMATTED_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, "output_of_fetched_routine")
TMP_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, "tmp")

# Output filenames (will be prefixed by section for some)
ATTENDANCE_DASHBOARD_HTML_FILENAME_TPL = 'attendance_dashboard_{section}.html'
ATTENDANCE_DATA_CSV_FILENAME_TPL = 'dashboard_data_{section}.csv'
ATTENDANCE_DATA_JSON_FILENAME_TPL = 'dashboard_data_{section}.json'

FINAL_ROUTINE_CSV_FILENAME = 'final_combined_routine.csv'
FINAL_ROUTINE_JSON_FILENAME = 'final_combined_routine.json'


# --- Load Credentials ---
def load_credentials(file_path):
    """Loads credentials from a JSON file."""
    print(f"Attempting to load credentials from: {file_path}", flush=True)
    if not os.path.isabs(file_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
        print("Credentials file found and JSON parsed.", flush=True)
        required_top_keys = ["users", "login_url", "attendance_dashboard_url"]
        if not all(key in credentials for key in required_top_keys):
            missing = [key for key in required_top_keys if key not in credentials]
            print(f"Error: Credentials file is missing top-level keys: {', '.join(missing)}", flush=True)
            return None
        if not isinstance(credentials["users"], list) or not credentials["users"]:
            print("Error: 'users' array in credentials file is missing or empty.", flush=True)
            return None
        for user in credentials["users"]:
            required_user_keys = ["id", "username", "password", "section_label"]
            if not all(key in user for key in required_user_keys):
                print(f"Error: A user in credentials file is missing required keys. Expected: {required_user_keys}, Found: {list(user.keys())}", flush=True)
                return None
        print("Credentials loaded and validated successfully.", flush=True)
        return credentials
    except FileNotFoundError:
        print(f"Error: Credentials file '{file_path}' not found.", flush=True)
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{file_path}'. Check its format.", flush=True)
        return None
    except Exception as e:
        print(f"An unexpected error occurred in load_credentials: {e}", flush=True)
        return None

# --- Load Teacher Details from Local File ---
def load_teacher_details_from_file(file_path):
    """Loads teacher details from a local JSON file."""
    print(f"Attempting to load teacher details from: {file_path}", flush=True)
    if not os.path.isabs(file_path):
        # Assuming TEACHER_DETAILS_FILE is relative to the script's directory if not absolute
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_path)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            teacher_details = json.load(f)
        print(f"Successfully loaded {len(teacher_details)} teacher entries from {file_path}.", flush=True)
        return teacher_details
    except FileNotFoundError:
        print(f"Error: Teacher details file '{file_path}' not found. Please create it.", flush=True)
        return {}
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{file_path}'. Please check its format.", flush=True)
        return {}
    except Exception as e:
        print(f"An unexpected error occurred in load_teacher_details_from_file: {e}", flush=True)
        return {}


# --- Parse Data from Attendance Dashboard HTML ---
def parse_attendance_dashboard_data(html_content, user_section_label_tag):
    soup = BeautifulSoup(html_content, 'html.parser')
    dashboard_entries = []
    print(f"--- Parsing Attendance Dashboard HTML for user section {user_section_label_tag} ---", flush=True)

    main_table = soup.find('table', id="ctl00_MainContainer_gvCourseList")
    if not main_table:
        print(f"Could not find data table on dashboard for user section {user_section_label_tag}.", flush=True)
        return dashboard_entries

    rows = main_table.find_all('tr')
    if len(rows) < 2:
        print(f"Dashboard data table for user section {user_section_label_tag} has no data rows.", flush=True)
        return dashboard_entries

    for row_idx, row in enumerate(rows[1:]): # Skip header row
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

    print(f"Extracted {len(dashboard_entries)} entries from dashboard for user section {user_section_label_tag}.", flush=True)
    return dashboard_entries

# --- Save Data Functions ---
def save_data_to_file(data, output_dir, filename, file_type='csv'):
    if not data: return
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, filename)

    if file_type == 'csv':
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            print(f"CSV data for {filename} must be list of dicts. Got: {type(data)}", flush=True); return
        # Use a predefined robust set of headers for the final combined routine
        if "final_combined_routine" in filename:
             fieldnames = ["CourseCode", "CourseTitle", "Teacher", "TeacherPhone", "TeacherEmail", "Day", "Room", "TimeSlot", "Section"]
        else: # For other CSVs, derive from data
            fieldnames = list(data[0].keys())

        try:
            with open(output_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader(); writer.writerows(data)
            print(f"Data saved to {output_file_path}", flush=True)
        except Exception as e: print(f"Error saving CSV {output_file_path}: {e}", flush=True)
    elif file_type == 'json':
        try:
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"Data saved to {output_file_path}", flush=True)
        except Exception as e: print(f"Error saving JSON {output_file_path}: {e}", flush=True)

# --- Helper function to perform scraping for a single user ---
def scrape_dashboard_for_user(driver, user_creds, common_urls):
    user_dashboard_data = []
    section_label = user_creds['section_label']

    print(f"\n--- Logging in as {user_creds['id']} (for section: {section_label}) ---", flush=True)
    driver.get(common_urls['login_url']); time.sleep(1) # Allow page to start loading
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "logMain_UserName"))).send_keys(user_creds['username'])
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Password"))).send_keys(user_creds['password'])
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "logMain_Button1"))).click()
    # Wait for a known element on the dashboard after login
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_lbtnUserName")))
    print(f"Successfully logged in as {user_creds['id']}.", flush=True); time.sleep(2) # Brief pause

    print(f"Navigating to Attendance Dashboard for section {section_label}: {common_urls['attendance_dashboard_url']}", flush=True)
    driver.get(common_urls['attendance_dashboard_url']); time.sleep(2) # Allow page to start loading
    semester_dropdown_id = "ctl00_MainContainer_ddlHeldIn"
    # Wait for the original select element to be present
    WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.ID, semester_dropdown_id)))

    # Interact with the Select2 dropdown
    original_select_element = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, semester_dropdown_id)))
    options_in_dropdown = original_select_element.find_elements(By.TAG_NAME, "option")
    # Find the first non-default semester (value not "0")
    first_semester_text = next((opt.text for opt in options_in_dropdown if opt.get_attribute("value") != "0"), None)

    if not first_semester_text:
        raise Exception(f"No actual semester option found in dropdown for section {section_label}.")

    # Click the Select2 container to open the dropdown
    s2_container_xpath = f"//select[@id='{semester_dropdown_id}']/following-sibling::span[contains(@class,'select2-container')]//span[contains(@class,'select2-selection--single')]"
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, s2_container_xpath))).click()

    # Click the desired option in the opened Select2 results
    s2_option_xpath = f"//span[contains(@class, 'select2-results')]//ul[contains(@class, 'select2-results__options')]//li[text()=\"{first_semester_text}\"]"
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, s2_option_xpath))).click()

    print(f"Semester '{first_semester_text}' selected on Attendance Dashboard for section {section_label}.", flush=True); time.sleep(3) # Wait for content to update

    # Wait for the table inside the update panel to be loaded
    update_panel_id = "ctl00_MainContainer_UpdatePanel02"
    WebDriverWait(driver, 45).until(
        EC.presence_of_element_located((By.XPATH, f"//div[@id='{update_panel_id}']//table[@id='ctl00_MainContainer_gvCourseList']"))
    )
    dashboard_container = driver.find_element(By.ID, update_panel_id)
    dashboard_html_content = dashboard_container.get_attribute('innerHTML')

    if dashboard_html_content:
        os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
        dash_html_file = ATTENDANCE_DASHBOARD_HTML_FILENAME_TPL.format(section=section_label)
        with open(os.path.join(TMP_OUTPUT_DIR, dash_html_file), 'w', encoding='utf-8') as f:
            f.write("<html><head><meta charset='utf-8'></head><body>" + dashboard_html_content + "</body></html>")

        user_dashboard_data = parse_attendance_dashboard_data(dashboard_html_content, section_label)
        if user_dashboard_data:
            dash_csv_file = ATTENDANCE_DATA_CSV_FILENAME_TPL.format(section=section_label)
            dash_json_file = ATTENDANCE_DATA_JSON_FILENAME_TPL.format(section=section_label)
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_csv_file, "csv")
            save_data_to_file(user_dashboard_data, TMP_OUTPUT_DIR, dash_json_file, "json")

    print(f"Finished processing dashboard for user {user_creds['id']}.", flush=True)
    return user_dashboard_data

# --- Main Script ---
def main():
    print("Executing main() function...", flush=True)
    credentials_data = load_credentials(CREDENTIALS_FILE)
    if not credentials_data:
        print("Failed to load credentials. Exiting.", flush=True); return

    teacher_details_lookup = load_teacher_details_from_file(TEACHER_DETAILS_FILE)
    if not teacher_details_lookup: # It returns {} on error, so this check is fine
        print(f"Warning: Failed to load teacher details from '{TEACHER_DETAILS_FILE}'. "
              "Full teacher names, phone numbers, and emails might be missing in the output.", flush=True)
        # Keep teacher_details_lookup as {} (empty dict) to avoid errors later with .get()

    all_dashboard_data_collected = []

    common_urls = {
        "login_url": credentials_data["login_url"],
        "attendance_dashboard_url": credentials_data["attendance_dashboard_url"]
    }

    # --- WebDriver Initialization (Handles browser choice automatically) ---
    options = None
    service = None
    web_driver_class = None

    print(f"Configuring WebDriver for selected browser: {PREFERRED_BROWSER.upper()}", flush=True)

    try:
        if PREFERRED_BROWSER.lower() == "firefox":
            options = FirefoxOptions()
            options.add_argument("--headless")
            print("Setting up automatic WebDriver for Firefox (GeckoDriver)...", flush=True)
            service = FirefoxService(GeckoDriverManager().install())
            web_driver_class = webdriver.Firefox

        elif PREFERRED_BROWSER.lower() == "chrome":
            options = ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            print("Setting up automatic WebDriver for Chrome (ChromeDriver)...", flush=True)
            service = ChromeService(ChromeDriverManager().install())
            web_driver_class = webdriver.Chrome
        else:
            print(f"Fatal Error: Invalid browser choice '{PREFERRED_BROWSER}'. Please set it to 'firefox' or 'chrome'.", flush=True)
            return
            
    except Exception as e_driver_setup:
        print(f"Fatal Error setting up WebDriver for {PREFERRED_BROWSER.upper()}: {e_driver_setup}", flush=True)
        print("Please ensure the selected browser is installed on your system.", flush=True)
        return

    if not web_driver_class or not service or not options:
         print(f"Fatal Error: WebDriver components were not correctly initialized for {PREFERRED_BROWSER.upper()}.", flush=True)
         return
    # --- End of WebDriver Service and Options Initialization ---

    

    for user_profile in credentials_data["users"]:
        driver = None # Initialize driver to None for each user iteration
        try:
            print(f"\n--- Creating WebDriver instance for User: {user_profile['id']} using {PREFERRED_BROWSER.upper()} ---", flush=True)
            # Create a new driver instance for each user
            driver = web_driver_class(service=service, options=options)
            driver.implicitly_wait(15) # Set implicit wait for the new driver instance
            print(f"{PREFERRED_BROWSER.upper()} WebDriver instance for user {user_profile['id']} created successfully.", flush=True)

            user_data = scrape_dashboard_for_user(driver, user_profile, common_urls)
            all_dashboard_data_collected.extend(user_data)

        except WebDriverException as e_driver_instance:
            print(f"Error creating or using WebDriver instance for user {user_profile['id']}: {e_driver_instance}", flush=True)
            if driver: # If driver object exists but failed during operation
                try:
                    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
                    error_page_source_path = os.path.join(TMP_OUTPUT_DIR, f"error_page_source_webdriver_fail_{user_profile['id']}.html")
                    with open(error_page_source_path, "w", encoding="utf-8") as f_err:
                        f_err.write(driver.page_source)
                    print(f"Saved page source at WebDriver failure to: {error_page_source_path}", flush=True)
                except Exception as e_save_source:
                    print(f"Could not save page source on WebDriver failure: {e_save_source}", flush=True)
            # Continue to the next user if this one failed critically (e.g., driver couldn't start for them)
            continue
        except Exception as e_user_scrape: # Catch other exceptions during this user's processing
            print(f"An unexpected error occurred during scraping for user {user_profile['id']}: {e_user_scrape}", flush=True)
            if driver: # Attempt to capture page source if driver was initialized
                try:
                    os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
                    error_page_source_path = os.path.join(TMP_OUTPUT_DIR, f"error_page_source_general_error_{user_profile['id']}.html")
                    with open(error_page_source_path, "w", encoding="utf-8") as f_err:
                        f_err.write(driver.page_source)
                    print(f"Saved page source at general error to: {error_page_source_path}", flush=True)
                except Exception as e_save_source:
                    print(f"Could not save page source on general error: {e_save_source}", flush=True)
            # Depending on severity, you might want to 'continue' or 'return'
            # For now, assume we try next user.
        finally:
            if driver:
                driver.quit()
                print(f"WebDriver session for user {user_profile['id']} ({PREFERRED_BROWSER.upper()}) closed.", flush=True)

    # --- Merging and Final Output ---
    if not all_dashboard_data_collected:
        print("No dashboard data collected from any user. Cannot generate final routine.", flush=True); return

    print("\n--- Combining Data for Final Routine ---", flush=True)
    final_combined_routine = []

    primary_user_section_label = credentials_data["users"][0]["section_label"]
    friend_section_label = None
    if len(credentials_data["users"]) > 1:
        friend_section_label = credentials_data["users"][1]["section_label"]


    for dash_item in all_dashboard_data_collected:
        is_lab_course = "lab" in dash_item.get("CourseTitle", "").lower()
        item_user_section = dash_item.get("UserScrapedSection")

        include_this_item_schedule_one = False
        include_this_item_schedule_two = False

        if item_user_section == primary_user_section_label:
            include_this_item_schedule_one = True
            include_this_item_schedule_two = True
        elif item_user_section == friend_section_label and is_lab_course:
            include_this_item_schedule_one = True
            include_this_item_schedule_two = True

        # Process Schedule One
        if include_this_item_schedule_one and \
           ((dash_item.get("ScheduleOne_Day") and not dash_item.get("ScheduleOne_Day","").lower().startswith("time :") and dash_item.get("ScheduleOne_Day","").strip() != "") or \
            (dash_item.get("ScheduleOne_Time") and not dash_item.get("ScheduleOne_Time","").lower().startswith("room :") and dash_item.get("ScheduleOne_Time","").strip() != "") or \
            dash_item.get("ScheduleOne_TeacherInitial")):

            entry1 = {
                "CourseCode": dash_item.get("CourseCode"), "CourseTitle": dash_item.get("CourseTitle"),
                "Section": dash_item.get("CourseSection"), "Day": dash_item.get("ScheduleOne_Day"),
                "Room": dash_item.get("ScheduleOne_Room"), "TimeSlot": dash_item.get("ScheduleOne_Time")
            }
            teacher_initial_one = dash_item.get("ScheduleOne_TeacherInitial")
            teacher_detail1 = teacher_details_lookup.get(teacher_initial_one, {}) # Use .get for safety
            entry1["Teacher"] = teacher_detail1.get("FullName", teacher_initial_one or "N/A")
            entry1["TeacherPhone"] = teacher_detail1.get("Phone", "")
            entry1["TeacherEmail"] = teacher_detail1.get("Email", "")
            final_combined_routine.append(entry1)

        # Process Schedule Two
        if include_this_item_schedule_two:
            sch2_day = dash_item.get("ScheduleTwo_Day","")
            sch2_time = dash_item.get("ScheduleTwo_Time","")
            sch2_teacher_initial = dash_item.get("ScheduleTwo_TeacherInitial","")

            is_sch2_data_valid = bool(sch2_teacher_initial and sch2_day and \
                                   not sch2_day.lower().startswith("time :") and \
                                   not sch2_day.strip() == "" and \
                                   sch2_time and \
                                   not sch2_time.lower().startswith("room :") and \
                                   not sch2_time.strip() == "")

            if is_sch2_data_valid:
                entry2 = {
                    "CourseCode": dash_item.get("CourseCode"), "CourseTitle": dash_item.get("CourseTitle"),
                    "Section": dash_item.get("CourseSection"),
                    "Day": sch2_day,
                    "Room": dash_item.get("ScheduleTwo_Room"), "TimeSlot": sch2_time
                }
                teacher_detail2 = teacher_details_lookup.get(sch2_teacher_initial, {}) # Use .get for safety
                entry2["Teacher"] = teacher_detail2.get("FullName", sch2_teacher_initial or "N/A")
                entry2["TeacherPhone"] = teacher_detail2.get("Phone", "")
                entry2["TeacherEmail"] = teacher_detail2.get("Email", "")
                final_combined_routine.append(entry2)

    if final_combined_routine:
        unique_final_routine = []
        seen_tuples = set() # Set to store tuples of identifying fields to check for uniqueness
        for item in final_combined_routine:
            # Define what makes an entry unique (e.g., combination of course, day, time, section, teacher)
            # Adjust this tuple based on how you define a unique class slot
            item_tuple = (
                item.get("CourseCode"), item.get("Day"), item.get("TimeSlot"),
                item.get("Section"), item.get("Teacher") # Teacher might be "N/A" if initial not found
            )
            if item_tuple not in seen_tuples:
                unique_final_routine.append(item)
                seen_tuples.add(item_tuple)

        print(f"Generated {len(unique_final_routine)} unique combined routine entries for final output.", flush=True)
        save_data_to_file(unique_final_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_CSV_FILENAME, "csv")
        save_data_to_file(unique_final_routine, FORMATTED_OUTPUT_DIR, FINAL_ROUTINE_JSON_FILENAME, "json")
    else:
        print("Could not generate final combined routine data (no valid entries found after processing).", flush=True)

    print("\nScript processing completed.", flush=True)

if __name__ == "__main__":
    print("Script execution started via __main__...", flush=True)
    try:
        main()
    except Exception as e_global:
        print(f"Global unhandled exception in main: {e_global}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print("Script execution finished.", flush=True)