"""Tests for extract_ucam: parsing, merge semantics, and fail-stop writing.

The browser workflow is exercised separately in a live run; here every network
boundary is replaced so the suite stays offline and sub-second.
"""

import asyncio
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract_ucam as eu

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REPORT_HTML = os.path.join(FIXTURES, "routine_report.html")


# ----------------------------- report parsing -----------------------------

def test_parse_report_html_extracts_fields():
    with open(REPORT_HTML, encoding="utf-8") as handle:
        entries = eu.parse_report_html(handle.read(), default_section="B")

    assert len(entries) == 4
    first = entries[0]
    assert first == {
        "CourseCode": "CSE-4101",
        "CourseTitle": "Artificial Intelligence",
        "Teacher": "UKD_Utpol Kanti Das",
        "TeacherPhone": "01859222633",
        "TeacherEmail": "ukdas@niter.edu.bd",
        "Day": "Mon",
        "Room": "120",
        "TimeSlot": "9:15 AM - 10:30 AM",
        "Section": "B",
    }
    # The lab section comes from the report's Section column, not the account label.
    assert entries[2]["CourseTitle"] == "Computer Networks Lab"
    assert entries[2]["Section"] == "B2"
    assert entries[3]["TeacherEmail"] == "ab@niter.edu.bd"


def test_parse_report_html_uses_default_section_when_column_missing():
    html = """
    <table><tr><td>CSE-3201</td><td>Algorithms</td></tr>
    <tr><td></td><td></td><td>Sun</td><td>204</td><td>9:0</td></tr></table>
    """
    entries = eu.parse_report_html(html, default_section="B1")
    assert entries[0]["Section"] == "B1"


def test_parse_report_html_ignores_rows_before_a_course():
    html = "<table><tr><td>Mon</td><td>120</td><td>9:0</td><td>B</td></tr></table>"
    assert eu.parse_report_html(html) == []


# ----------------------------- roles and merge -----------------------------

def _entry(code, title, day, slot, section):
    return {
        "CourseCode": code,
        "CourseTitle": title,
        "Teacher": "",
        "TeacherPhone": "",
        "TeacherEmail": "",
        "Day": day,
        "Room": "120",
        "TimeSlot": slot,
        "Section": section,
    }


def test_resolve_roles_defaults_to_positional_behaviour():
    accounts = [{"username": "a"}, {"username": "b"}]
    resolved = eu.resolve_roles(accounts)
    assert [role for _account, role in resolved] == ["primary", "lab_merge"]


def test_resolve_roles_honours_explicit_roles():
    accounts = [{"username": "a", "role": "lab_merge"}, {"username": "b", "role": "primary"}]
    resolved = eu.resolve_roles(accounts)
    assert [role for _account, role in resolved] == ["lab_merge", "primary"]


def test_resolve_roles_rejects_two_primaries():
    accounts = [{"username": "a", "role": "primary"}, {"username": "b", "role": "primary"}]
    with pytest.raises(ValueError, match="exactly one"):
        eu.resolve_roles(accounts)


def test_resolve_roles_rejects_unknown_role():
    with pytest.raises(ValueError, match="unknown role|has role"):
        eu.resolve_roles([{"username": "a", "role": "boss"}])


def test_merge_keeps_all_primary_courses_but_only_labs_from_secondary():
    primary = [
        _entry("CSE-4101", "Artificial Intelligence", "Mon", "9:0 - 10:0", "B"),
        _entry("CSE-4108", "Computer Networks Lab", "Tue", "1:0 - 4:0", "B"),
    ]
    secondary = [
        _entry("CSE-4108", "Computer Networks Lab", "Tue", "1:0 - 4:0", "B2"),
        _entry("CSE-4109", "Collaborative Computing", "Thu", "9:0 - 10:0", "B1"),
    ]

    merged = eu.merge_entries([("primary", primary), ("lab_merge", secondary)])

    assert [entry["CourseCode"] for entry in merged] == [
        "CSE-4101", "CSE-4108", "CSE-4108",
    ]
    # The identical primary slot is deduped, the secondary lab is kept under its
    # own section, and "Collaborative Computing" is not a lab so it is dropped.
    assert [(entry["CourseCode"], entry["Section"]) for entry in merged] == [
        ("CSE-4101", "B"),
        ("CSE-4108", "B"),
        ("CSE-4108", "B2"),
    ]


