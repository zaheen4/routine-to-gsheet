import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gsheet_formatter as gf


# ----------------------------- load_routine_data -----------------------------

def test_load_routine_data_valid(tmp_path):
    data = [{"CourseCode": "CSE-3201", "Day": "Sun"}]
    path = tmp_path / "routine.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert gf.load_routine_data(str(path)) == data


def test_load_routine_data_missing_file(tmp_path):
    assert gf.load_routine_data(str(tmp_path / "nope.json")) == []


def test_load_routine_data_invalid_json(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text("not json", encoding="utf-8")
    assert gf.load_routine_data(str(path)) == []


def test_load_routine_data_empty_list(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text("[]", encoding="utf-8")
    assert gf.load_routine_data(str(path)) == []


# ----------------------------- combine_contact_info -----------------------------

def test_combine_contact_info_both_present():
    assert gf.combine_contact_info("123", "a@b.com") == "123\na@b.com"


def test_combine_contact_info_phone_only():
    assert gf.combine_contact_info("123", "") == "123"


def test_combine_contact_info_email_only():
    assert gf.combine_contact_info("", "a@b.com") == "a@b.com"


def test_combine_contact_info_neither():
    assert gf.combine_contact_info("", "") == ""


# ----------------------------- build_sheet_data -----------------------------

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
    rows = gf.build_sheet_data([_entry(), _entry(CourseCode="CSE-3212", Day="Wed")])
    assert rows[0] == gf.SHEET_HEADERS
    assert len(rows) == 3


def test_build_sheet_data_merges_contact_column():
    rows = gf.build_sheet_data([_entry()])
    assert rows[1][7] == "123\na@b.com"


def test_build_sheet_data_without_contact_uses_fallback():
    rows = gf.build_sheet_data([_entry(TeacherPhone="", TeacherEmail="")])
    assert rows[1][7] == ""


def test_build_sheet_data_invalid_returns_none():
    assert gf.build_sheet_data([]) is None
    assert gf.build_sheet_data("not a list") is None
    assert gf.build_sheet_data([["not", "dict"]]) is None


# ----------------------------- contact_column_letter -----------------------------

def test_contact_column_letter_is_h():
    assert gf.contact_column_letter() == "H"


# ----------------------------- get_or_create_worksheet -----------------------------

class _FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self.clear_called = False
        self.updated = None
        self.formatted = None

    def clear(self):
        self.clear_called = True

    def update(self, values, range_name):
        self.updated = (values, range_name)

    def format(self, rng, fmt):
        self.formatted = (rng, fmt)


class _FakeSpreadsheet:
    def __init__(self, existing=None, not_found=False):
        self._existing = existing or {}
        self.not_found = not_found
        self.created = []

    def worksheet(self, name):
        if name in self._existing:
            return self._existing[name]
        raise gf.gspread.exceptions.WorksheetNotFound(name)

    def add_worksheet(self, title, rows, cols):
        ws = _FakeWorksheet(title)
        self.created.append((title, rows, cols))
        return ws


def test_get_or_create_worksheet_returns_existing():
    ws = _FakeWorksheet("backend")
    ss = _FakeSpreadsheet(existing={"backend": ws})
    assert gf.get_or_create_worksheet(ss, "backend") is ws


def test_get_or_create_worksheet_creates_new():
    ss = _FakeSpreadsheet(not_found=True)
    ws = gf.get_or_create_worksheet(ss, "backend", rows=15, cols=10)
    assert ws is not None
    assert ("backend", 15, 10) in ss.created


# ----------------------------- write_data_to_sheet -----------------------------

def test_write_data_to_sheet_success():
    ws = _FakeWorksheet("backend")
    ok = gf.write_data_to_sheet(ws, [_entry()])
    assert ok is True
    assert ws.clear_called is True
    assert ws.updated is not None
    assert ws.updated[0][0] == gf.SHEET_HEADERS
    assert ws.formatted == ("H2:H2", {"wrapStrategy": "WRAP"})


def test_write_data_to_sheet_empty_returns_false():
    ws = _FakeWorksheet("backend")
    assert gf.write_data_to_sheet(ws, []) is False
    assert ws.clear_called is False


def test_write_data_to_sheet_invalid_returns_false():
    ws = _FakeWorksheet("backend")
    assert gf.write_data_to_sheet(ws, [["not", "dict"]]) is False