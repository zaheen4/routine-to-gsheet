# Automated UCAM Class Routine to Google Sheets

An automated solution for scraping class schedules from the UCAM web portal and synchronizing them with a Google Spreadsheet.

**New here?** Follow the step-by-step bring-up guide in [**SETUP.md**](SETUP.md) — it covers Google Cloud setup, configuration, first run, and automation.

## Final Output Preview

![Class Routine Demo](assets/screenshot_of_output.png)

[**Demo Output Spreadsheet**](https://docs.google.com/spreadsheets/d/1mE36dYY9u4rgwbJl9rq8LibBlB-VLd_K3Jli_Db3bxA/edit?usp=sharing)

### Key Features
* **Automated Extraction**: Authenticates with the UCAM portal to retrieve schedule data.
* **Multi-User Consolidation**: Supports merging schedules from two accounts (e.g., for lab section synchronization).
* **Data Enrichment**: Integrates teacher contact details from local configuration files.
* **Flexible Browser Support**: Compatible with both Firefox and Google Chrome.
* **Sheets Integration**: Uploads raw data and triggers Google Apps Script for post-processing.
* **Advanced Processing**: Normalizes time formats to 12-hour display, sorts chronologically, and generates a "Last Updated" timestamp.

---

## Prerequisites

* **Python 3.10+**
* **pip** (Python package manager)
* **Google Chrome** or **Chromium**
* **Xvfb** (Required for headless Linux environments)
* **Google Account** with enabled access to Google Drive and Google Cloud Platform

---

## Project Structure
```text
project_root/
├── routine_scrapper.py         # Primary scraping logic for UCAM portal
├── gsheet_formatter.py         # Google Sheets API integration
├── config.py                   # Central runtime configuration
├── SETUP.md                    # Step-by-step bring-up guide
├── .env.example                # Environment variable overrides template
├── apps_script/                # Google Apps Script source
│   └── Code.gs                 # Paste into Extensions > Apps Script
├── tests/                      # Unit test suite (pytest)
├── configs_to_edit/            # User configuration directory
│   ├── ucam_login_credentials.json.example.txt
│   └── teacher_contact_details.json.example.txt
├── google_cloud_keys/          # API credentials directory
│   ├── service_account_key.json.example.txt
│   └── oauth_client_secret.json.example.txt
├── scripts/                    # Local automation and helper scripts
│   ├── run_routine.sh          # Runner script (Unix/macOS)
│   ├── run_routine.bat         # Runner script (Windows)
│   ├── setup.py                # Config scaffold + validation
│   ├── check_setup.py          # Online preflight check
│   ├── routine-automation.service.example
│   ├── routine-automation.timer.example
│   └── routine-automation.plist.example
├── output_of_fetched_routine/  # Local cache for scraped data
├── requirements.txt            # Project dependencies
├── token.pickle                # Cached Google API authentication token
└── README.md                   # Documentation
```

---

## Setup

The full walkthrough lives in [**SETUP.md**](SETUP.md): Google Cloud setup and Apps Script deployment (Phase A), local configuration (Phase B), first run (Phase C), and automation (Phase D). A condensed quickstart follows.

Create a virtual environment and install dependencies:

**Unix/macOS:**
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

**Windows:**
```powershell
python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt
```

All commands below use `.venv/bin/python` (Unix/macOS) or `.\venv\Scripts\python.exe` (Windows); the venv need not be activated for them to work.

Scaffold the config files from templates:

```bash
.venv/bin/python scripts/setup.py
```

Then edit the real files it creates — your UCAM login (`configs_to_edit/ucam_login_credentials.json`) and your `.env`, where you must set `SPREADSHEET_NAME` (exact name of your Google Spreadsheet) and `APP_SCRIPT_ID` (from the Apps Script deployment). See **SETUP.md Phase B4/A6** for what goes in each.

The formatter auto-creates both worksheets (`backend` and `NewMain`) if they don't already exist. A freshly created `NewMain` gets `SHEET_HEADERS` written to `B3:I3`; sorted data lands at `B4` as the Apps Script dictates.

When using Chrome, the scraper auto-detects the browser binary (PATH scan on Linux, the well-known `.app` bundle path on macOS, Program Files / `%LOCALAPPDATA%` on Windows) and downloads a chromedriver matching that binary's major version. Set `CHROME_BINARY_PATH` in `.env` to force a specific binary (useful when both Google Chrome and Chromium are installed).

---

## Usage

1. **Scrape Routine**:
   ```bash
   .venv/bin/python routine_scrapper.py
   ```
   *Note: On headless Linux, run via `xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" .venv/bin/python routine_scrapper.py`.*
2. **Update Sheets**:
   ```bash
   .venv/bin/python gsheet_formatter.py
   ```
   *Note: On the first execution, an OAuth consent window will open in your browser to generate `token.pickle`.*

To run both stages in one go, use `scripts/run_routine.sh` (Unix/macOS) or `scripts\run_routine.bat` (Windows).

---

## Testing

Run the unit test suite (covers dashboard parsing, merge logic, browser workflow steps, sheet-building helpers, and setup validation):

```bash
.venv/bin/python -m pytest tests/ -q
```

---

## Automation

Weekly automation — a systemd timer (Linux), Task Scheduler (Windows), or a launchd agent (macOS) — is documented in **SETUP.md Phase D**.

---

## Verification

Before your first run, run the preflight check:

```bash
.venv/bin/python scripts/check_setup.py
```

It verifies the config files, that your spreadsheet opens with the service account, and that the Apps Script ID is configured.

---

## Troubleshooting

A troubleshooting table (spreadsheet not shared, consent blocked, 7-day token expiry, ChromeDriver version mismatch, and more) lives in **SETUP.md**.
