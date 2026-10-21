#!/usr/bin/env python3
"""Extract the routine from UCAM's official Student Class Routine Report.

This replaces the old attendance-dashboard scraper. The report is a plain SSRS
table, so it yields exactly what the sheet needs - course, teacher, phone,
email, day, room, time slot and section - without a second contact-lookup file.

Design contracts:

* **Fail-stop.** A run with any failed account writes nothing and exits 1. The
  previous output is invalidated up front, so a failed scrape can never leave a
  file that the formatter or the calendar exporter would publish.
* **Role-aware merge.** The ``primary`` account contributes every course; each
  ``lab_merge`` account contributes only courses whose title contains the
  standalone word "lab". Roles are optional and default to the historic
  positional behaviour (users[0] primary, the rest lab_merge).
* **Atomic write.** The JSON manifest is written to a temporary sibling and
  renamed with ``os.replace``, so readers never see a half-written file.
* **One Chrome lookup.** ``browser_lookup`` is the single source of truth, shared
  with ``scripts/setup.py`` and ``scripts/check_setup.py``.

Usage::

    python extract_ucam.py --output output/routine_data.json
    python extract_ucam.py --headed            # visible browser for debugging
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import nodriver as nd
import nodriver.core.browser as _nd_browser
from bs4 import BeautifulSoup

from browser_lookup import get_chrome_executable
from config import (
    CHROME_BINARY_PATH,
    HEADLESS,
    LOGIN_URL,
    OUTPUT_DIR,
    ROUTINE_REPORT_URL,
    setup_logging,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# `OUTPUT_DIR` is configurable and may be relative to the project root; anchor it
# so a run from another working directory still writes where the readers look.
_output_dir = OUTPUT_DIR if os.path.isabs(OUTPUT_DIR) else os.path.join(BASE_DIR, OUTPUT_DIR)
OUTPUT_DIR_PATH = _output_dir
DEFAULT_OUTPUT_PATH = os.path.join(OUTPUT_DIR_PATH, "routine_data.json")
TMP_DIR = os.path.join(BASE_DIR, "tmp")

CREDENTIALS_PATH = os.path.join(BASE_DIR, "configs_to_edit", "ucam_login_credentials.json")

# Browser retry policy: a fresh browser per attempt (a half-broken CDP session
# cannot be reused) and a failed account aborts the whole run.
ACCOUNT_RETRY_ATTEMPTS = 2
RETRY_SETTLE_SECONDS = 5

# Element/DOM constants. Kept module-level so tests and debugging agree with the
# workflow about what is being waited for.
LOGIN_USERNAME_ID = "logMain_UserName"
LOGIN_PASSWORD_ID = "logMain_Password"
LOGIN_BUTTON_ID = "logMain_Button1"
SEMESTER_SELECT_ID = "ctl00_MainContainer_ddlHeldIn"
REPORT_TABLE_ID = "ctl00_MainContainer_ReportViewer1_fixedTable"
REPORT_CONTENT_ID = "ctl00_MainContainer_ReportViewer1_ctl09_ReportArea"

CLOUDFLARE_MARKERS = ("just a moment", "cloudflare", "attention required")
LOGIN_WAIT_ATTEMPTS = 12
REPORT_TABLE_WAIT_SECONDS = 60

LAB_TITLE_RE = re.compile(r"\blab\b", re.IGNORECASE)

log = logging.getLogger("extract_ucam")

# ---------------------------------------------------------------------------
# nodriver resilience
# ---------------------------------------------------------------------------


async def _resilient_browser_start(self=None):
    """Start Chrome with a 15-second CDP connect window (upstream uses 2.5s).

    Slow/containerised hosts regularly miss upstream's five 500ms retries while
    Chrome is still booting. This is byte-for-byte upstream's ``Browser.start``
    apart from the retry budget, so keep it in sync when nodriver changes - the
    guard below fails loudly instead of silently misbehaving.
    """
    if not self:
        raise RuntimeError("use ``await Browser.create()`` to create a new instance")

    if self._process or self._process_pid:
        if self._process.returncode is not None:
            return await self.create(config=self.config)
        raise RuntimeError("ignored! this call has no effect when already running.")

    connect_existing = False
    if self.config.host is not None and self.config.port is not None:
        connect_existing = True
    else:
        self.config.host = "127.0.0.1"
        self.config.port = _nd_browser.util.free_port()

    if getattr(self.config, "_extensions", None):
        self.config.add_argument(
            "--load-extension=%s" % ",".join(str(_) for _ in self.config._extensions)
        )

    exe = self.config.browser_executable_path
    params = self.config()

    if not connect_existing:
        self._process = await asyncio.create_subprocess_exec(
            exe,
            *params,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=_nd_browser.is_posix,
        )
        self._process_pid = self._process.pid

    self._http = _nd_browser.HTTPApi((self.config.host, self.config.port))
    _nd_browser.util.get_registered_instances().add(self)
    await asyncio.sleep(0.5)

    for _attempt in range(1, 31):
        try:
            self.info = _nd_browser.ContraDict(await self._http.get("version"), silent=True)
            if self.info:
                break
        except Exception:
            if self._process and self._process.returncode is not None:
                stderr = await self._process.stderr.read()
                raise RuntimeError(
                    "Browser process exited with code %s: %s"
                    % (self._process.returncode, stderr.decode(errors="ignore"))
                ) from None
            await asyncio.sleep(0.5)

    if not self.info:
        raise TimeoutError("Failed to connect to browser after 15 seconds.")

    self.websocket_url = self.info.webSocketDebuggerUrl
    await self.attach()
    await self.update_targets()
    return self


def install_resilient_browser_start():
    """Patch ``Browser.start`` after checking the internals this fork relies on."""
    browser_cls = getattr(_nd_browser, "Browser", None)
    if browser_cls is None:
        raise RuntimeError("nodriver.core.browser.Browser is missing; update extract_ucam.py")

    missing = [
        "nodriver.core.browser.%s" % name
        for name in ("util", "HTTPApi", "ContraDict", "is_posix")
        if not hasattr(_nd_browser, name)
    ]
    for name in ("free_port", "get_registered_instances"):
        if not hasattr(_nd_browser.util, name):
            missing.append("nodriver.core.browser.util.%s" % name)

    referenced = set()
    for func in (browser_cls.start, browser_cls.__init__):
        code = getattr(func, "__code__", None)
        if code:
            referenced.update(code.co_names)
    for name in ("config", "_process", "_process_pid", "_http", "info",
                 "websocket_url", "attach", "update_targets"):
        if name not in referenced:
            missing.append("Browser.%s" % name)

    if missing:
        raise RuntimeError(
            "nodriver internals changed (missing: %s). Update extract_ucam.py's "
            "resilient browser start, or pin a compatible nodriver." % ", ".join(missing)
        )

    browser_cls.start = _resilient_browser_start


install_resilient_browser_start()


# ---------------------------------------------------------------------------
# Credentials and merge rules
# ---------------------------------------------------------------------------

VALID_ROLES = ("primary", "lab_merge")


def load_credentials(path=None):
    """Load and validate the account list.

    ``UCAM_ACCOUNTS`` (a JSON list) overrides the file, which keeps the engine
    usable from a shell without touching the gitignored credential file.
    """
    raw_override = os.getenv("UCAM_ACCOUNTS")
    data = {}
    if raw_override:
        try:
            accounts = json.loads(raw_override)
        except json.JSONDecodeError as exc:
            raise ValueError("UCAM_ACCOUNTS is not valid JSON: %s" % exc) from exc
        if not isinstance(accounts, list) or not accounts:
            raise ValueError("UCAM_ACCOUNTS must be a non-empty JSON list")
        data = {"users": accounts, "login_url": LOGIN_URL}
        source = "UCAM_ACCOUNTS"
    else:
        path = path or CREDENTIALS_PATH
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "UCAM credentials not found at '%s'. Copy "
                "configs_to_edit/ucam_login_credentials.json.example.txt and fill it in, "
                "or set UCAM_ACCOUNTS." % path
            ) from exc
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON in UCAM credentials '%s': %s" % (path, exc)) from exc
        source = path

    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, list) or not users:
        raise ValueError("UCAM credentials in '%s' need a non-empty 'users' list" % source)

    for index, user in enumerate(users):
        if not isinstance(user, dict):
            raise ValueError("users[%d] in '%s' is not an object" % (index, source))
        for key in ("username", "password"):
            if not str(user.get(key) or "").strip():
                raise ValueError("users[%d] in '%s' is missing '%s'" % (index, source, key))

    resolve_roles(users)  # validate roles early, before a browser starts
    return {
        "users": users,
        "login_url": (data.get("login_url") if isinstance(data, dict) else None) or LOGIN_URL,
    }


def resolve_roles(accounts):
    """Return ``[(account, role), ...]`` with the historic positional default.

    Exactly one primary is allowed. If no role is explicit, users[0] is primary
    and every other account is a lab merge; that keeps the existing credential
    file working unchanged.
    """
    explicit = [(index, account.get("role")) for index, account in enumerate(accounts)
                if account.get("role")]
    for index, role in explicit:
        if role not in VALID_ROLES:
            raise ValueError(
                "users[%d] has role %r; expected one of %s"
                % (index, role, ", ".join(VALID_ROLES))
            )

    primary_indexes = [index for index, role in explicit if role == "primary"]
    if len(primary_indexes) > 1:
        raise ValueError("exactly one account may have role 'primary'; found %d"
                         % len(primary_indexes))

    if primary_indexes:
        primary_index = primary_indexes[0]
    else:
        unassigned = [index for index, account in enumerate(accounts)
                      if not account.get("role")]
        primary_index = unassigned[0] if unassigned else 0

    resolved = []
    for index, account in enumerate(accounts):
        role = account.get("role") or ("primary" if index == primary_index else "lab_merge")
        resolved.append((account, role))
    return resolved


def merge_entries(per_account_entries):
    """Apply the role-aware merge and dedupe.

    Args:
        per_account_entries: iterable of ``(role, entries)`` pairs.

    Returns:
        list[dict]: primary courses first, then qualifying lab courses, deduped
        by ``(CourseCode, Day, TimeSlot, Section)``.
    """
    combined = []
    for role, entries in per_account_entries:
        if role == "primary":
            combined.extend(entries)
        elif role == "lab_merge":
            combined.extend(entry for entry in entries
                            if LAB_TITLE_RE.search(entry.get("CourseTitle", "") or ""))
        else:  # pragma: no cover - resolve_roles rejects this first
            raise ValueError("unknown role %r" % (role,))

    unique = []
    seen = set()
    for entry in combined:
        key = (
            entry.get("CourseCode"),
            entry.get("Day"),
            entry.get("TimeSlot"),
            entry.get("Section"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------

RE_COURSE_CODE = re.compile(r"\b([A-Z]{2,4}-\d{4})\b")
RE_TIME_SLOT = re.compile(
    r"(\d{1,2}:\d{1,2}\s*(?:AM|PM)?\s*-\s*\d{1,2}:\d{1,2}\s*(?:AM|PM)?)",
    re.IGNORECASE,
)
RE_PHONE = re.compile(r"\b(01\d{9})\b")
RE_EMAIL = re.compile(r"\b([\w.-]+@[\w.-]+\.\w+)\b")
RE_ROOM = re.compile(r"\b(AC-\d{3}|\d{3}|CSE\s+Lab[-\s]?\d*|Lab[-\s]?\d+)\b", re.IGNORECASE)
RE_SECTION = re.compile(r"\b(B|B1|B2|A|A1|A2|C|C1|C2)\b")
DAYS_OF_WEEK = ("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri")


def _looks_like_teacher(text):
    """Teacher cells look like ``UKD_Utpol Kanti Das`` (initials + name)."""
    return "_" in text and any(char.isupper() for char in text)


def parse_report_html(html, default_section="B"):
    """Parse routine entries out of the SSRS report table.

    The report repeats the course block for each schedule line: a row carrying
    the course code (and title in the next cell), followed by rows whose Day is
    followed by Room, Time Slot and Section in that order.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    current_course_code = None
    current_title = None

    for row in soup.find_all("tr"):
        cells = [cell.get_text(separator=" ", strip=True) for cell in row.find_all("td")]
        if not cells:
            continue

        row_text = " | ".join(cells)

        code_match = RE_COURSE_CODE.search(row_text)
        if code_match and "Course" not in row_text:
            current_course_code = code_match.group(1)
            for index, text in enumerate(cells):
                if text == current_course_code and index + 1 < len(cells):
                    current_title = cells[index + 1]
                    break

        day_found = next((day for day in DAYS_OF_WEEK if day in cells), None)
        if not day_found or not current_course_code:
            continue

        day_index = cells.index(day_found)

        room = cells[day_index + 1].strip() if day_index + 1 < len(cells) else ""
        if not room:
            room_match = RE_ROOM.search(row_text)
            room = room_match.group(1).strip() if room_match else ""

        time_slot = cells[day_index + 2].strip() if day_index + 2 < len(cells) else ""
        if not time_slot:
            time_match = RE_TIME_SLOT.search(row_text)
            time_slot = time_match.group(1).strip() if time_match else ""

        section = cells[day_index + 3].strip() if day_index + 3 < len(cells) else ""
        if not section:
            section_match = RE_SECTION.search(row_text)
            section = section_match.group(1).strip() if section_match else default_section

        teacher = ""
        teacher_phone = ""
        teacher_email = ""
        for text in cells:
            if _looks_like_teacher(text):
                teacher = text
            phone_match = RE_PHONE.search(text)
            if phone_match:
                teacher_phone = phone_match.group(1)
            email_match = RE_EMAIL.search(text)
            if email_match:
                teacher_email = email_match.group(1)

        entries.append({
            "CourseCode": current_course_code,
            "CourseTitle": current_title or "",
            "Teacher": teacher,
            "TeacherPhone": teacher_phone,
            "TeacherEmail": teacher_email,
            "Day": day_found,
            "Room": room,
            "TimeSlot": time_slot,
            "Section": section,
        })

    return entries


