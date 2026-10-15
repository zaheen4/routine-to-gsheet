import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gsheet_formatter as gf
import routine_format as rf

# ----------------------------- credential path anchoring -----------------------------

def test_credential_paths_are_anchored_to_the_project_root():
    # Relative paths would resolve against the current working directory, so a
    # run from anywhere other than the project root would look for (and fail to
    # find) the service account key somewhere else.
    for path in (
        gf.GOOGLE_SERVICE_ACCOUNT_KEY_FILE,
        gf.SCRAPED_DATA_JSON_PATH,
    ):
        assert os.path.isabs(path), path
        assert path.startswith(gf.BASE_DIR + os.sep), path


# ----------------------------- load_routine_data -----------------------------

def test_load_routine_data_valid(tmp_path):
    data = [{"CourseCode": "CSE-3201", "Day": "Sun"}]
    path = tmp_path / "routine.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert gf.load_routine_data(str(path)) == (data, None)


def test_load_routine_data_manifest(tmp_path):
    payload = {
        "generated_at": "2026-10-15T10:00:00Z",
        "semester": "Fall 2026",
        "accounts": [],
        "entries": [{"CourseCode": "CSE-3201"}],
    }
    path = tmp_path / "routine.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert gf.load_routine_data(str(path)) == (
        payload["entries"], payload["generated_at"])


