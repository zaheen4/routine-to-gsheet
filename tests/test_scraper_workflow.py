import os
import sys
import time

import pytest
from selenium.common.exceptions import NoSuchElementException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routine_scrapper as rs

TAG_NAME = "tag name"
S2_CONTAINER_XPATH = (
    f"//select[@id='{rs.SEMESTER_DROPDOWN_ID}']/"
    f"following-sibling::span[contains(@class,'select2-container')]"
)
TABLE_XPATH = (
    f"//div[@id='{rs.UPDATE_PANEL_ID}']//table[@id='{rs.COURSE_TABLE_ID}']"
)


def _s2_option_xpath(text):
    return f"//span[contains(@class, 'select2-results')]//li[text()=\"{text}\"]"


class FakeElement:
    def __init__(self, text="", value=None, html=None):
        self.text = text
        self._value = value
        self.html = html
        self.sent_keys = ""
        self.clicked = False

    def get_attribute(self, name):
        if name == "value":
            return self._value
        if name == "innerHTML":
            return self.html
        return None

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def send_keys(self, keys):
        self.sent_keys = keys

    def click(self):
        self.clicked = True


class FakeSelect(FakeElement):
    def __init__(self, options):
        super().__init__()
        self.options = options

    def find_elements(self, by, value):
        if str(by).lower() == TAG_NAME and value == "option":
            return self.options
        return []


class FakeDriver:
    """Minimal driver double: finds elements from a registry and records calls."""

    def __init__(self, title="UCAM", titles=None, elements=None, source=""):
        self.title = title
        self._titles = list(titles) if titles else None
        self.current_url = ""
        self.page_source = source
        self.gets = []
        self._elements = elements or {}

    def get(self, url):
        self.gets.append(url)
        self.current_url = url
        if self._titles:
            self.title = self._titles.pop(0)

    def find_element(self, by, value):
        key = (by, value)
        if key in self._elements:
            return self._elements[key]
        raise NoSuchElementException(f"no element for {key}")

    def find_elements(self, by, value):
        key = (by, value)
        result = self._elements.get(key, [])
        return result if isinstance(result, list) else [result]


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    for attr in (
        "LOGIN_WAIT_S",
        "LOGIN_FIELD_WAIT_S",
        "LOGIN_SUCCESS_WAIT_S",
        "SEMESTER_WAIT_S",
        "COURSE_TABLE_WAIT_S",
    ):
        monkeypatch.setattr(rs, attr, 0.01)


def _by_id(**kwargs):
    return {(rs.By.ID, k): v for k, v in kwargs.items()}


def _login_elements(user="", password="", button=True, success=True):
    elements = _by_id(
        logMain_UserName=FakeElement(),
        logMain_Password=FakeElement(),
        logMain_Button1=FakeElement(),
    )
    if success:
        elements[(rs.By.ID, rs.LOGIN_SUCCESS_ID)] = FakeElement()
    return elements


# ----------------------------- masking_visit -----------------------------

def test_masking_visit_navigates_to_google():
    driver = FakeDriver()
    rs.masking_visit(driver)
    assert driver.gets == ["https://www.google.com"]


def test_masking_visit_tolerates_driver_failure():
    driver = FakeDriver()
    driver.get = lambda url: (_ for _ in ()).throw(RuntimeError("boom"))
    rs.masking_visit(driver)  # must not raise


# ----------------------------- _is_cloudflare_blocked -----------------------------

def test_cloudflare_markers_detected():
    assert rs._is_cloudflare_blocked("Just a moment...")
    assert rs._is_cloudflare_blocked("Cloudflare Ray ID")
    assert rs._is_cloudflare_blocked("Attention Required! | Cloudflare")
    assert not rs._is_cloudflare_blocked("UCAM Student Portal")


# ----------------------------- bypass_cloudflare_and_wait_for_login -----------------------------

def test_bypass_succeeds_when_login_fields_present():
    driver = FakeDriver(elements=_login_elements())
    rs.bypass_cloudflare_and_wait_for_login(driver, "https://login")
    assert driver.gets == ["https://login"]


def test_bypass_retries_through_cloudflare_then_succeeds():
    driver = FakeDriver(
        titles=["Just a moment...", "UCAM Student Portal"],
        elements=_login_elements(),
    )
    rs.bypass_cloudflare_and_wait_for_login(driver, "https://login")
    assert driver.gets == ["https://login", "https://login"]


def test_bypass_raises_when_login_never_appears():
    driver = FakeDriver(title="UCAM Student Portal", elements={}, source="snippet")
    with pytest.raises(rs.TimeoutException):
        rs.bypass_cloudflare_and_wait_for_login(driver, "https://login")
    assert len(driver.gets) == rs.PORTAL_ACCESS_ATTEMPTS


# ----------------------------- authenticate -----------------------------

