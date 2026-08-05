import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gsheet_formatter as gf


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