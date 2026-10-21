"""Tests for the stdlib ICS exporter."""

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ics_exporter as ie

NOW = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Monday


def _entry(code="CSE-4101", title="Artificial Intelligence", day="Mon",
           slot="9:15 AM - 10:30 AM", section="B", room="120",
           teacher="UKD_Utpol Kanti Das", phone="01859222633",
           email="ukdas@niter.edu.bd"):
    return {
        "CourseCode": code,
        "CourseTitle": title,
        "Teacher": teacher,
        "TeacherPhone": phone,
        "TeacherEmail": email,
        "Day": day,
        "Room": room,
        "TimeSlot": slot,
        "Section": section,
    }


def _unwrap(text):
    return text.replace("\r\n ", "")


# ----------------------------- escaping and folding -----------------------------

def test_ics_escape_escapes_rfc5545_specials():
    assert ie.ics_escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"


def test_fold_line_keeps_each_line_within_75_octets():
    folded = ie.fold_line("SUMMARY:" + "A" * 200)
    parts = folded.split("\r\n")
    assert all(len(part.encode("utf-8")) <= 75 for part in parts)
    assert parts[0].startswith("SUMMARY:")
    assert all(part.startswith(" ") for part in parts[1:])
    assert _unwrap(folded) == "SUMMARY:" + "A" * 200


def test_fold_line_does_not_split_multibyte_characters():
    folded = ie.fold_line("DESCRIPTION:" + "\u0985" * 100)
    assert _unwrap(folded) == "DESCRIPTION:" + "\u0985" * 100
    folded.encode("utf-8").decode("utf-8")  # every chunk is valid UTF-8


# ----------------------------- semester end -----------------------------

def test_semester_end_from_label():
    assert ie.semester_end_from_string(
        "2024-2025 Level 4 Term 1 January-July 2026"
    ) == date(2026, 7, 31)


def test_semester_end_from_label_is_case_insensitive():
    assert ie.semester_end_from_string("january-december 2027") == date(2027, 12, 31)


def test_semester_end_unknown_label_returns_none():
    assert ie.semester_end_from_string("Level 4 Term 1") is None


def test_resolve_semester_end_prefers_explicit_iso_date():
    assert ie.resolve_semester_end("2026-06-30", "January-July 2026") == date(2026, 6, 30)


def test_resolve_semester_end_rejects_bad_explicit_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        ie.resolve_semester_end("30/06/2026", None)


# ----------------------------- event shape -----------------------------

def test_generate_ics_has_crlf_and_one_alarm_per_event():
    text = ie.generate_ics(
        [_entry(), _entry(code="CSE-4108", title="Networks", day="Wed",
                          slot="1:30 PM - 4:0 PM")],
        semester="January-July 2026",
        semester_end=date(2026, 7, 31),
        now=NOW,
    )

    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == 2
    assert text.count("BEGIN:VALARM") == text.count("END:VALARM") == 2
    assert text.count("ACTION:DISPLAY") == 2
    assert text.count("TRIGGER:-PT30M") == 2


def test_generate_ics_emits_byday_timezone_and_until():
    text = ie.generate_ics(
        [_entry(day="Mon"), _entry(code="CSE-4108", title="Networks", day="Wed")],
        semester="January-July 2026",
        semester_end=date(2026, 7, 31),
        now=NOW,
    )
    unfolded = _unwrap(text)

    assert "BEGIN:VTIMEZONE" in unfolded
    assert "TZID:Asia/Dhaka" in unfolded
    assert "TZOFFSETTO:+0600" in unfolded
    assert "DTSTART;TZID=Asia/Dhaka:20260105T091500" in unfolded
    assert "DTSTART;TZID=Asia/Dhaka:20260107T091500" in unfolded
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260731T235959Z" in unfolded
    assert "RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL=20260731T235959Z" in unfolded


