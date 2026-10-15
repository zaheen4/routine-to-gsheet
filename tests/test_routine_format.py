"""Tests for routine_format: the ported Code.gs sort/format behaviour.

These cases are the acceptance criteria for the port. They started life as the
17-case node:test suite against apps_script/Code.gs; the behaviours that were
pure data transformation moved here, and the ones that only made sense against a
live sheet (clearing the old block, the empty-backend notice) moved to the
writer tests in test_gsheet_formatter.py.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routine_format as rf

# ----------------------------- row shape: combine_contact_info -----------------------------

def test_combine_contact_info_both_present():
    assert rf.combine_contact_info("123", "a@b.com") == "123\na@b.com"


def test_combine_contact_info_phone_only():
    assert rf.combine_contact_info("123", "") == "123"


def test_combine_contact_info_email_only():
    assert rf.combine_contact_info("", "a@b.com") == "a@b.com"


def test_combine_contact_info_neither():
    assert rf.combine_contact_info("", "") == ""


# ----------------------------- row shape: build_sheet_data -----------------------------

def _entry(**overrides):
    base = {
        "CourseCode": "CSE-3201",
        "CourseTitle": "Operating Systems",
        "Section": "B",
        "Day": "Sun",
        "Room": "120",
        "TimeSlot": "11:0 - 12:15",
        "Teacher": "SS",
        "TeacherPhone": "123",
        "TeacherEmail": "a@b.com",
    }
    base.update(overrides)
    return base


def test_build_sheet_data_header_and_rows():
    rows = rf.build_sheet_data([_entry(), _entry(CourseCode="CSE-3212", Day="Wed")])
    assert rows[0] == rf.SHEET_HEADERS
    assert len(rows) == 3


def test_build_sheet_data_merges_contact_column():
    rows = rf.build_sheet_data([_entry()])
    assert rows[1][7] == "123\na@b.com"


def test_build_sheet_data_without_contact_uses_fallback():
    rows = rf.build_sheet_data([_entry(TeacherPhone="", TeacherEmail="")])
    assert rows[1][7] == ""


def test_build_sheet_data_invalid_returns_none():
    assert rf.build_sheet_data([]) is None
    assert rf.build_sheet_data("not a list") is None
    assert rf.build_sheet_data([["not", "dict"]]) is None


# ----------------------------- row shape: contact_column_letter -----------------------------

def test_contact_column_letter_is_h():
    assert rf.contact_column_letter() == "H"


# ----------------------------- parse_and_format_time -----------------------------

def test_parse_and_format_time_normalises_a_portal_slot_without_ampm():
    # The portal emits no period at all; 07:00-11:59 is inferred AM, the rest PM.
    assert rf.parse_and_format_time("11:45 - 1:0") == ("11:45 AM - 1:00 PM", 705)


def test_parse_and_format_time_handles_a_single_time():
    assert rf.parse_and_format_time("9:0") == ("9:00 AM", 540)


def test_parse_and_format_time_keeps_an_explicit_period():
    assert rf.parse_and_format_time("2:30 PM - 4:00 PM") == ("2:30 PM - 4:00 PM", 870)


def test_parse_and_format_time_treats_12xx_as_noon():
    assert rf.parse_and_format_time("12:0 - 12:50") == ("12:00 PM - 12:50 PM", 720)


def test_parse_and_format_time_treats_12xx_am_as_midnight():
    # 12:30 AM is hour 0: it must format as 12 (not 0) and sort at 30 minutes.
    assert rf.parse_and_format_time("12:30 AM") == ("12:30 AM", 30)


def test_parse_and_format_time_returns_an_empty_slot_for_blank_input():
    for blank in ["", "   ", None]:
        assert rf.parse_and_format_time(blank) == ("", rf.BLANK_TIME)
    assert rf.BLANK_TIME == 99999


def test_parse_and_format_time_passes_unparseable_text_through_sorting_last():
    assert rf.parse_and_format_time("TBA") == ("TBA", rf.UNPARSEABLE_TIME)
    assert rf.UNPARSEABLE_TIME == 99998


def test_parse_and_format_time_treats_an_empty_end_as_absent():
    # The JS falsy-string trap: "9:0 - " split into ["9:0", ""], and the empty
    # second part meant "no end time", *not* an unparseable one.
    assert rf.parse_and_format_time("9:0 - ") == ("9:00 AM", 540)


def test_parse_and_format_time_zero_pads_minutes_and_reports_start_for_sorting():
    # Sorting uses the start time only, even when an end time is present.
    assert rf.parse_and_format_time("10:5 - 12:0") == ("10:05 AM - 12:00 PM", 605)


def test_parse_and_format_time_tolerates_a_non_string_slot():
    # Deliberate divergence from Code.gs: its `timeStr.trim()` guard sat outside
    # the try block, so a non-string slot threw instead of being caught. The
    # scraper never produces one; a malformed JSON should not crash the run.
    assert rf.parse_and_format_time(5) == (5, rf.BLANK_TIME)


def test_parse_and_format_time_keeps_garbage_in_a_slot_with_an_end_time():
    # Only the *start* token decides the sort key; an unparseable end is passed
    # through verbatim next to a perfectly good start.
    assert rf.parse_and_format_time("9:0 - xyz") == ("9:00 AM - xyz", 540)


# ----------------------------- normalize_day -----------------------------

def test_normalize_day_maps_each_weekday():
    for day, expected in rf.DAY_ORDER.items():
        assert rf.normalize_day(day) == expected
        assert rf.normalize_day(day.lower()) == expected
        assert rf.normalize_day(f"  {day}  ") == expected


def test_normalize_day_blank_or_non_string_is_the_missing_sentinel():
    for blank in ["", "   ", None]:
        assert rf.normalize_day(blank) == rf.MISSING_DAY
    assert rf.MISSING_DAY == 998


def test_normalize_day_unrecognised_is_the_unknown_sentinel():
    assert rf.normalize_day("Funday") == rf.UNKNOWN_DAY
    assert rf.UNKNOWN_DAY == 999


# ----------------------------- build_newmain_rows -----------------------------

def _courses(rows):
    return [row[0] for row in rows]


def test_build_newmain_rows_sorts_by_day_and_time():
    rows = rf.build_newmain_rows([
        _entry(CourseCode="CSE-3201", Day="Wed", TimeSlot="11:0 - 12:15"),
        _entry(CourseCode="CSE-3202", Day="Sat", TimeSlot="9:0 - 10:20"),
        _entry(CourseCode="CSE-3203", Day="Wed", TimeSlot="8:30 - 9:50"),
    ])
    assert _courses(rows) == ["CSE-3202", "CSE-3203", "CSE-3201"]
    assert [row[5] for row in rows] == [
        "9:00 AM - 10:20 AM",
        "8:30 AM - 9:50 AM",
        "11:00 AM - 12:15 PM",
    ]
    assert all(len(row) == rf.DATA_WIDTH for row in rows)


def test_build_newmain_rows_drops_the_header_row():
    rows = rf.build_newmain_rows([_entry()])
    assert len(rows) == 1
    assert rows[0][0] == "CSE-3201"


def test_build_newmain_rows_keeps_the_contact_column():
    rows = rf.build_newmain_rows([_entry()])
    assert rows[0][7] == "123\na@b.com"
    assert rows[0][3] == "Sun"


def test_build_newmain_rows_sorts_unknown_or_missing_days_last():
    rows = rf.build_newmain_rows([
        _entry(CourseCode="CSE-3201", Day="", TimeSlot="1:0 - 2:0"),       # missing -> 998
        _entry(CourseCode="CSE-3202", Day="Mon", TimeSlot="9:0 - 10:0"),   # Monday -> 3
        _entry(CourseCode="CSE-3203", Day="Funday", TimeSlot="9:0 - 10:0"),  # unknown -> 999
    ])
    # A recognised day first, then the blank day, then the unrecognised one.
    assert _courses(rows) == ["CSE-3202", "CSE-3201", "CSE-3203"]


def test_build_newmain_rows_orders_ties_within_a_day_by_start_time():
    rows = rf.build_newmain_rows([
        _entry(CourseCode="CSE-3201", Day="Sun", TimeSlot="2:0 - 3:0"),
        _entry(CourseCode="CSE-3202", Day="Sun", TimeSlot="10:0 - 11:0"),
        _entry(CourseCode="CSE-3203", Day="Sun", TimeSlot=""),
    ])
    # 10:00 AM (600) < 2:00 PM (840) < blank (99999).
    assert _courses(rows) == ["CSE-3202", "CSE-3201", "CSE-3203"]


def test_build_newmain_rows_is_stable_for_equal_day_and_time():
    rows = rf.build_newmain_rows([
        _entry(CourseCode="FIRST", Day="Sun", TimeSlot="9:0 - 10:0"),
        _entry(CourseCode="SECOND", Day="Sun", TimeSlot="9:0 - 10:0"),
        _entry(CourseCode="THIRD", Day="Sun", TimeSlot="9:0 - 10:0"),
    ])
    assert _courses(rows) == ["FIRST", "SECOND", "THIRD"]


def test_build_newmain_rows_empty_or_invalid_is_empty_list():
    assert rf.build_newmain_rows([]) == []
    assert rf.build_newmain_rows("not a list") == []
    assert rf.build_newmain_rows([["not", "dict"]]) == []


def test_build_newmain_rows_unknown_days_do_not_crash_the_sort():
    rows = rf.build_newmain_rows([
        _entry(CourseCode="A", Day="Mon", TimeSlot=""),
        _entry(CourseCode="B", Day=None, TimeSlot=None),
    ])
    assert _courses(rows) == ["A", "B"]


# ----------------------------- stamp placement -----------------------------

def test_stamp_row_stays_below_the_data_for_every_routine_size():
    # 1..100 rows: the stamp and signature must never land inside the B..I data
    # block. The old fixed I24/I25 cells did exactly that past 20 rows.
    for row_count in [1, 5, 16, 20, 21, 30, 100]:
        last_data_row = rf.DATA_START_ROW + row_count - 1
        stamp_row = rf.stamp_row_for(last_data_row)
        signature_row = stamp_row + 1

        assert stamp_row == last_data_row + 2
        assert signature_row == last_data_row + 3
        inside_block = rf.DATA_START_ROW <= stamp_row <= last_data_row
        assert inside_block is False
        assert stamp_row >= rf.STAMP_MIN_ROW


def test_stamp_row_sits_below_the_no_data_notice():
    # The notice occupies B4, so the stamp still starts at row 6.
    assert rf.stamp_row_for(rf.DATA_START_ROW) == 6


def test_stamp_row_tolerates_a_missing_last_row():
    assert rf.stamp_row_for(None) == rf.STAMP_MIN_ROW


# ----------------------------- format_stamp -----------------------------

def test_format_stamp_uses_the_fixed_gmt_plus_6_offset():
    # 13:00 UTC is 19:00 in the fixed report timezone.
    now = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    assert rf.format_stamp(now) == "Last Updated: 15 October, 2026 19:00"


def test_format_stamp_treats_a_naive_datetime_as_utc():
    assert rf.format_stamp(datetime(2026, 10, 15, 13, 0)) == rf.format_stamp(
        datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    )


def test_format_stamp_rolls_over_the_year_at_the_offset():
    # 20:00 UTC on New Year's Eve is 02:00 the next year in GMT+6. Also covers
    # the missing leading zero on the day, the month name, and 24-hour padding.
    now = datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert rf.format_stamp(now) == "Last Updated: 1 January, 2027 02:00"


def test_format_stamp_names_every_month_in_english():
    # Explicit month tuple, not strftime("%B"): the stamp must not drift with
    # the process locale.
    for month_number, name in enumerate(rf.MONTHS, start=1):
        now = datetime(2027, month_number, 9, 6, 0, tzinfo=timezone.utc)
        assert rf.format_stamp(now) == f"Last Updated: 9 {name}, 2027 12:00"


def test_format_stamp_accepts_non_utc_aware_datetimes():
    # An offset anything like +06:00 maps to itself in the fixed timezone.
    now = datetime(2026, 10, 15, 19, 0, tzinfo=timezone(timedelta(hours=6)))
    assert rf.format_stamp(now) == "Last Updated: 15 October, 2026 19:00"
