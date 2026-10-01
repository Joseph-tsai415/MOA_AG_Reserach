"""Golden tests for run-directory naming. Pins CLAUDE.md §2 behaviour."""

from __future__ import annotations

import pytest

from app import naming


# --- slugify ---------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("Atopic Dermatitis", "atopic_dermatitis"),
    ("  Curcumin  ", "curcumin"),
    ("Non-alcoholic Fatty Liver", "non_alcoholic_fatty_liver"),
    ("IL-4/IL-13", "il_4_il_13"),
    ("七白散", ""),                      # CJK slugifies to empty — the key edge case
    ("", ""),
])
def test_slugify(raw, expected):
    assert naming.slugify(raw) == expected


# --- base_name -------------------------------------------------------------
def test_base_name_single_compound():
    assert naming.base_name(["Curcumin"], "Atopic Dermatitis") == "curcumin_atopic_dermatitis"


def test_base_name_multi_compound_uses_disease_only():
    assert naming.base_name(["Curcumin", "Gallic acid"], "Atopic Dermatitis") == "atopic_dermatitis"


def test_base_name_cjk_only_compound_falls_back_to_disease():
    # A CJK-only compound name slugifies to empty; must NOT emit "_atopic_dermatitis".
    assert naming.base_name(["七白散"], "Atopic Dermatitis") == "atopic_dermatitis"


def test_base_name_cjk_only_disease_raises():
    with pytest.raises(ValueError, match="slugifies to empty"):
        naming.base_name(["Curcumin"], "七白散")


# --- session increment -----------------------------------------------------
def test_next_session_dir_first_run(tmp_path):
    assert naming.next_session_dir(tmp_path, ["Curcumin"], "Atopic Dermatitis") \
        == "curcumin_atopic_dermatitis_session1"


def test_next_session_dir_increments_past_highest(tmp_path):
    for n in (1, 2, 9):
        (tmp_path / f"curcumin_atopic_dermatitis_session{n}").mkdir()
    assert naming.next_session_dir(tmp_path, ["Curcumin"], "Atopic Dermatitis") \
        == "curcumin_atopic_dermatitis_session10"


def test_bare_base_dir_counts_as_session1(tmp_path):
    # A directory equal to the base (no suffix) means session1 is taken.
    (tmp_path / "curcumin_atopic_dermatitis").mkdir()
    assert naming.next_session_dir(tmp_path, ["Curcumin"], "Atopic Dermatitis") \
        == "curcumin_atopic_dermatitis_session2"


def test_unrelated_sibling_dirs_are_ignored(tmp_path):
    (tmp_path / "psoriasis_session7").mkdir()
    (tmp_path / "curcumin_atopic_dermatitis_session1").mkdir()
    assert naming.next_session_dir(tmp_path, ["Curcumin"], "Atopic Dermatitis") \
        == "curcumin_atopic_dermatitis_session2"


def test_next_probe_dir(tmp_path):
    assert naming.next_probe_dir(tmp_path) == "probe_session1"
    (tmp_path / "probe_session1").mkdir()
    assert naming.next_probe_dir(tmp_path) == "probe_session2"
