import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routine_scrapper as rs

TABLE_CSS = f"#{rs.UPDATE_PANEL_ID} #{rs.COURSE_TABLE_ID}"


def _semester_options_json(target_text="Fall 2024"):
    return json.dumps([
        {"text": "Select Semester", "value": "0"},
        {"text": target_text, "value": "7"},
    ])


class FakeElement:
    def __init__(self, text="", value=None, html=None):
        self.text = text
        self._value = value
        self.html = html
        self.sent_keys = ""
        self.clicked = False

    async def send_keys(self, keys):
        self.sent_keys = keys

    async def click(self):
        self.clicked = True


class FakeTab:
    """Async double for a nodriver Tab: scripted gets/selects/evaluates."""

    def __init__(self, title="UCAM", titles=None, elements=None, source=""):
        self.title = title
        self._titles = list(titles) if titles else None
        self.current_url = ""
        self.gets = []
        self.evaluations = []
        self._elements = elements or {}
        self._content = source
        self.eval_map = {}
        self.eval_default = None

    async def get(self, url):
        self.gets.append(url)
        self.current_url = url
        if self._titles:
            self.title = self._titles.pop(0)

    async def sleep(self, t):
        pass

    async def select(self, css, timeout=10):
        return self._elements.get(css)

    async def evaluate(self, expression):
        self.evaluations.append(expression)
        if expression.strip() == "document.title":
            return self.title
        if expression in self.eval_map:
            value = self.eval_map[expression]
            return value(self, expression) if callable(value) else value
        if self.eval_default is not None:
            value = self.eval_default
            return value(self, expression) if callable(value) else value
        return None

    async def get_content(self):
        return self._content


@pytest.fixture(autouse=True)
def _fast_clock(monkeypatch):
    ticks = [0.0]

    def monotonic():
        ticks[0] += 1.0
        return ticks[0]

    async def noop_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(time, "monotonic", monotonic)
    monkeypatch.setattr(rs.asyncio, "sleep", noop_sleep)
    for attr in (
        "LOGIN_WAIT_S",
        "LOGIN_FIELD_WAIT_S",
        "LOGIN_SUCCESS_WAIT_S",
        "SEMESTER_WAIT_S",
        "COURSE_TABLE_WAIT_S",
    ):
        monkeypatch.setattr(rs, attr, 0.01)


def _login_tab(success=True, **elements):
    tab = FakeTab(elements={
        f"#{rs.LOGIN_USERNAME_ID}": FakeElement(),
        f"#{rs.LOGIN_PASSWORD_ID}": FakeElement(),
        f"#{rs.LOGIN_BUTTON_ID}": FakeElement(),
        **elements,
    })
    if success:
        tab._elements[f"#{rs.LOGIN_SUCCESS_ID}"] = FakeElement()
    return tab


def _semester_tab(target_text="Fall 2024", with_dashboard=False):
    tab = FakeTab()
    tab.eval_map[rs._semester_options_js()] = _semester_options_json(target_text)
    tab.eval_map[rs._select2_selection_js()] = True
    tab.eval_map[rs._select2_option_js(target_text)] = True
    if with_dashboard:
        tab.eval_map[rs._dashboard_html_js()] = SAMPLE_DASHBOARD_HTML
        tab._elements[TABLE_CSS] = FakeElement()
    return tab


# ----------------------------- masking_visit -----------------------------

async def test_masking_visit_navigates_to_google():
    tab = FakeTab()
    await rs.masking_visit(tab)
    assert tab.gets == ["https://www.google.com"]


async def test_masking_visit_tolerates_tab_failure():
    tab = FakeTab()

    async def boom(url):
        raise RuntimeError("boom")

    tab.get = boom
    await rs.masking_visit(tab)  # must not raise


# ----------------------------- _is_cloudflare_blocked -----------------------------

def test_cloudflare_markers_detected():
    assert rs._is_cloudflare_blocked("Just a moment...")
    assert rs._is_cloudflare_blocked("Cloudflare Ray ID")
    assert rs._is_cloudflare_blocked("Attention Required! | Cloudflare")
    assert not rs._is_cloudflare_blocked("UCAM Student Portal")


# ----------------------------- bypass_cloudflare_and_wait_for_login -----------------------------

async def test_bypass_succeeds_when_login_fields_present():
    tab = _login_tab()
    await rs.bypass_cloudflare_and_wait_for_login(tab, "https://login")
    assert tab.gets == ["https://login"]


async def test_bypass_retries_through_cloudflare_then_succeeds():
    tab = FakeTab(
        titles=["Just a moment...", "UCAM Student Portal"],
        elements={f"#{rs.LOGIN_USERNAME_ID}": FakeElement()},
    )
    await rs.bypass_cloudflare_and_wait_for_login(tab, "https://login")
    assert tab.gets == ["https://login", "https://login"]