def test_generate_ics_omits_until_when_semester_is_already_over():
    text = _unwrap(ie.generate_ics(
        [_entry()],
        semester="January-July 2025",
        semester_end=date(2025, 12, 31),
        now=NOW,
    ))
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO\r\n" in text
    assert "UNTIL=" not in text


def test_generate_ics_includes_summary_location_and_contact():
    text = _unwrap(ie.generate_ics([_entry()], semester="S", now=NOW))
    assert "SUMMARY:CSE-4101: Artificial Intelligence" in text
    assert "LOCATION:120" in text
    assert "DESCRIPTION:UKD_Utpol Kanti Das\\n01859222633\\nukdas@niter.edu.bd" in text


def test_uid_is_stable_and_section_aware():
    first = ie.stable_uid(_entry())
    assert first == ie.stable_uid(_entry())
    assert first != ie.stable_uid(_entry(section="B2"))
    assert first == "cse-4101-b-mon-091500@routine-to-gsheet"


def test_generate_ics_is_reproducible_for_a_fixed_now():
    one = ie.generate_ics([_entry()], semester="S", now=NOW)
    two = ie.generate_ics([_entry()], semester="S", now=NOW)
    assert one == two


def test_generate_ics_skips_unparseable_slots():
    text = _unwrap(ie.generate_ics(
        [_entry(), _entry(code="CSE-9999", title="Broken", slot="TBA")],
        semester="S",
        now=NOW,
    ))
    assert text.count("BEGIN:VEVENT") == 1
    assert "CSE-9999" not in text


def test_generate_ics_raises_when_nothing_is_usable():
    with pytest.raises(ValueError, match="No usable events"):
        ie.generate_ics([_entry(slot="")], semester="S", now=NOW)


def test_missing_end_time_defaults_to_one_hour():
    text = _unwrap(ie.generate_ics([_entry(slot="9:15 AM")], semester="S", now=NOW))
    assert "DTSTART;TZID=Asia/Dhaka:20260105T091500" in text
    assert "DTEND;TZID=Asia/Dhaka:20260105T101500" in text


def test_next_occurrence_includes_today():
    assert ie.next_occurrence("Mon", date(2026, 1, 5)) == date(2026, 1, 5)
    assert ie.next_occurrence("Wed", date(2026, 1, 5)) == date(2026, 1, 7)


# ----------------------------- I/O and CLI -----------------------------

def test_write_ics_writes_crlf_without_translation(tmp_path):
    path = tmp_path / "routine.ics"
    ie.write_ics(str(path), "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    raw = path.read_bytes()
    assert raw == b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"


def test_main_exports_and_reports_success(tmp_path):
    data = tmp_path / "routine_data.json"
    output = tmp_path / "routine.ics"
    data.write_text(json.dumps({
        "generated_at": "2026-01-05T00:00:00Z",
        "semester": "January-July 2026",
        "entries": [_entry()],
    }), encoding="utf-8")

    assert ie.main(["--data", str(data), "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert text.count("BEGIN:VEVENT") == 1
    assert "UNTIL=20260731T235959Z" in _unwrap(text)


def test_main_returns_nonzero_for_empty_entries(tmp_path):
    data = tmp_path / "routine_data.json"
    data.write_text(json.dumps({"entries": []}), encoding="utf-8")
    assert ie.main(["--data", str(data), "--output", str(tmp_path / "out.ics")]) == 1


def test_main_returns_nonzero_for_missing_file(tmp_path):
    assert ie.main(["--data", str(tmp_path / "nope.json"),
                    "--output", str(tmp_path / "out.ics")]) == 1


def test_load_routine_data_accepts_legacy_list(tmp_path):
    data = tmp_path / "legacy.json"
    data.write_text(json.dumps([_entry()]), encoding="utf-8")
    entries, semester, generated_at = ie.load_routine_data(str(data))
    assert len(entries) == 1
    assert semester is None
    assert generated_at is None
