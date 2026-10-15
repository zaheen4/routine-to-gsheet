"""Tests for browser_lookup: the shared Chrome/Chromium discovery logic."""
import os

import browser_lookup as bl

# ----------------------------- platform_chrome_candidates -----------------------------

def test_platform_candidates_macos(monkeypatch):
    monkeypatch.setattr(bl.sys, "platform", "darwin")
    candidates = bl.platform_chrome_candidates()
    assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in candidates
    assert "/Applications/Chromium.app/Contents/MacOS/Chromium" in candidates


def test_platform_candidates_windows(monkeypatch):
    monkeypatch.setattr(bl.os, "name", "nt")
    for var in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PROGRAMFILES", "C:\\Program Files")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\u\\AppData\\Local")
    candidates = bl.platform_chrome_candidates()
    assert os.path.join("C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe") in candidates
    assert os.path.join("C:\\Users\\u\\AppData\\Local", "Google", "Chrome", "Application", "chrome.exe") in candidates


def test_platform_candidates_linux_empty(monkeypatch):
    monkeypatch.setattr(bl.sys, "platform", "linux")
    assert bl.platform_chrome_candidates() == []


def test_platform_candidates_windows_dedupes(monkeypatch):
    monkeypatch.setattr(bl.os, "name", "nt")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setenv("PROGRAMFILES", "C:\\Program Files")
    monkeypatch.setenv("PROGRAMW6432", "C:\\Program Files")
    candidates = bl.platform_chrome_candidates()
    expected = os.path.join("C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe")
    assert candidates.count(expected) == 1


# ----------------------------- find_on_path -----------------------------

def test_find_on_path_prefers_google_chrome_stable(monkeypatch):
    available = {"chromium": "/usr/bin/chromium", "google-chrome-stable": "/usr/bin/google-chrome-stable"}
    monkeypatch.setattr(bl.shutil, "which", lambda name: available.get(name))
    assert bl.find_on_path() == "/usr/bin/google-chrome-stable"


def test_find_on_path_none_installed(monkeypatch):
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    assert bl.find_on_path() is None


# ----------------------------- get_chrome_executable -----------------------------

def test_get_chrome_executable_uses_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(bl.shutil, "which", lambda name: "/usr/bin/whatever")
    assert bl.get_chrome_executable(str(fake)) == str(fake)


def test_get_chrome_executable_missing_override_falls_back(monkeypatch):
    monkeypatch.setattr(bl.shutil, "which", lambda name: "/usr/bin/" + name)
    assert bl.get_chrome_executable("/nonexistent/chrome") == "/usr/bin/google-chrome-stable"


def test_get_chrome_executable_uses_well_known_path(monkeypatch):
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    fake = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(bl, "platform_chrome_candidates", lambda: [fake])
    monkeypatch.setattr(bl.os.path, "isfile", lambda p: p == fake)
    assert bl.get_chrome_executable() == fake


def test_get_chrome_executable_no_binary(monkeypatch):
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    monkeypatch.setattr(bl, "platform_chrome_candidates", lambda: [])
    assert bl.get_chrome_executable() is None
