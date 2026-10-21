#!/usr/bin/env python3
"""Export the scraped routine to an RFC 5545 calendar file.

The output is meant to be imported into Google Calendar (or any CalDAV client):

* weekly ``VEVENT``s, one per routine slot;
* a single ``ACTION:DISPLAY`` alarm 30 minutes before each class;
* a proper ``VTIMEZONE`` (Asia/Dhaka is a fixed +0600 offset, no DST);
* CRLF line endings and 75-octet folding, per RFC 5545;
* stable UIDs, so re-importing a refreshed file updates events instead of
  duplicating them.

Only the standard library is used, so this stage adds no runtime dependency.

Usage::

    python ics_exporter.py --data output/routine_data.json --output output/routine.ics
"""

import argparse
import calendar
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import CALENDAR_TIMEZONE, OUTPUT_DIR, SEMESTER_END, setup_logging
from routine_format import parse_time_range_minutes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_OUTPUT_DIR_PATH = OUTPUT_DIR if os.path.isabs(OUTPUT_DIR) else os.path.join(BASE_DIR, OUTPUT_DIR)
DEFAULT_DATA_PATH = os.path.join(_OUTPUT_DIR_PATH, "routine_data.json")
DEFAULT_ICS_PATH = os.path.join(_OUTPUT_DIR_PATH, "routine.ics")

PRODID = "-//routine-to-gsheet//UCAM Routine Exporter//EN"
CALENDAR_NAME = "Class Routine"
ALARM_MINUTES = 30

DAY_TO_BYDAY = {
    "SAT": "SA",
    "SUN": "SU",
    "MON": "MO",
    "TUE": "TU",
    "WED": "WE",
    "THU": "TH",
    "FRI": "FR",
}
# Python's date.weekday(): Monday = 0.
DAY_TO_WEEKDAY = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}

log = logging.getLogger("ics_exporter")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_SEMESTER_LABEL_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s*[-\u2013\u2014]\s*"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def ics_escape(text):
    """Escape a TEXT value per RFC 5545 section 3.3.11."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def fold_line(line):
    """Fold a content line to at most 75 octets (RFC 5545 section 3.1).

    Continuation lines start with a single space. Splitting is done on UTF-8
    characters so multi-byte text is never cut in half.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    chunks = []
    start = 0
    first = True
    while start < len(encoded):
        limit = 75 if first else 74
        end = min(start + limit, len(encoded))
        # If the cut lands inside a multi-byte sequence, move back to its start.
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[start:end].decode("utf-8"))
        start = end
        first = False
    return "\r\n ".join(chunks)


def _render(lines):
    return "".join(fold_line(line) + "\r\n" for line in lines)


