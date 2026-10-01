"""Golden tests for terminal-state classification.

The invariant these exist to protect: A HALT IS NOT A FAILURE.
"""

from __future__ import annotations

import pytest

from app import classify as C

REPORT = "step5_final_report.md"
PDF = "result.pdf"
QA = "report_qa_review.md"

BOTTOM_LINE_REPORT = """\
# Mechanism of Action Analysis

## Bottom Line
Promising but unproven. The cheapest decisive experiment is an NF-kB reporter
in IL-4/IL-13-stimulated keratinocytes.

## Section 1: Scientific Hypothesis
Text that must not be captured.
"""


# --- bottom line extraction ------------------------------------------------
def test_extract_bottom_line(run_dir_factory):
    d = run_dir_factory(files={REPORT: BOTTOM_LINE_REPORT})
    got = C.extract_bottom_line(d / REPORT)
    assert got.startswith("Promising but unproven.")
    assert "must not be captured" not in got


@pytest.mark.parametrize("heading", ["# Bottom Line", "## bottom line", "#### BOTTOM LINE"])
def test_extract_bottom_line_heading_depth_and_case(run_dir_factory, heading):
    d = run_dir_factory(files={REPORT: f"{heading}\nVerdict here.\n\n## Next\nNo.\n"})
    assert C.extract_bottom_line(d / REPORT) == "Verdict here."


def test_extract_bottom_line_absent_returns_none(run_dir_factory):
    d = run_dir_factory(files={REPORT: "# Report\nNo such section.\n"})
    assert C.extract_bottom_line(d / REPORT) is None


# --- QA verdict ------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Review body...\n\nVerdict: SHIP\n", "SHIP"),
    ("Verdict: BLOCK — not a valid deliverable\n", "BLOCK"),
    ("Verdict: FIX-FIRST\n", "FIX-FIRST"),
    ("no verdict anywhere", None),
])
def test_extract_qa_verdict(run_dir_factory, text, expected):
    d = run_dir_factory(files={QA: text})
    assert C.extract_qa_verdict(d / QA) == expected


# --- the halt invariant ----------------------------------------------------
@pytest.mark.parametrize("halt_file,reason", [
    ("HALT_provenance.md", "provenance_gate"),
    ("HALT_no_intersection.md", "no_specificity"),
])
def test_halt_is_not_a_failure(run_dir_factory, halt_file, reason):
    d = run_dir_factory(halt_file)
    out = C.classify(d)
    assert out.status == C.STATUS_HALTED
    assert out.reason == reason
    assert out.is_deliverable is True


def test_halt_outranks_timeout(run_dir_factory):
    d = run_dir_factory("HALT_provenance.md")
    assert C.classify(d, timed_out=True).status == C.STATUS_HALTED


def test_cancelled_outranks_halt(run_dir_factory):
    d = run_dir_factory("HALT_provenance.md")
    assert C.classify(d, cancelled=True).status == C.STATUS_CANCELLED


# --- success / failure ----------------------------------------------------
def test_report_plus_pdf_is_completed(run_dir_factory):
    d = run_dir_factory(PDF, files={REPORT: BOTTOM_LINE_REPORT})
    out = C.classify(d)
    assert out.status == C.STATUS_COMPLETED
    assert out.is_deliverable is True
    assert out.verdict.startswith("Promising but unproven.")


def test_qa_block_fails_even_with_report_and_pdf(run_dir_factory):
    d = run_dir_factory(PDF, files={REPORT: BOTTOM_LINE_REPORT, QA: "Verdict: BLOCK\n"})
    out = C.classify(d)
    assert out.status == C.STATUS_FAILED
    assert out.reason == "qa_block"
    assert out.qa_verdict == "BLOCK"


def test_report_without_pdf_is_incomplete_pdf(run_dir_factory):
    d = run_dir_factory(files={REPORT: BOTTOM_LINE_REPORT})
    out = C.classify(d)
    assert out.status == C.STATUS_FAILED
    assert out.reason == "incomplete_pdf"


def test_no_report_is_incomplete_and_names_furthest_artifact(run_dir_factory):
    d = run_dir_factory("step1_target_list_A.md", "step3_hub_targets.md")
    out = C.classify(d)
    assert out.status == C.STATUS_FAILED
    assert out.reason == "incomplete"
    assert "step3_hub_targets.md" in out.detail


def test_timeout_without_halt(run_dir_factory):
    d = run_dir_factory("step1_target_list_A.md")
    assert C.classify(d, timed_out=True).status == C.STATUS_TIMED_OUT


# --- infra failures stay a PLATFORM concern -------------------------------
@pytest.mark.parametrize("err,reason", [
    ("Your credit balance is too low to access the API", "insufficient_credit"),
    ("authentication_error: invalid x-api-key", "auth_failed"),
    ("rate_limit exceeded", "rate_limited"),
    ("Error: overloaded", "api_overloaded"),
    ("something unrelated", None),
])
def test_detect_infra_failure(err, reason):
    got = C.detect_infra_failure(err)
    assert (got[0] if got else None) == reason


def test_infra_failure_says_pipeline_did_not_fail(run_dir_factory):
    d = run_dir_factory("step1_target_list_A.md")
    out = C.classify(d, agent_error="credit balance is too low")
    assert out.reason == "insufficient_credit"
    assert "did not fail" in out.detail


# --- artifact collection --------------------------------------------------
def test_collect_artifacts_excludes_transient_dirs(run_dir_factory):
    d = run_dir_factory(
        REPORT, "figures/step1.png",
        "_pdf_preview/page_1.png", "geo_tmp/x.soft", "tool-results/dump.json",
        "scripts/__pycache__/x.pyc",
    )
    names = {a["name"] for a in C.collect_artifacts(d)}
    assert names == {REPORT, "figures/step1.png"}
