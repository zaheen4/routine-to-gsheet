import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.setup as s


# ----------------------------- scaffold_files -----------------------------

def _write(root, rel, content):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_scaffold_files_creates_missing(tmp_path):
    for template_rel in s.TEMPLATE_MAP.values():
        _write(tmp_path, template_rel, "{}")
    lines = s.scaffold_files(str(tmp_path))
    assert any("created" in line and "ucam_login_credentials.json" in line for line in lines)
    assert os.path.exists(os.path.join(tmp_path, ".env"))


def test_scaffold_files_never_overwrites_existing(tmp_path):
    for template_rel in s.TEMPLATE_MAP.values():
        _write(tmp_path, template_rel, "{}")
    _write(tmp_path, ".env", "APP_SCRIPT_ID=keep-me")
    lines = s.scaffold_files(str(tmp_path))
    assert any("exists" in line and ".env" in line for line in lines)
    with open(os.path.join(tmp_path, ".env"), encoding="utf-8") as f:
        assert "keep-me" in f.read()


# ----------------------------- validate_credentials_json -----------------------------

def test_validate_credentials_json_valid(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [{"id": "a", "username": "u", "password": "p", "section_label": "A1"}],
        "login_url": "http://x",
        "attendance_dashboard_url": "http://y",
    }), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert ok
    assert errors == []


def test_validate_credentials_json_missing_file(tmp_path):
    ok, errors = s.validate_credentials_json(str(tmp_path / "nope.json"))
    assert not ok
    assert "missing" in errors[0]


def test_validate_credentials_json_invalid_json(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("not json", encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert not ok
    assert "not valid JSON" in errors[0]


def test_validate_credentials_json_missing_keys(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"users": []}), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert not ok
    assert any("top-level" in e for e in errors)
    assert any("non-empty" in e for e in errors)


def test_validate_credentials_json_user_missing_keys(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [{"id": "a"}],
        "login_url": "http://x",
        "attendance_dashboard_url": "http://y",
    }), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert not ok
    assert any("users[0]" in e for e in errors)


# ----------------------------- validate_teacher_details -----------------------------

def test_validate_teacher_details_absent_is_ok(tmp_path):
    ok, errors = s.validate_teacher_details(str(tmp_path / "nope.json"))
    assert ok
    assert errors == []


def test_validate_teacher_details_valid(tmp_path):
    path = tmp_path / "teachers.json"
    path.write_text(json.dumps({"SS": {"FullName": "A"}}), encoding="utf-8")
    ok, errors = s.validate_teacher_details(str(path))
    assert ok
    assert errors == []


def test_validate_teacher_details_not_an_object(tmp_path):
    path = tmp_path / "teachers.json"
    path.write_text("[1, 2]", encoding="utf-8")
    ok, errors = s.validate_teacher_details(str(path))
    assert not ok
    assert "JSON object" in errors[0]


# ----------------------------- validate_env -----------------------------

def test_validate_env_ready(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "SPREADSHEET_NAME=My Sheet\nAPP_SCRIPT_ID=AKfycb...abc\n", encoding="utf-8")
    ok, errors = s.validate_env(str(path))
    assert ok
    assert errors == []


def test_validate_env_missing_file(tmp_path):
    ok, errors = s.validate_env(str(tmp_path / ".env"))
    assert not ok
    assert "missing" in errors[0]


def test_validate_env_ok_without_spreadsheet_name(tmp_path):
    path = tmp_path / ".env"
    path.write_text("APP_SCRIPT_ID=AKfycb...abc\n", encoding="utf-8")
    ok, errors = s.validate_env(str(path))
    assert ok
    assert errors == []


def test_validate_env_placeholder_id(tmp_path):
    path = tmp_path / ".env"
    path.write_text("APP_SCRIPT_ID=YOUR_APP_SCRIPT_ID_GOES_HERE\n", encoding="utf-8")
    ok, errors = s.validate_env(str(path))
    assert not ok
    assert any("APP_SCRIPT_ID" in e for e in errors)


# ----------------------------- find_browser -----------------------------

def test_find_browser_returns_path_entry(monkeypatch):
    def fake_which(name):
        return "/usr/bin/%s" % name if name == "google-chrome" else None
    monkeypatch.setattr(s.shutil, "which", fake_which)
    assert s.find_browser() == "google-chrome"


def test_find_browser_none(monkeypatch):
    monkeypatch.setattr(s.shutil, "which", lambda name: None)
    assert s.find_browser() is None


def test_find_browser_macos_app_bundle(monkeypatch):
    monkeypatch.setattr(s.shutil, "which", lambda name: None)
    fake = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(s, "_platform_chrome_candidates", lambda: [fake])
    monkeypatch.setattr(s.os.path, "exists", lambda p: p == fake)
    assert s.find_browser() == fake


def test_setup_platform_candidates_macos(monkeypatch):
    monkeypatch.setattr(s.sys, "platform", "darwin")
    candidates = s._platform_chrome_candidates()
    assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in candidates
    assert "/Applications/Chromium.app/Contents/MacOS/Chromium" in candidates


def test_setup_platform_candidates_windows(monkeypatch):
    monkeypatch.setattr(s.os, "name", "nt")
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\u\\AppData\\Local")
    candidates = s._platform_chrome_candidates()
    assert os.path.join("C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe") in candidates
    assert os.path.join("C:\\Users\\u\\AppData\\Local", "Google", "Chrome", "Application", "chrome.exe") in candidates