def test_load_routine_data_manifest_without_entries(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text(json.dumps({"generated_at": "2026-10-15T10:00:00Z"}), encoding="utf-8")
    assert gf.load_routine_data(str(path)) == ([], None)


def test_load_routine_data_unsupported_payload(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text(json.dumps("nope"), encoding="utf-8")
    assert gf.load_routine_data(str(path)) == ([], None)


def test_load_routine_data_missing_file(tmp_path):
    assert gf.load_routine_data(str(tmp_path / "nope.json")) == ([], None)


def test_load_routine_data_invalid_json(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text("not json", encoding="utf-8")
    assert gf.load_routine_data(str(path)) == ([], None)


def test_load_routine_data_empty_list(tmp_path):
    path = tmp_path / "routine.json"
    path.write_text("[]", encoding="utf-8")
    assert gf.load_routine_data(str(path)) == ([], None)


# ----------------------------- data_age_hours -----------------------------

def test_data_age_hours_none_without_timestamp():
    assert gf.data_age_hours(None) is None
    assert gf.data_age_hours("") is None


def test_data_age_hours_unparseable():
    assert gf.data_age_hours("last tuesday") is None


def test_data_age_hours_fresh():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = gf.data_age_hours(now)
    assert age is not None
    assert age < 0.1


def test_data_age_hours_old():
    stamp = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = gf.data_age_hours(stamp)
    assert age > 71



# ----------------------------- shared test entries -----------------------------

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


# ----------------------------- get_or_create_worksheet -----------------------------

class _FakeWorksheet:
    def __init__(self, title, row_count=1000, col_count=26):
        self.title = title
        self.row_count = row_count
        self.col_count = col_count
        self.clear_called = False
        self.updated = None
        self.formatted = None
        self.updates = []
        self.batch_cleared = None
        self.resized = None

    def clear(self):
        self.clear_called = True

    def update(self, values, range_name=None, **kwargs):
        self.updated = (values, range_name)
        self.updates.append((values, range_name, kwargs))

    def format(self, rng, fmt):
        self.formatted = (rng, fmt)

    def batch_clear(self, ranges):
        self.batch_cleared = list(ranges)

    def resize(self, rows=None, cols=None):
        self.resized = (rows, cols)
        if rows is not None:
            self.row_count = rows
        if cols is not None:
            self.col_count = cols


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
        ws = _FakeWorksheet(title, row_count=rows, col_count=cols)
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


def test_get_or_create_worksheet_seeds_headers_on_create():
    ss = _FakeSpreadsheet(not_found=True)
    ws = gf.get_or_create_worksheet(ss, "NewMain", rows=30, cols=10, seed_headers=True)
    assert ws is not None
    assert ("NewMain", 30, 10) in ss.created
    assert ws.updated == ([rf.SHEET_HEADERS], 'B3')
    assert ws.formatted == ("B3:I3", {'textFormat': {'bold': True}})


def test_get_or_create_worksheet_existing_does_not_overwrite():
    ws = _FakeWorksheet("NewMain")
    ss = _FakeSpreadsheet(existing={"NewMain": ws})
    result = gf.get_or_create_worksheet(ss, "NewMain", seed_headers=True)
    assert result is ws
    assert ws.updated is None
    assert ws.formatted is None


# ----------------------------- grow_worksheet (the grid-limits guard) -----------------------------

def test_grow_worksheet_resizes_when_the_routine_outgrew_the_sheet():
    # A sheet sized for a 25-row routine, now asked to hold 40: without this the
    # write fails with "Range exceeds grid limits".
    ws = _FakeWorksheet("NewMain", row_count=30, col_count=10)
    gf.grow_worksheet(ws, min_rows=46, min_cols=9)
    assert ws.resized == (46, 10)
    assert ws.row_count == 46


def test_grow_worksheet_is_a_noop_when_the_sheet_is_already_big_enough():
    ws = _FakeWorksheet("NewMain", row_count=1000, col_count=26)
    gf.grow_worksheet(ws, min_rows=46, min_cols=9)
    assert ws.resized is None


def test_grow_worksheet_never_shrinks_a_worksheet():
    # Extra rows/columns may have been added deliberately to the sheet.
    ws = _FakeWorksheet("backend", row_count=500, col_count=20)
    gf.grow_worksheet(ws, min_rows=10, min_cols=8)
    assert ws.resized is None
    assert ws.row_count == 500
    assert ws.col_count == 20


def test_grow_worksheet_grows_columns_independently():
    ws = _FakeWorksheet("NewMain", row_count=1000, col_count=5)
    gf.grow_worksheet(ws, min_rows=10, min_cols=9)
    assert ws.resized == (1000, 9)


def test_get_or_create_worksheet_grows_an_existing_sheet():
    ws = _FakeWorksheet("NewMain", row_count=30, col_count=10)
    ss = _FakeSpreadsheet(existing={"NewMain": ws})
    assert gf.get_or_create_worksheet(ss, "NewMain", min_rows=46, min_cols=9) is ws
    assert ws.resized == (46, 10)


# ----------------------------- write_data_to_sheet -----------------------------

def test_write_data_to_sheet_success():
    ws = _FakeWorksheet("backend")
    ok = gf.write_data_to_sheet(ws, [_entry()])
    assert ok is True
    assert ws.clear_called is True
    assert ws.updated is not None
    assert ws.updated[0][0] == rf.SHEET_HEADERS
    assert ws.formatted == ("H2:H2", {"wrapStrategy": "WRAP"})


def test_write_data_to_sheet_empty_returns_false():
    ws = _FakeWorksheet("backend")
    assert gf.write_data_to_sheet(ws, []) is False
    assert ws.clear_called is False


def test_write_data_to_sheet_invalid_returns_false():
    ws = _FakeWorksheet("backend")
    assert gf.write_data_to_sheet(ws, [["not", "dict"]]) is False


# ----------------------------- write_newmain_sheet -----------------------------

_STAMP_NOW = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
_EXPECTED_STAMP = "Last Updated: 15 October, 2026"


def test_write_newmain_sheet_writes_sorted_rows_as_raw_at_b4():
    ws = _FakeWorksheet("NewMain")
    entries = [
        _entry(CourseCode="CSE-3201", Day="Wed", TimeSlot="11:0 - 12:15"),
        _entry(CourseCode="CSE-3202", Day="Sat", TimeSlot="9:0 - 10:20"),
    ]
    assert gf.write_newmain_sheet(ws, entries, now=_STAMP_NOW) is True

    values, range_name, kwargs = ws.updates[0]
    assert range_name == "B4"
    # RAW matches how 'backend' is written; without it NewMain would inherit
    # Sheets' own coercion and the two sheets could disagree.
    assert kwargs == {"value_input_option": "RAW"}
    assert [row[0] for row in values] == ["CSE-3202", "CSE-3201"]
    assert values[0][5] == "9:00 AM - 10:20 AM"
    assert all(len(row) == rf.DATA_WIDTH for row in values)


def test_write_newmain_sheet_clears_content_without_losing_formatting():
    ws = _FakeWorksheet("NewMain")
    gf.write_newmain_sheet(ws, [_entry()], now=_STAMP_NOW)
    # batch_clear touches content only: a manual styling pass on the sheet
    # survives, whereas worksheet.clear() would wipe the formats too.
    assert ws.batch_cleared == ["B4:I1000"]
    assert ws.clear_called is False


def test_write_newmain_sheet_stamps_below_the_data_in_the_last_column():
    ws = _FakeWorksheet("NewMain")
    entries = [_entry(CourseCode=f"CSE-{n}", Day="Sun", TimeSlot="9:0 - 10:0") for n in range(3)]
    gf.write_newmain_sheet(ws, entries, now=_STAMP_NOW)

    # Three data rows sit at B4:B6, so the footer is at I8 and I9.
    assert ws.updates[1] == ([[_EXPECTED_STAMP]], "I8", {})
    assert ws.updates[2] == ([[rf.SIGNATURE]], "I9", {})
    assert ws.formatted == ("I9", {"horizontalAlignment": "RIGHT"})
    # The stamp must not land in the data columns above/beside the block.
    assert all(not rng.startswith("B") for _, rng, _ in ws.updates[1:])


def test_write_newmain_sheet_reports_the_empty_backend_notice():
    ws = _FakeWorksheet("NewMain")
    assert gf.write_newmain_sheet(ws, [], now=_STAMP_NOW) is True
    assert ws.updates[0] == ([[rf.NO_DATA_MESSAGE]], "B4", {})
    # The notice occupies B4, so the footer still starts at row 6.
    assert ws.updates[1] == ([[_EXPECTED_STAMP]], "I6", {})


def test_write_newmain_sheet_defaults_to_utc_now():
    ws = _FakeWorksheet("NewMain")
    assert gf.write_newmain_sheet(ws, [_entry()]) is True
    assert ws.updates[1][0][0][0].startswith("Last Updated: ")


def test_write_newmain_sheet_returns_false_when_the_write_fails():
    class _RaisingWorksheet:
        title = "NewMain"
        row_count = 1000

        def batch_clear(self, ranges):
            raise RuntimeError("boom")

    assert gf.write_newmain_sheet(_RaisingWorksheet(), [_entry()]) is False


# ----------------------------- main: exit code contract -----------------------------

class _FakeGC:
    def __init__(self, spreadsheet=None, not_found=False):
        self._spreadsheet = spreadsheet
        self._not_found = not_found
        self.opened = []

    def open(self, name):
        self.opened.append(name)
        if self._not_found:
            raise gf.gspread.exceptions.SpreadsheetNotFound(name)
        return self._spreadsheet


# Sentinel: "use the current UTC time" for generated_at.
_NOW = object()


def _stale_timestamp(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _main_spreadsheet():
    """A spreadsheet that already owns both worksheets the workflow touches."""
    return _FakeSpreadsheet(existing={
        "backend": _FakeWorksheet("backend"),
        "NewMain": _FakeWorksheet("NewMain"),
    })


def _patch_main(monkeypatch, data=None, gc=None, newmain_ok=True,
                generated_at=_NOW, max_age=48):
    """Wire main()'s external dependencies to fakes; returns call counters."""
    calls = {"newmain": 0}
    entries = [_entry()] if data is None else data
    stamp = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if generated_at is _NOW else generated_at
    )
    monkeypatch.setattr(gf, "load_routine_data", lambda path: (entries, stamp))
    monkeypatch.setattr(gf, "authenticate_gsheet", lambda path: gc)
    monkeypatch.setattr(gf, "MAX_DATA_AGE_HOURS", max_age)

    def fake_write(worksheet, entries, now=None):
        calls["newmain"] += 1
        return newmain_ok

    monkeypatch.setattr(gf, "write_newmain_sheet", fake_write)
    return calls


def test_main_returns_zero_when_sync_succeeds(monkeypatch):
    calls = _patch_main(monkeypatch, gc=_FakeGC(_main_spreadsheet()))
    assert gf.main() == 0
    assert calls["newmain"] == 1


def test_main_returns_nonzero_when_data_missing(monkeypatch):
    _patch_main(monkeypatch, data=[], gc=_FakeGC(_main_spreadsheet()))
    assert gf.main() != 0


def test_main_returns_nonzero_when_authentication_fails(monkeypatch):
    _patch_main(monkeypatch, gc=None)
    assert gf.main() != 0


def test_main_returns_nonzero_when_spreadsheet_not_found(monkeypatch):
    _patch_main(monkeypatch, gc=_FakeGC(not_found=True))
    assert gf.main() != 0


def test_main_returns_nonzero_when_backend_write_fails(monkeypatch):
    calls = _patch_main(monkeypatch, gc=_FakeGC(_main_spreadsheet()))
    monkeypatch.setattr(gf, "write_data_to_sheet", lambda ws, data: False)
    assert gf.main() != 0
    # NewMain must not be rewritten: it would republish the previous run's
    # sorted rows as if they were this run's.
    assert calls["newmain"] == 0


def test_main_returns_nonzero_when_newmain_write_fails(monkeypatch):
    calls = _patch_main(monkeypatch, gc=_FakeGC(_main_spreadsheet()), newmain_ok=False)
    assert gf.main() != 0
    assert calls["newmain"] == 1


def test_main_returns_nonzero_when_data_is_stale(monkeypatch):
    calls = _patch_main(
        monkeypatch,
        gc=_FakeGC(_main_spreadsheet()),
        generated_at=_stale_timestamp(72),
    )
    assert gf.main() != 0
    assert calls["newmain"] == 0


def test_main_returns_nonzero_when_data_has_no_timestamp(monkeypatch):
    # A legacy bare-list payload carries no generated_at, so freshness is
    # unverifiable - refuse rather than republish data of unknown age.
    calls = _patch_main(
        monkeypatch,
        gc=_FakeGC(_main_spreadsheet()),
        generated_at=None,
    )
    assert gf.main() != 0
    assert calls["newmain"] == 0


def test_main_publishes_fresh_data_within_limit(monkeypatch):
    calls = _patch_main(
        monkeypatch,
        gc=_FakeGC(_main_spreadsheet()),
        generated_at=_stale_timestamp(2),
    )
    assert gf.main() == 0
    assert calls["newmain"] == 1


def test_main_age_check_can_be_disabled(monkeypatch):
    calls = _patch_main(
        monkeypatch,
        gc=_FakeGC(_main_spreadsheet()),
        generated_at=_stale_timestamp(24 * 30),
        max_age=0,
    )
    assert gf.main() == 0
    assert calls["newmain"] == 1


def test_main_grows_the_worksheets_to_fit_a_grown_routine(monkeypatch):
    # Both sheets exist already but are too small; main() must grow them rather
    # than let the write fail with "Range exceeds grid limits".
    backend_ws = _FakeWorksheet("backend", row_count=30, col_count=10)
    newmain_ws = _FakeWorksheet("NewMain", row_count=30, col_count=10)
    spreadsheet = _FakeSpreadsheet(existing={"backend": backend_ws, "NewMain": newmain_ws})
    entries = [_entry(CourseCode=f"CSE-{n}") for n in range(40)]

    calls = _patch_main(monkeypatch, data=entries, gc=_FakeGC(spreadsheet))
    assert gf.main() == 0
    assert calls["newmain"] == 1
    assert backend_ws.row_count == 41          # header + 40 entries
    assert newmain_ws.row_count == 46          # 40 entries + header + 2 footer rows
    # Already wide enough for B..I, so the width is left as it is.
    assert newmain_ws.col_count == 10

