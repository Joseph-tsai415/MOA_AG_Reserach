"""Shared fixtures. These tests pin the CURRENT behaviour of the service layer
so the agent-harness refactor can be verified as behaviour-preserving. They
must pass unchanged after the manifest refactor; if one fails, the refactor is
wrong, not the test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# runner/ is the import root: `from app import naming`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def run_dir_factory(tmp_path):
    """Build a fake run directory. Positional args are empty-ish files;
    keyword args are files with content (key = filename with dots as
    underscores is NOT done — pass real names via the `files` dict instead)."""

    def _make(*filenames: str, files: dict[str, str] | None = None) -> Path:
        """Build a fake run directory.

        Positional args are filenames created with placeholder content, for tests that
        only care whether a file exists. `files` maps filename -> exact content, for
        tests that read it back. Both accept nested paths ("figures/step1.png").
        """
        d = tmp_path / "run"
        d.mkdir(exist_ok=True)
        for name in filenames:
            p = d / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("placeholder\n", encoding="utf-8")
        for name, content in (files or {}).items():
            p = d / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return d

    return _make