# ---------------------------------------------------------------------------
# Browser workflow
# ---------------------------------------------------------------------------


class ScrapeTimeoutError(RuntimeError):
    """The portal never produced the element/table a step needed."""


def _browser_args(headless):
    args = [
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-software-rasterizer",
        "--ozone-platform=x11",
        "--window-size=1920,1080",
    ]
    if headless:
        args.append("--no-sandbox")
    return args


def _dump_debug_html(account_id, html):
    """Keep the last response for a failed account so the parser can be fixed."""
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(account_id))
        path = os.path.join(TMP_DIR, "error_log_%s.html" % safe_id)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(html)
        log.info("Saved failed-account HTML to '%s'", path)
    except OSError as exc:  # pragma: no cover - best effort diagnostics only
        log.warning("Could not save debug HTML for %s: %s", account_id, exc)


async def _report_has_content(tab):
    """True once the report area contains a rendered course row.

    ``ctl00_MainContainer_ReportViewer1_fixedTable`` is only the report viewer's
    *layout* table: it exists (empty) before the asynchronous postback renders
    the report. Waiting for a course-code pattern inside the report area avoids
    parsing that empty shell.
    """
    try:
        return bool(await tab.evaluate(
            "(() => {"
            "  const el = document.getElementById(%s);"
            "  const text = (el && el.innerText) || document.body.innerText || '';"
            "  return /[A-Z]{2,4}-\\d{4}/.test(text);"
            "})()" % json.dumps(REPORT_CONTENT_ID)
        ))
    except Exception:
        # Navigation during the postback can invalidate the execution context.
        return False


