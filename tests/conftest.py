"""Shared pytest fixtures.

Safety net for the developer's local state: the pipeline writes generated
artifacts to ``output/`` (gitignored). ``extract_ucam.run_extraction`` invalidates
the previous manifest as its first action and then writes the new one, so a test
that calls it would otherwise delete the real ``output/routine_data.json`` - a
file that cannot be restored from git. The autouse fixture below redirects the
module-level output/tmp paths into a per-test ``tmp_path``. Tests that care about
an exact location still pass their own path explicitly.
"""
import pytest

import extract_ucam as eu


@pytest.fixture(autouse=True)
def isolated_output_dirs(tmp_path, monkeypatch):
    """Redirect the scraper's output and debug directories into tmp_path."""
    output_dir = tmp_path / "out"
    monkeypatch.setattr(eu, "OUTPUT_DIR_PATH", str(output_dir))
    monkeypatch.setattr(eu, "DEFAULT_OUTPUT_PATH", str(output_dir / "routine_data.json"))
    monkeypatch.setattr(eu, "TMP_DIR", str(tmp_path / "tmp"))
