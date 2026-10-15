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
    _write(tmp_path, ".env", "SPREADSHEET_NAME=keep-me")
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


def test_validate_credentials_json_accepts_valid_roles(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [
            {"id": "a", "username": "u", "password": "p", "section_label": "A1", "role": "primary"},
            {"id": "b", "username": "u", "password": "p", "section_label": "A2", "role": "lab_merge"},
        ],
        "login_url": "http://x",
        "attendance_dashboard_url": "http://y",
    }), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert ok, errors


def test_validate_credentials_json_rejects_unknown_role(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [{"id": "a", "username": "u", "password": "p",
                   "section_label": "A1", "role": "boss"}],
        "login_url": "http://x",
        "attendance_dashboard_url": "http://y",
    }), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert not ok
    assert any("unknown role" in e for e in errors)


def test_validate_credentials_json_rejects_two_primaries(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({
        "users": [
            {"id": "a", "username": "u", "password": "p", "section_label": "A1", "role": "primary"},
            {"id": "b", "username": "u", "password": "p", "section_label": "A2", "role": "primary"},
        ],
        "login_url": "http://x",
        "attendance_dashboard_url": "http://y",
    }), encoding="utf-8")
    ok, errors = s.validate_credentials_json(str(path))
    assert not ok
    assert any("at most one" in e for e in errors)


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

def test_validate_env_ok_when_present(tmp_path):
    path = tmp_path / ".env"
    path.write_text("SPREADSHEET_NAME=My Sheet\n", encoding="utf-8")
    ok, errors = s.validate_env(str(path))
    assert ok
    assert errors == []


def test_validate_env_missing_file(tmp_path):
    ok, errors = s.validate_env(str(tmp_path / ".env"))
    assert not ok
    assert "missing" in errors[0]


def test_validate_env_accepts_an_empty_file(tmp_path):
    # Every value .env can hold has a working default in config.py
    # (SPREADSHEET_NAME, TARGET_SHEET_NAME, MAX_DATA_AGE_HOURS, LOG_LEVEL), so
    # there is no required key to check - only the file's presence.
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    ok, errors = s.validate_env(str(path))
    assert ok
    assert errors == []


# ----------------------------- find_browser -----------------------------

def test_find_browser_uses_shared_lookup(monkeypatch):
    # setup must report exactly what the scraper would launch, so it delegates
    # to browser_lookup and passes the configured CHROME_BINARY_PATH through.
    captured = {}

    def fake_lookup(env_override=None):
        captured["env_override"] = env_override
        return "/usr/bin/google-chrome-stable"

    monkeypatch.setattr(s, "get_chrome_executable", fake_lookup)
    monkeypatch.setattr(s, "CHROME_BINARY_PATH", "/opt/chrome")
    assert s.find_browser() == "/usr/bin/google-chrome-stable"
    assert captured["env_override"] == "/opt/chrome"


def test_find_browser_none(monkeypatch):
    monkeypatch.setattr(s, "get_chrome_executable", lambda env_override=None: None)
    assert s.find_browser() is None


# ----------------------------- secret permissions -----------------------------

def test_scaffold_creates_private_files(tmp_path):
    if os.name == "nt":
        return  # POSIX permission bits are not meaningful on Windows
    for template_rel in s.TEMPLATE_MAP.values():
        _write(tmp_path, template_rel, "{}")
    s.scaffold_files(str(tmp_path))
    for real_rel in s.TEMPLATE_MAP:
        mode = os.stat(os.path.join(tmp_path, real_rel)).st_mode & 0o777
        assert mode == s.PRIVATE_FILE_MODE, (real_rel, oct(mode))


def test_check_secret_permissions_flags_world_readable(tmp_path):
    if os.name == "nt":
        return
    _write(tmp_path, "configs_to_edit/ucam_login_credentials.json", "{}")
    os.chmod(os.path.join(tmp_path, "configs_to_edit/ucam_login_credentials.json"), 0o644)
    warnings = s.check_secret_permissions(str(tmp_path))
    assert any("ucam_login_credentials.json" in w for w in warnings)


def test_check_secret_permissions_quiet_when_private(tmp_path):
    if os.name == "nt":
        return
    _write(tmp_path, ".env", "SPREADSHEET_NAME=x")
    os.chmod(os.path.join(tmp_path, ".env"), 0o600)
    assert s.check_secret_permissions(str(tmp_path)) == []


def test_check_secret_permissions_ignores_absent_files(tmp_path):
    assert s.check_secret_permissions(str(tmp_path)) == []
