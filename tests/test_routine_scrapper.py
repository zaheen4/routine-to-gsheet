import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routine_scrapper as rs


# ----------------------------- Sample HTML fixture -----------------------------

SAMPLE_HTML = """
<html>
<body>
<table id="ctl00_MainContainer_gvCourseList">
<tr>
    <th>SL</th><th>Course Info</th><th>Schedule 1</th><th>Schedule 2</th><th>Attendance</th>
</tr>
<tr>
    <td>1</td>
    <td>Course Code :<br/>CSE-3201<br/>Title : Operating Systems<br/>Credit : 3.00<br/>Section : B</td>
    <td>Day :<br/>Sun<br/>Time : 11:0 - 12:15<br/>Room : 120<br/>Teacher : SS</td>
    <td>Day :<br/>Mon<br/>Time : 11:0 - 12:15<br/>Room : 204<br/>Teacher : SS</td>
    <td>Total Class : 5<br/>Attendance Percentage :<br/>80.00</td>
</tr>
<tr>
    <td>2</td>
    <td>Course Code :<br/>CSE-3212<br/>Title : Operating Systems Lab<br/>Credit : 1.50<br/>Section : B2</td>
    <td>Day :<br/>Wed<br/>Time : 9:0 - 11:50<br/>Room : 302<br/>Teacher : JTT</td>
    <td>Day :<br/>Thu<br/>Time : 9:0 - 11:50<br/>Room : 302<br/>Teacher : JTT</td>
    <td>Total Class : 5<br/>Attendance Percentage :<br/>90.00</td>
</tr>
<tr>
    <td>3</td>
    <td>Course Code :<br/>CSE-3203<br/>Title : Missing Schedule<br/>Credit : 3.00<br/>Section : B</td>
    <td>Time : 11:0 - 12:15<br/>Room : 120<br/>Teacher : SS</td>
    <td>Day :<br/>Fri<br/>Time : 11:0 - 12:15<br/>Room : 204<br/>Teacher : SS</td>
    <td>Total Class : 5</td>
</tr>
</table>
</body>
</html>
"""


# ----------------------------- load_credentials -----------------------------

def test_load_credentials_valid(tmp_path):
    creds = {
        "users": [
            {"id": 1, "username": "u1", "password": "p1", "section_label": "B1"},
        ],
        "login_url": "https://example.com/login",
        "attendance_dashboard_url": "https://example.com/dash",
    }
    path = tmp_path / "creds.json"
    path.write_text(json.dumps(creds), encoding="utf-8")
    assert rs.load_credentials(str(path)) == creds


def test_load_credentials_missing_top_keys(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"users": []}), encoding="utf-8")
    assert rs.load_credentials(str(path)) is None


