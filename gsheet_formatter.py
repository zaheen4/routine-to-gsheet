import gspread
import json
import os
import pickle
import traceback
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config import SPREADSHEET_NAME, APP_SCRIPT_ID, setup_logging

setup_logging()
logger = logging.getLogger(__name__)
logger.info("gsheet_formatter.py starting...")

# [Configuration]
TARGET_SHEET_NAME = 'backend'

# [Path Constants]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPED_DATA_JSON_PATH = os.path.join(BASE_DIR, "output_of_fetched_routine", "final_combined_routine.json")

# [Google Cloud Platform Configuration]
GOOGLE_KEYS_DIR = 'google_cloud_keys'
GOOGLE_SERVICE_ACCOUNT_KEY_FILE = os.path.join(GOOGLE_KEYS_DIR, 'service_account_key.json')
GOOGLE_OAUTH_CLIENT_SECRET_FILE = os.path.join(GOOGLE_KEYS_DIR, 'oauth_client_secret.json')

# Scopes for Apps Script and Spreadsheet API access
APP_SCRIPT_SCOPES = [
    'https://www.googleapis.com/auth/script.projects',
    'https://www.googleapis.com/auth/script.external_request',
    'https://www.googleapis.com/auth/spreadsheets'
]
TOKEN_PICKLE_FILE = 'token.pickle'


# [Helper Functions]

def load_routine_data(json_file_path):
    """
    Loads the processed routine data from the generated JSON file.
    
    Args:
        json_file_path (str): Path to the JSON source file.
        
    Returns:
        list: A list of routine entries or an empty list if loading fails.
    """
    logger.info("Loading routine data from: %s", json_file_path)
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info("Successfully loaded %d routine entries.", len(data))
        return data
    except FileNotFoundError:
        logger.error("Error: Source file '%s' not found.", json_file_path)
        return []
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in '%s'.", json_file_path)
        return []
    except Exception as e:
        logger.error("Unexpected error in load_routine_data: %s", e)
        return []

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

def get_or_create_worksheet(spreadsheet, sheet_name, rows=100, cols=20):
    """
    Retrieves a worksheet by name, creating it if it does not exist.
    
    Args:
        spreadsheet (gspread.Spreadsheet): The target spreadsheet object.
        sheet_name (str): Name of the worksheet to retrieve or create.
        rows (str): Initial row count for new worksheet.
        cols (str): Initial column count for new worksheet.
        
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

        if not isinstance(data_to_write, list) or not data_to_write or not isinstance(data_to_write[0], dict):
            logger.error("Invalid data format. Expected a list of dictionaries.")
            return False

        # Define sheet headers
        sheet_headers = [
            "Course", "Course Title", "Sect", "Day", "Room", "Time Slot", "Teacher", "Teacher Phone and Email"
        ]
        
        all_rows = [sheet_headers]
        
        for item in data_to_write:
            teacher_phone = item.get("TeacherPhone", "")
            teacher_email = item.get("TeacherEmail", "")
            
            # Combine contact details
            contact_combined = ""
            if teacher_phone and teacher_email:
                contact_combined = f"{teacher_phone}\n{teacher_email}"
            else:
                contact_combined = teacher_phone or teacher_email
            
            row_values = [
                item.get("CourseCode", ""),
                item.get("CourseTitle", ""),
                item.get("Section", ""),
                item.get("Day", ""),
                item.get("Room", ""),
                item.get("TimeSlot", ""),
                item.get("Teacher", ""),
                contact_combined
            ]
            all_rows.append(row_values)
            
        # Bulk update worksheet starting from A1
        worksheet.update(values=all_rows, range_name='A1')
        
        # Apply WRAP strategy to the contact column (Column H)
        contact_col_idx = sheet_headers.index("Teacher Phone and Email") + 1
        contact_col_letter = gspread.utils.rowcol_to_a1(1, contact_col_idx)[:-1]
        
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
            logger.info("Authenticating with Google OAuth...")
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes)
            creds = flow.run_local_server(port=0)
        
        with open(token_pickle_file, 'wb') as token:
            pickle.dump(creds, token)
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

if __name__ == "__main__":
    logger.info("Initializing Google Sheets formatting workflow...")
    
    # 1. Load data source
    routine_data = load_routine_data(SCRAPED_DATA_JSON_PATH)
    if not routine_data:
        logger.warning("Data source empty. Termination sequence initiated.")
        exit()

    # 2. Authenticate and establish connection
    gc = authenticate_gsheet(GOOGLE_SERVICE_ACCOUNT_KEY_FILE)
    if not gc:
        logger.error("Authentication failure. Exiting.")
        exit()

    try:
        logger.info("Opening spreadsheet: '%s'", SPREADSHEET_NAME)
        spreadsheet = gc.open(SPREADSHEET_NAME)
        
        # 3. Synchronize data with the 'backend' worksheet
        target_ws = get_or_create_worksheet(
            spreadsheet, 
            TARGET_SHEET_NAME, 
            rows=len(routine_data)+5, 
            cols=10
        ) 
        
        if target_ws:
            if write_data_to_sheet(target_ws, routine_data):
                logger.info("Spreadsheet synchronization successful.")
            else:
                logger.error("Synchronization failed.")
        else:
            logger.error("Target worksheet unreachable. Exiting.")

    except gspread.exceptions.SpreadsheetNotFound:
        logger.error("Spreadsheet '%s' not found.", SPREADSHEET_NAME)
        exit()
    except Exception as e:
        logger.error("Critical error during synchronization: %s", e)
        traceback.print_exc()
        exit()

    # 4. Trigger post-processing via Apps Script
    logger.info("\nTriggering post-processing workflow...")
    if APP_SCRIPT_ID == 'YOUR_APP_SCRIPT_ID_GOES_HERE':
        logger.warning("APP_SCRIPT_ID is not configured.")
    else:
        call_success = call_apps_script_function(
            script_id=APP_SCRIPT_ID,
            function_name="triggerSortFromPython",
            client_secrets_file=GOOGLE_OAUTH_CLIENT_SECRET_FILE,
            token_pickle_file=TOKEN_PICKLE_FILE,
            scopes=APP_SCRIPT_SCOPES
        )
        if call_success:
            logger.info("Post-processing complete. Sheets updated.")
        else:
            logger.error("Post-processing trigger failed.")

    logger.info("Workflow execution finished.")
