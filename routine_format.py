"""Pure routine formatting: the row shape and the sort/format transformation.

This module has no third-party imports (like ``browser_lookup.py``) so it can be
imported and tested without a browser, a spreadsheet, or a Google account.

The transformation here used to live in ``apps_script/Code.gs`` and run inside
the spreadsheet. It is pure data manipulation - sort by day and start time,
normalise the portal's AM/PM-less time slots to 12-hour form, and build the
footer stamp - so it belongs next to the rest of the pipeline, where the same
pytest run that covers the scraper covers it too.
"""

import re
from datetime import timedelta, timezone

# [Column layout]
# 'backend' and 'NewMain' both carry the same 8 columns. On 'NewMain' the block
# starts at B4 (the header row is B3:I3, seeded when the worksheet is created).
SHEET_HEADERS = [
    "Course", "Course Title", "Sect", "Day", "Room", "Time Slot", "Teacher", "Teacher Phone and Email"
]
CONTACT_COLUMN_HEADER = "Teacher Phone and Email"

DATA_START_ROW = 4
DATA_START_COL = 2
DATA_WIDTH = len(SHEET_HEADERS)

# [Sort sentinels]
# Days sort 1..7. A blank/absent day sorts after every real day, and a day we
# cannot recognise (a typo, say) sorts after that; times follow the same idea.
DAY_ORDER = {"SAT": 1, "SUN": 2, "MON": 3, "TUE": 4, "WED": 5, "THU": 6, "FRI": 7}
MISSING_DAY = 998
UNKNOWN_DAY = 999
BLANK_TIME = 99999
UNPARSEABLE_TIME = 99998

# [Footer]
STAMP_MIN_ROW = 6
STAMP_PREFIX = "Last Updated: "
SIGNATURE = "Made by Z  :)"
NO_DATA_MESSAGE = "No data found in 'backend' sheet."

# Fixed offset, deliberately not the spreadsheet's own timezone: this preserves
# the timestamps the Apps Script produced (REPORT_TIMEZONE = "GMT+6").
REPORT_UTC_OFFSET_HOURS = 6
REPORT_TIMEZONE = timezone(timedelta(hours=REPORT_UTC_OFFSET_HOURS))

# English month names hardcoded on purpose: strftime("%B") follows the process
# locale, and the platform-specific "%-d" is not portable to Windows, whereas
# the JS output was always "d MMMM, yyyy HH:mm" with no leading zero.
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Portal slots look like "11:45 - 1:0" or "9:0" - no AM/PM, minutes unpadded.
# Deliberately not anchored at the end: Code.gs's regex accepted a trailing
# garbage character and ignored it.
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2})(?:\s*(AM|PM))?", re.IGNORECASE)


# [Row shape helpers]

def combine_contact_info(phone, email):
    """
    Combines teacher phone and email into a single cell value.
    """
    if phone and email:
        return f"{phone}\n{email}"
    return phone or email


def build_sheet_data(data_to_write):
    """
    Converts routine entry dicts into the 2D list expected by the sheet
    (header row followed by one row per entry). Returns None on bad input.
    """
    if not isinstance(data_to_write, list) or not data_to_write or not isinstance(data_to_write[0], dict):
        return None

    all_rows = [list(SHEET_HEADERS)]
    for item in data_to_write:
        all_rows.append([
            item.get("CourseCode", ""),
            item.get("CourseTitle", ""),
            item.get("Section", ""),
            item.get("Day", ""),
            item.get("Room", ""),
            item.get("TimeSlot", ""),
            item.get("Teacher", ""),
            combine_contact_info(item.get("TeacherPhone", ""), item.get("TeacherEmail", "")),
        ])
    return all_rows


def contact_column_letter():
    """
    Returns the sheet column letter for the combined contact column (or "" if absent).
    """
    if CONTACT_COLUMN_HEADER not in SHEET_HEADERS:
        return ""
    col_idx = SHEET_HEADERS.index(CONTACT_COLUMN_HEADER) + 1
    letters = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