def test_load_credentials_empty_users(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(
        json.dumps({"users": [], "login_url": "x", "attendance_dashboard_url": "y"}),
        encoding="utf-8",
    )
    assert rs.load_credentials(str(path)) is None


def test_load_credentials_invalid_json(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("not json", encoding="utf-8")
    assert rs.load_credentials(str(path)) is None


# ----------------------------- load_teacher_details -----------------------------

def test_load_teacher_details_valid(tmp_path):
    details = {"SS": {"FullName": "Test Teacher", "Phone": "123", "Email": "t@x.com"}}
    path = tmp_path / "teachers.json"
    path.write_text(json.dumps(details), encoding="utf-8")
    assert rs.load_teacher_details_from_file(str(path)) == details


def test_load_teacher_details_missing_file(tmp_path):
    assert rs.load_teacher_details_from_file(str(tmp_path / "nope.json")) == {}


def test_load_teacher_details_invalid_json(tmp_path):
    path = tmp_path / "teachers.json"
    path.write_text("not json", encoding="utf-8")
    assert rs.load_teacher_details_from_file(str(path)) == {}


def test_load_teacher_details_skips_underscore_keys(tmp_path):
    details = {
        "_comment": "not a teacher",
        "SS": {"FullName": "Test Teacher", "Phone": "123", "Email": "t@x.com"},
    }
    path = tmp_path / "teachers.json"
    path.write_text(json.dumps(details), encoding="utf-8")
    assert rs.load_teacher_details_from_file(str(path)) == {"SS": details["SS"]}


# ----------------------------- parse_attendance_dashboard_data -----------------------------

def test_parse_dashboard_entries():
    entries = rs.parse_attendance_dashboard_data(SAMPLE_HTML, "B1")
    assert len(entries) == 3

    e1 = entries[0]
    assert e1["CourseCode"] == "CSE-3201"
    assert e1["CourseTitle"] == "Operating Systems"
    assert e1["Credit"] == "3.00"
    assert e1["CourseSection"] == "B"
    assert e1["ScheduleOne_Day"] == "Sun"
    assert e1["ScheduleOne_Time"] == "11:0 - 12:15"
    assert e1["ScheduleOne_Room"] == "120"
    assert e1["ScheduleOne_TeacherInitial"] == "SS"
    assert e1["ScheduleTwo_Day"] == "Mon"


def test_parse_dashboard_missing_table():
    assert rs.parse_attendance_dashboard_data("<html></html>", "B1") == []


def test_parse_dashboard_row_without_day_keeps_other_slot():
    entries = rs.parse_attendance_dashboard_data(SAMPLE_HTML, "B1")
    e3 = entries[2]
    assert e3["ScheduleOne_Day"] == ""
    assert e3["ScheduleTwo_Day"] == "Fri"


# ----------------------------- save_data_to_file -----------------------------

def test_save_csv(tmp_path):
    data = [{"A": 1, "B": 2}, {"A": 3, "B": 4}]
    rs.save_data_to_file(data, str(tmp_path), "out.csv", "csv", fieldnames=["A", "B"])
    out = tmp_path / "out.csv"
    assert out.exists()
    assert out.read_text(encoding="utf-8").splitlines()[0] == "A,B"


def test_save_json(tmp_path):
    data = [{"A": 1, "B": 2}]
    rs.save_data_to_file(data, str(tmp_path), "out.json", "json")
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == data


def test_save_empty_data_no_file(tmp_path):
    rs.save_data_to_file([], str(tmp_path), "none.csv", "csv")
    assert not (tmp_path / "none.csv").exists()


# ----------------------------- _schedule_entry -----------------------------

def test_schedule_entry_builds_and_joins_teacher():
    item = {
        "CourseCode": "CSE-3201",
        "CourseTitle": "Operating Systems",
        "CourseSection": "B",
        "ScheduleOne_Day": "Sun",
        "ScheduleOne_Time": "11:0 - 12:15",
        "ScheduleOne_Room": "120",
        "ScheduleOne_TeacherInitial": "SS",
    }
    details = {"SS": {"FullName": "Sumon Saha", "Phone": "123", "Email": "s@x.com"}}
    entry = rs._schedule_entry(item, "ScheduleOne", details)
    assert entry == {
        "CourseCode": "CSE-3201",
        "CourseTitle": "Operating Systems",
        "Section": "B",
        "Day": "Sun",
        "Room": "120",
        "TimeSlot": "11:0 - 12:15",
        "Teacher": "Sumon Saha",
        "TeacherPhone": "123",
        "TeacherEmail": "s@x.com",
    }


def test_schedule_entry_skips_missing_day():
    item = {
        "CourseCode": "X",
        "CourseTitle": "Y",
        "CourseSection": "B",
        "ScheduleOne_Day": "",
    }
    assert rs._schedule_entry(item, "ScheduleOne", {}) is None


def test_schedule_entry_unknown_teacher_uses_initial():
    item = {
        "CourseCode": "X",
        "CourseTitle": "Y",
        "CourseSection": "B",
        "ScheduleOne_Day": "Sun",
        "ScheduleOne_TeacherInitial": "ZZ",
    }
    entry = rs._schedule_entry(item, "ScheduleOne", {})
    assert entry["Teacher"] == "ZZ"


# ----------------------------- build_final_routine -----------------------------

def _item(cc, title, section, d1, t1="11:0 - 12:15"):
    return {
        "CourseCode": cc,
        "CourseTitle": title,
        "Credit": "3.00",
        "CourseSection": section,
        "UserScrapedSection": section,
        "ScheduleOne_Day": d1,
        "ScheduleOne_Time": t1,
        "ScheduleOne_Room": "120",
        "ScheduleOne_TeacherInitial": "SS",
        "ScheduleTwo_Day": "",
        "ScheduleTwo_Time": "",
        "ScheduleTwo_Room": "",
        "ScheduleTwo_TeacherInitial": "",
    }


def test_build_final_routine_primary_keeps_all_secondary_only_lab():
    data = [
        _item("CSE-3201", "Operating Systems", "B1", "Sun"),
        _item("CSE-3212", "Operating Systems Lab", "B2", "Wed"),
        _item("CSE-3211", "Data Structures Lab", "B2", "Tue"),
        _item("CSE-3205", "Discrete Math", "B2", "Thu"),
    ]
    final = rs.build_final_routine(data, "B1", "B2", {})
    codes = {e["CourseCode"] for e in final}
    assert codes == {"CSE-3201", "CSE-3212", "CSE-3211"}
    assert "CSE-3205" not in codes


def test_build_final_routine_dedupes():
    data = [
        _item("CSE-3201", "Operating Systems", "B1", "Sun"),
        _item("CSE-3201", "Operating Systems", "B1", "Sun"),
    ]
    final = rs.build_final_routine(data, "B1", "B2", {})
    assert len(final) == 1


def test_build_final_routine_no_secondary():
    data = [_item("CSE-3201", "Operating Systems", "B1", "Sun")]
    final = rs.build_final_routine(data, "B1", None, {})
    assert len(final) == 1


# ----------------------------- missing_teacher_initials -----------------------------

def test_missing_teacher_initials_returns_unknowns():
    data = [
        {"ScheduleOne_TeacherInitial": "SS", "ScheduleTwo_TeacherInitial": "ZZ"},
        {"ScheduleOne_TeacherInitial": "TA", "ScheduleTwo_TeacherInitial": ""},
    ]
    assert rs.missing_teacher_initials(data, {"SS": {}, "TA": {}}) == ["ZZ"]


def test_missing_teacher_initials_empty_when_all_known():
    data = [
        {"ScheduleOne_TeacherInitial": "SS", "ScheduleTwo_TeacherInitial": "JTT"},
    ]
    assert rs.missing_teacher_initials(data, {"SS": {}, "JTT": {}}) == []


def test_missing_teacher_initials_ignores_empty_values():
    data = [{"ScheduleOne_TeacherInitial": "", "ScheduleTwo_TeacherInitial": None}]
    assert rs.missing_teacher_initials(data, {}) == []


# ----------------------------- build_final_routine warnings -----------------------------

def test_build_final_routine_warns_on_missing_teacher(caplog):
    item = _item("CSE-3201", "Operating Systems", "B1", "Sun")
    item["ScheduleOne_TeacherInitial"] = "ZZ"
    data = [item]
    rs.build_final_routine(data, "B1", "B2", {"SS": {"FullName": "S"}})
    assert any(
        "ZZ" in r.message and "not found" in r.message
        for r in caplog.records if r.levelname == "WARNING"
    )


def test_build_final_routine_no_warning_when_all_known(caplog):
    data = [_item("CSE-3201", "Operating Systems", "B1", "Sun")]
    rs.build_final_routine(data, "B1", "B2", {"SS": {"FullName": "S"}})
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


# ----------------------------- Chrome binary resolution -----------------------------

def test_get_chrome_executable_uses_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(rs, "CHROME_BINARY_PATH", str(fake))
    assert rs.get_chrome_executable() == str(fake)


def test_get_chrome_executable_env_override_missing_falls_back(monkeypatch):
    monkeypatch.setattr(rs, "CHROME_BINARY_PATH", "/nonexistent/chrome")
    monkeypatch.setattr(rs.shutil, "which", lambda name: "/usr/bin/" + name)
    assert rs.get_chrome_executable() == "/usr/bin/google-chrome-stable"


def test_get_chrome_executable_prefers_google_chrome_stable(monkeypatch):
    monkeypatch.setattr(rs, "CHROME_BINARY_PATH", None)
    available = {"chromium": "/usr/bin/chromium", "google-chrome-stable": "/usr/bin/google-chrome-stable"}
    monkeypatch.setattr(rs.shutil, "which", lambda name: available.get(name))
    assert rs.get_chrome_executable() == "/usr/bin/google-chrome-stable"


def test_get_chrome_executable_no_binary(monkeypatch):
    monkeypatch.setattr(rs, "CHROME_BINARY_PATH", None)
    monkeypatch.setattr(rs.shutil, "which", lambda name: None)
    assert rs.get_chrome_executable() is None


def test_get_chrome_major_version_parses(monkeypatch):
    monkeypatch.setattr(rs.subprocess, "check_output", lambda *a, **k: b"Google Chrome 148.0.7778.96\n")
    assert rs.get_chrome_major_version("/usr/bin/google-chrome-stable") == 148


def test_get_chrome_major_version_no_binary_returns_none(monkeypatch):
    monkeypatch.setattr(rs, "CHROME_BINARY_PATH", None)
    monkeypatch.setattr(rs.shutil, "which", lambda name: None)
    assert rs.get_chrome_major_version(None) is None


def test_get_chrome_major_version_unparseable_output(monkeypatch):
    monkeypatch.setattr(rs.subprocess, "check_output", lambda *a, **k: b"unrecognized output\n")
    assert rs.get_chrome_major_version("/usr/bin/google-chrome-stable") is None


def test_get_chrome_major_version_command_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("not found")
    monkeypatch.setattr(rs.subprocess, "check_output", boom)
    assert rs.get_chrome_major_version("/usr/bin/google-chrome-stable") is None
