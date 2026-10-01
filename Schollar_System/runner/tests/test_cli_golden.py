"""Pins today's CLI contract. Task 14 rebuilds this parser from the manifest's
`inputs[]`; every assertion here must still hold afterwards.

Note what the real contract is, because it is not the obvious one:
  * --compounds is ONE comma-separated string, not nargs="+".
  * Neither --compounds nor --disease is argparse-`required`; they are validated
    conditionally, because --kind probe legitimately needs neither.
"""

from __future__ import annotations

import pytest

from app.run_once import build_parser, parse_args, split_values


# --- the parser itself (no validation) ------------------------------------
def test_compounds_is_a_single_comma_separated_string():
    args = build_parser().parse_args(
        ["--compounds", "Curcumin", "--disease", "Atopic Dermatitis"])
    assert args.compounds == "Curcumin"          # a str, NOT ["Curcumin"]
    assert args.disease == "Atopic Dermatitis"


def test_multiple_compounds_travel_as_one_comma_joined_value():
    args = build_parser().parse_args(
        ["--compounds", "Curcumin,Gallic acid", "--disease", "AD"])
    assert args.compounds == "Curcumin,Gallic acid"


def test_compounds_and_disease_default_to_empty_string():
    args = build_parser().parse_args([])
    assert args.compounds == ""
    assert args.disease == ""


def test_kind_defaults_to_moa_and_rejects_unknown_values():
    assert build_parser().parse_args([]).kind == "moa"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--kind", "nonsense"])


def test_dry_run_flag_defaults_false_and_sets_true():
    p = build_parser()
    assert p.parse_args([]).dry_run is False
    assert p.parse_args(["--dry-run"]).dry_run is True


# --- the comma-splitting conversion ---------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("Curcumin", ["Curcumin"]),
    ("Curcumin,Gallic acid", ["Curcumin", "Gallic acid"]),
    ("  Curcumin , Gallic acid  ", ["Curcumin", "Gallic acid"]),
    ("Curcumin,,Gallic acid", ["Curcumin", "Gallic acid"]),   # empties dropped
    ("", []),
    (None, []),
])
def test_split_values(raw, expected):
    assert split_values(raw) == expected


# --- the CONDITIONAL validation -------------------------------------------
def test_moa_requires_both_values():
    with pytest.raises(SystemExit):
        parse_args(["--compounds", "Curcumin"])          # no --disease
    with pytest.raises(SystemExit):
        parse_args(["--disease", "AD"])                  # no --compounds
    with pytest.raises(SystemExit):
        parse_args([])                                    # neither


def test_moa_accepts_both_values():
    args = parse_args(["--compounds", "Curcumin", "--disease", "AD"])
    assert args.kind == "moa"


def test_probe_needs_neither_value():
    # The reason the validation is conditional rather than argparse-required.
    args = parse_args(["--kind", "probe"])
    assert args.kind == "probe"
    assert args.compounds == ""


def test_whitespace_only_values_do_not_satisfy_moa():
    with pytest.raises(SystemExit):
        parse_args(["--compounds", "   ", "--disease", "   "])
