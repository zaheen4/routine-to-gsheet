"""Shared pytest fixtures.

Safety net for the developer's local state: ``routine_scrapper.main()`` deletes
the previous combined routine (``FORMATTED_OUTPUT_DIR``) as its very first
action - by design, so a run that dies before writing cannot leave last week's
data where the formatter would publish it.

That makes any test which calls ``main()`` destructive by default: it would wipe
the real ``output_of_fetched_routine/`` contents, which are gitignored generated
files that cannot be restored from git (this actually happened once). The
autouse fixture below points both output directories at a per-test ``tmp_path``;
tests that care about the exact location still override them explicitly, and
pytest's ``tmp_path`` is the same directory in both cases.
"""
import pytest

import routine_scrapper as rs


@pytest.fixture(autouse=True)
def isolated_output_dirs(tmp_path, monkeypatch):
    """Redirect the scraper's output directories into the test's tmp_path."""
    monkeypatch.setattr(rs, "FORMATTED_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(rs, "TMP_OUTPUT_DIR", str(tmp_path / "tmp"))