def _format_offset(offset):
    """Render a ``timedelta`` UTC offset as ``+HHMM`` / ``-HHMM``."""
    minutes = int((offset or timedelta(0)).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return "%s%02d%02d" % (sign, hours, remainder)


def _timezone_info(timezone_name, reference):
    try:
        tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown timezone %r: %s" % (timezone_name, exc)) from exc
    local_reference = reference.astimezone(tz)
    offset = _format_offset(local_reference.utcoffset())
    return tz, offset


def build_vtimezone(timezone_name, reference):
    """Emit a fixed-offset VTIMEZONE.

    The pipeline's schedules are in Asia/Dhaka, which never observes DST, so a
    single STANDARD block with identical FROM/TO offsets is exact.
    """
    _tz, offset = _timezone_info(timezone_name, reference)
    return [
        "BEGIN:VTIMEZONE",
        "TZID:%s" % timezone_name,
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:%s" % offset,
        "TZOFFSETTO:%s" % offset,
        "TZNAME:%s" % offset,
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------


def normalize_day(day):
    return str(day or "").strip().upper()


def next_occurrence(day, reference):
    """First date on/after ``reference`` that falls on ``day`` (e.g. "Mon")."""
    weekday = DAY_TO_WEEKDAY[normalize_day(day)]
    return reference + timedelta(days=(weekday - reference.weekday()) % 7)


def stable_uid(entry):
    """Deterministic UID, so a refreshed import updates instead of duplicating."""
    def slug(value):
        return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")

    start, _end = parse_time_range_minutes(entry.get("TimeSlot", ""))
    if start is None:
        raise ValueError("Cannot build a UID without a start time: %r" % entry.get("TimeSlot"))
    start_stamp = "%02d%02d00" % (start // 60, start % 60)
    return "%s-%s-%s-%s@routine-to-gsheet" % (
        slug(entry.get("CourseCode")),
        slug(entry.get("Section")),
        slug(entry.get("Day")),
        start_stamp,
    )


def semester_end_from_string(semester):
    """Derive the last day of the semester from a label like "January-July 2026"."""
    if not semester:
        return None
    match = _SEMESTER_LABEL_RE.search(str(semester))
    if not match:
        return None
    end_month = _MONTHS[match.group(2).lower()]
    year = int(match.group(3))
    return date(year, end_month, calendar.monthrange(year, end_month)[1])


def resolve_semester_end(explicit, semester):
    """Prefer the explicit ISO date, else derive it from the semester label."""
    if explicit:
        try:
            return date.fromisoformat(str(explicit))
        except ValueError as exc:
            raise ValueError(
                "SEMESTER_END must be an ISO date (YYYY-MM-DD), got %r" % (explicit,)
            ) from exc
    return semester_end_from_string(semester)


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local_stamp(day, minutes):
    hour, minute = divmod(minutes, 60)
    return "%sT%02d%02d00" % (day.strftime("%Y%m%d"), hour, minute)


def build_event(entry, *, reference_date, timezone_name, semester_end, dtstamp):
    """Build one ``VEVENT`` block, or ``None`` when the slot is unusable."""
    day_key = normalize_day(entry.get("Day"))
    if day_key not in DAY_TO_BYDAY:
        log.warning("Skipping entry with unknown day %r: %s",
                    entry.get("Day"), entry.get("CourseCode"))
        return None

    start, end = parse_time_range_minutes(entry.get("TimeSlot", ""))
    if start is None:
        log.warning("Skipping entry with unparseable time %r: %s",
                    entry.get("TimeSlot"), entry.get("CourseCode"))
        return None
    if end is None or end <= start:
        # The report always has an end; a missing one should not drop the class.
        end = start + 60

    first_date = next_occurrence(day_key, reference_date)
    summary = "%s: %s" % (entry.get("CourseCode", ""), entry.get("CourseTitle", ""))
    summary = summary.strip().rstrip(":")

    lines = [
        "BEGIN:VEVENT",
        "UID:%s" % stable_uid(entry),
        "DTSTAMP:%s" % _stamp(dtstamp),
        "DTSTART;TZID=%s:%s" % (timezone_name, _local_stamp(first_date, start)),
        "DTEND;TZID=%s:%s" % (timezone_name, _local_stamp(first_date, end)),
    ]

    rrule = "RRULE:FREQ=WEEKLY;BYDAY=%s" % DAY_TO_BYDAY[day_key]
    if semester_end is not None and semester_end >= first_date:
        rrule += ";UNTIL=%sT235959Z" % semester_end.strftime("%Y%m%d")
    elif semester_end is not None:
        log.warning(
            "Semester end %s is before the first event (%s); omitting UNTIL so the "
            "calendar still renders.", semester_end, first_date,
        )
    lines.append(rrule)

    lines.append("SUMMARY:%s" % ics_escape(summary))
    room = str(entry.get("Room") or "").strip()
    if room:
        lines.append("LOCATION:%s" % ics_escape(room))
    contact = "\n".join(
        part for part in (
            entry.get("Teacher"),
            entry.get("TeacherPhone"),
            entry.get("TeacherEmail"),
        ) if part
    )
    if contact:
        lines.append("DESCRIPTION:%s" % ics_escape(contact))
    lines.append("STATUS:CONFIRMED")
    lines.extend([
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:%s" % ics_escape("%s in %d minutes" % (summary, ALARM_MINUTES)),
        "TRIGGER:-PT%dM" % ALARM_MINUTES,
        "END:VALARM",
        "END:VEVENT",
    ])
    return lines


def generate_ics(entries, *, semester=None, timezone_name=CALENDAR_TIMEZONE,
                 semester_end=None, now=None):
    """Render all entries into one calendar document.

    Raises:
        ValueError: when no entry yields a usable event.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    tz, _offset = _timezone_info(timezone_name, moment)
    reference_date = moment.astimezone(tz).date()
    resolved_end = resolve_semester_end(semester_end, semester)

    # Warn once (not once per event) when the whole semester is already over.
    effective_end = resolved_end
    if resolved_end is not None:
        first_dates = [
            next_occurrence(entry.get("Day"), reference_date)
            for entry in entries
            if normalize_day(entry.get("Day")) in DAY_TO_WEEKDAY
        ]
        if first_dates and resolved_end < min(first_dates):
            log.warning(
                "Semester end %s is before the first event (%s); omitting UNTIL so "
                "the calendar still renders.", resolved_end, min(first_dates),
            )
            effective_end = None

    dtstamp = moment.astimezone(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:%s" % PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:%s" % ics_escape(semester or CALENDAR_NAME),
        "X-WR-TIMEZONE:%s" % timezone_name,
    ]
    lines.extend(build_vtimezone(timezone_name, moment))

    events = 0
    for entry in entries:
        event = build_event(
            entry,
            reference_date=reference_date,
            timezone_name=timezone_name,
            semester_end=effective_end,
            dtstamp=dtstamp,
        )
        if event:
            lines.extend(event)
            events += 1

    if not events:
        raise ValueError("No usable events in the routine data.")

    lines.append("END:VCALENDAR")
    return _render(lines)


# ---------------------------------------------------------------------------
# I/O and CLI
# ---------------------------------------------------------------------------


def load_routine_data(path):
    """Return ``(entries, semester, generated_at)`` from a manifest or list."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("'%s' has no 'entries' list." % path)
        return entries, data.get("semester"), data.get("generated_at")
    if isinstance(data, list):
        return data, None, None
    raise ValueError("Unsupported payload in '%s'." % path)


def write_ics(path, text):
    """Write CRLF content without newline translation."""
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export the routine to an .ics calendar.")
    parser.add_argument("--data", default=DEFAULT_DATA_PATH,
                        help="Routine manifest (default: %(default)s)")
    parser.add_argument("--output", default=DEFAULT_ICS_PATH,
                        help="ICS destination (default: %(default)s)")
    parser.add_argument("--timezone", default=CALENDAR_TIMEZONE,
                        help="Calendar timezone (default: %(default)s)")
    parser.add_argument("--semester-end", default=SEMESTER_END,
                        help="Last day of the semester, YYYY-MM-DD (default: derived)")
    args = parser.parse_args(argv if argv is not None else [])

    setup_logging()
    try:
        entries, semester, generated_at = load_routine_data(args.data)
    except (OSError, ValueError) as exc:
        log.error("Could not read routine data: %s", exc)
        return 1

    if not entries:
        log.error("Routine data is empty; nothing to export.")
        return 1

    try:
        text = generate_ics(
            entries,
            semester=semester,
            timezone_name=args.timezone,
            semester_end=args.semester_end,
            now=_manifest_moment(generated_at),
        )
    except ValueError as exc:
        log.error("Could not build the calendar: %s", exc)
        return 1

    try:
        write_ics(args.output, text)
    except OSError as exc:
        log.error("Could not write '%s': %s", args.output, exc)
        return 1

    log.info("Wrote %d events to '%s'.", text.count("BEGIN:VEVENT"), args.output)
    return 0


def _manifest_moment(generated_at):
    """Use the scrape time as ``now`` when available (keeps output reproducible)."""
    if not generated_at:
        return None
    try:
        normalized = generated_at.replace("Z", "+00:00")
        moment = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
