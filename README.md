# Automated UCAM Class Routine to Google Sheets

An automated solution for scraping class schedules from the UCAM web portal and synchronizing them with a Google Spreadsheet.

## Final Output Preview

The following image demonstrates the final, formatted routine sheet. It features conditional formatting and chronological sorting by day and time.

![Class Routine Demo](assets/screenshot_of_output.png)

[**Demo Output Spreadsheet**](https://docs.google.com/spreadsheets/d/1mE36dYY9u4rgwbJl9rq8LibBlB-VLd_K3Jli_Db3bxA/edit?usp=sharing)

### Key Features
* **Automated Extraction**: Authenticates with the UCAM portal to retrieve schedule data.
* **Multi-User Consolidation**: Supports merging schedules from two accounts (e.g., for lab section synchronization).
* **Data Enrichment**: Integrates teacher contact details from local configuration files.
* **Flexible Browser Support**: Compatible with both Firefox and Google Chrome.
* **Sheets Integration**: Uploads raw data and triggers Google Apps Script for post-processing.
* **Advanced Processing**: 
    * Normalizes time formats to 12-hour display.
    * Chronological sorting by day and time.
    * Generates a "Last Updated" timestamp.

---

## Prerequisites
Ensure the following software is installed on your system:

* **Python 3.10+**
* **pip** (Python package manager)
* **Google Chrome** (Recommended; utilized with `undetected-chromedriver` for reliability).
* **Xvfb** (Required for headless Linux environments, such as GitHub Actions).
* **Google Account** with enabled access to Google Drive and Google Cloud Platform.

---

## Project Structure
```text
project_root/
├── .github/workflows/          # CI/CD automation workflows
│   └── run-routine-job.yml     # Scheduled routine scraper workflow
├── routine_scrapper.py         # Primary scraping logic for UCAM portal
├── gsheet_formatter.py         # Google Sheets API integration
├── configs_to_edit/            # User configuration directory
│   ├── ucam_login_credentials.json.example
│   └── teacher_contact_details.json.example
├── google_cloud_keys/          # API credentials directory
│   ├── service_account_key.json.example
│   └── oauth_client_secret.json.example
├── output_of_fetched_routine/  # Local cache for scraped data
├── requirements.txt            # Project dependencies
├── encode.py                   # Utility for GitHub Secrets encoding
├── flatten.sh                  # Utility for local 'act' testing
├── act_test.sh                 # Local CI/CD testing script
├── token.pickle                # Cached Google API authentication token
└── README.md                   # Documentation
```

---

## Installation and Setup

### 1. Project Initialization
Clone the repository and navigate to the project root:

```bash
git clone https://github.com/zaheen4/routine-to-gsheet.git
cd routine-to-gsheet
```

### 2. Dependency Management
It is recommended to use a virtual environment for dependency isolation.

**Unix/macOS:**
```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

**Windows:**
```powershell
python -m venv venv; .\venv\Scripts\activate; pip install -r requirements.txt
```

### 3. Browser Configuration
Set your `PREFERRED_BROWSER` in `routine_scrapper.py`:
```python
PREFERRED_BROWSER = "chrome"  # Options: "chrome", "firefox"
```

### 4. Configuration
1. **UCAM Credentials**: Rename `configs_to_edit/ucam_login_credentials.json.example` to `ucam_login_credentials.json` and provide your credentials.
2. **Teacher Details**: Rename `configs_to_edit/teacher_contact_details.json.example` to `teacher_contact_details.json` and populate as needed.

### 5. Google Cloud Platform Setup
Enable the following APIs in the [Google Cloud Console](https://console.cloud.google.com/):
* Google Sheets API
* Google Apps Script API
* Google Drive API

#### Service Account Key
1. Create a Service Account under **IAM & Admin > Service Accounts**.
2. Assign the **Editor** role.
3. Generate a JSON key, rename it to `service_account_key.json`, and place it in `google_cloud_keys/`.
4. **Note**: Share your target Google Sheet with the `client_email` found in the JSON file.

#### OAuth Client ID
1. Create an **OAuth client ID** (Desktop app) under **APIs & Services > Credentials**.
2. Download the JSON, rename it to `oauth_client_secret.json`, and place it in `google_cloud_keys/`.

### 6. Script Configuration
Update the following variables in `gsheet_formatter.py`:
* `SPREADSHEET_NAME`: The exact name of your Google Spreadsheet.
* `TARGET_SHEET_NAME`: Set to `'backend'`.
* `APP_SCRIPT_ID`: Obtained in the next step.

#### Google Apps Script Deployment
1. Open your Google Sheet and navigate to **Extensions > Apps Script**.
2. Deploy the following code:

<details>
<summary>Click to view Apps Script Source Code</summary>

```javascript
// Google Apps Script: Code.gs

const SIGNATURE = "Made by Z  :)";

function triggerSortFromPython() {
  sortBackendData(null);
}

function sortBackendData(e) {
  if (e && e.source.getActiveSheet().getName() !== "backend") return;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const backendSheet = ss.getSheetByName("backend");
  const targetSheet = ss.getSheetByName("NewMain");
  const targetStartCell = "B4";

  if (!backendSheet || !targetSheet) {
    console.error("Required sheets ('backend' or 'NewMain') not found.");
    return;
  }

  const lastRow = backendSheet.getLastRow();
  if (lastRow < 2) {
    const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
    const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
    targetSheet.getRange(startRowOutput, startColOutput, targetSheet.getMaxRows() - startRowOutput + 1, 8).clearContent();
    targetSheet.getRange(targetStartCell).setValue("No data found in 'backend' sheet.");
    updateMetadata(targetSheet);
    return;
  }

  const data = backendSheet.getRange("A2:H" + lastRow).getValues();
  const dayOrder = { "SAT": 1, "SUN": 2, "MON": 3, "TUE": 4, "WED": 5, "THU": 6, "FRI": 7 };

  const processedData = data.map(row => {
    const day = row[3];
    const timeSlotRaw = row[5];
    let sortableDay = 998;
    if (day && typeof day === 'string' && day.trim() !== '') {
      sortableDay = dayOrder[day.trim().toUpperCase()] || 999;
    }
    const { formatted, sortable } = parseAndFormatTime(timeSlotRaw);
    const newRow = [...row];
    newRow[5] = formatted;
    return [...newRow, sortableDay, sortable];
  });

  processedData.sort((a, b) => {
    const dayDiff = a[a.length - 2] - b[b.length - 2];
    return dayDiff !== 0 ? dayDiff : a[a.length - 1] - b[b.length - 1];
  });

  const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
  const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
  targetSheet.getRange(startRowOutput, startColOutput, Math.max(1, targetSheet.getLastRow() - startRowOutput + 1), 8).clearContent();

  if (processedData.length > 0) {
    targetSheet.getRange(startRowOutput, startColOutput, processedData.length, 8)
      .setValues(processedData.map(row => row.slice(0, 8)));
  }
  updateMetadata(targetSheet);
}

function updateMetadata(sheet) {
  const currentDate = Utilities.formatDate(new Date(), "GMT+6", "d MMMM, yyyy HH:mm");
  sheet.getRange("I24").setValue("Last Updated: " + currentDate).setHorizontalAlignment("left");
  sheet.getRange("I25").setValue(SIGNATURE).setHorizontalAlignment("right");
}

function parseAndFormatTime(timeStr) {
  if (!timeStr || timeStr.trim() === '') return { formatted: "", sortable: 99999 };
  try {
    const parts = timeStr.trim().split(/\s*-\s*/);
    const getSortable = (tStr) => {
      const match = tStr.match(/^(\d{1,2}):(\d{1,2})(?:\s*(AM|PM))?/i);
      if (!match) return { formatted: tStr, sortable: 99998 };
      let hour = parseInt(match[1]);
      const min = parseInt(match[2]);
      const period = match[3] ? match[3].toUpperCase() : (hour >= 7 && hour <= 11 ? 'AM' : 'PM');
      if (period === 'PM' && hour < 12) hour += 12;
      if (period === 'AM' && hour === 12) hour = 0;
      return { 
        formatted: `${hour % 12 || 12}:${min.toString().padStart(2, '0')} ${period}`, 
        sortable: hour * 60 + min 
      };
    };
    const start = getSortable(parts[0]);
    const end = parts[1] ? getSortable(parts[1]) : { formatted: "" };
    return { 
      formatted: end.formatted ? `${start.formatted} - ${end.formatted}` : start.formatted, 
      sortable: start.sortable 
    };
  } catch (e) {
    return { formatted: timeStr, sortable: 99999 };
  }
}
```
</details>

3. **Deploy** as an **API Executable**.
4. Copy the **Script ID** into `gsheet_formatter.py`.

---

## Usage

### Local Execution
1. **Scrape Routine**:
   ```bash
   python3 routine_scrapper.py
   ```
2. **Update Sheets**:
   ```bash
   python3 gsheet_formatter.py
   ```
   *Note: On the first execution, an OAuth consent window will open in your browser to generate `token.pickle`.*

---

## Automation (GitHub Actions)
The workflow in `.github/workflows/run-routine-job.yml` automates the synchronization on a schedule.

### Configuration (Repository Secrets)
Add the following secrets to your repository:
* `UCAM_LOGIN_CREDENTIALS`: Content of `ucam_login_credentials.json`
* `TEACHER_CONTACT_DETAILS`: Content of `teacher_contact_details.json`
* `GOOGLE_SERVICE_ACCOUNT_KEY`: Content of `service_account_key.json`
* `GOOGLE_OAUTH_CLIENT_SECRET`: Content of `oauth_client_secret.json`
* `TOKEN_PICKLE_B64`: Base64 encoded string of `token.pickle`

#### Encoding the Token
Use the provided utility to generate the base64 string:
```bash
python3 encode.py
```

### Local Workflow Validation
Test the action locally using [act](https://github.com/nektos/act):
1. Run `./flatten.sh` to generate the `.secrets` file.
2. Run `./act_test.sh` to execute the local test.

---

## Verification
- [ ] Check the `backend` sheet for raw data.
- [ ] Verify the `NewMain` sheet for sorted and formatted routine data.
- [ ] Confirm the "Last Updated" timestamp is current.

---

## Troubleshooting
* **Permissions**: Ensure the target sheet is shared with the Service Account email.
* **API Limits**: Check the Google Cloud Console for quota errors if updates fail.
* **Selectors**: If UCAM updates their UI, the scraping logic in `routine_scrapper.py` may require adjustments.