# [Transformation]

def _format_one_time(text):
    """(formatted, sortable) for a single time token; the getSortable() port."""
    match = _TIME_RE.match(text)
    if not match:
        return text, UNPARSEABLE_TIME

    hour = int(match.group(1))
    minute = int(match.group(2))
    # An explicit period always wins; otherwise 07:00-11:59 is assumed AM.
    period = match.group(3).upper() if match.group(3) else ("AM" if 7 <= hour <= 11 else "PM")
    if period == "PM" and hour < 12:
        hour += 12
    if period == "AM" and hour == 12:
        hour = 0

    # "hour % 12 or 12" is applied *after* the adjustment above, so "12:30 AM"
    # (hour 0) formats as 12 and sorts at 30 minutes past midnight.
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {period}", hour * 60 + minute


def parse_and_format_time(time_str):
    """
    Normalise a portal time slot for display, and reduce it to a sort key.

    Returns:
        tuple(str, int): (formatted, sortable). A slot with an end time is
        rendered "start - end"; a start-only slot is rendered as just the start.
    """
    if not time_str or (isinstance(time_str, str) and not time_str.strip()):
        return "", BLANK_TIME
    try:
        parts = re.split(r"\s*-\s*", time_str.strip())
        start_text, start_sortable = _format_one_time(parts[0])
        # Truthiness, not length: JS treated a missing *or empty* end as absent,
        # so "9:0 - " renders as a start-only slot.
        end_text = parts[1] if len(parts) > 1 else ""
        if end_text:
            end_formatted, _ = _format_one_time(end_text)
            formatted = f"{start_text} - {end_formatted}" if end_formatted else start_text
        else:
            formatted = start_text
        return formatted, start_sortable
    except Exception:
        # A non-string slot (e.g. a number in a hand-edited JSON) has no
        # .strip(). Deliberate divergence from Code.gs, where that case threw
        # out of the function: its `timeStr.trim()` guard on line 100 sat
        # *outside* the try block, so the intended catch never saw it. The
        # scraper always emits a string or null, so this only affects malformed
        # input - and reporting it as a blank-sorting slot beats crashing.
        return time_str, BLANK_TIME


def normalize_day(day):
    """Map a day cell to its sort key (1..7, else the missing/unknown sentinel)."""
    if isinstance(day, str) and day.strip():
        return DAY_ORDER.get(day.strip().upper(), UNKNOWN_DAY)
    return MISSING_DAY


def build_newmain_rows(entries):
    """
    Build the sorted, 12-hour-normalised rows for 'NewMain'.

    Reuses build_sheet_data (dropping its header row) and then rewrites the Time
    Slot column in place, so 'backend' and 'NewMain' cannot drift in column
    mapping - there is one definition of what a routine row is.

    Returns:
        list[list]: 8-column rows, sorted by (day, start time) and stable for
        ties. Empty when there is nothing to write.
    """
    all_rows = build_sheet_data(entries)
    if all_rows is None:
        return []

    decorated = []
    for row in all_rows[1:]:
        values = list(row)
        values[5], sortable = parse_and_format_time(values[5])
        decorated.append((normalize_day(values[3]), sortable, values))

    # Python's sort is stable, matching the JS Array.prototype.sort this was
    # ported from, so entries sharing a day and start time keep their order.
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [values for _, _, values in decorated]


def stamp_row_for(last_data_row):
    """Row for the footer stamp: two below the data, never inside the block."""
    return max(int(last_data_row or 0) + 2, STAMP_MIN_ROW)


def format_stamp(now):
    """Render the footer stamp: "Last Updated: <d Month, yyyy HH:mm>"."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    moment = now.astimezone(REPORT_TIMEZONE)
    return (
        f"{STAMP_PREFIX}{moment.day} {MONTHS[moment.month - 1]}, "
        f"{moment.year} {moment.hour:02d}:{moment.minute:02d}"
    )
