# Automated UCAM Class Routine to Google Sheets

This project automates scraping your class routine from the UCAM web portal and uploads it to a Google Spreadsheet for easy access and organization. The data is then processed, sorted, and displayed in a user-friendly format by a Google Apps Script.


### Features ✨
* Scrapes class routine data using your UCAM credentials.
* Supports fetching data from one or two UCAM accounts to consolidate schedules (useful for lab sections).
* Enriches routine data with teacher contact details from a local configuration file.
* Allows you to choose between **Firefox** or **Chrome** browsers for scraping.
* Uploads the processed routine data to a 'specified' sheet in Google Spreadsheet.

* Triggers a Google Apps Script that:
    * Reads data from the 'specified' sheet.
    * Parses and formats time slots.
    * Sorts the routine data by day, then time.
    * Clears and writes the sorted data to a 'New' sheet starting at cell 'B4'.
    * Adds "Last Updated" timestamp and a signature to specific cells in the 'New' sheet.


## Prerequisites 🛠️

Before you begin, make sure you have the following installed:



* Python 3.7+
* Pip (Python package installer)
* Your chosen web browser:
    * Mozilla Firefox
    * Google Chrome
* The corresponding WebDriver for your chosen browser:
    * GeckoDriver (for Firefox)
    * ChromeDriver (for Chrome)
* A Google Account and an active Google Cloud Platform (GCP) project.


## Project Structure 📂

Here's an overview of the important files and directories:

```bash
project_root/ 
|-- routine_scrapper.py             # Main script for scraping UCAM data 
|-- gsheet_formatter.py             # Main script for Google Sheets integration 
| 
|-- configs_to_edit/                # ❗ **YOU MUST EDIT FILES HERE** 
|   |-- ucam_login_credentials.json.example.txt # Template for UCAM login details 
|   |-- teacher_contact_details.json.example.txt  # Template for teacher contacts 
| 
|-- google_cloud_keys/              # ❗ **STORE YOUR DOWNLOADED GOOGLE KEYS HERE** 
|   |-- service_account_key.json.example.txt    # placeholder for your service account key 
|   |-- oauth_client_secret.json.example.txt  # placeholder for your OAuth client secret 
| 
|-- output_of_fetched_routine       # Stores the final JSON output from the scraper 
|   |-- final_combined_routine.json   # Used by gsheet_formatter.py 
| 
|-- tmp/                            # Temporary HTML/data files during scraping 
|-- webdriver/                      # Recommended location for WebDriver executables 
|   |-- geckodriver                 # Example for macOS/Linux (Firefox) 
|   |-- chromedriver                # Example for macOS/Linux (Chrome) 
|   |-- geckodriver.exe             # Example for Windows (Firefox) 
|   |-- chromedriver.exe            # Example for Windows (Chrome) 
| 
|-- token.pickle                    # Auto-generated after Google OAuth (DO NOT EDIT) 
|-- README.md                       # This file (you are reading it!) 

```

## Setup Instructions ⚙️

Follow these steps carefully to get the project running:


### 1. Get the Project Files

Clone or download all project files to your local machine.


### 2. Install Python Dependencies

It's highly recommended to use a Python virtual environment.

* Optional: Create and activate a virtual environment

    ```bash
    python3 -m venv venv
    ```
    ```bash
    # On macOS/Linux:
    source venv/bin/activate

    # On Windows:
    # venv\Scripts\activate
    ```
* Install required packages 
    ```bash
    pip install -r requirements.txt
    ```



### 3. Set Up WebDriver 🌐

You need to set up the WebDriver for the browser you intend to use.


#### A. Choose Your Browser

Open ```routine_scrapper.py``` in a text editor. Near the top, set the ```PREFERRED_BROWSER``` variable:

```python
# Browser Choice: "firefox" or "chrome" 
PREFERRED_BROWSER = "firefox"  # Change to "chrome" if you prefer 
```