async def test_bypass_raises_when_login_never_appears():
    tab = FakeTab(title="UCAM Student Portal", source="snippet")
    with pytest.raises(rs.ScrapeTimeoutError):
        await rs.bypass_cloudflare_and_wait_for_login(tab, "https://login")
    assert len(tab.gets) == rs.PORTAL_ACCESS_ATTEMPTS


# ----------------------------- authenticate -----------------------------

async def test_authenticate_fills_form_and_clicks():
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    tab = _login_tab(
        **{
            f"#{rs.LOGIN_USERNAME_ID}": user_field,
            f"#{rs.LOGIN_PASSWORD_ID}": pass_field,
            f"#{rs.LOGIN_BUTTON_ID}": login_btn,
        }
    )
    creds = {"username": "u", "password": "p", "id": 1}
    await rs.authenticate(creds, tab)
    assert user_field.sent_keys == "u"
    assert pass_field.sent_keys == "p"
    assert login_btn.clicked is True


async def test_authenticate_raises_when_success_element_missing():
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    tab = FakeTab(elements={
        f"#{rs.LOGIN_USERNAME_ID}": user_field,
        f"#{rs.LOGIN_PASSWORD_ID}": pass_field,
        f"#{rs.LOGIN_BUTTON_ID}": login_btn,
    })
    with pytest.raises(rs.ScrapeTimeoutError):
        await rs.authenticate({"username": "u", "password": "p", "id": 1}, tab)


# ----------------------------- select_semester -----------------------------

async def test_select_semester_chooses_first_non_placeholder():
    tab = _semester_tab("Fall 2024")
    chosen = await rs.select_semester(tab, "https://dash", "B1")
    assert chosen == "Fall 2024"
    assert tab.gets[-1] == "https://dash"
    assert rs._select2_selection_js() in tab.evaluations
    assert rs._select2_option_js("Fall 2024") in tab.evaluations


async def test_select_semester_raises_with_no_valid_option():
    tab = FakeTab()
    tab.eval_map[rs._semester_options_js()] = json.dumps(
        [{"text": "Select Semester", "value": "0"}]
    )
    with pytest.raises(ValueError):
        await rs.select_semester(tab, "https://dash", "B1")


async def test_select_semester_raises_when_dropdown_missing():
    tab = FakeTab()
    with pytest.raises(rs.ScrapeTimeoutError):
        await rs.select_semester(tab, "https://dash", "B1")


# ----------------------------- extract_dashboard -----------------------------

async def test_extract_dashboard_returns_parsed_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", str(tmp_path))
    tab = _semester_tab(with_dashboard=True)
    entries = await rs.extract_dashboard(tab, "B1")
    assert len(entries) == 1
    assert entries[0]["CourseCode"] == "CSE-3201"
    assert (tmp_path / "dashboard_data_B1.csv").exists()
    assert (tmp_path / "dashboard_data_B1.json").exists()


async def test_extract_dashboard_no_html_returns_empty(monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", "/tmp/nonexistent_dir")
    tab = FakeTab()
    tab._elements[TABLE_CSS] = FakeElement()
    assert await rs.extract_dashboard(tab, "B1") == []


# ----------------------------- scrape_dashboard_for_user -----------------------------

async def test_scrape_dashboard_for_user_runs_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", str(tmp_path))
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    tab = _semester_tab("Fall 2024", with_dashboard=True)
    tab._elements.update({
        f"#{rs.LOGIN_USERNAME_ID}": user_field,
        f"#{rs.LOGIN_PASSWORD_ID}": pass_field,
        f"#{rs.LOGIN_BUTTON_ID}": login_btn,
        f"#{rs.LOGIN_SUCCESS_ID}": FakeElement(),
    })

    creds = {"id": 1, "username": "u", "password": "p", "section_label": "B1"}
    urls = {"login_url": "https://login", "attendance_dashboard_url": "https://dash"}

    entries = await rs.scrape_dashboard_for_user(tab, creds, urls)
    assert len(entries) == 1
    assert tab.gets[0] == "https://www.google.com"
    assert "https://login" in tab.gets
    assert tab.gets[-1] == "https://dash"
    assert user_field.sent_keys == "u"
    assert login_btn.clicked is True


SAMPLE_DASHBOARD_HTML = """
<table id="ctl00_MainContainer_gvCourseList">
<tr><th>SL</th><th>C</th><th>S1</th><th>S2</th><th>A</th></tr>
<tr>
  <td>1</td>
  <td>Course Code :<br/>CSE-3201<br/>Title : Operating Systems<br/>Credit : 3.00<br/>Section : B</td>
  <td>Day :<br/>Sun<br/>Time : 11:0 - 12:15<br/>Room : 120<br/>Teacher : SS</td>
  <td>Day :<br/>Mon<br/>Time : 11:0 - 12:15<br/>Room : 204<br/>Teacher : SS</td>
  <td>Total Class : 5</td>
</tr>
</table>
"""
