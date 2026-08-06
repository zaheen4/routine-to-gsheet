# Setup & Bring-Up Guide

This guide walks a brand-new user through setting up the UCAM Class Routine pipeline for their own class. It is the companion to [README.md](README.md), which focuses on what the project does; this document focuses on getting it running end to end.

If you already have a working installation and are moving to a new machine, jump straight to [Phase B](#phase-b--local-setup) and reuse the files listed in [What you will need](#what-you-will-need).

---

## Overview

The pipeline has three parts:

1. **Scraper** (`routine_scrapper.py`) — logs into the UCAM (NITER) student portal with your credentials and scrapes the class-schedule dashboard. Requires a **Chrome or Chromium browser**.
2. **Formatter** (`gsheet_formatter.py`) — writes the scraped routine into the `backend` tab of a Google Spreadsheet using a **service account**, then calls a **Google Apps Script** to sort/format it into the `NewMain` tab.
3. **Google Apps Script** (`apps_script/Code.gs`) — a small script bound to your spreadsheet that does the final sorting and formatting. It is invoked by the formatter over the Apps Script API using an **OAuth client**.

> **Why two Google credentials?** The service account is what authorizes *reading/writing the spreadsheet* (server-to-server, no login). The OAuth client is what authorizes *calling your Apps Script* on your behalf. For a normal consumer Google account (not a Workspace account), both are required — a service account cannot invoke a personal Apps Script.

### What you will need

| # | Item | Source |
|---|------|--------|
| 1 | Python 3.10+ | python.org / your OS package manager |
| 2 | Google Chrome **or** Chromium | google.com/chrome or your OS package manager |
| 3 | `xvfb-run` (Linux, headless only) | your OS package manager (`xvfb`) |
| 4 | A Google account | — |
| 5 | Your UCAM (NITER) portal username & password | your institution |
| 6 | Your `section_label` (e.g. `A1`) | appears in the UCAM portal |

---

## Phase A — Google Cloud Setup (done once, in the browser)

### A1. Create the spreadsheet

1. Go to [sheets.new](https://sheets.new) and create a new spreadsheet.
2. **Name it exactly** what you will put in `SPREADSHEET_NAME` (default `CSE-03_B_ClassRoutine`). The formatter looks it up by name via `gc.open(...)`, so a wrong name means `SpreadsheetNotFound`.
3. You can leave it empty for now — the formatter auto-creates the `backend` and `NewMain` tabs if they don't exist.

### A2. Enable the required APIs

In the [Google Cloud Console](https://console.cloud.google.com/), create a project (or reuse one), then enable these APIs under **APIs & Services > Library**:

- Google Sheets API
- Google Apps Script API
- Google Drive API

### A3. Create a service account

1. Under **APIs & Services > Credentials > Create Credentials > Service Account**.
2. Give it a name (e.g. `routine-sync`) and assign the **Editor** role.
3. In the service account's **Keys** tab, **Add Key > Create new key > JSON**. A file downloads.
4. Rename that file to `service_account_key.json` and place it in `google_cloud_keys/` (replacing the placeholder of the same name).
5. **Share your spreadsheet with this service account**:
   - Open your spreadsheet, click **Share**, and paste the `client_email` from `service_account_key.json`.
   - Give it **Editor** access.
   - This is the single most common setup mistake — if you skip it, the formatter authenticates fine but fails to find/open the spreadsheet.

### A4. Configure the OAuth consent screen

1. Under **APIs & Services > OAuth consent screen**, choose **External** (anyone with a Google account).
2. Fill in an **App name** and a **Support email**.
3. Under **Audience > Test users**, add **your own email address**. Without this, the OAuth flow will show "access blocked".
4. **Publish the app to Production** (button on the consent screen). This matters: for apps left in **Testing** mode, Google **revokes refresh tokens after 7 days**, which would force you to re-authenticate every week. Publishing to Production makes the refresh token long-lived.

### A5. Create an OAuth client ID

1. Under **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
2. Application type: **Desktop app**.
3. Download the JSON, rename it to `oauth_client_secret.json`, and place it in `google_cloud_keys/`.

### A6. Deploy the Google Apps Script

1. Open your spreadsheet, then go to **Extensions > Apps Script**.
2. Delete any stub code and paste the **entire** contents of [`apps_script/Code.gs`](apps_script/Code.gs).
3. Click **Deploy > New deployment**.
4. Type: **API Executable**. Description is optional.
5. Click **Deploy**, then **copy the Script ID** from the deployment dialog.
6. Save it as `APP_SCRIPT_ID` in your `.env` (see [Phase B](#phase-b--local-setup)).

---

## Phase B — Local Setup

### B1. Clone and install dependencies

```bash
git clone https://github.com/zaheen4/routine-to-gsheet.git
cd routine-to-gsheet
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
```

### B2. Install system dependencies

- **Chrome or Chromium** — the scraper auto-detects the binary (prefers `google-chrome-stable`) and downloads a matching chromedriver automatically. If you have both installed and hit a version mismatch, pin one via `CHROME_BINARY_PATH` in `.env`.
- **Xvfb** — only needed on Linux without a desktop, so the scraper can run headless.

### B3. Scaffold the configuration

Run the setup helper (from the project root):

```bash
.venv/bin/python scripts/setup.py
```

This copies the template files to their real names if they're missing:

| File | What it is |
|------|-----------|
| `configs_to_edit/ucam_login_credentials.json` | Your UCAM login (1 account, or 2 if you merge a friend's lab schedule) |
| `configs_to_edit/teacher_contact_details.json` | Optional teacher contact lookup by initials |
| `.env` | Runtime settings: spreadsheet name, target tab, Apps Script ID |

It will **not** create `google_cloud_keys/*.json` for you (those must be downloaded from Google Cloud in Phase A), but it will tell you if they're missing.

### B4. Fill in the configuration files

**`configs_to_edit/ucam_login_credentials.json`** — edit the real file that `setup.py` created:

```json
{
  "users": [
    {
      "id": "my_primary_account",
      "username": "YOUR_UCAM_ID",
      "password": "YOUR_UCAM_PASSWORD",
      "section_label": "A1"
    }
  ],
  "login_url": "https://ucam.niter.edu.bd/Security/Login.aspx",
  "attendance_dashboard_url": "https://ucam.niter.edu.bd/Module/Dashboard/StudentClassAttendanceDashboard.aspx?mmi=40545a1b42555b5c4e63"
}
```

- **One account is enough.** Add a second `users[]` entry only if you want to merge a lab schedule from another student's account (that second account's non-lab courses are ignored).
- The two URLs are for the NITER portal and usually need no changes.

**`configs_to_edit/teacher_contact_details.json`** — optional. Keyed by the teacher initials that appear in the portal (e.g. `"SS"`), mapping to `FullName` / `Phone` / `Email`. Leave the file empty (`{}`) if you don't need it.

**`.env`** — set the values that apply to you (see `.env.example` for the full list):

```env
PREFERRED_BROWSER=chrome
HEADLESS=false
SPREADSHEET_NAME=CSE-03_B_ClassRoutine
TARGET_SHEET_NAME=backend
APP_SCRIPT_ID=your_script_id_from_phase_A6
LOG_LEVEL=INFO
```

> `TARGET_SHEET_NAME` defaults to `backend` and only needs changing if you also rename the tabs in `apps_script/Code.gs`.

---

## Phase C — First Run

### C1. Scrape the routine

```bash
.venv/bin/python routine_scrapper.py
```

On a headless Linux box (no desktop), use `xvfb-run`:

```bash
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" .venv/bin/python routine_scrapper.py
```

This logs into UCAM, scrapes the dashboard, and writes `output_of_fetched_routine/final_combined_routine.json`.

### C2. Format and sync to Google Sheets

```bash
.venv/bin/python gsheet_formatter.py
```

- The **first run opens an OAuth consent window in your browser** to create `token.pickle`. **Run this from a machine/session with a display**; if you run it fully headless and the token is missing, it now fails fast with a message instead of hanging.
- The formatter writes raw data to `backend`, creates `NewMain` if needed, then calls your Apps Script to sort and format it.

### C3. Verify

- [ ] `backend` tab contains the raw routine rows.
- [ ] `NewMain` tab contains the sorted routine, and headers (if freshly created) at `B3:I3`.
- [ ] `NewMain` shows a current **Last Updated** timestamp (bottom-right area).

---

## Phase D — Optional Automation (Linux systemd)

To run the pipeline automatically every Saturday at 19:00 (with catch-up if the machine was off):

```bash
mkdir -p ~/.config/systemd/user/
sed "s|/path/to/your/project|$(pwd)|g" scripts/routine-automation.service.example > ~/.config/systemd/user/routine-automation.service
cp scripts/routine-automation.timer.example ~/.config/systemd/user/routine-automation.timer
systemctl --user daemon-reload
systemctl --user enable --now routine-automation.timer
```

Check the next run with `systemctl --user list-timers`.

---

## Preflight Check

After configuration, run the preflight checker to confirm everything is reachable before the first real run:

```bash
.venv/bin/python scripts/check_setup.py
```

It verifies the local files are valid, that the spreadsheet opens with your service account (catches the "not shared" case), and that `.env` is populated.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `SpreadsheetNotFound: ...` | Sheet not created, wrong `SPREADSHEET_NAME`, or **sheet not shared with the service account `client_email`** | Share the sheet (Editor) with the service account email from `google_cloud_keys/service_account_key.json`; check the name in `.env`. |
| `403 ... The caller does not have permission` | Service account lacks access | Same as above. |
| OAuth window shows **"access blocked"** | Consent screen is External but your email isn't a **test user** | Add your email under **OAuth consent screen > Test users**. |
| Formatter says **re-auth required** / fails fast | `token.pickle` missing or refresh token expired | Run `gsheet_formatter.py` once from a session with a display. If this keeps recurring every ~week, your OAuth app is still in **Testing** mode — publish to Production (A4). |
| **ChromeDriver version mismatch** error | Both Google Chrome and Chromium installed; wrong binary chosen | Set `CHROME_BINARY_PATH` in `.env` to your preferred binary (e.g. `/usr/bin/google-chrome-stable`). |
| `No valid routine entries filtered` | Portal hasn't published the current semester's schedule yet | Nothing to fix — the schedule isn't live. Check back later. |
| Formatter warns `APP_SCRIPT_ID is not configured` | `.env` missing or still has the placeholder | Set `APP_SCRIPT_ID` from Phase A6. |

---

## Bringing this up on a NEW machine (not a fresh class)

You only need to repeat:

1. Clone + venv + `pip install -r requirements.txt`.
2. Install Chrome/Chromium (+ Xvfb if headless).
3. Copy these gitignored files from your old machine:
   - `configs_to_edit/ucam_login_credentials.json`
   - `configs_to_edit/teacher_contact_details.json`
   - `google_cloud_keys/service_account_key.json`
   - `google_cloud_keys/oauth_client_secret.json`
   - `.env`
   - `token.pickle` (or run the formatter once interactively to regenerate it)
4. Optionally reinstall the systemd timer (Phase D).

Nothing on the Google side changes — the same spreadsheet, service account, OAuth client, and Apps Script deployment are reused.
