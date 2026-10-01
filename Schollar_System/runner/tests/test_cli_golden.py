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


def test_every_declared_dest_and_default_is_pinned(monkeypatch):
    """All 14 argparse dests, by name and default, in one shot. Task 14
    regenerates this parser from a manifest; if it drops, renames, or
    re-types any of the ten args no other test here touches (--prompt,
    --run-id, --run-dir, --extra, --model, --max-turns, --timeout,
    --max-cost, --resume, --idle-wait), this is the only test that notices.
    """
    # MOA_RUN_DIR leaks in from the environment by design (app/run_once.py:84),
    # so clear it first or this test is machine/CI-state-dependent.
    monkeypatch.delenv("MOA_RUN_DIR", raising=False)
    got = vars(build_parser().parse_args([]))
    assert got == {
        "kind": "moa",
        "prompt": "",
        "compounds": "",
        "disease": "",
        "run_id": None,
        "run_dir": None,
        "extra": "",
        "model": None,
        "max_turns": None,
        "timeout": None,
        "max_cost": None,
        "resume": None,
        "idle_wait": None,
        "dry_run": False,
    }


def test_run_dir_default_comes_from_MOA_RUN_DIR(monkeypatch):
    # CLAUDE.md §2 / app/run_once.py:84: in service mode the run directory is
    # assigned upstream by an atomic counter and passed in via this env var.
    # Losing this default would make every queued run scan-and-increment
    # results/ locally, which races under a queue.
    monkeypatch.setenv("MOA_RUN_DIR", "x_session9")
    assert build_parser().parse_args([]).run_dir == "x_session9"
    monkeypatch.delenv("MOA_RUN_DIR")
    assert build_parser().parse_args([]).run_dir is None


def test_numeric_arguments_are_converted_not_left_as_strings():
    # app/run_once.py:89-93: --max-turns/--timeout are type=int, --max-cost/
    # --idle-wait are type=float. A manifest round-trip that yields strings
    # passes every other test here, then fails at int(args.timeout / 60)
    # (run_once.py:497, :509).
    args = build_parser().parse_args(
        ["--max-turns", "7", "--timeout", "9", "--max-cost", "1.5", "--idle-wait", "2.5"])
    assert args.max_turns == 7 and isinstance(args.max_turns, int)
    assert args.timeout == 9 and isinstance(args.timeout, int)
    assert args.max_cost == 1.5 and isinstance(args.max_cost, float)
    assert args.idle_wait == 2.5 and isinstance(args.idle_wait, float)


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


def test_moa_requires_both_values_error_text(capsys):
    # pytest.raises(SystemExit) above only sees the exit code; pin the
    # message text too, since "same error messages" is a stated constraint
    # and Task 14 could otherwise reword it freely.
    with pytest.raises(SystemExit):
        parse_args([])
    captured = capsys.readouterr()
    assert "--compounds and --disease are required for --kind moa" in captured.err


def test_moa_accepts_both_values():
    args = parse_args(["--compounds", "Curcumin", "--disease", "AD"])
    assert args.kind == "moa"
    # The real content of this test is "no SystemExit"; also pin that
    # validation passes the values through unmutated.
    assert args.compounds == "Curcumin"
    assert args.disease == "AD"


def test_probe_needs_neither_value():
    # The reason the validation is conditional rather than argparse-required.
    args = parse_args(["--kind", "probe"])
    assert args.kind == "probe"
    assert args.compounds == ""


def test_whitespace_only_values_do_not_satisfy_moa():
    with pytest.raises(SystemExit):
        parse_args(["--compounds", "   ", "--disease", "   "])