Also, check the ```GECKODRIVER_PATH``` and ```CHROMEDRIVER_PATH``` variables in the same file. The defaults point to the ```webdriver/``` directory.


#### B. Download and Place WebDriver



* **If using Firefox (GeckoDriver)**:
    1. Download the latest GeckoDriver from [Mozilla's GeckoDriver GitHub Releases](https://github.com/mozilla/geckodriver/releases). Make sure it matches your Firefox version and OS.
    2. Extract the ```geckodriver``` executable.
    3. Place it into the ```webdriver/``` directory in your project. For macOS/Linux, ensure it's executable.

        ```bash
        chmod +x webdriver/geckodriver
        ```
* **If using Chrome (ChromeDriver)**:
    1. Download ChromeDriver that **matches your installed Google Chrome version**. Find downloads on the [ChromeDriver - WebDriver for Chrome](https://googlechromelabs.github.io/chrome-for-testing/) page.
    2. Extract the ```chromedriver``` executable.
    3. Place it into the ```webdriver/``` directory. For macOS/Linux, ensure it's executable.

        ```bash
        chmod +x webdriver/chromedriver
        ```

Alternatively, you can place the WebDriver executable in a directory listed in your system's PATH. If you do this, make sure the path variables in ```routine_scrapper.py``` are updated or the script relies on the system PATH.


### 4. Configure UCAM Portal Access 🔑


#### A. UCAM Login Credentials



1. Go to the ```configs_to_edit/``` directory.

2. **Copy** ```ucam_login_credentials.json.example.txt``` and **rename** the copy to ```ucam_login_credentials.json```.
3. Open ```ucam_login_credentials.json``` and fill in your details:
    * ```users:``` A list for one or two UCAM accounts.
        * ```id:``` A descriptive name (e.g., "my_primary_section").
        * ```username:``` Your UCAM Student ID.
        * ```password:``` Your UCAM portal password.
        * ```section_label:``` A label for this section (e.g., "A1").
    * **Note on ```users``` list**: The script uses the ```section_label``` of the first user (```users[0]```) as the primary. Data from a second user ```(users[1]```) might be used for combining lab courses.
    * ```login_url``` and ```attendance_dashboard_url```: These are usually pre-filled correctly.


#### B. Teacher Contact Details



1. In ```configs_to_edit/```, **copy** ```teacher_contact_details.json.example.txt``` and **rename** it to ```teacher_contact_details.json```.

2. Open ```teacher_contact_details.json``` and update it with your teachers' info.
    * Keys are teacher initials (e.g., "SS", "JTT") as seen on the UCAM portal.
    * Provide ```FullName```, ```Phone```, and ```Email``` for each.


### 5. Set Up Google Cloud Platform (GCP) and API Keys ☁️


#### A. GCP Project & APIs



1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create or select a GCP project.
2. In your project, go to "APIs & Services" > "Library" and **enable**:
    * **Google Sheets API**
    * **Google Apps Script API**
    * **Google Drive API**


#### B. Service Account Key (for Google Sheets)

This allows the script to write to your Google Sheet.



1. In GCP, go to "IAM & Admin" > "Service Accounts" and click "+ CREATE SERVICE ACCOUNT".

2. Fill in a name and (optional) description. Click "CREATE AND CONTINUE".
3. Grant a role (e.g., ```Editor```). Click "CONTINUE", then "DONE".
4. Find the new service account, click its email, go to the "KEYS" tab.
5. Click "ADD KEY" > "Create new key". Select "JSON" and "CREATE". A JSON file downloads.
6. **Rename this downloaded file to** ```service_account_key.json```.
7. Move ```service_account_key.json``` into the ```google_cloud_keys/``` directory.
8. **Share** your Google** Sheet**:
    * Open ```service_account_key.json``` and copy the ```client_email``` address.
    * In your Google Spreadsheet, click "Share" and add this ```client_email``` as an "Editor". This allows the Python script to write to the 'backend' sheet.


#### C. OAuth 2.0 Client ID (for Google Apps Script)

This allows triggering your Apps Script.



1. In GCP, go to "APIs & Services" > "Credentials".

2. Click "+ CREATE CREDENTIALS" > "OAuth client ID".
3. Select "Application type" as "Desktop app". Give it a name. Click "CREATE".
4. Download the JSON configuration file (click the download icon next to the new Client ID).
5. **Rename this downloaded file to** ```oauth_client_secret.json```.
6. Move ```oauth_client_secret.json``` into the ```google_cloud_keys/``` directory.


### 6. Configure ```gsheet_formatter.py``` 📝

Open ```gsheet_formatter.py``` and update these constants:



* ```SPREADSHEET_NAME```: The **exact name** of your Google Spreadsheet.
```python
SPREADSHEET_NAME = 'My Class Routine' # Example
```

* ```TARGET_SHEET_NAME```: This should be ```'backend'```. This is the sheet where the Python script gsheet_formatter.py writes the raw data. Your Apps Script will then read from this 'backend' sheet.
```python
TARGET_SHEET_NAME = 'backend'
```

* ```APP_SCRIPT_ID```: The ID of your Google Apps Script.
    1. **Set up Google Sheets**:
        * Ensure your Google Spreadsheet has at least two sheets: one named **```backend```** (this is where ```gsheet_formatter.py``` will write data) and another named **```NewMain```** (this is where your Apps Script will write the sorted data).
    2. **Create Apps Script**: Go to [Google Apps Script](https://script.google.com), open the script associated with your Google Sheet (or create a new one and associate it by opening the Sheet > Extensions > Apps Script).
    3. Name your Apps Script project (e.g., "RoutineProcessor").
    4. Replace the default ```Code.gs``` content with the following Apps Script code. Important: Review the script, especially sheet names and cell references, to ensure they match your setup.

    <details><summary>Click to view the full Apps Script code</summary>

    ```javascript
    // Google Apps Script: Code.gs

    const SIGNATURE = "Made by Z  :)";

    // This function will be called by your Python script
    function triggerSortFromPython() {
    // Call the main sorting function.
    // We pass 'null' for the event object 'e' since this isn't a manual edit.
    sortBackendData(null);
    }

    function sortBackendData(e) {
    // Check if the edited sheet is the 'backend' sheet (only relevant if script is also triggered by onEdit)
    // If called by Python, 'e' will be null, so this check is bypassed.
    if (e && e.source.getActiveSheet().getName() !== "backend") {
        return; // Exit if the edit was not on the backend sheet (for onEdit trigger)
    }

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const backendSheet = ss.getSheetByName("backend");
    const targetSheet = ss.getSheetByName("NewMain"); // This is where sorted data goes
    const targetStartCell = "B4"; // Starting cell in "NewMain" for the sorted data
    // const newMainSheet = ss.getSheetByName("NewMain"); // Already defined as targetSheet

    // Check if essential sheets exist
    if (!backendSheet) {
        // SpreadsheetApp.getUi().alert("Error", "Sheet 'backend' not found!", SpreadsheetApp.getUi().ButtonSet.OK); // UI alert won't show from Python
        console.error("Apps Script Error: Sheet 'backend' not found!");
        return;
    }
    if (!targetSheet) {
        // SpreadsheetApp.getUi().alert("Error", "Sheet 'NewMain' not found! Please create it.", SpreadsheetApp.getUi().ButtonSet.OK);
        console.error("Apps Script Error: Sheet 'NewMain' not found! Please create it.");
        return;
    }

    const lastRow = backendSheet.getLastRow();
    // If backendSheet has only a header (row 1) or is empty (lastRow < 2)
    if (lastRow < 2) {
        const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
        const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
        // Clear previous content in the target area (8 columns wide, adjust if your data has different width)
        targetSheet.getRange(startRowOutput, startColOutput, targetSheet.getMaxRows() - startRowOutput + 1, 8).clearContent();
        targetSheet.getRange(targetStartCell).setValue("No data found in 'backend' sheet to sort (only header or empty).");

        // Update timestamp and signature even if no data
        // Ensure this timezone is correct for your desired output, or use Session.getScriptTimeZone()
        const currentDate = Utilities.formatDate(new Date(), "GMT+6", "d MMMM, yyyy HH:mm");
        targetSheet.getRange("I24").setValue("Last Updated: " + currentDate).setHorizontalAlignment("left");
        targetSheet.getRange("I25").setValue(SIGNATURE).setHorizontalAlignment("right"); // Use the constant
        console.log("Apps Script: No data in 'backend' to process. Timestamp updated.");
        return;
    }

    // Get data from A2:H (assuming 8 columns of data) to the last row with content
    const data = backendSheet.getRange("A2:H" + lastRow).getValues();

    const dayOrder = {
        "SAT": 1,
        "SUN": 2,
        "MON": 3,
        "TUE": 4,
        "WED": 5,
        "THU": 6,
        "FRI": 7
    };

    // --- Helper function to parse and format time strings ---
    function parseAndFormatTime(timeStr) {
        if (!timeStr || typeof timeStr !== 'string' || timeStr.trim() === '') {
        return {
            formatted: "",
            sortable: 99999
        }; // High sortable for empty/invalid
        }

        try {
        const parts = timeStr.trim().split(/\s*-\s*/);
        let startTime = parts[0];
        let endTime = parts[1] || "";

        function getSortableAndFormatted(tStr) {
            if (!tStr || tStr.trim() === '') return {
            formatted: "",
            sortable: 99999
            };

            let hour = 0;
            let minute = 0;
            let explicitPeriod = '';

            const match = tStr.match(/^(\d{1,2}):(\d{1,2})(?:\s*(AM|PM))?/i);
            if (match) {
            hour = parseInt(match[1]);
            minute = parseInt(match[2]);
            explicitPeriod = match[3] ? match[3].toUpperCase() : '';
            } else {
            console.warn("Time string does not match expected pattern: " + tStr + ". Using original.");
            return {
                formatted: tStr,
                sortable: 99998
            }; // Different high sortable for pattern mismatch
            }

            let sortableHour = hour;
            let finalDisplayPeriod = '';

            if (explicitPeriod === 'PM') {
            if (sortableHour < 12) {
                sortableHour += 12;
            } // 1 PM -> 13
            finalDisplayPeriod = 'PM';
            } else if (explicitPeriod === 'AM') {
            if (sortableHour === 12) {
                sortableHour = 0;
            } // 12 AM -> 0 (midnight)
            finalDisplayPeriod = 'AM';
            } else { // No explicit AM/PM, infer based on typical class hours
            if (hour >= 7 && hour <= 11) { // Typically AM hours
                finalDisplayPeriod = 'AM';
            } else if (hour === 12 || (hour >= 1 && hour <= 5)) { // Typically PM hours
                finalDisplayPeriod = 'PM';
                if (hour >= 1 && hour <= 5) {
                sortableHour += 12;
                } // 1 PM -> 13 etc. (12 PM is already 12)
            } else { // Ambiguous or outside typical routine hours
                finalDisplayPeriod = (hour >= 6 && hour < 7) ? 'AM' : 'PM'; // Default assumption for ambiguous like 6:xx
                console.warn("Ambiguous time (no AM/PM, outside typical 7-11 AM or 12-5 PM): " + tStr + ". Assuming " + finalDisplayPeriod);
            }
            }

            const sortableValue = sortableHour * 60 + minute;
            let displayHour = sortableHour;
            if (displayHour === 0) {
            displayHour = 12;
            } // 00:XX -> 12:XX AM
            else if (displayHour > 12) {
            displayHour -= 12;
            } // 13:XX -> 1:XX PM

            const formattedDisplay = `${displayHour}:${String(minute).padStart(2, '0')} ${finalDisplayPeriod}`;
            return {
            formatted: formattedDisplay,
            sortable: sortableValue
            };
        }

        const parsedStart = getSortableAndFormatted(startTime);
        const parsedEnd = getSortableAndFormatted(endTime);

        let formattedTimeSlot = parsedStart.formatted;
        // Only append end time if it's valid and different from start time
        if (parsedEnd.formatted && parsedEnd.sortable < 90000 && parsedEnd.sortable > parsedStart.sortable) {
            formattedTimeSlot += ` - ${parsedEnd.formatted}`;
        } else if (parsedEnd.formatted && parsedEnd.sortable < 90000 && !endTime.includes("-")) {
            // If only one time was provided (no hyphen), use it.
            // This case might need refinement based on how single times are expected.
        }

        return {
            formatted: formattedTimeSlot,
            sortable: parsedStart.sortable
        };

        } catch (e) {
        console.error("Error parsing time slot string '" + timeStr + "':", e);
        return {
            formatted: timeStr,
            sortable: 99999
        }; // Fallback
        }
    }
    // --- End of helper function ---

    const processedData = data.map(row => {
        const day = row[3]; // Column D (Day - 0-indexed, so 3)
        const timeSlotRaw = row[5]; // Column F (Time Slot - 0-indexed, so 5)

        let sortableDay = 998; // Default for empty/unrecognized day
        if (day && typeof day === 'string' && day.trim() !== '') {
        sortableDay = dayOrder[day.trim().toUpperCase()] || 999; // Use 999 for unrecognized days to sort them last
        }

        const {
        formatted: formattedTimeSlot,
        sortable: sortableTime
        } = parseAndFormatTime(timeSlotRaw);

        const newRow = [...row]; // Create a mutable copy of the row
        newRow[5] = formattedTimeSlot; // Update the Time Slot column in the copy

        return [...newRow, sortableDay, sortableTime]; // Append sort keys
    });

    // Sort by day, then by time
    processedData.sort((a, b) => {
        const dayA = a[a.length - 2]; // sortableDay
        const dayB = b[b.length - 2]; // sortableDay
        const timeA = a[a.length - 1]; // sortableTime
        const timeB = b[b.length - 1]; // sortableTime

        if (dayA !== dayB) {
        return dayA - dayB;
        }
        return timeA - timeB;
    });

    // Clear previous content in target sheet and write new sorted data
    const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
    const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
    // Clear a sufficiently large area, assuming 8 columns of data from original source
    targetSheet.getRange(startRowOutput, startColOutput, Math.max(1, targetSheet.getLastRow() - startRowOutput + 1), 8).clearContent();


    if (processedData.length > 0) {
        // Write data, excluding the appended sort keys (original 8 columns)
        targetSheet.getRange(startRowOutput, startColOutput, processedData.length, 8) // Write 8 columns
        .setValues(processedData.map(row => row.slice(0, 8))); // Slice off the two sort keys, take original 8 columns
    } else {
        targetSheet.getRange(targetStartCell).setValue("No valid data processed from 'backend' sheet.");
    }

    // Update timestamp and signature in "NewMain" sheet
    const currentDate = Utilities.formatDate(new Date(), "GMT+6", "d MMMM, yyyy HH:mm"); // Ensure timezone is correct
    targetSheet.getRange("I24").setValue("Last Updated: " + currentDate).setHorizontalAlignment("left");
    targetSheet.getRange("I25").setValue(SIGNATURE).setHorizontalAlignment("right"); // Use the constant

    console.log("Apps Script: Routine processing complete. Data sorted and written to 'NewMain'.");
    }
    ```

    </details>
    

    5. **Deploy**: Click "Deploy" > "New deployment". Select type: "API Executable". Configure "Execute as" (Me) and "Who has access". Click "Deploy".
    6. **Copy the Script ID** (from the deployment success dialog or "Project Settings" (gear icon on the left) > "IDs" > "Script ID").
    7. Paste this Script ID into the ```APP_SCRIPT_ID``` variable in ```gsheet_formatter.py```. <br>
    ```python
    APP_SCRIPT_ID = 'AKfycby............YOUR_SCRIPT_ID............7FoeQ' # Example
    ```
    
    8. In ```gsheet_formatter.py```, ensure the ```function_name``` in the ```call_apps_script_function``` call is ```"triggerSortFromPython"```, which matches the entry point function in your Apps Script.<br><br>
    ```python
    # In gsheet_formatter.py, inside the main execution block: 

    apps_script_call_success = call_apps_script_function( 
        script_id=APP_SCRIPT_ID, 
        function_name="triggerSortFromPython", # This should match your Apps Script 
        # ... other parameters 
    ) 
    
    ```

## How to Run the Scripts 🚀



1. **Open your terminal** (e.g., Terminal on macOS, Command Prompt or PowerShell on Windows).
2. **Navigate to the project's root directory.**
3. **Run the Scraper Script:** 
```bash
python3 routine_scrapper.py
```
 
Monitor the terminal for progress. It will create output_of_fetched_routine/final_combined_routine.json.

4. **Run the Google Sheet Formatter Script:** 
```bash
python3 gsheet_formatter.py
```

* First-Time Run: A browser window may open for Google authentication (OAuth). Follow the prompts. A ```token.pickle``` file will be created to store authorization for future runs.
This script uploads data to the 'backend' sheet and then triggers your Apps Script.



## Check Your Output ✅

* ```output_of_fetched_routine/final_combined_routine.json```: Contains the raw scraped routine data.
* **Google Sheet**:
    * The ```backend``` sheet should be populated with the raw, unsorted data by ```gsheet_formatter.py```.
    * The ```NewMain``` sheet should display the sorted and formatted routine, with the "Last Updated" timestamp in cell ```I24``` and signature in ```I25```, processed by your Apps Script.


## Troubleshooting Tips 🔍



* ```FileNotFoundError``` for ```.json``` files: Ensure you copied ```.example``` files, renamed them correctly, and placed them in ```configs_to_edit/``` or ```google_cloud_keys/```.

* WebDriver Errors (```selenium.common.exceptions...```):
    * Confirm your chosen browser (Firefox/Chrome) is installed.
    * Verify the correct WebDriver (GeckoDriver/ChromeDriver) is in ```webdriver/``` or system PATH and is compatible with your browser version.
* **UCAM Login Fails**: Check credentials in ```configs_to_edit/ucam_login_credentials.json```. The UCAM portal might have changed, which could affect scraping.
* **Google API Errors (Python Script)**:
    * Double-check "Google Sheets API" & "Google Apps Script API" are enabled in GCP.
    * Verify the ```client_email``` from ```google_cloud_keys/service_account_key.json``` has "Editor" access to your Google Sheet.
    * Confirm ```SPREADSHEET_NAME``` in ```gsheet_formatter.py``` is correct. ```TARGET_SHEET_NAME``` in ```gsheet_formatter.py``` should be ```'backend'```.
    * Ensure ```APP_SCRIPT_ID``` in ```gsheet_formatter.py``` is correct and the ```function_name``` parameter matches "triggerSortFromPython".
* **Apps Script Issues (Data not appearing in 'NewMain' or not sorted)**:
    * Open your Apps Script project in Google Drive. Go to "Executions" (play icon on the left sidebar) to see if ```triggerSortFromPython``` or ```sortBackendData``` ran and if there were errors.
    * In your Apps Script, ensure the sheet name variables (e.g., for ```backendSheet``` and ```targetSheet```) correctly point to "backend" and "NewMain".
    * Verify the ```targetStartCell``` in the Apps Script (```"B4"```) is where you expect data to begin in "NewMain".
    
    * Check for typos in sheet names within the Apps Script.

    * The time parsing logic in the Apps Script is complex; if times are not appearing correctly, add ```console.log``` statements within ```parseAndFormatTime``` and its sub-functions to debug the values at each step.