async def _wait_for_report_table(tab, account_id, timeout_s=REPORT_TABLE_WAIT_SECONDS):
    """Poll until the report body is actually rendered."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await _report_has_content(tab):
            return True
        await asyncio.sleep(1)
    body = await tab.evaluate("document.body ? document.body.innerHTML : ''")
    _dump_debug_html(account_id, body or "")
    raise ScrapeTimeoutError(
        "Report content did not render within %ds for %s" % (timeout_s, account_id)
    )


async def _wait_for_login_form(tab, account_id):
    for attempt in range(1, LOGIN_WAIT_ATTEMPTS + 1):
        title = (await tab.evaluate("document.title")) or ""
        if any(marker in title.lower() for marker in CLOUDFLARE_MARKERS):
            log.info("[%s] Cloudflare challenge active (attempt %d); waiting...",
                     account_id, attempt)
            await asyncio.sleep(4)
            continue
        user_input = await tab.select("#%s" % LOGIN_USERNAME_ID, timeout=6)
        if user_input:
            return user_input
        await asyncio.sleep(2)
    raise ScrapeTimeoutError(
        "Could not load login fields for %s (Cloudflare block)." % account_id
    )


async def extract_account_routine(account, chrome_bin, headed=False, login_url=LOGIN_URL):
    """Log in and return ``(semester, entries)`` for one account."""
    username = account["username"]
    password = account["password"]
    account_id = account.get("id") or username
    section_label = account.get("section_label") or "B"
    headless = False if headed else HEADLESS

    log.info("Starting browser for %s (%s) [headless=%s]...",
             account_id, username, headless)
    browser = await nd.start(
        headless=headless,
        sandbox=False,
        browser_executable_path=chrome_bin,
        browser_args=_browser_args(headless),
    )
    tab = browser.main_tab if hasattr(browser, "main_tab") else browser

    try:
        # A neutral first visit builds the Cloudflare clearance cookie before the
        # portal is loaded, which is far more reliable than hitting it cold.
        await tab.get("https://www.google.com")
        await asyncio.sleep(2)

        log.info("[%s] Accessing UCAM login...", account_id)
        await tab.get(login_url)
        await asyncio.sleep(6)

        user_input = await _wait_for_login_form(tab, account_id)
        password_input = await tab.select("#%s" % LOGIN_PASSWORD_ID, timeout=5)
        login_button = await tab.select("#%s" % LOGIN_BUTTON_ID, timeout=5)
        if not password_input or not login_button:
            raise ScrapeTimeoutError("Login form incomplete for %s" % account_id)

        log.info("[%s] Authenticating...", account_id)
        await user_input.send_keys(username)
        await password_input.send_keys(password)
        await login_button.click()
        await asyncio.sleep(8)

        log.info("[%s] Loading Student Class Routine Report...", account_id)
        await tab.get(ROUTINE_REPORT_URL)
        await asyncio.sleep(8)

        # Pick the first active semester (value != "0"). The postback redraws the
        # report asynchronously, so wait for the table instead of sleeping.
        semester_name = await tab.evaluate(
            """
            (() => {
                const sel = document.getElementById(%s);
                if (!sel) return null;
                for (let i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].value !== "0") {
                        sel.value = sel.options[i].value;
                        if (sel.onchange) { sel.onchange(); }
                        sel.dispatchEvent(new Event("change", { bubbles: true }));
                        return sel.options[i].text;
                    }
                }
                return null;
            })()
            """ % json.dumps(SEMESTER_SELECT_ID)
        )
        log.info("[%s] Synchronized semester: %s", account_id, semester_name)
        await _wait_for_report_table(tab, account_id)

        report_html = await tab.evaluate(
            """
            (() => {
                const area = document.getElementById(%s);
                if (area && area.innerText && /[A-Z]{2,4}-\\d{4}/.test(area.innerText)) {
                    return area.innerHTML;
                }
                return document.body.innerHTML;
            })()
            """ % json.dumps(REPORT_CONTENT_ID)
        )

        entries = parse_report_html(report_html, default_section=section_label)
        if not entries:
            _dump_debug_html(account_id, report_html or "")
            raise RuntimeError("No class entries parsed for %s" % account_id)

        log.info("[%s] Extracted %d class entries.", account_id, len(entries))
        return semester_name or "Active Semester", entries
    finally:
        browser.stop()


async def scrape_account_with_retries(account, chrome_bin, headed=False, login_url=LOGIN_URL):
    """Run an account in a fresh browser, retrying once."""
    account_id = account.get("id") or account.get("username")
    last_error = None
    for attempt in range(1, ACCOUNT_RETRY_ATTEMPTS + 1):
        try:
            return await extract_account_routine(
                account, chrome_bin, headed=headed, login_url=login_url
            )
        except Exception as exc:
            last_error = exc
            log.warning("Attempt %d/%d failed for %s: %s",
                        attempt, ACCOUNT_RETRY_ATTEMPTS, account_id, exc)
            if attempt < ACCOUNT_RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_SETTLE_SECONDS)
    raise RuntimeError("Failed to extract %s after %d attempts: %s"
                       % (account_id, ACCOUNT_RETRY_ATTEMPTS, last_error))


# ---------------------------------------------------------------------------
# Manifest writing
# ---------------------------------------------------------------------------


def invalidate_previous_output(output_path):
    """Delete the previous manifest before a run so failure cannot look fresh."""
    for path in (output_path, str(output_path) + ".tmp"):
        try:
            os.remove(path)
            log.info("Removed previous output '%s'.", path)
        except FileNotFoundError:
            pass


def write_manifest(output_path, semester, entries, accounts_processed, now=None):
    """Atomically write ``{generated_at, semester, accounts_processed, entries}``."""
    moment = now or datetime.now(timezone.utc)
    payload = {
        "generated_at": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "semester": semester,
        "accounts_processed": list(accounts_processed),
        "entries": entries,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp_path, output_path)
    return payload


async def run_extraction(output_path=None, headed=False, credentials_path=None):
    """Scrape every configured account and write the manifest, or fail loudly."""
    output_path = Path(output_path or DEFAULT_OUTPUT_PATH)
    invalidate_previous_output(output_path)

    if not headed and "WAYLAND_DISPLAY" in os.environ:
        os.environ.pop("WAYLAND_DISPLAY", None)

    chrome_bin = get_chrome_executable(CHROME_BINARY_PATH)
    if not chrome_bin:
        raise RuntimeError(
            "No Chrome/Chromium binary found. Install one or set CHROME_BINARY_PATH in .env."
        )
    credentials = load_credentials(credentials_path)
    resolved_accounts = resolve_roles(credentials["users"])

    per_account_entries = []
    processed = []
    failures = []
    semester = None

    for index, (account, role) in enumerate(resolved_accounts):
        if index:
            await asyncio.sleep(4)  # let the previous Chrome fully exit
        account_id = account.get("id") or account.get("username")
        try:
            account_semester, entries = await scrape_account_with_retries(
                account, chrome_bin, headed=headed, login_url=credentials["login_url"]
            )
        except Exception as exc:
            log.error("Giving up on %s: %s", account_id, exc)
            failures.append(account_id)
            continue
        semester = semester or account_semester
        per_account_entries.append((role, entries))
        processed.append(account_id)

    if failures:
        raise RuntimeError(
            "Partial extraction (%d/%d accounts): %s. Refusing to write a "
            "partial routine." % (len(failures), len(resolved_accounts),
                                   ", ".join(map(str, failures)))
        )

    merged = merge_entries(per_account_entries)
    if not merged:
        raise RuntimeError("No routine entries were extracted from any account.")

    payload = write_manifest(
        output_path,
        semester or "Active Semester",
        merged,
        processed,
    )
    log.info("Wrote %d unique entries from %d accounts to '%s'.",
             len(payload["entries"]), len(processed), output_path)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract the routine from UCAM's official Student Class Routine Report."
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT_PATH,
        help="Target JSON path (default: %(default)s)",
    )
    parser.add_argument(
        "--credentials",
        default=CREDENTIALS_PATH,
        help="Credential file (default: %(default)s)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser (debugging); default follows HEADLESS.",
    )
    args = parser.parse_args(argv)

    setup_logging()
    try:
        asyncio.run(
            run_extraction(
                args.output,
                headed=args.headed,
                credentials_path=args.credentials,
            )
        )
    except Exception as exc:
        log.error("Scraper terminated with error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