def test_merge_dedupes_identical_slots():
    entry = _entry("CSE-4101", "AI", "Mon", "9:0 - 10:0", "B")
    merged = eu.merge_entries([("primary", [entry, dict(entry)])])
    assert len(merged) == 1


def test_merge_does_not_treat_collaborative_as_a_lab():
    secondary = [_entry("CSE-4109", "Collaborative Computing", "Thu", "9:0 - 10:0", "B1")]
    assert eu.merge_entries([("lab_merge", secondary)]) == []


# ----------------------------- credentials -----------------------------

def test_load_credentials_reads_users_and_login_url(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [{"username": "u", "password": "p", "section_label": "B"}],
        "login_url": "https://example.test/login",
    }), encoding="utf-8")

    loaded = eu.load_credentials(str(path))
    assert loaded["login_url"] == "https://example.test/login"
    assert loaded["users"][0]["username"] == "u"


def test_load_credentials_rejects_missing_users(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="users"):
        eu.load_credentials(str(path))


def test_load_credentials_ucam_accounts_env_override(monkeypatch):
    monkeypatch.setenv("UCAM_ACCOUNTS", json.dumps([
        {"username": "env-user", "password": "p", "section_label": "B"},
    ]))
    loaded = eu.load_credentials("/does/not/exist.json")
    assert loaded["users"][0]["username"] == "env-user"


# ----------------------------- writing -----------------------------

def test_invalidate_previous_output_removes_json_and_tmp(tmp_path):
    output = tmp_path / "routine_data.json"
    output.write_text("{}", encoding="utf-8")
    tmp = tmp_path / "routine_data.json.tmp"
    tmp.write_text("{}", encoding="utf-8")

    eu.invalidate_previous_output(str(output))

    assert not output.exists()
    assert not tmp.exists()


def test_write_manifest_is_atomic_and_timestamped(tmp_path):
    output = tmp_path / "routine_data.json"
    entries = [_entry("CSE-4101", "AI", "Mon", "9:0 - 10:0", "B")]

    payload = eu.write_manifest(str(output), "January-July 2026", entries, ["Account 1"])

    assert output.exists()
    assert not (tmp_path / "routine_data.json.tmp").exists()
    on_disk = json.loads(output.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", on_disk["generated_at"])
    assert on_disk["accounts_processed"] == ["Account 1"]


def _fake_credentials():
    return {
        "users": [{"id": "Account 1", "username": "u", "password": "p", "section_label": "B"}],
        "login_url": "https://example.test/login",
    }


def test_run_extraction_fails_stop_without_writing(tmp_path, monkeypatch):
    output = tmp_path / "routine_data.json"

    async def fail(_account, _chrome, headed=False, login_url=None):
        raise RuntimeError("cloudflare blocked us")

    monkeypatch.setattr(eu, "load_credentials", lambda path=None: _fake_credentials())
    monkeypatch.setattr(eu, "get_chrome_executable", lambda override=None: "/bin/true")
    monkeypatch.setattr(eu, "scrape_account_with_retries", fail)

    with pytest.raises(RuntimeError, match="Partial extraction"):
        asyncio.run(eu.run_extraction(str(output), headed=True))

    assert not output.exists()
    assert not (tmp_path / "routine_data.json.tmp").exists()


def test_run_extraction_writes_manifest_on_success(tmp_path, monkeypatch):
    output = tmp_path / "routine_data.json"

    async def succeed(_account, _chrome, headed=False, login_url=None):
        return "January-July 2026", [
            _entry("CSE-4101", "AI", "Mon", "9:0 - 10:0", "B"),
        ]

    monkeypatch.setattr(eu, "load_credentials", lambda path=None: _fake_credentials())
    monkeypatch.setattr(eu, "get_chrome_executable", lambda override=None: "/bin/true")
    monkeypatch.setattr(eu, "scrape_account_with_retries", succeed)

    payload = asyncio.run(eu.run_extraction(str(output), headed=True))

    assert output.exists()
    assert payload["semester"] == "January-July 2026"
    assert len(payload["entries"]) == 1