def test_authenticate_fills_form_and_clicks():
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    elements = _by_id(
        logMain_UserName=user_field,
        logMain_Password=pass_field,
        logMain_Button1=login_btn,
        ctl00_lbtnUserName=FakeElement(),
    )
    driver = FakeDriver(elements=elements)
    creds = {"username": "u", "password": "p", "id": 1}
    rs.authenticate(creds, driver)
    assert user_field.sent_keys == "u"
    assert pass_field.sent_keys == "p"
    assert login_btn.clicked is True


def test_authenticate_raises_when_success_element_missing():
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    elements = _by_id(
        logMain_UserName=user_field,
        logMain_Password=pass_field,
        logMain_Button1=login_btn,
    )
    driver = FakeDriver(elements=elements)
    with pytest.raises(rs.TimeoutException):
        rs.authenticate({"username": "u", "password": "p", "id": 1}, driver)


# ----------------------------- select_semester -----------------------------

def _semester_driver(target_text="Fall 2024"):
    dropdown = FakeSelect(
        [
            FakeElement(text="Select Semester", value="0"),
            FakeElement(text=target_text, value="7"),
        ]
    )
    s2_container, s2_option = FakeElement(), FakeElement()
    elements = _by_id(ctl00_MainContainer_ddlHeldIn=dropdown)
    elements[(rs.By.XPATH, S2_CONTAINER_XPATH)] = s2_container
    elements[(rs.By.XPATH, _s2_option_xpath(target_text))] = s2_option
    return FakeDriver(elements=elements), s2_container, s2_option


def test_select_semester_chooses_first_non_placeholder():
    driver, s2_container, s2_option = _semester_driver("Fall 2024")
    chosen = rs.select_semester(driver, "https://dash", "B1")
    assert chosen == "Fall 2024"
    assert s2_container.clicked is True
    assert s2_option.clicked is True
    assert driver.gets[-1] == "https://dash"


def test_select_semester_raises_with_no_valid_option():
    driver = FakeDriver(
        elements=_by_id(ctl00_MainContainer_ddlHeldIn=FakeSelect([]))
    )
    with pytest.raises(ValueError):
        rs.select_semester(driver, "https://dash", "B1")


# ----------------------------- extract_dashboard -----------------------------

def test_extract_dashboard_returns_parsed_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", str(tmp_path))
    panel = FakeElement(html=SAMPLE_DASHBOARD_HTML)
    elements = _by_id(ctl00_MainContainer_UpdatePanel02=panel)
    elements[(rs.By.XPATH, TABLE_XPATH)] = FakeElement()
    driver = FakeDriver(elements=elements)
    entries = rs.extract_dashboard(driver, "B1")
    assert len(entries) == 1
    assert entries[0]["CourseCode"] == "CSE-3201"
    assert (tmp_path / "dashboard_data_B1.csv").exists()
    assert (tmp_path / "dashboard_data_B1.json").exists()


def test_extract_dashboard_no_html_returns_empty(monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", "/tmp/nonexistent_dir")
    panel = FakeElement(html=None)
    elements = _by_id(ctl00_MainContainer_UpdatePanel02=panel)
    elements[(rs.By.XPATH, TABLE_XPATH)] = FakeElement()
    driver = FakeDriver(elements=elements)
    assert rs.extract_dashboard(driver, "B1") == []


# ----------------------------- scrape_dashboard_for_user -----------------------------

def test_scrape_dashboard_for_user_runs_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", str(tmp_path))
    user_field, pass_field, login_btn = FakeElement(), FakeElement(), FakeElement()
    dropdown = FakeSelect([FakeElement(text="Fall 2024", value="7")])
    panel = FakeElement(html=SAMPLE_DASHBOARD_HTML)
    s2_container, s2_option = FakeElement(), FakeElement()

    elements = _by_id(
        logMain_UserName=user_field,
        logMain_Password=pass_field,
        logMain_Button1=login_btn,
        ctl00_lbtnUserName=FakeElement(),
        ctl00_MainContainer_ddlHeldIn=dropdown,
        ctl00_MainContainer_UpdatePanel02=panel,
    )
    elements[(rs.By.XPATH, S2_CONTAINER_XPATH)] = s2_container
    elements[(rs.By.XPATH, _s2_option_xpath("Fall 2024"))] = s2_option
    elements[(rs.By.XPATH, TABLE_XPATH)] = FakeElement()
    driver = FakeDriver(elements=elements)

    creds = {"id": 1, "username": "u", "password": "p", "section_label": "B1"}
    urls = {"login_url": "https://login", "attendance_dashboard_url": "https://dash"}

    entries = rs.scrape_dashboard_for_user(driver, creds, urls)
    assert len(entries) == 1
    assert driver.gets[0] == "https://www.google.com"
    assert "https://login" in driver.gets
    assert driver.gets[-1] == "https://dash"
    assert user_field.sent_keys == "u"
    assert login_btn.clicked is True
    assert s2_option.clicked is True


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
