# agent-harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `MOA_AG_Reserach/Schollar_System/` into a standalone repository named `agent-harness` whose container build context is self-contained, and replace the MOA-specific knowledge in its service layer with a payload-declared manifest, so the harness can run any agent core.

**Architecture:** An *agent core* is a self-describing directory (`CLAUDE.md` + `.claude/` + optional python packages + `agent-core.yaml`). The harness is a generic Python package that reads the manifest and supplies everything payload-specific — run-directory naming, progress milestones, terminal-state rules, the trigger prompt, CLI inputs, required paths and reference data. A three-stage Dockerfile copies a selected core into `/app/`, the harness into `/opt/harness/`, and nothing reaches above the repo root.

**Tech Stack:** Python 3.12, `claude-agent-sdk`, `pyyaml`, pytest, Docker/BuildKit, micromamba, Node 24 (Claude Code CLI), AWS SAM/CloudFormation (untouched except env names).

**Spec:** `docs/superpowers/specs/2026-10-01-agent-harness-extraction-design.md` — read it before Task 1. Every task argues from it.

## Global Constraints

- **Python 3.12.** The conda env name is payload-declared (`python.conda_env`), not hard-coded.
- **New dependencies allowed in the harness: `pyyaml` only.** No pydantic, no jinja2 — the manifest loader uses `pyyaml` + dataclasses, and the template renderer is ~40 lines of `str` work.
- **No optional variants** (project CLAUDE.md §5). A missing manifest, a missing required path, or unobtainable required reference data **fails loudly**. Never warn-and-continue.
- **A halt is a valid outcome, never a failure.** Exit code 10. This invariant must survive every refactor in this plan.
- **Golden tests are written before the code they protect moves**, must pass unchanged afterwards, and may never be edited to accommodate a refactor. If a golden test fails after a refactor, the refactor is wrong.
- **Module name is `harness`** everywhere — natively and in-container. The old `app.` / `service.` split is retired.
- **Env prefix is `HARNESS_*`.** The only `MOA_*` variables that survive are `MOA_RUN_DIR` and `MOA_CJK_FONT`, both payload-declared, because `MOA_AG_Reserach/CLAUDE.md` reads them and must not be edited.
- **`MOA_AG_Reserach/CLAUDE.md` is not modified by this plan.** If a task appears to require editing it, the task is wrong.
- **Two repos are in play.** `OLD` = `D:\Dev\projects\MOA_AG_Reserach`, `NEW` = `D:\Dev\projects\agent-harness`. `OLD/Schollar_System/` is kept frozen as a rollback path and is never deleted by this plan.
- **Commit after every task.** Conventional-commit prefixes (`test:`, `feat:`, `refactor:`, `chore:`, `docs:`).
- **NO git submodule, and nothing is pushed to `MOA_AG_Reserach`.** Cores are plain
  drop-in directories under `cores/`. The MOA core is **copied** to `cores/moa-ag/`
  and is **git-ignored** in the harness repo. Rationale: the harness must not depend
  on one payload's repository to build or to test itself, and coupling the build to
  a remote submodule ref was the only thing in this plan that required pushing to a
  shared default branch. A submodule remains available later, purely as a
  reproducibility option, and is documented as such — it is not on the critical path.
- **The harness's own committed test suite must pass with `hello-core` alone.** Tests
  that need the MOA core **skip** when `cores/moa-ag/` is absent (it is not
  committed). A fresh clone must therefore be green without any payload present —
  that property is the genericity claim, stated as a test rather than a README
  sentence.
- **`agent-harness` is a PRIVATE GitHub repo.** It carries AWS infra templates,
  deploy scripts and API config. Scan for committed secrets before the first push.

---

## File Structure

### Phase A — tests land in the OLD repo first (so they pin current behaviour)

| File | Responsibility |
|---|---|
| `OLD/Schollar_System/runner/tests/conftest.py` | pytest path setup + shared run-directory fixture factory |
| `OLD/Schollar_System/runner/tests/test_naming_golden.py` | pins `naming.base_name` + `_next_for_base` |
| `OLD/Schollar_System/runner/tests/test_classify_golden.py` | pins `classify`, `extract_bottom_line`, `extract_qa_verdict` |
| `OLD/Schollar_System/runner/tests/test_progress_golden.py` | pins milestone emission, phase-start-once, monotonic percent |
| `OLD/Schollar_System/runner/tests/test_prompt_golden.py` | pins rendered prompts byte-for-byte via snapshot files |
| `OLD/Schollar_System/runner/tests/snapshots/*.txt` | the byte-exact expected prompts |
| `OLD/Schollar_System/runner/tests/test_cli_golden.py` | pins today's `run_once` CLI contract |

### Phase B onward — the NEW repo

| File | Responsibility |
|---|---|
| `NEW/harness/manifest.py` | load + validate `agent-core.yaml` (schema 1); the single source of payload truth |
| `NEW/harness/templates.py` | the tiny `{field\|filter}` renderer used by `naming` and `prompt` |
| `NEW/harness/preflight.py` | manifest-driven environment validation (replaces hard-coded asserts in `entrypoint.sh`) |
| `NEW/harness/naming.py` | generic: slug + session scan + `run_dir` template resolution |
| `NEW/harness/progress.py` | generic watcher; milestones injected |
| `NEW/harness/classify.py` | generic classifier; halts/success/headline/qa injected. Keeps `_INFRA_FAILURES` (platform-owned) |
| `NEW/harness/prompt.py` | loads payload prompt templates; owns the default probe template |
| `NEW/harness/run_once.py` | CLI built from `inputs[]` |
| `NEW/harness/worker.py` | SQS body → `inputs[]` |
| `NEW/harness/config.py` | `HARNESS_*` settings + core/manifest resolution |
| `NEW/harness/smoke_test.py` | `$0` image validation, manifest-driven |
| `NEW/harness/claude_runner.py`, `cloud.py`, `events.py`, `sanitize.py`, `task_protection.py` | **moved unchanged** |
| `NEW/container/Dockerfile` | 3 stages; every `COPY` resolves inside the repo root |
| `NEW/container/requirements/platform.txt` | service-layer deps only |
| `NEW/cores/slot/` | gitignored copy-paste slot (default `HARNESS_CORE`) |
| `NEW/cores/hello-core/` | the genericity proof |
| `NEW/manifests/` | sidecar manifests, outside `cores/` so it can't be mistaken for a core |
| `OLD/agent-core.yaml` | MOA-AG declares itself |
| `OLD/.agent-core/prompt_run.md` | the MOA trigger prompt, moved out of harness code |
| `OLD/runner-requirements/{base,omics,full}.txt` | the scientific dependency tiers |

---

## Phase A — Pin current behaviour

### Task 1: pytest scaffold + `naming` golden tests

**Files:**
- Create: `OLD/Schollar_System/runner/tests/conftest.py`
- Create: `OLD/Schollar_System/runner/tests/test_naming_golden.py`
- Create: `OLD/Schollar_System/runner/pytest.ini`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: a `tests/` package importable as `from app import naming`; the `run_dir_factory` fixture reused by Tasks 2 and 3 with signature `run_dir_factory(*filenames: str, files: dict[str, str] | None = None) -> Path` — positional args become placeholder files, `files` maps filename → exact content. Both accept nested paths (`"figures/step1.png"`). **Note:** an earlier draft of this line said `**contents: str`; that was wrong, and every call site in Tasks 2 and 3 uses `files={...}`.

- [ ] **Step 1: Create the pytest config and conftest**

`OLD/Schollar_System/runner/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

`OLD/Schollar_System/runner/tests/conftest.py`:

```python
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
    """Build a fake run directory.

    Positional args are filenames created with placeholder content, for tests that
    only care whether a file exists. `files` maps filename -> exact content, for
    tests that read it back. Both accept nested paths ("figures/step1.png").
    """

    def _make(*filenames: str, files: dict[str, str] | None = None) -> Path:
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
```

- [ ] **Step 2: Write the failing naming tests**

`OLD/Schollar_System/runner/tests/test_naming_golden.py`:

```python
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
```

- [ ] **Step 3: Run the tests — they should PASS against current code**

Run: `cd OLD/Schollar_System/runner && conda run -n moa python -m pytest tests/test_naming_golden.py -v`

Expected: **all PASS.** These pin existing behaviour, so a failure here means the test encodes a wrong expectation — read `app/naming.py` and fix the test, not the module.

- [ ] **Step 4: Commit**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/runner/pytest.ini Schollar_System/runner/tests/
git commit -m "test: pin run-directory naming behaviour before the agent-harness extraction

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `classify` golden tests

**Files:**
- Create: `OLD/Schollar_System/runner/tests/test_classify_golden.py`

**Interfaces:**
- Consumes: `run_dir_factory` fixture from Task 1
- Produces: nothing consumed by later tasks (a pure gate)

- [ ] **Step 1: Write the failing tests**

`OLD/Schollar_System/runner/tests/test_classify_golden.py`:

```python
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
```

- [ ] **Step 2: Run the tests**

Run: `cd OLD/Schollar_System/runner && conda run -n moa python -m pytest tests/test_classify_golden.py -v`

Expected: all PASS. If `test_extract_bottom_line_heading_depth_and_case` fails for `####`, read the regex at `app/classify.py:58` (`#{1,4}`) and correct the test to match reality — do not change the module.

- [ ] **Step 3: Commit**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/runner/tests/test_classify_golden.py
git commit -m "test: pin terminal-state classification, including halt-is-not-failure

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `progress` golden tests

**Files:**
- Create: `OLD/Schollar_System/runner/tests/test_progress_golden.py`

**Interfaces:**
- Consumes: `run_dir_factory` from Task 1
- Produces: `RecordingEmitter` test double — reused in no later task, but its shape documents the `EventEmitter.emit(type, message, **fields)` contract that Task 11 must preserve

- [ ] **Step 1: Write the failing tests**

`OLD/Schollar_System/runner/tests/test_progress_golden.py`:

```python
"""Golden tests for filesystem-driven progress.

Progress comes from artifact appearance, not model prose. These pin the
milestone table, the emit-once rule, and percent monotonicity.
"""

from __future__ import annotations

from app import progress as P


class RecordingEmitter:
    """Stands in for events.EventEmitter — records (type, message, fields)."""

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, event_type: str, message: str = "", **fields):
        self.events.append((event_type, message, fields))

    def types(self) -> list[str]:
        return [e[0] for e in self.events]

    def artifacts(self) -> list[str]:
        return [e[2]["artifact"] for e in self.events if "artifact" in e[2]]


def _write(d, name: str, body: str = "x"):
    p = d / name
    p.write_text(body, encoding="utf-8")


def test_milestone_table_is_ordered_and_ends_at_100():
    percents = [m.percent for m in P.MILESTONES]
    assert percents == sorted(percents), "milestones must be non-decreasing"
    assert percents[-1] == 100
    assert P.MILESTONES[-1].filename == "result.pdf"
    assert len(P.MILESTONES) == 14


def test_halt_files_are_known():
    assert set(P.HALT_FILES) == {"HALT_provenance.md", "HALT_no_intersection.md"}


def test_each_milestone_emits_once(run_dir_factory):
    d = run_dir_factory()
    em = RecordingEmitter()
    w = P.ProgressWatcher(d, em, poll_seconds=0.01)

    _write(d, "step1_target_list_A.md")
    w.scan()
    w.scan()  # second scan must not re-emit

    assert em.artifacts().count("step1_target_list_A.md") == 1


def test_phase_started_emitted_once_per_phase(run_dir_factory):
    d = run_dir_factory()
    em = RecordingEmitter()
    w = P.ProgressWatcher(d, em, poll_seconds=0.01)

    # Three milestones, all in the "mechanism" phase.
    for name in ("step4_moa_summary.md", "step4_moa_table.md", "step4_signature_reversal.md"):
        _write(d, name)
        w.scan()

    assert em.types().count("phase.started") == 1


def test_empty_file_is_not_a_milestone(run_dir_factory):
    d = run_dir_factory()
    em = RecordingEmitter()
    w = P.ProgressWatcher(d, em, poll_seconds=0.01)
    (d / "step1_target_list_A.md").write_text("", encoding="utf-8")
    w.scan()
    assert em.artifacts() == []


def test_percent_is_monotonic_under_out_of_order_writes(run_dir_factory):
    d = run_dir_factory()
    em = RecordingEmitter()
    w = P.ProgressWatcher(d, em, poll_seconds=0.01)

    _write(d, "result.pdf")          # 100 first
    w.scan()
    _write(d, "step0_provenance.md")  # 5 second — must NOT walk back
    w.scan()

    assert w.percent == 100


def test_halt_file_emits_run_halted(run_dir_factory):
    d = run_dir_factory()
    em = RecordingEmitter()
    w = P.ProgressWatcher(d, em, poll_seconds=0.01)
    _write(d, "HALT_provenance.md")
    w.scan()
    w.scan()
    assert em.types().count("run.halted") == 1


def test_missing_run_dir_is_a_noop(tmp_path):
    em = RecordingEmitter()
    w = P.ProgressWatcher(tmp_path / "nope", em, poll_seconds=0.01)
    w.scan()
    assert em.events == []
```

- [ ] **Step 2: Run the tests**

Run: `cd OLD/Schollar_System/runner && conda run -n moa python -m pytest tests/test_progress_golden.py -v`

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/runner/tests/test_progress_golden.py
git commit -m "test: pin filesystem-driven progress milestones

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `prompt` byte-identical snapshot tests

**Files:**
- Create: `OLD/Schollar_System/runner/tests/test_prompt_golden.py`
- Create: `OLD/Schollar_System/runner/tests/snapshots/` (generated in Step 2)

**Interfaces:**
- Consumes: nothing
- Produces: `tests/snapshots/{run_basic,run_extra,probe_default,probe_custom}.txt` — the byte-exact expected prompts that Task 13 must still reproduce

- [ ] **Step 1: Write the test, which generates snapshots on first run**

`OLD/Schollar_System/runner/tests/test_prompt_golden.py`:

```python
"""Byte-identical snapshot tests for the trigger prompts.

Rationale: the prompt IS the interface to the agent. A whitespace change can
alter behaviour, so the refactor that moves this text into payload-owned
template files must reproduce it exactly. Set REGEN=1 to (re)write snapshots;
never do that to make a failing test pass after the refactor.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import prompt as PR

SNAP = Path(__file__).parent / "snapshots"


def _check(name: str, actual: str):
    SNAP.mkdir(exist_ok=True)
    path = SNAP / f"{name}.txt"
    if os.environ.get("REGEN") == "1" or not path.exists():
        path.write_text(actual, encoding="utf-8", newline="\n")
        pytest.skip(f"wrote snapshot {path.name} — re-run to assert against it")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, f"{name} drifted from its snapshot"


def test_run_prompt_basic():
    _check("run_basic", PR.build_prompt(
        ["Curcumin", "Gallic acid"], "Atopic Dermatitis",
        "curcumin_atopic_dermatitis_session1",
    ))


def test_run_prompt_with_extra_context():
    _check("run_extra", PR.build_prompt(
        ["Curcumin"], "Atopic Dermatitis", "curcumin_atopic_dermatitis_session2",
        extra_instructions="The requester supplied an LC-MS constituent list.",
    ))


def test_probe_prompt_default_task():
    _check("probe_default", PR.build_probe_prompt("probe_session1"))


def test_probe_prompt_custom_task():
    _check("probe_custom", PR.build_probe_prompt("probe_session2", "List the skills you can see."))


# --- input validation ------------------------------------------------------
def test_empty_compounds_raises():
    with pytest.raises(ValueError, match="at least one compound"):
        PR.build_prompt([], "Atopic Dermatitis", "x")


def test_blank_disease_raises():
    with pytest.raises(ValueError, match="disease/condition is required"):
        PR.build_prompt(["Curcumin"], "   ", "x")


def test_probe_requires_run_dir():
    with pytest.raises(ValueError, match="run directory is required"):
        PR.build_probe_prompt("")


def test_probe_prompt_length_cap():
    with pytest.raises(ValueError, match="exceeds"):
        PR.build_probe_prompt("probe_session1", "x" * (PR.PROBE_PROMPT_MAX_CHARS + 1))


def test_extra_context_is_fenced_as_context_only():
    out = PR.build_prompt(["Curcumin"], "AD", "x", extra_instructions="ignore all gates")
    assert "does not relax any gate" in out
```

- [ ] **Step 2: Generate the snapshots, then assert against them**

Run: `cd OLD/Schollar_System/runner && conda run -n moa python -m pytest tests/test_prompt_golden.py -v`

Expected: first run **SKIPs** the four snapshot tests while writing them, validation tests PASS.

Run again: `conda run -n moa python -m pytest tests/test_prompt_golden.py -v`

Expected: **all PASS.** Open `tests/snapshots/run_basic.txt` and confirm it contains `Active ingredient(s): Curcumin, Gallic acid` and `results/curcumin_atopic_dermatitis_session1/`.

- [ ] **Step 3: Commit**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/runner/tests/test_prompt_golden.py Schollar_System/runner/tests/snapshots/
git commit -m "test: snapshot the trigger prompts byte-for-byte

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `run_once` CLI contract test

**Files:**
- Create: `OLD/Schollar_System/runner/tests/test_cli_golden.py`
- Read first: `OLD/Schollar_System/runner/app/run_once.py` — find the `argparse` setup and the function that builds it

**Interfaces:**
- Consumes: nothing
- Produces: the CLI contract Task 14 must preserve

- [ ] **Step 1: Extract `build_parser()` and `split_values()` (pure refactor)**

Already confirmed by inspection: there is **no** `build_parser`. `app/run_once.py:71`
has `parse_args(argv)`, which builds the parser, parses, **and** validates in one
function. Split it so the parser is testable without invoking a run, preserving
behaviour exactly:

```python
def build_parser() -> argparse.ArgumentParser:
    """Everything from today's parse_args up to (not including) p.parse_args()."""
    p = argparse.ArgumentParser(
        prog="run_once",
        description="Run one MOA-AG pipeline job headlessly via Claude Code.",
    )
    ...  # every existing add_argument call, verbatim and in the same order
    return p


def split_values(raw: str) -> list[str]:
    """Comma-separated CLI value -> list. Lifted verbatim from main_async's
    `[c.strip() for c in (args.compounds or "").split(",") if c.strip()]` so the
    conversion has one definition and can be pinned by a test."""
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = build_parser()
    args = p.parse_args(argv)
    # Conditional, NOT argparse `required=True`: --kind probe needs neither value.
    if args.kind == "moa" and not (args.compounds.strip() and args.disease.strip()):
        p.error("--compounds and --disease are required for --kind moa")
    ...  # any remaining existing validation, unchanged
    return args
```

Then replace the inline list comprehension at `app/run_once.py:413` with
`compounds = split_values(args.compounds)`. Commit this extraction on its own
before writing the test.

> **The CLI contract this pins, which Task 14 MUST NOT change:** `--compounds` is a
> single **comma-separated string** (`--compounds "Gallic acid,Phellopterin"`), with
> `default=""`. It is NOT `nargs="+"`. `worker.py:128` depends on it
> (`compounds=",".join(compounds)`) and so does `doc/API_PROTOCOL.md`. When Task 14
> generates arguments from a manifest `string_list` input, it generates **this**
> shape — a single string split by `split_values` — not `nargs="+"`. Changing the
> CLI shape mid-refactor would violate the Global Constraint that today's exact CLI
> still parses.

- [ ] **Step 2: Write the test**

`OLD/Schollar_System/runner/tests/test_cli_golden.py`:

```python
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
```

Before running, read `app/run_once.py:71-101` and confirm every asserted attribute
and default matches. **If any expectation above disagrees with the module, change
the test to match the module and report it** — the point is to pin reality.

- [ ] **Step 3: Run the tests**

Run: `cd OLD/Schollar_System/runner && conda run -n moa python -m pytest tests/ -v`

Expected: **the whole Phase-A suite PASSES.** Record the test count — Task 6 must reproduce it exactly.

- [ ] **Step 4: Commit**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/runner/app/run_once.py Schollar_System/runner/tests/test_cli_golden.py
git commit -m "test: pin the run_once CLI contract

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Phase B — Extract to the new repo

### Task 6: create `agent-harness`, move files, rename the package

**Files:**
- Create: `NEW/` (whole repo)
- Move: everything from `OLD/Schollar_System/` per the mapping below
- Modify: every `from .x import` / `from app.x import` → `from harness.x import`

**Interfaces:**
- Consumes: the Phase-A test suite (travels to `NEW/tests/`)
- Produces: `NEW` repo where `conda run -n moa python -m pytest tests/ -v` passes with the same count as Task 5 Step 3

- [ ] **Step 1: Create the repo and copy the tree**

```bash
mkdir -p /d/Dev/projects/agent-harness
cd /d/Dev/projects/agent-harness
git init -b main
cp -r /d/Dev/projects/MOA_AG_Reserach/Schollar_System/. .

# --- Drop build detritus that should never have been in the tree ---
find . -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf frontend-amplify/.expo frontend-amplify/dist frontend-amplify/frontend-dist.zip

# --- SECRETS: delete before the first `git add`, not after ---
# A secret committed and then removed still lives in the history. All four of
# these were found by an explicit scan of the source tree; .env.example is the
# only env file that is meant to be tracked.
rm -f runner/.env
rm -f frontend-ref/.env          # a second .env the first draft of this plan missed
rm -rf infra/.aws-sam            # SAM build output; contains a built copy of the handler config

# --- Verify the tree is clean before anything is staged ---
echo "--- env files remaining (expect ONLY .env.example) ---"
find . -name '.env' -o -name '.env.*' | grep -v node_modules
echo "--- credential-shaped strings (expect NO output) ---"
grep -rIlE 'sk-ant-[A-Za-z0-9_-]{10}|AKIA[0-9A-Z]{16}|gh[pous]_[A-Za-z0-9]{20}|-----BEGIN [A-Z ]*PRIVATE KEY-----' \
    . 2>/dev/null | grep -v node_modules
echo "--- end scan ---"
```

**If either scan prints anything other than `.env.example`, stop and report it.**
Do not stage, commit or push until the tree is clean. A secret reaches the remote
on the first push and is then effectively public regardless of later deletion.

> Note on AWS account ids: `infra/config.yaml` and `infra/NEXT_STEPS.md` contain the
> account numbers `830278488932` and `712035115112`. These stay — they are not
> credentials, and the repo is private. They are, however, a concrete reason the
> private choice was correct.

- [ ] **Step 2: Move to the target layout**

```bash
cd /d/Dev/projects/agent-harness
mkdir -p harness container cores/slot manifests tests
git mv 2>/dev/null; true      # nothing tracked yet; plain mv below

mv runner/app/*.py              harness/
mv runner/smoke_test.py         harness/smoke_test.py
mv runner/tests/*               tests/
mv runner/pytest.ini            pytest.ini
mv runner/Dockerfile runner/docker-compose.yml runner/entrypoint.sh \
   runner/run_local.ps1 runner/.env.example  container/
mv runner/requirements          container/requirements
mv runner/container/conda container/conda
mv runner/container/conda-init.sh container/conda-init.sh
mv watch_run.ps1 container/watch_run.ps1 2>/dev/null || true
rmdir runner/container runner/app 2>/dev/null || true
rm -rf runner
```

- [ ] **Step 3: Rename the package in every import**

```bash
cd /d/Dev/projects/agent-harness
# Relative imports inside the package are unchanged (`from .events import ...`).
# Absolute ones, and the tests, move from `app` to `harness`.
grep -rln "from app\.\|import app\.\|from app import\|app\.run_once\|app\.worker\|service\.run_once\|service\.worker" \
    harness tests container doc *.md 2>/dev/null \
  | xargs sed -i \
      -e 's/\bfrom app import\b/from harness import/g' \
      -e 's/\bfrom app\./from harness./g' \
      -e 's/\bimport app\./import harness./g' \
      -e 's/\bapp\.run_once\b/harness.run_once/g' \
      -e 's/\bapp\.worker\b/harness.worker/g' \
      -e 's/\bservice\.run_once\b/harness.run_once/g' \
      -e 's/\bservice\.worker\b/harness.worker/g' \
      -e 's/\bservice\.smoke_test\b/harness.smoke_test/g'
```

Then fix `tests/conftest.py`: the `sys.path` insert pointed at `runner/`; it now
points at the repo root.

```python
# tests/conftest.py — replace the path line with:
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

(That is already correct relative to the new location — `tests/` is now directly
under the repo root — so verify rather than assume.)

- [ ] **Step 4: Run the suite in the new location**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/ -v`

Expected: **same pass count as Task 5 Step 3.** Any failure here is a move error, not a behaviour change — the modules were not edited.

- [ ] **Step 5: Add `.gitignore` and `.dockerignore`**

`NEW/.gitignore`:

```gitignore
# Secrets
.env
.env.*
!.env.example

# The copy-paste core slot: never committed. Cores are pinned as submodules.
cores/slot/*
!cores/slot/README.md

# Node
node_modules/
dist/
build/
.next/
*.tsbuildinfo
npm-debug.log*
yarn-error.log*

# Lambda bundles / SAM output
*.zip
backend-handler/.aws-sam/
infra/.aws-sam/
infra/packaged.yaml

# Amplify
frontend-amplify/.amplify/
frontend-amplify/amplify_outputs.json
frontend-amplify/.expo/

# Python
__pycache__/
*.py[cod]
.pytest_cache/

# Local run output
out/
```

`NEW/.dockerignore` — **generic patterns only**; everything payload-specific is
declared in a core's `agent-core.yaml` (`image.exclude`) and applied in the
Dockerfile's `core-stage`:

```dockerignore
# Build context = this repo root. Only generic, universally-irrelevant things
# belong here: .dockerignore is static and cannot read a core's manifest.
.git
.gitignore
.github

# Run output — never part of an image.
results/
reviews/
reviews_archive/
out/

# The harness's own agent config must NEVER ship in the image: the image
# carries the CORE's CLAUDE.md, and a second one would corrupt every run.
CLAUDE.md
.claude/

# Tests and docs are not runtime.
tests/
doc/
docs/

# The product layer builds its own bundles.
frontend-amplify/
backend-handler/node_modules/
infra/.aws-sam/
**/.env

# Python / editor / OS noise
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ipynb_checkpoints/
.venv/
venv/
env/
.vscode/
.idea/
.DS_Store
Thumbs.db
desktop.ini
*.log
```

> Note: `CLAUDE.md` and `.claude/` are excluded **at the context level**, which is
> the strongest available guarantee that the harness's own agent config cannot
> reach the image. Task 17's smoke test asserts it independently.

- [ ] **Step 6: Create `cores/slot/README.md`**

```markdown
# The agent-core slot

Drop any agent core in this directory and build — the image packs whatever is
here. A core is a directory containing, at minimum:

- `CLAUDE.md` (or whatever `agent.instructions` in its manifest names)
- `agent-core.yaml` — the manifest. See `../../doc/ADDING_A_CORE.md`.

```bash
cp -r /path/to/my-core/. cores/slot/
docker compose -f container/docker-compose.yml build
```

Nothing here is committed (see `.gitignore`). For a reproducible,
commit-pinned core, add it as a submodule under `cores/<name>/` instead and
build with `HARNESS_CORE=<name>`.
```

- [ ] **Step 7: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add -A
git commit -m "chore: extract the harness from MOA_AG_Reserach/Schollar_System

Self-contained build context: every COPY now resolves inside this repo root.
Package renamed app/ -> harness/, retiring the app. vs service. module split
that differed between the native and container run paths.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: freeze the old copy; add the submodule

**Files:**
- Create: `OLD/Schollar_System/MOVED.md`
- Create: `NEW/CLAUDE.md`
- Create: `NEW/.claude/` (minimal)
- Modify: `NEW/.gitmodules` (via `git submodule add`)

**Interfaces:**
- Consumes: the `NEW` repo from Task 6
- Produces: `cores/moa-ag/` populated; `HARNESS_CORE=moa-ag` resolvable

- [ ] **Step 1: Mark the old tree dead**

`OLD/Schollar_System/MOVED.md`:

```markdown
# MOVED — this tree is frozen

This directory has been extracted into its own repository:

    D:\Dev\projects\agent-harness   (github.com/Joseph-tsai415/agent-harness)

**Do not edit anything here.** It is retained only as a rollback path: it still
builds the pre-extraction image. The canonical service layer, container and
deployment code live in `agent-harness`, which consumes this repository as an
*agent core* (pinned at `cores/moa-ag/`).

What this repository provides to the harness:

| File | Purpose |
|---|---|
| `agent-core.yaml` | the manifest — how the harness runs this core |
| `.agent-core/prompt_run.md` | the trigger prompt |
| `runner-requirements/*.txt` | the scientific dependency tiers |

Frozen on 2026-10-01.
```

- [ ] **Step 2: Add the harness's own agent config**

`NEW/CLAUDE.md`:

```markdown
# agent-harness — operating manual

A harness that packages an **agent core** into a container and runs it
headlessly with Claude Code as the task runner. The harness is payload-agnostic;
everything domain-specific is declared by the core in its `agent-core.yaml`.

## The boundary rule

**Nothing in `harness/` may contain payload-specific knowledge.** No artifact
filenames, no domain vocabulary, no package names belonging to a core. If you
find yourself about to hard-code one, it belongs in the manifest schema instead
(`harness/manifest.py`) and in that core's `agent-core.yaml`.

The one exception is `classify._INFRA_FAILURES` — credit exhaustion, auth
failure, rate limiting and API overload are platform concerns and stay here.

## Layout

| Path | What |
|---|---|
| `harness/` | the python package; `python -m harness.run_once` |
| `container/` | Dockerfile, compose, entrypoint, requirements (platform only) |
| `cores/slot/` | gitignored copy-paste core slot (default) |
| `cores/<name>/` | submodule-pinned cores |
| `manifests/` | sidecar manifests for cores you cannot modify |
| `backend-handler/`, `infra/`, `frontend-amplify/` | the Schollar reference service |
| `tests/` | golden tests — see below |

## Golden tests are not negotiable

`tests/` pins behaviour that predates the genericization. **Never edit a golden
test to make it pass.** If one fails, the change is wrong.

```bash
conda run -n moa python -m pytest tests/ -v
```

## Three outcomes, not two

A run ends `completed`, **`halted`**, or `failed`. A halt means the core's own
gate fired and is a VALID result (exit code 10), never an error. Any code that
treats `halted` as a red error is a bug.

## Adding a core

See `doc/ADDING_A_CORE.md`.
```

`NEW/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(conda run -n moa python -m pytest:*)",
      "Bash(docker compose:*)",
      "Bash(git status)",
      "Bash(git diff:*)"
    ]
  }
}
```

- [ ] **Step 3: Drop the MOA core in as a plain directory (no submodule)**

The harness must not need a payload's repository to build or test itself, so a
core is just a directory. `cores/moa-ag/` is **git-ignored** — it is a local
working copy, not harness content.

```bash
cd /d/Dev/projects/agent-harness
mkdir -p cores/moa-ag
# Copy the agent core only. Exclude run output, the frozen harness copy, and
# git metadata: .dockerignore and the manifest's image.exclude both guard this
# too, but there is no reason to copy 10 GB of results to delete it later.
rsync -a --delete \
  --exclude '.git/' --exclude 'results/' --exclude 'reviews/' \
  --exclude 'reviews_archive/' --exclude 'Schollar_System/' \
  --exclude 'docs/' --exclude 'validation/' --exclude '.superpowers/' \
  --exclude '__pycache__/' \
  /d/Dev/projects/MOA_AG_Reserach/ cores/moa-ag/
ls cores/moa-ag/CLAUDE.md cores/moa-ag/moa_lib
```

If `rsync` is unavailable in Git Bash, use
`cp -r /d/Dev/projects/MOA_AG_Reserach/. cores/moa-ag/` followed by
`rm -rf cores/moa-ag/{.git,results,reviews,reviews_archive,Schollar_System,docs,validation,.superpowers}`.

Then record whether the 322 MB reference file came along — it is **not** in git,
so whether it is present depends on whether the download script has ever been run
on this machine. Both outcomes are valid and Task 16 handles each:

```bash
ls -la cores/moa-ag/.claude/skills/mirna-targets/data/ 2>&1 | head
```

Note the result in your report: **present** → Task 16's build uses it with zero
network; **absent** → Task 16's `core-stage` provisions it (the path this plan
exists to make work).

- [ ] **Step 4: Ignore the core copies, keep `hello-core` committed**

Append to `NEW/.gitignore` (replacing the `cores/slot/*` block from Task 6):

```gitignore
# Cores are drop-in payloads, not harness content: a local working copy of
# someone's agent core does not belong in this repo's history. hello-core is the
# exception — it IS harness content: the reference core the test suite runs on.
cores/*
!cores/slot/
!cores/hello-core/
cores/slot/*
!cores/slot/README.md
```

- [ ] **Step 5: Commit both repos (no push to MOA_AG_Reserach)**

```bash
cd /d/Dev/projects/agent-harness
git add -A && git commit -m "chore: add harness CLAUDE.md; cores are git-ignored drop-ins

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"

cd /d/Dev/projects/MOA_AG_Reserach
git add Schollar_System/MOVED.md
git commit -m "docs: freeze Schollar_System; the harness now lives in its own repo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Do not push `MOA_AG_Reserach`, and do not merge its branch.** Operator decision:
the commits stay on the local branch `feat/agent-harness-extraction`, unmerged and
unpushed. `MOA_AG_Reserach` is a **public** repo and the harness code does not
belong in it; only `agent-core.yaml`, `.agent-core/`, `runner-requirements/` and
`MOVED.md` do, and those stay on the branch too until the operator says otherwise.

- [ ] **Step 6: Create the PRIVATE GitHub repo and push the harness**

Only after the Step 1 secret scan came back clean (`.env.example` and nothing else).

```bash
cd /d/Dev/projects/agent-harness
gh repo create agent-harness --private --source=. --remote=origin --push
gh repo view --json nameWithOwner,visibility,isPrivate
```

Expected: `"visibility":"PRIVATE"`, `"isPrivate":true`. **If it reports PUBLIC, stop
and report it** — the repo carries `infra/` CloudFormation templates, deploy scripts
and AWS account ids, and flipping a repo private after a push does not un-publish
what was already fetched or indexed.

`gh` is already authenticated as `Joseph-tsai415` with `repo` scope (verified).

---

## Phase C — The manifest

### Task 8: `manifest.py` — load and validate schema 1

**Files:**
- Create: `NEW/harness/manifest.py`
- Create: `NEW/tests/test_manifest.py`
- Modify: `NEW/container/requirements/platform.txt` (add `pyyaml`)

**Interfaces:**
- Consumes: nothing
- Produces — the API every later task uses:
  - `load_manifest(core_root: Path, *, sidecar_dir: Path | None = None) -> Manifest`
  - `class ManifestError(Exception)`
  - `Manifest` dataclass with attributes: `name: str`, `display_name: str`, `version: str`, `instructions: str`, `setting_sources: list[str]`, `run_dir_env: str`, `defaults: Defaults`, `conda_env: str`, `package_paths: list[str]`, `import_check: list[str]`, `requirements: dict[str, str]`, `default_profile: str`, `inputs: list[InputSpec]`, `run_dir: RunDirSpec`, `prompt_run: str | None`, `prompt_probe: str | None`, `milestones: list[Milestone]`, `halts: dict[str, str]`, `success_requires: list[str]`, `deliverable: str | None`, `headline_artifact: str | None`, `headline_section: str | None`, `qa_artifact: str | None`, `qa_verdicts: list[str]`, `qa_blocking: list[str]`, `required_paths: list[str]`, `reference_data: list[ReferenceData]`, `image_exclude: list[str]`, `image_env: dict[str, str]`, `artifact_exclude: list[str]`
  - `class Milestone` with `artifact: str`, `phase: str`, `percent: int`, `label: str`
  - `class InputSpec` with `name: str`, `type: str`, `required: bool`, `cli: str`, `help: str = ""`, and a `is_list` property (`type == "string_list"`)
  - `class RunDirSpec` with `template: str`, `fallback: str`, `session_suffix: str`, `probe_base: str`
  - `class ReferenceData` with `path: str`, `min_bytes: int`, `required: bool`, `provision: str | None`
  - `class Defaults` with `model: str`, `max_turns: int`, `permission_mode: str`

- [ ] **Step 1: Write the failing tests**

`NEW/tests/test_manifest.py`:

```python
from __future__ import annotations

import textwrap

import pytest

from harness.manifest import ManifestError, load_manifest

MINIMAL = """\
schema: 1
core: {name: tiny, display_name: "Tiny core", version: "0.1"}
agent:
  instructions: CLAUDE.md
  run_dir_env: TINY_RUN_DIR
inputs:
  - {name: topic, type: string, required: true, cli: --topic}
run_dir:
  template: "{topic|slug}"
  fallback: "{topic|slug}"
progress:
  milestones:
    - {artifact: out.md, phase: work, percent: 50, label: "Output"}
    - {artifact: done.md, phase: done, percent: 100, label: "Done"}
outcome:
  success_requires: [done.md]
image:
  required_paths: [CLAUDE.md]
"""


def _core(tmp_path, body: str, name: str = "agent-core.yaml"):
    d = tmp_path / "core"
    d.mkdir(exist_ok=True)
    (d / name).write_text(textwrap.dedent(body), encoding="utf-8")
    (d / "CLAUDE.md").write_text("# tiny\n", encoding="utf-8")
    return d


def test_loads_minimal_manifest(tmp_path):
    m = load_manifest(_core(tmp_path, MINIMAL))
    assert m.name == "tiny"
    assert m.run_dir_env == "TINY_RUN_DIR"
    assert [i.name for i in m.inputs] == ["topic"]
    assert len(m.milestones) == 2
    assert m.success_requires == ["done.md"]


def test_defaults_are_applied(tmp_path):
    m = load_manifest(_core(tmp_path, MINIMAL))
    assert m.setting_sources == ["project"]
    assert m.defaults.permission_mode == "bypassPermissions"
    assert m.conda_env == ""          # absent means "no conda env required"
    assert m.package_paths == []
    assert m.artifact_exclude == []


def test_missing_manifest_raises(tmp_path):
    d = tmp_path / "bare"
    d.mkdir()
    with pytest.raises(ManifestError, match="no agent-core.yaml"):
        load_manifest(d)


def test_sidecar_manifest_is_found(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    (core / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
    side = tmp_path / "manifests"
    side.mkdir()
    (side / "core.yaml").write_text(textwrap.dedent(MINIMAL), encoding="utf-8")
    m = load_manifest(core, sidecar_dir=side)
    assert m.name == "tiny"


def test_wrong_schema_version_raises(tmp_path):
    with pytest.raises(ManifestError, match="schema"):
        load_manifest(_core(tmp_path, MINIMAL.replace("schema: 1", "schema: 2")))


@pytest.mark.parametrize("drop", ["core:", "agent:", "inputs:", "run_dir:", "progress:"])
def test_missing_required_section_names_the_key(tmp_path, drop):
    body = "\n".join(l for l in MINIMAL.splitlines() if not l.startswith(drop))
    with pytest.raises(ManifestError) as exc:
        load_manifest(_core(tmp_path, body))
    assert drop.rstrip(":") in str(exc.value)


def test_non_monotonic_milestones_raise(tmp_path):
    bad = MINIMAL.replace("percent: 50", "percent: 90").replace("percent: 100", "percent: 20")
    with pytest.raises(ManifestError, match="non-decreasing"):
        load_manifest(_core(tmp_path, bad))


def test_duplicate_milestone_artifact_raises(tmp_path):
    bad = MINIMAL.replace("artifact: done.md", "artifact: out.md")
    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(_core(tmp_path, bad))


def test_instructions_file_must_exist(tmp_path):
    d = _core(tmp_path, MINIMAL)
    (d / "CLAUDE.md").unlink()
    with pytest.raises(ManifestError, match="CLAUDE.md"):
        load_manifest(d)


def test_input_referenced_by_template_must_exist(tmp_path):
    bad = MINIMAL.replace('template: "{topic|slug}"', 'template: "{nope|slug}"')
    with pytest.raises(ManifestError, match="nope"):
        load_manifest(_core(tmp_path, bad))


def test_moa_manifest_loads(tmp_path):
    """The real thing, once Task 9 has written it."""
    from pathlib import Path
    core = Path(__file__).resolve().parents[1] / "cores" / "moa-ag"
    if not (core / "agent-core.yaml").exists():
        pytest.skip("cores/moa-ag not populated yet (Task 9)")
    m = load_manifest(core)
    assert m.name == "moa-ag"
    assert len(m.milestones) == 14
    assert set(m.halts) == {"HALT_provenance.md", "HALT_no_intersection.md"}
    assert m.run_dir_env == "MOA_RUN_DIR"
    assert m.conda_env == "moa"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_manifest.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'harness.manifest'`.

- [ ] **Step 3: Implement `harness/manifest.py`**

```python
"""The agent-core manifest — the single source of payload-specific truth.

A core is a directory that describes itself. Everything the harness needs to
know about a payload lives here: what the agent reads, what inputs a run takes,
how run directories are named, which artifacts mark progress, what counts as a
halt, and what the image must contain.

Design rules:
  * Validate EAGERLY and name the offending key. A build that proceeds on a
    half-understood manifest fails later and more expensively.
  * No silent defaults for anything essential. An absent optional section
    yields an empty collection, never an invented value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA = 1
MANIFEST_NAME = "agent-core.yaml"


class ManifestError(Exception):
    """A manifest is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Defaults:
    model: str = ""
    max_turns: int = 0
    permission_mode: str = "bypassPermissions"


@dataclass(frozen=True)
class Milestone:
    artifact: str
    phase: str
    percent: int
    label: str


@dataclass(frozen=True)
class InputSpec:
    name: str
    type: str          # "string" | "string_list"
    required: bool
    cli: str
    help: str = ""     # optional argparse help; a default is generated when absent

    @property
    def is_list(self) -> bool:
        return self.type == "string_list"


@dataclass(frozen=True)
class RunDirSpec:
    template: str
    fallback: str
    session_suffix: str = "_session{n}"
    probe_base: str = "probe"


@dataclass(frozen=True)
class ReferenceData:
    path: str
    min_bytes: int = 1
    required: bool = True
    provision: str | None = None


@dataclass(frozen=True)
class Manifest:
    # identity
    name: str
    display_name: str
    version: str
    # agent
    instructions: str
    setting_sources: list[str]
    run_dir_env: str
    defaults: Defaults
    # python payload
    conda_env: str
    package_paths: list[str]
    import_check: list[str]
    requirements: dict[str, str]
    default_profile: str
    # run shape
    inputs: list[InputSpec]
    run_dir: RunDirSpec
    prompt_run: str | None
    prompt_probe: str | None
    # observability + outcome
    milestones: list[Milestone]
    halts: dict[str, str]
    success_requires: list[str]
    deliverable: str | None
    headline_artifact: str | None
    headline_section: str | None
    qa_artifact: str | None
    qa_verdicts: list[str]
    qa_blocking: list[str]
    # image contract
    required_paths: list[str]
    reference_data: list[ReferenceData]
    image_exclude: list[str]
    image_env: dict[str, str]
    artifact_exclude: list[str]
    # provenance
    source: Path = field(default_factory=Path)

    def input_by_name(self, name: str) -> InputSpec:
        for spec in self.inputs:
            if spec.name == name:
                return spec
        raise ManifestError(f"no input named {name!r}")


# --- helpers ---------------------------------------------------------------
def _require(mapping: dict, key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, "", [], {}):
        raise ManifestError(f"{where}: required key '{key}' is missing or empty")
    return mapping[key]


def _section(doc: dict, key: str, *, required: bool) -> dict:
    value = doc.get(key)
    if value is None:
        if required:
            raise ManifestError(f"manifest is missing the required '{key}' section")
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"'{key}' must be a mapping, got {type(value).__name__}")
    return value


def _template_fields(template: str) -> set[str]:
    """Field names referenced by a `{name|filter}` / `{name.attr|filter}` template."""
    out: set[str] = set()
    depth = 0
    buf = ""
    for ch in template:
        if ch == "{":
            depth, buf = depth + 1, ""
        elif ch == "}" and depth:
            depth -= 1
            out.add(buf.split("|")[0].split(".")[0].strip())
        elif depth:
            buf += ch
    return {f for f in out if f}


# --- loading ---------------------------------------------------------------
def load_manifest(core_root: Path, *, sidecar_dir: Path | None = None) -> Manifest:
    core_root = Path(core_root)
    path = core_root / MANIFEST_NAME
    if not path.is_file() and sidecar_dir:
        candidate = Path(sidecar_dir) / f"{core_root.name}.yaml"
        if candidate.is_file():
            path = candidate
    if not path.is_file():
        raise ManifestError(
            f"no {MANIFEST_NAME} in {core_root} (and no sidecar in "
            f"{sidecar_dir or '<none>'}). Every agent core must declare itself — "
            f"see doc/ADDING_A_CORE.md."
        )

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ManifestError(f"{path}: top level must be a mapping")

    schema = doc.get("schema")
    if schema != SCHEMA:
        raise ManifestError(f"{path}: unsupported schema {schema!r}; this harness speaks schema {SCHEMA}")

    core = _section(doc, "core", required=True)
    agent = _section(doc, "agent", required=True)
    python = _section(doc, "python", required=False)
    run_dir_raw = _section(doc, "run_dir", required=True)
    prompt = _section(doc, "prompt", required=False)
    progress = _section(doc, "progress", required=True)
    outcome = _section(doc, "outcome", required=False)
    image = _section(doc, "image", required=False)
    artifacts = _section(doc, "artifacts", required=False)

    # --- inputs ---
    raw_inputs = doc.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ManifestError("manifest is missing the required 'inputs' section (a non-empty list)")
    inputs: list[InputSpec] = []
    seen: set[str] = set()
    for i, item in enumerate(raw_inputs):
        where = f"inputs[{i}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where}: must be a mapping")
        name = _require(item, "name", where)
        if name in seen:
            raise ManifestError(f"{where}: duplicate input name {name!r}")
        seen.add(name)
        itype = item.get("type", "string")
        if itype not in ("string", "string_list"):
            raise ManifestError(f"{where}: type must be 'string' or 'string_list', got {itype!r}")
        inputs.append(InputSpec(
            name=name, type=itype,
            required=bool(item.get("required", False)),
            cli=item.get("cli") or f"--{name.replace('_', '-')}",
            help=item.get("help", ""),
        ))

    # --- run_dir, cross-checked against inputs ---
    spec = RunDirSpec(
        template=_require(run_dir_raw, "template", "run_dir"),
        fallback=run_dir_raw.get("fallback") or _require(run_dir_raw, "template", "run_dir"),
        session_suffix=run_dir_raw.get("session_suffix", "_session{n}"),
        probe_base=run_dir_raw.get("probe_base", "probe"),
    )
    for template in (spec.template, spec.fallback):
        unknown = _template_fields(template) - seen
        if unknown:
            raise ManifestError(
                f"run_dir template {template!r} references unknown input(s): "
                f"{', '.join(sorted(unknown))}. Declared inputs: {', '.join(sorted(seen))}"
            )
    if "{n}" not in spec.session_suffix:
        raise ManifestError("run_dir.session_suffix must contain '{n}'")

    # --- milestones ---
    raw_ms = progress.get("milestones")
    if not isinstance(raw_ms, list) or not raw_ms:
        raise ManifestError("progress.milestones must be a non-empty list")
    milestones: list[Milestone] = []
    seen_art: set[str] = set()
    last = -1
    for i, item in enumerate(raw_ms):
        where = f"progress.milestones[{i}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where}: must be a mapping")
        artifact = _require(item, "artifact", where)
        if artifact in seen_art:
            raise ManifestError(f"{where}: duplicate artifact {artifact!r}")
        seen_art.add(artifact)
        percent = item.get("percent")
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            raise ManifestError(f"{where}: percent must be an int 0-100, got {percent!r}")
        if percent < last:
            raise ManifestError(
                f"{where}: percent {percent} < previous {last}; milestones must be non-decreasing"
            )
        last = percent
        milestones.append(Milestone(
            artifact=artifact,
            phase=_require(item, "phase", where),
            percent=percent,
            label=item.get("label", artifact),
        ))

    # --- outcome ---
    halts = outcome.get("halts") or {}
    if not isinstance(halts, dict):
        raise ManifestError("outcome.halts must be a mapping of filename -> reason")
    headline = outcome.get("headline") or {}
    qa = outcome.get("qa") or {}

    # --- reference data ---
    reference: list[ReferenceData] = []
    for i, item in enumerate(image.get("reference_data") or []):
        where = f"image.reference_data[{i}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where}: must be a mapping")
        reference.append(ReferenceData(
            path=_require(item, "path", where),
            min_bytes=int(item.get("min_bytes", 1)),
            required=bool(item.get("required", True)),
            provision=item.get("provision"),
        ))

    defaults_raw = agent.get("defaults") or {}
    instructions = _require(agent, "instructions", "agent")
    if not (core_root / instructions).is_file():
        raise ManifestError(
            f"agent.instructions points at {instructions!r}, which does not exist in {core_root}"
        )

    return Manifest(
        name=_require(core, "name", "core"),
        display_name=core.get("display_name", core.get("name", "")),
        version=str(core.get("version", "")),
        instructions=instructions,
        setting_sources=list(agent.get("setting_sources") or ["project"]),
        run_dir_env=_require(agent, "run_dir_env", "agent"),
        defaults=Defaults(
            model=defaults_raw.get("model", ""),
            max_turns=int(defaults_raw.get("max_turns", 0)),
            permission_mode=defaults_raw.get("permission_mode", "bypassPermissions"),
        ),
        conda_env=python.get("conda_env", ""),
        package_paths=list(python.get("package_paths") or []),
        import_check=list(python.get("import_check") or []),
        requirements=dict(python.get("requirements") or {}),
        default_profile=python.get("default_profile", ""),
        inputs=inputs,
        run_dir=spec,
        prompt_run=prompt.get("run"),
        prompt_probe=prompt.get("probe"),
        milestones=milestones,
        halts=dict(halts),
        success_requires=list(outcome.get("success_requires") or []),
        deliverable=outcome.get("deliverable"),
        headline_artifact=headline.get("artifact"),
        headline_section=headline.get("section"),
        qa_artifact=qa.get("artifact"),
        qa_verdicts=list(qa.get("verdicts") or []),
        qa_blocking=list(qa.get("blocking") or []),
        required_paths=list(image.get("required_paths") or []),
        reference_data=reference,
        image_exclude=list(image.get("exclude") or []),
        image_env=dict(image.get("env") or {}),
        artifact_exclude=list(artifacts.get("exclude") or []),
        source=path,
    )
```

- [ ] **Step 4: Add the MOA-core skip guard used by every later shim**

`cores/moa-ag/` is a git-ignored drop-in, so a fresh clone does not have it. The
golden-test shims in Tasks 10–14 load its manifest at module import, which would
**error** rather than skip. This helper makes them skip cleanly, which is what
keeps the harness's committed suite green with `hello-core` alone.

`NEW/tests/_core.py`:

```python
"""Locating the MOA agent core, for the golden tests that pin its behaviour.

The MOA core is a drop-in working copy, deliberately not committed to the harness
repo (see .gitignore). The harness's own suite must therefore be green without it:
tests that pin MOA behaviour SKIP, they do not error. That property is the
genericity claim expressed as a test rather than a README sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MOA_CORE = Path(__file__).resolve().parents[1] / "cores" / "moa-ag"


def moa_manifest_or_skip():
    """Load the MOA core's manifest, or skip the whole module if it is absent."""
    if not (MOA_CORE / "agent-core.yaml").is_file():
        pytest.skip(
            f"cores/moa-ag not present at {MOA_CORE} — it is a git-ignored drop-in. "
            f"Copy the agent core in to run the MOA golden tests.",
            allow_module_level=True,
        )
    from harness.manifest import load_manifest

    return load_manifest(MOA_CORE)
```

For `from _core import ...` to resolve, `tests/` must be on `sys.path`. Add this to
`tests/conftest.py` next to the existing repo-root insert:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))   # so tests can import _core
```

- [ ] **Step 5: Add `pyyaml` to the platform requirements**

`NEW/container/requirements/platform.txt` — create it with **only** service-layer deps:

```text
# The HARNESS's own dependencies. The scientific stack belongs to the agent
# core and is declared by its manifest (python.requirements).
claude-agent-sdk>=0.1.0
boto3>=1.34
pyyaml>=6.0
```

- [ ] **Step 5: Run the tests**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_manifest.py -v`

Expected: all PASS except `test_moa_manifest_loads`, which SKIPs until Task 9.

- [ ] **Step 6: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/manifest.py tests/test_manifest.py container/requirements/platform.txt
git commit -m "feat(manifest): agent-core.yaml schema 1 loader with eager validation

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: write MOA-AG's manifest, prompts and requirements

**Files:**
- Create: `OLD/agent-core.yaml`
- Create: `OLD/.agent-core/prompt_run.md`
- Create: `OLD/runner-requirements/{base,omics,full}.txt` (moved from the harness)
- Delete: `NEW/container/requirements/{base,omics,full}.txt`
- **Do NOT modify** `OLD/CLAUDE.md`

**Interfaces:**
- Consumes: `load_manifest` from Task 8
- Produces: `cores/moa-ag/agent-core.yaml` — the manifest every later task tests against

- [ ] **Step 1: Move the scientific requirements into the science repo**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
mkdir -p runner-requirements
cp /d/Dev/projects/agent-harness/container/requirements/base.txt  runner-requirements/
cp /d/Dev/projects/agent-harness/container/requirements/omics.txt runner-requirements/
cp /d/Dev/projects/agent-harness/container/requirements/full.txt  runner-requirements/
cd /d/Dev/projects/agent-harness
git rm container/requirements/base.txt container/requirements/omics.txt container/requirements/full.txt
```

In each moved file, fix the `-r` cross-references so they resolve within
`runner-requirements/` (e.g. `omics.txt` beginning `-r base.txt` still works —
verify with `head -5 runner-requirements/omics.txt`).

- [ ] **Step 2: Extract the trigger prompt verbatim**

Copy `TEMPLATE` from `NEW/harness/prompt.py` into `OLD/.agent-core/prompt_run.md`
**byte for byte**, with no edits. The placeholders stay exactly
`{compounds}`, `{disease}`, `{run_dir}`, `{extra}`.

```bash
mkdir -p /d/Dev/projects/MOA_AG_Reserach/.agent-core
cd /d/Dev/projects/agent-harness
conda run -n moa python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.')
from harness import prompt
Path(r'D:\Dev\projects\MOA_AG_Reserach\.agent-core\prompt_run.md').write_text(
    prompt.TEMPLATE, encoding='utf-8', newline='\n')
print('wrote', len(prompt.TEMPLATE), 'chars')
"
```

Using the module as the source guarantees byte-fidelity — Task 13's snapshot
tests depend on it.

- [ ] **Step 3: Write the manifest**

`OLD/agent-core.yaml` — the full document from the spec §4, with `prompt.probe`
**omitted** (the harness owns the default probe template; see Task 13):

```yaml
# How the agent-harness runs this repository as an agent core.
# See: https://github.com/Joseph-tsai415/agent-harness → doc/ADDING_A_CORE.md
#
# This file does NOT change the science. CLAUDE.md remains the operating manual
# and is not edited; MOA_RUN_DIR and MOA_CJK_FONT stay MOA-owned names, declared
# below, precisely so that stays true.
schema: 1

core:
  name: moa-ag
  display_name: "MOA-AG network pharmacology pipeline"
  version: v11.2

agent:
  instructions: CLAUDE.md
  setting_sources: [project]     # without this, CLAUDE.md is invisible to the agent
  run_dir_env: MOA_RUN_DIR       # CLAUDE.md §2 reads this name
  defaults:
    model: claude-opus-5
    max_turns: 400
    permission_mode: bypassPermissions

python:
  conda_env: moa                 # CLAUDE.md §7: `conda activate moa`
  package_paths: [moa_lib]
  import_check:
    - moa_lib.citation_grounding
    - moa_lib.provenance
    - moa_lib.specificity_controls
    - rdkit
    - matplotlib_venn
  requirements:
    base:  runner-requirements/base.txt
    omics: runner-requirements/omics.txt
    full:  runner-requirements/full.txt
  default_profile: omics

inputs:
  - {name: compounds, type: string_list, required: true,  cli: --compounds}
  - {name: disease,   type: string,      required: true,  cli: --disease}
  - {name: notes,     type: string,      required: false, cli: --notes}

run_dir:
  template: "{compounds.first|slug}_{disease|slug}"
  fallback: "{disease|slug}"
  session_suffix: "_session{n}"
  probe_base: probe

prompt:
  run: .agent-core/prompt_run.md

progress:
  milestones:
    - {artifact: step0_provenance.md,           phase: provenance,    percent: 5,   label: "Provenance & plausibility gate"}
    - {artifact: step1_target_list_A.md,        phase: targets,       percent: 20,  label: "Compound targets (List A)"}
    - {artifact: step2_disease_genes_B.md,      phase: disease_genes, percent: 35,  label: "Disease genes (List B)"}
    - {artifact: step2_disease_signature.md,    phase: disease_genes, percent: 38,  label: "Data-driven disease signature"}
    - {artifact: step3_hub_targets.md,          phase: intersection,  percent: 45,  label: "Hub targets locked"}
    - {artifact: step4_moa_summary.md,          phase: mechanism,     percent: 60,  label: "Mechanism narrative"}
    - {artifact: step4_moa_table.md,            phase: mechanism,     percent: 65,  label: "MOA overview table"}
    - {artifact: step4_signature_reversal.md,   phase: mechanism,     percent: 68,  label: "L1000 signature reversal"}
    - {artifact: validation_plan.md,            phase: report,        percent: 75,  label: "Validation roadmap"}
    - {artifact: step5_final_report.md,         phase: report,        percent: 80,  label: "Final report drafted"}
    - {artifact: step5_confidence_dashboard.md, phase: report,        percent: 83,  label: "Confidence dashboard"}
    - {artifact: data_integrity_check.md,       phase: report,        percent: 86,  label: "Lineage self-audit"}
    - {artifact: report_qa_review.md,           phase: qa_review,     percent: 90,  label: "Report QA review"}
    - {artifact: result.pdf,                    phase: pdf,           percent: 100, label: "PDF deliverable"}

outcome:
  # A halt is the pipeline refusing to manufacture a result. It is a VALID
  # scientific outcome and must never be reported as an error.
  halts:
    HALT_provenance.md: provenance_gate
    HALT_no_intersection.md: no_specificity
  success_requires: [step5_final_report.md]
  deliverable: result.pdf
  headline:
    artifact: step5_final_report.md
    section: "Bottom Line"
  qa:
    artifact: report_qa_review.md
    verdicts: [SHIP, FIX-FIRST, BLOCK]
    blocking: [BLOCK]

image:
  required_paths: [CLAUDE.md, moa_lib, .claude/skills]
  reference_data:
    # ~322 MB, over GitHub's per-file limit, so NOT in git. The upstream host
    # 504s often enough that downloading at RUN time is a liability — the image
    # carries it, and a build without it fails rather than degrading silently.
    - path: .claude/skills/mirna-targets/data/hsa_MTI.csv
      min_bytes: 100000000
      required: true
      provision: "python .claude/skills/mirna-targets/scripts/download_reference_data.py"
  exclude:
    - results/
    - reviews/
    - reviews_archive/
    - Schollar_System/
    - validation/
    - docs/
    - .claude/settings.local.json
    - ".claude/skills/*/data/"
    - "!.claude/skills/mirna-targets/data/"
  env:
    MOA_CJK_FONT: /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

artifacts:
  exclude: [_pdf_preview/, geo_tmp/, tool-results/, "**/__pycache__/**"]
```

- [ ] **Step 4: Commit in the science repo (locally — do NOT push)**

```bash
cd /d/Dev/projects/MOA_AG_Reserach
git add agent-core.yaml .agent-core/ runner-requirements/
git commit -m "feat: declare this repo as an agent core for the harness

Adds agent-core.yaml, the trigger prompt and the scientific dependency tiers.
CLAUDE.md is deliberately unchanged: MOA_RUN_DIR and MOA_CJK_FONT stay
MOA-owned names, declared in the manifest.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

These three paths are the only things this plan adds to the science repo. They
stay on the local branch for the operator to review.

- [ ] **Step 5: Re-sync the core copy and verify the real manifest loads**

`cores/moa-ag/` is a copy, so the new files must be synced into it:

```bash
cd /d/Dev/projects/agent-harness
cp /d/Dev/projects/MOA_AG_Reserach/agent-core.yaml cores/moa-ag/
mkdir -p cores/moa-ag/.agent-core cores/moa-ag/runner-requirements
cp /d/Dev/projects/MOA_AG_Reserach/.agent-core/*.md cores/moa-ag/.agent-core/
cp /d/Dev/projects/MOA_AG_Reserach/runner-requirements/*.txt cores/moa-ag/runner-requirements/
conda run -n moa python -m pytest tests/test_manifest.py::test_moa_manifest_loads -v
```

Expected: **PASS** (no longer skipped).

- [ ] **Step 6: Commit the harness side**

```bash
cd /d/Dev/projects/agent-harness
git add container/requirements
git commit -m "chore: scientific dependency tiers now belong to the core, not the harness

container/requirements/ keeps platform.txt only. The science stack is declared by
the core's manifest (python.requirements) and resolved at build time.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

`cores/moa-ag/` produces no diff — it is git-ignored.

---

### Task 10: `templates.py` + manifest-driven `naming.py`

**Files:**
- Create: `NEW/harness/templates.py`
- Create: `NEW/tests/test_templates.py`
- Modify: `NEW/harness/naming.py`
- **Do not modify** `NEW/tests/test_naming_golden.py` except for the import shim described in Step 4

**Interfaces:**
- Consumes: `Manifest`, `RunDirSpec`, `InputSpec` from Task 8
- Produces:
  - `templates.slugify(value: str) -> str`
  - `templates.render(template: str, values: dict[str, object]) -> str`
  - `naming.base_name(manifest: Manifest, values: dict[str, object]) -> str`
  - `naming.next_session_dir(results_root: Path, manifest: Manifest, values: dict) -> str`
  - `naming.next_probe_dir(results_root: Path, manifest: Manifest) -> str`

- [ ] **Step 1: Write the failing template tests**

`NEW/tests/test_templates.py`:

```python
from __future__ import annotations

import pytest

from harness.templates import render, slugify


@pytest.mark.parametrize("raw,expected", [
    ("Atopic Dermatitis", "atopic_dermatitis"),
    ("  Curcumin  ", "curcumin"),
    ("IL-4/IL-13", "il_4_il_13"),
    ("七白散", ""),
    ("", ""),
])
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_render_plain_field():
    assert render("{disease}", {"disease": "AD"}) == "AD"


def test_render_slug_filter():
    assert render("{disease|slug}", {"disease": "Atopic Dermatitis"}) == "atopic_dermatitis"


def test_render_first_of_list():
    assert render("{compounds.first|slug}", {"compounds": ["Curcumin", "X"]}) == "curcumin"


def test_render_combined():
    out = render("{compounds.first|slug}_{disease|slug}",
                 {"compounds": ["Curcumin"], "disease": "Atopic Dermatitis"})
    assert out == "curcumin_atopic_dermatitis"


def test_render_missing_field_raises():
    with pytest.raises(KeyError):
        render("{nope}", {"disease": "AD"})


def test_render_first_on_empty_list_is_empty():
    assert render("{compounds.first|slug}", {"compounds": []}) == ""


def test_render_literal_text_is_preserved():
    assert render("run-{disease|slug}-end", {"disease": "AD"}) == "run-ad-end"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_templates.py -v`

Expected: FAIL — `No module named 'harness.templates'`.

- [ ] **Step 3: Implement `harness/templates.py`**

```python
"""A deliberately tiny template renderer for manifest-declared strings.

Scope is intentionally minimal — `{field}`, `{field|slug}`, `{field.first|slug}`
— because the only consumers are run-directory names and prompt variables. A
general template engine here would be a liability: it would invite cores to put
logic in strings.
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def slugify(value: str) -> str:
    """'Atopic Dermatitis' -> 'atopic_dermatitis'; CJK-only -> '' (by design:
    the caller must transliterate upstream rather than emit a half-name)."""
    return _NON_WORD.sub("_", str(value).strip().lower()).strip("_")


_FILTERS = {"slug": slugify}


def render(template: str, values: dict[str, object]) -> str:
    """Substitute `{field}`, `{field|slug}` and `{field.first|slug}`.

    Raises KeyError naming the field if it is not in `values` — an unknown
    field is a manifest bug and must not render as empty text.
    """

    def _one(match: re.Match[str]) -> str:
        expr = match.group(1)
        body, _, filter_name = expr.partition("|")
        field, _, attr = body.strip().partition(".")
        field, attr, filter_name = field.strip(), attr.strip(), filter_name.strip()

        if field not in values:
            raise KeyError(f"template field {field!r} is not among {sorted(values)}")
        value = values[field]

        if attr == "first":
            value = value[0] if isinstance(value, (list, tuple)) and value else ""
        elif attr:
            raise KeyError(f"unsupported attribute {attr!r} in {expr!r} (only '.first')")

        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)

        if filter_name:
            if filter_name not in _FILTERS:
                raise KeyError(f"unknown filter {filter_name!r}; known: {sorted(_FILTERS)}")
            return _FILTERS[filter_name](str(value))
        return str(value)

    return _PLACEHOLDER.sub(_one, template)
```

- [ ] **Step 4: Rewrite `harness/naming.py`**

```python
"""Run-directory naming, driven by the core's manifest.

IMPORTANT — concurrency. A core's instructions may tell the agent to scan and
increment a session number. Under a queue that is a race: two workers both see
`_session10` missing and both claim it. In service mode the run directory is
assigned upstream (an atomic counter) and passed in via the env var the manifest
names (`agent.run_dir_env`). The scan-based path here is for LOCAL
single-process runs only.
"""

from __future__ import annotations

import re
from pathlib import Path

from .manifest import Manifest
from .templates import render, slugify  # noqa: F401  (slugify re-exported)


def base_name(manifest: Manifest, values: dict[str, object]) -> str:
    """Resolve the run-directory base. Spec §4 'run_dir resolution':

    1. Render `template`.
    2. Fall back to `fallback` if a list input referenced by `template` has more
       than one element, OR any `|slug` in `template` renders empty.
    3. If `fallback` also renders empty, raise.
    """
    spec = manifest.run_dir

    multi = any(
        isinstance(values.get(i.name), (list, tuple)) and len(values[i.name]) > 1
        for i in manifest.inputs
        if i.is_list
    )

    candidate = "" if multi else render(spec.template, values)
    if not multi and _has_empty_slug(spec.template, values):
        candidate = ""

    if not candidate:
        candidate = render(spec.fallback, values)
    if not candidate:
        raise ValueError(
            f"run directory slugifies to empty from template {spec.template!r} "
            f"and fallback {spec.fallback!r} — ASCII-transliterate the inputs upstream"
        )
    return candidate


def _has_empty_slug(template: str, values: dict[str, object]) -> bool:
    """True if any `{...|slug}` placeholder in `template` renders empty."""
    for expr in re.findall(r"\{([^{}]+)\}", template):
        if "|slug" not in expr:
            continue
        if not render("{" + expr + "}", values):
            return True
    return False


def next_session_dir(results_root: Path, manifest: Manifest, values: dict[str, object]) -> str:
    """LOCAL ONLY. Scan-and-increment; not safe under concurrency."""
    return _next_for_base(results_root, base_name(manifest, values), manifest.run_dir.session_suffix)


def next_probe_dir(results_root: Path, manifest: Manifest) -> str:
    """LOCAL ONLY. Same scheme, base from `run_dir.probe_base`."""
    return _next_for_base(results_root, manifest.run_dir.probe_base, manifest.run_dir.session_suffix)


def _next_for_base(results_root: Path, base: str, session_suffix: str) -> str:
    results_root = Path(results_root)
    results_root.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(
        "^" + re.escape(base) + re.escape(session_suffix).replace(r"\{n\}", r"(\d+)") + "$"
    )

    highest = 0
    for child in results_root.iterdir():
        if not child.is_dir():
            continue
        if child.name == base:
            highest = max(highest, 1)
            continue
        match = pattern.match(child.name)
        if match:
            highest = max(highest, int(match.group(1)))

    return base + session_suffix.replace("{n}", str(highest + 1))
```

- [ ] **Step 5: Adapt the golden test to the new signature — behaviour assertions unchanged**

The golden test calls `naming.base_name(["Curcumin"], "Atopic Dermatitis")`. The
signature is now manifest-driven. Add a shim **at the top of
`tests/test_naming_golden.py`** and change only the call sites — **never an
expected value**:

```python
# --- shim: the golden expectations below are unchanged; only the call
# convention moved from positional args to (manifest, values). ---
from pathlib import Path

from harness import naming as _naming
from _core import moa_manifest_or_skip

_MOA = moa_manifest_or_skip()


class naming:  # noqa: N801 — keeps the original test bodies readable
    slugify = staticmethod(_naming.slugify)

    @staticmethod
    def base_name(compounds, disease):
        return _naming.base_name(_MOA, {"compounds": compounds, "disease": disease, "notes": ""})

    @staticmethod
    def next_session_dir(root, compounds, disease):
        return _naming.next_session_dir(
            root, _MOA, {"compounds": compounds, "disease": disease, "notes": ""})

    @staticmethod
    def next_probe_dir(root):
        return _naming.next_probe_dir(root, _MOA)
```

Delete the old `from app import naming` line. Every `assert` stays byte-identical.

- [ ] **Step 6: Run both suites**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_templates.py tests/test_naming_golden.py -v`

Expected: **all PASS**, including `test_base_name_cjk_only_compound_falls_back_to_disease`
and `test_base_name_cjk_only_disease_raises`. If the CJK cases fail, the
`_has_empty_slug` / fallback logic is wrong — fix `naming.py`, not the test.

- [ ] **Step 7: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/templates.py harness/naming.py tests/test_templates.py tests/test_naming_golden.py
git commit -m "refactor(naming): resolve run directories from the manifest

Golden expectations unchanged; only the call convention moved.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: manifest-driven `progress.py`

**Files:**
- Modify: `NEW/harness/progress.py`
- Modify: `NEW/tests/test_progress_golden.py` (import shim only)

**Interfaces:**
- Consumes: `Manifest`, `Milestone` from Task 8
- Produces: `ProgressWatcher(run_dir, emitter, *, milestones, halt_files, poll_seconds=5.0)` and `ProgressWatcher.from_manifest(run_dir, emitter, manifest, poll_seconds=5.0)`

- [ ] **Step 1: Modify `harness/progress.py`**

Replace the module-level `MILESTONES` / `HALT_FILES` constants and the
`__init__` signature. Keep **every line of `scan()`, `_loop()`, `start()` and
`stop()` unchanged** — the logic is already generic.

```python
"""Progress tracking by artifact appearance.

A core's manifest pins every output filename, which makes the filesystem a
*deterministic* progress signal — strictly better than parsing agent prose or
inferring from tool calls, both of which drift with model behaviour.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .events import EventEmitter
from .manifest import Manifest, Milestone

__all__ = ["Milestone", "ProgressWatcher"]


class ProgressWatcher:
    """Polls a run directory in a daemon thread and emits milestone events."""

    def __init__(
        self,
        run_dir: Path,
        emitter: EventEmitter,
        *,
        milestones: tuple[Milestone, ...] | list[Milestone],
        halt_files: tuple[str, ...] | list[str] = (),
        poll_seconds: float = 5.0,
    ):
        self.run_dir = Path(run_dir)
        self.emitter = emitter
        self.milestones = tuple(milestones)
        self.halt_files = tuple(halt_files)
        self.poll_seconds = poll_seconds
        self._seen: set[str] = set()
        self._phase_started: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.percent = 0
        self.phase = self.milestones[0].phase if self.milestones else ""

    @classmethod
    def from_manifest(cls, run_dir: Path, emitter: EventEmitter, manifest: Manifest,
                      poll_seconds: float = 5.0) -> "ProgressWatcher":
        return cls(run_dir, emitter,
                   milestones=manifest.milestones,
                   halt_files=tuple(manifest.halts),
                   poll_seconds=poll_seconds)
```

Then in `scan()` change exactly two references:
- `for halt in HALT_FILES:` → `for halt in self.halt_files:`
- `for milestone in MILESTONES:` → `for milestone in self.milestones:`

and `milestone.filename` → `milestone.artifact` throughout (the manifest's
`Milestone` names the field `artifact`).

- [ ] **Step 2: Add the shim to the golden test**

Replace `from app import progress as P` in `tests/test_progress_golden.py` with:

```python
from pathlib import Path

from harness import progress as _P
from _core import moa_manifest_or_skip

_MOA = moa_manifest_or_skip()


class P:  # noqa: N801 — keeps the original test bodies readable
    MILESTONES = tuple(_MOA.milestones)
    HALT_FILES = tuple(_MOA.halts)

    @staticmethod
    def ProgressWatcher(run_dir, emitter, poll_seconds=5.0):  # noqa: N802
        return _P.ProgressWatcher.from_manifest(run_dir, emitter, _MOA, poll_seconds)
```

Then change `m.filename` → `m.artifact` in `test_milestone_table_is_ordered_and_ends_at_100`.
Every other assertion — the count of 14, the 100 ceiling, emit-once,
monotonicity — stays as written.

- [ ] **Step 3: Run the tests**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_progress_golden.py -v`

Expected: all PASS.

- [ ] **Step 4: Update the one caller**

Run: `grep -rn "ProgressWatcher(" harness/` and update `run_once.py` / `worker.py`
to `ProgressWatcher.from_manifest(run_dir, emitter, manifest, settings.poll_seconds)`.

- [ ] **Step 5: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/progress.py tests/test_progress_golden.py harness/run_once.py harness/worker.py
git commit -m "refactor(progress): inject milestones from the manifest

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: manifest-driven `classify.py`

**Files:**
- Modify: `NEW/harness/classify.py`
- Modify: `NEW/tests/test_classify_golden.py` (import shim only)

**Interfaces:**
- Consumes: `Manifest` from Task 8
- Produces:
  - `classify(run_dir, manifest, *, timed_out=False, cancelled=False, agent_error=None) -> Outcome`
  - `extract_section(path: Path, heading: str) -> str | None` (generalises `extract_bottom_line`)
  - `extract_verdict(path: Path, verdicts: list[str]) -> str | None` (generalises `extract_qa_verdict`)
  - `collect_artifacts(run_dir: Path, exclude: list[str] = ()) -> list[dict]`
  - `classify_probe(...)` — unchanged signature
  - `detect_infra_failure(note)` — unchanged, stays platform-owned

- [ ] **Step 1: Modify `harness/classify.py`**

Three mechanical generalisations; **keep the ordering of the decision branches
exactly as it is** — `cancelled` > halt > `timed_out` > report+deliverable is a
deliberate precedence the golden tests pin.

1. `extract_bottom_line(report)` → `extract_section(path, heading)`, building the
   regex from the heading:

```python
def extract_section(path: Path, heading: str) -> str | None:
    """Pull a named section's body — what a frontend shows as the headline."""
    text = _read(path)
    if not text or not heading:
        return None
    pattern = r"^#{1,4}\s*" + r"\s*".join(re.escape(w) for w in heading.split()) + \
              r"\b[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    body = " ".join(line.strip() for line in match.group(1).splitlines() if line.strip())
    return re.sub(r"\s+", " ", body).strip()[:1200] or None
```

2. `extract_qa_verdict(review)` → `extract_verdict(path, verdicts)`:

```python
def extract_verdict(path: Path, verdicts: list[str]) -> str | None:
    text = _read(path, limit=40_000)
    if not text or not verdicts:
        return None
    alternatives = "|".join(re.escape(v).replace(r"\-", "-?") for v in verdicts)
    pattern = re.compile(r"\b(" + alternatives + r")\b", re.IGNORECASE)
    for chunk in (text[-6000:], text[:6000]):     # verdict is near the end
        match = pattern.search(chunk)
        if match:
            found = match.group(1).upper()
            for v in verdicts:                     # normalise to the declared spelling
                if v.upper().replace("-", "") == found.replace("-", ""):
                    return v
            return found
    return None
```

3. `classify()` takes `manifest` and reads `manifest.halts`,
   `manifest.success_requires`, `manifest.deliverable`,
   `manifest.headline_artifact`/`headline_section`, `manifest.qa_artifact`/
   `qa_verdicts`/`qa_blocking`, and passes `manifest.artifact_exclude` to
   `collect_artifacts`. Replace the hard-coded filenames; the branch structure
   does not change. The `reached = max(... startswith("step") ...)` line becomes
   generic — use the manifest's milestone artifacts:

```python
    milestone_names = [m.artifact for m in manifest.milestones]
    reached = next((n for n in reversed(milestone_names)
                    if any(a["name"] == n for a in artifacts)), None)
```

4. `collect_artifacts` takes the exclusion list instead of hard-coding it:

```python
def collect_artifacts(run_dir: Path, exclude: list[str] = ()) -> list[dict]:
    prefixes = tuple(p.rstrip("/") + "/" for p in exclude if not p.startswith("**"))
    globs = [p for p in exclude if p.startswith("**")]
    out: list[dict] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(run_dir).as_posix()
        if rel.startswith(prefixes) or any(fnmatch(rel, g) for g in globs):
            continue
        out.append({"name": rel, "size": path.stat().st_size})
    return out
```

Add `from fnmatch import fnmatch` at the top. `_HALT_REASONS` and `_QA_VERDICT`
are deleted; `_INFRA_FAILURES` and `detect_infra_failure` **stay**.

- [ ] **Step 2: Add the shim to the golden test**

Replace `from app import classify as C` in `tests/test_classify_golden.py` with:

```python
from pathlib import Path

from harness import classify as _C
from _core import moa_manifest_or_skip

_MOA = moa_manifest_or_skip()


class C:  # noqa: N801 — keeps the original test bodies readable
    STATUS_COMPLETED = _C.STATUS_COMPLETED
    STATUS_HALTED = _C.STATUS_HALTED
    STATUS_FAILED = _C.STATUS_FAILED
    STATUS_TIMED_OUT = _C.STATUS_TIMED_OUT
    STATUS_CANCELLED = _C.STATUS_CANCELLED
    detect_infra_failure = staticmethod(_C.detect_infra_failure)

    @staticmethod
    def classify(run_dir, **kw):
        return _C.classify(run_dir, _MOA, **kw)

    @staticmethod
    def extract_bottom_line(path):
        return _C.extract_section(path, "Bottom Line")

    @staticmethod
    def extract_qa_verdict(path):
        return _C.extract_verdict(path, _MOA.qa_verdicts)

    @staticmethod
    def collect_artifacts(run_dir):
        return _C.collect_artifacts(run_dir, _MOA.artifact_exclude)
```

Every assertion stays byte-identical.

- [ ] **Step 3: Run the tests**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_classify_golden.py -v`

Expected: **all PASS**, especially `test_halt_is_not_a_failure`,
`test_halt_outranks_timeout`, `test_cancelled_outranks_halt` and
`test_qa_block_fails_even_with_report_and_pdf`.

- [ ] **Step 4: Update callers**

Run: `grep -rn "classify(\|extract_bottom_line\|extract_qa_verdict\|collect_artifacts" harness/`
and thread `manifest` through `run_once.py`, `worker.py`, `cloud.py`.

- [ ] **Step 5: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/classify.py tests/test_classify_golden.py harness/run_once.py harness/worker.py harness/cloud.py
git commit -m "refactor(classify): read halts, success and QA rules from the manifest

_INFRA_FAILURES stays platform-owned: credit, auth, rate limit and overload are
harness concerns, not payload concerns.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: manifest-driven `prompt.py`

**Files:**
- Modify: `NEW/harness/prompt.py`
- Create: `NEW/harness/probe_prompt.md` (the harness's own default probe template)
- Modify: `NEW/tests/test_prompt_golden.py` (import shim only)
- **Do not touch** `NEW/tests/snapshots/*.txt`

**Interfaces:**
- Consumes: `Manifest`, `templates.render`
- Produces:
  - `build_prompt(manifest: Manifest, core_root: Path, values: dict, run_dir: str, *, extra_instructions: str = "") -> str`
  - `build_probe_prompt(manifest: Manifest, core_root: Path, run_dir: str, user_prompt: str | None = None) -> str`
  - `PROBE_MODEL`, `PROBE_MAX_TURNS`, `PROBE_TIMEOUT_SECONDS`, `PROBE_MAX_COST_USD`, `PROBE_PROMPT_MAX_CHARS` — unchanged

- [ ] **Step 1: Move the probe template into a harness-owned file**

The probe is the *harness's* own verification feature, not a payload's, so the
harness ships the template and a core may override it with `prompt.probe`. Copy
`PROBE_TEMPLATE` and `PROBE_DEFAULT_TASK` verbatim into
`NEW/harness/probe_prompt.md`, separated by a marker line:

```bash
cd /d/Dev/projects/agent-harness
conda run -n moa python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.')
from harness import prompt as p
Path('harness/probe_prompt.md').write_text(
    p.PROBE_TEMPLATE + '\n<<<DEFAULT_TASK>>>\n' + p.PROBE_DEFAULT_TASK,
    encoding='utf-8', newline='\n')
print('ok')
"
```

Generalise one sentence in the written file: replace
`Do NOT start the MOA-AG research pipeline described in CLAUDE.md.` with
`Do NOT start the pipeline or workflow described in your instructions.` This is
the only edit, and it is required because the file is now payload-agnostic.
**Note:** this changes `probe_default` / `probe_custom` snapshots. Regenerate
exactly those two with `REGEN=1` and inspect the diff to confirm the only change
is that sentence.

- [ ] **Step 2: Rewrite `harness/prompt.py`**

```python
"""Trigger prompts.

The RUN prompt belongs to the agent core — it is domain text, and the manifest
points at it (`prompt.run`). The PROBE prompt belongs to the harness: it is an
infrastructure check, shipped as `probe_prompt.md`, overridable by a core via
`prompt.probe`.

Keep both templates boring. Reproducibility comes from the core's instructions
being the operating manual, not from prompt cleverness.
"""

from __future__ import annotations

from pathlib import Path

from .manifest import Manifest
from .templates import render

PROBE_MODEL = "claude-sonnet-4-6"
PROBE_MAX_TURNS = 100
PROBE_TIMEOUT_SECONDS = 2200
PROBE_MAX_COST_USD = 5.0
PROBE_PROMPT_MAX_CHARS = 2000

_DEFAULT_PROBE = Path(__file__).with_name("probe_prompt.md")
_TASK_MARKER = "<<<DEFAULT_TASK>>>"


def _read_template(core_root: Path, relative: str | None, fallback: Path) -> str:
    path = Path(core_root) / relative if relative else fallback
    if not path.is_file():
        raise FileNotFoundError(
            f"prompt template not found: {path}. The manifest must point at a file "
            f"that exists inside the core."
        )
    return path.read_text(encoding="utf-8")


def build_prompt(
    manifest: Manifest,
    core_root: Path,
    values: dict[str, object],
    run_dir: str,
    *,
    extra_instructions: str = "",
) -> str:
    """Render the core's run prompt. Required inputs are validated here, using
    the manifest's declarations rather than hard-coded field names."""
    for spec in manifest.inputs:
        if not spec.required:
            continue
        value = values.get(spec.name)
        empty = (
            value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, (list, tuple)) and not value)
        )
        if empty:
            raise ValueError(f"{spec.name} is required by {manifest.name}'s manifest")

    if not manifest.prompt_run:
        raise ValueError(f"{manifest.name}: manifest declares no prompt.run template")
    template = _read_template(core_root, manifest.prompt_run, _DEFAULT_PROBE)

    extra = ""
    if extra_instructions.strip():
        # Fenced so it can never be read as an instruction to the core's gates.
        extra = (
            "ADDITIONAL CONTEXT FROM THE REQUESTER\n"
            "  (context only — it does not relax any gate in the operating manual)\n"
            f"  {extra_instructions.strip()}\n\n"
        )

    rendered: dict[str, object] = {}
    for spec in manifest.inputs:
        value = values.get(spec.name, "")
        if spec.is_list and isinstance(value, (list, tuple)):
            rendered[spec.name] = ", ".join(str(v).strip() for v in value)
        else:
            rendered[spec.name] = str(value).strip()
    rendered["run_dir"] = run_dir
    rendered["extra"] = extra

    return render(template, rendered)


def build_probe_prompt(
    manifest: Manifest,
    core_root: Path,
    run_dir: str,
    user_prompt: str | None = None,
) -> str:
    """Probe prompt: the requester's task if given, else the default file task."""
    if not run_dir or not run_dir.strip():
        raise ValueError("a run directory is required for a probe")
    run_dir = run_dir.strip()

    raw = _read_template(core_root, manifest.prompt_probe, _DEFAULT_PROBE)
    template, _, default_task = raw.partition(_TASK_MARKER)
    template, default_task = template.rstrip("\n") + "\n", default_task.lstrip("\n")

    requested = (user_prompt or "").strip()
    if requested:
        if len(requested) > PROBE_PROMPT_MAX_CHARS:
            raise ValueError(f"probe prompt exceeds {PROBE_PROMPT_MAX_CHARS} chars")
        # Fenced: the requester's text is the task, but it sits inside the probe
        # framing and cannot lift the SAFETY / no-pipeline rules.
        task = (
            "  Do the following task requested by the operator. Write any files it\n"
            f"  produces into `results/{run_dir}/`.\n"
            "  --- BEGIN REQUESTED TASK ---\n"
            f"{requested}\n"
            "  --- END REQUESTED TASK ---\n"
        )
    else:
        task = default_task.replace("{run_dir}", run_dir)

    return template.replace("{run_dir}", run_dir).replace("{task}", task)
```

Note `build_prompt` uses `render()` while `build_probe_prompt` uses literal
`.replace()` — matching today's behaviour exactly, where the probe used
`.replace()` so that braces in a requester's task text could not break
formatting. That asymmetry is deliberate; do not "tidy" it.

- [ ] **Step 3: Add the shim to the golden test**

Replace `from app import prompt as PR` in `tests/test_prompt_golden.py` with:

```python
from pathlib import Path

from harness import prompt as _PR
from harness.manifest import load_manifest

from _core import MOA_CORE as _CORE, moa_manifest_or_skip

_MOA = moa_manifest_or_skip()


class PR:  # noqa: N801 — keeps the original test bodies readable
    PROBE_PROMPT_MAX_CHARS = _PR.PROBE_PROMPT_MAX_CHARS

    @staticmethod
    def build_prompt(compounds, disease, run_dir, extra_instructions=""):
        return _PR.build_prompt(
            _MOA, _CORE,
            {"compounds": compounds, "disease": disease, "notes": ""},
            run_dir, extra_instructions=extra_instructions)

    @staticmethod
    def build_probe_prompt(run_dir, user_prompt=None):
        return _PR.build_probe_prompt(_MOA, _CORE, run_dir, user_prompt)
```

Also relax two validation assertions, because the messages are now
manifest-driven: `match="at least one compound"` → `match="compounds is required"`,
and `match="disease/condition is required"` → `match="disease is required"`.
These are message strings, not behaviour — the raise still happens for the same
input.

- [ ] **Step 4: Run the tests**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_prompt_golden.py -v`

Expected: `run_basic` and `run_extra` **PASS against the untouched snapshots** —
this is the proof the prompt survived the move byte-for-byte. The two probe
snapshots fail once; regenerate them with
`REGEN=1 conda run -n moa python -m pytest tests/test_prompt_golden.py` and
`git diff tests/snapshots/` must show **only** the generalised sentence.

- [ ] **Step 5: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/prompt.py harness/probe_prompt.md tests/test_prompt_golden.py tests/snapshots/
git commit -m "refactor(prompt): run prompt from the core, probe prompt from the harness

run_basic/run_extra snapshots are unchanged, proving the run prompt moved
byte-for-byte. The probe snapshots change by exactly one generalised sentence.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: `inputs`-driven CLI and worker

**Files:**
- Modify: `NEW/harness/run_once.py`
- Modify: `NEW/harness/worker.py`
- Modify: `NEW/tests/test_cli_golden.py` (import shim only)

**Interfaces:**
- Consumes: `Manifest`, `InputSpec`
- Produces: `build_parser(manifest: Manifest) -> argparse.ArgumentParser`; `split_values(raw: str) -> list[str]`; `collect_values(args, manifest) -> dict[str, object]`; `validate_values(parser, args, manifest) -> None`; `parse_args(argv, manifest) -> argparse.Namespace`

- [ ] **Step 1: Replace the hard-coded arguments**

In `harness/run_once.py`, change `build_parser()` to take the manifest and
generate the payload arguments, keeping every harness-owned flag
(`--dry-run`, `--kind`, `--run-dir`, `--resume`, …) exactly as it is:

```python
def build_parser(manifest: Manifest) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness.run_once",
        description=f"Run one {manifest.display_name} job, start to finish.",
    )
    # --- payload inputs, declared by the core's manifest ---
    # EVERY input is a single string argument with default="", including
    # string_list: a list arrives comma-separated and is split by split_values.
    # This is NOT a style choice — nargs="+" would change the CLI contract that
    # Task 5 pinned, and worker.py:128 (`",".join(compounds)`) plus
    # doc/API_PROTOCOL.md both depend on the comma form.
    #
    # `required` is NOT passed to argparse either. Requiredness is conditional:
    # `--kind probe` needs no payload input at all. It is validated below.
    for spec in manifest.inputs:
        metavar = spec.name.upper() + (",…" if spec.is_list else "")
        parser.add_argument(spec.cli, dest=spec.name, default="", metavar=metavar,
                            help=spec.help or (f"comma-separated {spec.name}"
                                               if spec.is_list else spec.name))
    # --- harness flags (unchanged; keep the existing block verbatim) ---
    ...
    return parser


def split_values(raw: str) -> list[str]:
    """Comma-separated CLI value -> list, dropping empties."""
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def collect_values(args: argparse.Namespace, manifest: Manifest) -> dict[str, object]:
    """Payload inputs out of parsed args, in manifest order, with list inputs split."""
    out: dict[str, object] = {}
    for spec in manifest.inputs:
        raw = getattr(args, spec.name, "") or ""
        out[spec.name] = split_values(raw) if spec.is_list else raw.strip()
    return out


def validate_values(parser, args, manifest: Manifest) -> None:
    """Conditional requiredness, preserving today's behaviour exactly: payload
    inputs are required for a real run, and not required for a probe."""
    if args.kind != "moa":
        return
    values = collect_values(args, manifest)
    missing = [s.cli for s in manifest.inputs if s.required and not values[s.name]]
    if missing:
        parser.error(f"{' and '.join(missing)} are required for --kind moa")
```

Call `validate_values(p, args, manifest)` from `parse_args` where today's
`if args.kind == "moa" and not (...)` check lives, then replace every
`args.compounds` / `args.disease` use in the module body with
`values = collect_values(args, manifest)` threaded into `build_prompt`,
`next_session_dir` and the event payloads.

`InputSpec` gains an optional `help: str = ""` field in `harness/manifest.py`
(Task 8) so a core can supply its own argument help text; absent, the generated
default above is used.

In `harness/worker.py`, map the SQS body generically. Today it accepts a list OR a
string and comma-joins for the CLI (`worker.py:120-128`) — preserve both halves:

```python
values = {}
for spec in manifest.inputs:
    raw = body.get(spec.name, "")
    if spec.is_list:
        values[spec.name] = [raw] if isinstance(raw, str) and raw else list(raw or [])
    else:
        values[spec.name] = str(raw or "")
```

- [ ] **Step 2: Add the shim to the golden test**

Replace `from app.run_once import build_parser` in `tests/test_cli_golden.py` with:

```python
from pathlib import Path

from _core import moa_manifest_or_skip
from harness.run_once import build_parser as _build_parser
from harness.run_once import parse_args as _parse_args
from harness.run_once import split_values  # noqa: F401 — manifest-free, imported as-is

_MOA = moa_manifest_or_skip()


def build_parser():
    return _build_parser(_MOA)


def parse_args(argv=None):
    return _parse_args(argv, _MOA)
```

Every assertion stays as written — this is the proof the CLI contract survived.

- [ ] **Step 3: Run the full suite**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/ -v`

Expected: **every test passes.** Confirm the count matches Task 5 Step 3 plus
the new `test_manifest.py` and `test_templates.py` tests.

- [ ] **Step 4: Verify the CLI is genuinely generic**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from harness.manifest import load_manifest
from harness.run_once import build_parser
build_parser(load_manifest(Path('cores/moa-ag'))).print_help()
"`

Expected: help text shows `--compounds`, `--disease`, `--notes`.

- [ ] **Step 5: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/run_once.py harness/worker.py tests/test_cli_golden.py
git commit -m "refactor(cli): build the parser and SQS mapping from manifest inputs

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: `HARNESS_*` env rename, `config.py`, `preflight.py`, `entrypoint.sh`

**Files:**
- Modify: `NEW/harness/config.py`
- Create: `NEW/harness/preflight.py`
- Create: `NEW/tests/test_preflight.py`
- Modify: `NEW/container/entrypoint.sh`, `NEW/container/docker-compose.yml`, `NEW/container/run_local.ps1`, `NEW/container/.env.example`

**Interfaces:**
- Consumes: `Manifest`
- Produces:
  - `settings.core_root: Path`, `settings.results_root: Path`, `settings.core: str`, `settings.manifest()` → `Manifest`
  - `preflight.check(manifest, core_root, results_root) -> list[str]` (returns failures; empty = OK)
  - `python -m harness.preflight` → exit 0 or 78

- [ ] **Step 1: Rename the env vars in `config.py`**

Apply the spec §8 mapping. `MOA_REPO_ROOT` → `HARNESS_CORE_ROOT`, and add:

```python
    # --- the agent core ---------------------------------------------------
    core_root: Path = field(default_factory=lambda: Path(_env("HARNESS_CORE_ROOT", "/app")))
    core: str = field(default_factory=lambda: _env("HARNESS_CORE", "slot"))
    manifest_dir: Path = field(
        default_factory=lambda: Path(_env("HARNESS_MANIFEST_DIR", "/opt/harness/manifests")))

    def manifest(self):
        """Load and cache the core's manifest. Raises ManifestError if absent —
        a run without a manifest is a configuration error, not a default."""
        from .manifest import load_manifest
        return load_manifest(self.core_root, sidecar_dir=self.manifest_dir)
```

Then rename every remaining `MOA_` env read in the file to `HARNESS_`, per the
spec table. **Do not** rename `MOA_RUN_DIR` or `MOA_CJK_FONT` — they are not read
by `config.py`; they are payload-declared and set from the manifest.

- [ ] **Step 2: Sweep the rest of the harness and container**

```bash
cd /d/Dev/projects/agent-harness
grep -rln "MOA_" harness container doc backend-handler infra *.md 2>/dev/null \
  | xargs sed -i \
      -e 's/\bMOA_REPO_ROOT\b/HARNESS_CORE_ROOT/g' \
      -e 's/\bMOA_RESULTS_ROOT\b/HARNESS_RESULTS_ROOT/g' \
      -e 's/\bMOA_MODEL\b/HARNESS_MODEL/g' \
      -e 's/\bMOA_MAX_TURNS\b/HARNESS_MAX_TURNS/g' \
      -e 's/\bMOA_TIMEOUT_SECONDS\b/HARNESS_TIMEOUT_SECONDS/g' \
      -e 's/\bMOA_MAX_COST_USD\b/HARNESS_MAX_COST_USD/g' \
      -e 's/\bMOA_PERMISSION_MODE\b/HARNESS_PERMISSION_MODE/g' \
      -e 's/\bMOA_ANSWER_TIMEOUT_SECONDS\b/HARNESS_ANSWER_TIMEOUT_SECONDS/g' \
      -e 's/\bMOA_INBOX_POLL_SECONDS\b/HARNESS_INBOX_POLL_SECONDS/g' \
      -e 's/\bMOA_IDLE_WAIT_SECONDS\b/HARNESS_IDLE_WAIT_SECONDS/g' \
      -e 's/\bMOA_IDLE_BUDGET_SECONDS\b/HARNESS_IDLE_BUDGET_SECONDS/g' \
      -e 's/\bMOA_TOOL_EVENT_EVERY\b/HARNESS_TOOL_EVENT_EVERY/g' \
      -e 's/\bMOA_PROGRESS_POLL_SECONDS\b/HARNESS_PROGRESS_POLL_SECONDS/g' \
      -e 's/\bMOA_BUILD_PROFILE\b/HARNESS_PROFILE/g' \
      -e 's/\bMOA_MEM_LIMIT\b/HARNESS_MEM_LIMIT/g' \
      -e 's/\bMOA_CPUS\b/HARNESS_CPUS/g' \
      -e 's/\bMOA_WORKER_DRY_RUN\b/HARNESS_DRY_RUN/g'
```

Then verify the only `MOA_` left are the two payload-owned names:

```bash
grep -rn "MOA_" harness container backend-handler infra | grep -v "MOA_RUN_DIR\|MOA_CJK_FONT" | grep -v cores/
```

Expected: **no output.** Anything printed is a missed rename.

- [ ] **Step 3: Write the failing preflight test**

`NEW/tests/test_preflight.py`:

```python
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from harness.manifest import load_manifest
from harness.preflight import check

MANIFEST = """\
schema: 1
core: {name: tiny, display_name: Tiny, version: "0.1"}
agent: {instructions: CLAUDE.md, run_dir_env: TINY_RUN_DIR}
inputs: [{name: topic, type: string, required: true, cli: --topic}]
run_dir: {template: "{topic|slug}", fallback: "{topic|slug}"}
progress: {milestones: [{artifact: done.md, phase: done, percent: 100, label: Done}]}
image:
  required_paths: [CLAUDE.md, lib]
  reference_data:
    - {path: data/big.csv, min_bytes: 10, required: true}
"""


@pytest.fixture
def core(tmp_path):
    d = tmp_path / "core"
    (d / "lib").mkdir(parents=True)
    (d / "data").mkdir()
    (d / "CLAUDE.md").write_text("# tiny\n", encoding="utf-8")
    (d / "agent-core.yaml").write_text(textwrap.dedent(MANIFEST), encoding="utf-8")
    (d / "data" / "big.csv").write_text("x" * 50, encoding="utf-8")
    return d


def test_healthy_core_passes(core, tmp_path):
    assert check(load_manifest(core), core, tmp_path / "results") == []


def test_missing_required_path_is_reported(core, tmp_path):
    (core / "lib").rmdir()
    failures = check(load_manifest(core), core, tmp_path / "results")
    assert any("lib" in f for f in failures)


def test_undersized_reference_data_is_reported(core, tmp_path):
    (core / "data" / "big.csv").write_text("x", encoding="utf-8")
    failures = check(load_manifest(core), core, tmp_path / "results")
    assert any("big.csv" in f and "bytes" in f for f in failures)


def test_unwritable_results_root_is_reported(core, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("nope")
    monkeypatch.setattr(Path, "mkdir", boom)
    failures = check(load_manifest(core), core, tmp_path / "results")
    assert any("writable" in f for f in failures)
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_preflight.py -v`

Expected: FAIL — `No module named 'harness.preflight'`.

- [ ] **Step 5: Implement `harness/preflight.py`**

```python
"""Manifest-driven environment validation.

Everything here is a fail-fast check. A run costs real money and takes tens of
minutes; discovering a missing credential or a truncated reference file at
minute 40 is the expensive way to find out.

Exit code 78 (EX_CONFIG) on failure, matching entrypoint.sh's contract.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .manifest import Manifest

EX_CONFIG = 78


def check(manifest: Manifest, core_root: Path, results_root: Path) -> list[str]:
    """Return a list of human-readable failures. Empty means the core is sound."""
    core_root, results_root = Path(core_root), Path(results_root)
    failures: list[str] = []

    for rel in manifest.required_paths:
        if not (core_root / rel).exists():
            failures.append(
                f"required path missing: {core_root / rel} "
                f"(declared in {manifest.name}'s image.required_paths)")

    for ref in manifest.reference_data:
        path = core_root / ref.path
        if not path.is_file():
            if ref.required:
                failures.append(
                    f"reference data missing from the image: {path}. "
                    f"Rebuild — the core-stage provisions it"
                    + (f" with: {ref.provision}" if ref.provision else "."))
            continue
        size = path.stat().st_size
        if size < ref.min_bytes:
            failures.append(
                f"reference data truncated: {path} is {size} bytes, "
                f"expected at least {ref.min_bytes}")

    for module in manifest.import_check:
        try:
            importlib.import_module(module)
        except Exception as exc:
            failures.append(f"import check failed: {module} ({type(exc).__name__}: {exc})")

    try:
        results_root.mkdir(parents=True, exist_ok=True)
        probe = results_root / ".write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        failures.append(f"{results_root} is not writable ({type(exc).__name__}: {exc})")

    return failures


def main() -> int:
    from .config import settings

    try:
        manifest = settings.manifest()
    except Exception as exc:
        print(f"[preflight] FATAL: {exc}", file=sys.stderr)
        return EX_CONFIG

    print(f"[preflight] core: {manifest.display_name} ({manifest.name} {manifest.version})",
          file=sys.stderr)

    failures = check(manifest, settings.core_root, settings.results_root)
    for failure in failures:
        print(f"[preflight] FATAL: {failure}", file=sys.stderr)
    if failures:
        return EX_CONFIG

    print(f"[preflight] ok — {len(manifest.milestones)} milestones, "
          f"{len(manifest.halts)} halt gates, "
          f"{len(manifest.import_check)} imports verified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Replace the hard-coded asserts in `entrypoint.sh`**

Keep sections 1 (Claude auth) and 2 (CLI on PATH) **exactly as they are** — they
are platform concerns. Replace sections 3–6 (the agent-core asserts, the writable
check, the mirna assert and the inline Python import block) with:

```bash
# --- 3. The agent core, its reference data, and the python stack ----------
# All manifest-driven: the core declares what must be present. See
# harness/preflight.py. Exits 78 on any failure, same as this script.
python -m harness.preflight || exit 78
```

- [ ] **Step 7: Run the tests**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/ -v`

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add -A
git commit -m "refactor: HARNESS_* env prefix and manifest-driven preflight

MOA_RUN_DIR and MOA_CJK_FONT deliberately keep their names: they are
payload-owned, declared by the manifest, and read by the core's own CLAUDE.md.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Phase D — Build

### Task 16: three-stage Dockerfile with core staging and reference provisioning

**Files:**
- Modify: `NEW/container/Dockerfile`
- Create: `NEW/container/stage_core.py`
- Modify: `NEW/container/docker-compose.yml`

**Interfaces:**
- Consumes: `Manifest`
- Produces: an image where `/app` is the core, `/opt/harness` is the harness, and `HARNESS_CORE` selects the core

- [ ] **Step 1: Write the staging script**

`NEW/container/stage_core.py` — runs inside the build, with **no harness imports**
(the harness is not installed in that stage) so it stays dependency-free except
`pyyaml`:

```python
#!/usr/bin/env python
"""Prune a staged agent core per its manifest, then provision reference data.

Runs inside the Dockerfile's core-stage. Deliberately standalone: it reads the
manifest with pyyaml directly rather than importing the harness, because the
harness is not on the path in that stage.

Exit non-zero on any required-path or required-reference-data failure. A build
that proceeds without them produces an image that LOOKS complete and degrades
silently at run time, which is the worst available outcome.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

CORE = Path(sys.argv[1] if len(sys.argv) > 1 else "/stage/core")


def log(msg: str) -> None:
    print(f"[stage_core] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[stage_core] FATAL: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def load() -> dict:
    path = CORE / "agent-core.yaml"
    sidecar = Path("/stage/manifests") / f"{os.environ.get('HARNESS_CORE', '')}.yaml"
    if not path.is_file() and sidecar.is_file():
        path = sidecar
    if not path.is_file():
        die(f"no agent-core.yaml in {CORE} and no sidecar at {sidecar}. "
            f"Every agent core must declare itself — see doc/ADDING_A_CORE.md.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def prune(patterns: list[str]) -> None:
    """Apply image.exclude. A leading '!' re-includes, so order matters:
    `.claude/skills/*/data/` then `!.claude/skills/mirna-targets/data/` keeps
    one essential cache while dropping every other."""
    keep = [p[1:].rstrip("/") for p in patterns if p.startswith("!")]
    drop = [p.rstrip("/") for p in patterns if not p.startswith("!")]

    def kept(rel: str) -> bool:
        return any(rel == k or rel.startswith(k + "/") for k in keep)

    removed = 0
    for pattern in drop:
        for path in sorted(CORE.glob(pattern), key=lambda p: len(str(p)), reverse=True):
            rel = path.relative_to(CORE).as_posix()
            if kept(rel):
                log(f"keep (re-included): {rel}")
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed += 1
        # Also honour bare directory names that glob() misses at depth.
        for path in sorted(CORE.rglob(Path(pattern).name),
                           key=lambda p: len(str(p)), reverse=True):
            rel = path.relative_to(CORE).as_posix()
            if not fnmatch.fnmatch(rel, pattern) or kept(rel):
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed += 1
    log(f"pruned {removed} path(s)")


def provision(entries: list[dict]) -> None:
    cache = Path("/stage/cache")
    for entry in entries:
        rel = entry["path"]
        target = CORE / rel
        minimum = int(entry.get("min_bytes", 1))
        required = bool(entry.get("required", True))

        if target.is_file() and target.stat().st_size >= minimum:
            log(f"reference data present: {rel} ({target.stat().st_size} bytes)")
            continue

        cached = cache / Path(rel).name
        if cached.is_file() and cached.stat().st_size >= minimum:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, target)
            log(f"reference data from build cache: {rel}")
            continue

        command = entry.get("provision")
        if not command:
            (die if required else log)(
                f"reference data missing and no provision command for {rel}")
            continue

        log(f"provisioning {rel}: {command}")
        result = subprocess.run(command, shell=True, cwd=CORE)
        ok = target.is_file() and target.stat().st_size >= minimum
        if not ok:
            size = target.stat().st_size if target.is_file() else 0
            message = (f"provisioning failed for {rel} "
                       f"(exit {result.returncode}, {size} bytes, need {minimum}). "
                       f"Command: {command}")
            if required:
                die(message)
            log("WARNING: " + message)
            continue

        cache.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, cached)
        log(f"provisioned and cached: {rel} ({target.stat().st_size} bytes)")


def verify(required_paths: list[str]) -> None:
    missing = [p for p in required_paths if not (CORE / p).exists()]
    if missing:
        die("required_paths missing after staging: " + ", ".join(missing))
    log(f"verified {len(required_paths)} required path(s)")


def emit_build_inputs(doc: dict) -> None:
    """Resolve the manifest's build-time choices to fixed paths the Dockerfile
    can consume. A Dockerfile cannot read YAML, and the requirements path and
    conda env name are both manifest-declared — so this stage resolves them and
    writes them where the builder stage can COPY --from here.

    Two deliberate asymmetries:
      * An ABSENT `python.requirements` is legitimate (a core may have no Python
        dependencies at all — see cores/hello-core) and yields an empty file.
      * A DECLARED `python.requirements` that lacks the requested profile is an
        operator error and fails the build loudly. Installing nothing silently
        because of a typo'd profile name is exactly the failure this project's
        'no optional variants' rule exists to prevent.
    """
    python = doc.get("python") or {}
    profile = os.environ.get("PROFILE", "").strip()
    requirements = python.get("requirements") or {}

    out = Path("/stage/requirements.txt")
    if not requirements:
        out.write_text("# this core declares no Python dependencies\n", encoding="utf-8")
        log("no python.requirements declared — core adds no dependencies")
    elif profile not in requirements:
        die(f"PROFILE={profile!r} is not among this core's declared requirement "
            f"profiles ({', '.join(sorted(requirements))}). Build with one of those, "
            f"or add the profile to the manifest.")
    else:
        source = CORE / requirements[profile]
        if not source.is_file():
            die(f"python.requirements[{profile}] points at {requirements[profile]!r}, "
                f"which does not exist in the core ({source})")
        # Copy the whole directory: a tier file may use `-r base.txt`, which only
        # resolves if its siblings come along.
        shutil.copytree(source.parent, Path("/stage/requirements.d"), dirs_exist_ok=True)
        out.write_text(f"-r /stage/requirements.d/{source.name}\n", encoding="utf-8")
        log(f"requirements: profile {profile} -> {requirements[profile]}")

    # An absent conda_env gets a fixed fallback name rather than no env at all, so
    # the image shape is invariant and `conda activate` always works.
    conda_env = (python.get("conda_env") or "harness").strip()
    Path("/stage/build.env").write_text(f"CONDA_ENV={conda_env}\n", encoding="utf-8")
    log(f"conda env: {conda_env}"
        + ("" if python.get("conda_env") else " (default — core declared none)"))


def main() -> None:
    doc = load()
    name = (doc.get("core") or {}).get("name", "?")
    log(f"staging core: {name}")

    image = doc.get("image") or {}
    prune(list(image.get("exclude") or []))
    provision(list(image.get("reference_data") or []))
    verify(list(image.get("required_paths") or []))
    emit_build_inputs(doc)

    total = sum(p.stat().st_size for p in CORE.rglob("*") if p.is_file())
    log(f"core staged: {total / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rewrite the Dockerfile's core section**

Replace the `--- the agent core ---` block and the mount-point block. Keep the
font/Node/apt layers and the trailing `CLAUDE_CODE_VERSION` block **exactly as they
are** — only the lines below change.

**`core-stage` must come FIRST, before `builder`.** The builder installs the
payload's dependency tier, and after Task 9 that tier lives inside the core at a
*manifest-declared* path which a Dockerfile cannot read. `core-stage` resolves it
(and the conda env name) to fixed paths the builder then copies from. Add this as
the first stage, above `builder`:

```dockerfile
# ---------------------------------------------------------------------------
# Stage 1 — stage the agent core: prune per manifest, provision reference data,
# and resolve the manifest's build-time choices (requirements tier, conda env
# name) to fixed paths, because a Dockerfile cannot read YAML.
#
# HARNESS_CORE selects which core goes into the image:
#   slot     the copy-paste slot (default) -> cores/slot/
#   <name>   a drop-in core, e.g. HARNESS_CORE=moa-ag -> cores/moa-ag/
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS core-stage

ARG HARNESS_CORE=slot
RUN pip install --no-cache-dir pyyaml

# Tools a core's provision command may need (the MOA core downloads a 322 MB
# reference CSV). Kept minimal: this stage is discarded.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget unzip \
    && rm -rf /var/lib/apt/lists/*

COPY cores/${HARNESS_CORE}/ /stage/core/
COPY manifests/ /stage/manifests/
COPY container/stage_core.py /stage/stage_core.py

# The cache mount means an upstream 504 on retry does not re-download 322 MB.
ARG PROFILE
ENV HARNESS_CORE=${HARNESS_CORE} PROFILE=${PROFILE}
RUN --mount=type=cache,target=/stage/cache,sharing=locked \
    python /stage/stage_core.py /stage/core
```

Then modify the **`builder`** stage to consume what `core-stage` resolved. Replace
its `COPY Schollar_System/runner/requirements/ /tmp/requirements/` line and the
`uv pip install` that follows with:

```dockerfile
# The harness's own deps are a fixed file; the payload's are whatever its manifest
# declared, already resolved by core-stage (a Dockerfile cannot read YAML).
COPY container/requirements/platform.txt /tmp/platform.txt
COPY --from=core-stage /stage/requirements.txt /tmp/core-requirements.txt
COPY --from=core-stage /stage/requirements.d/ /stage/requirements.d/
COPY --from=core-stage /stage/build.env /tmp/build.env

# The env is always created at a FIXED path, and the manifest's declared name
# becomes a symlink alias. That keeps every ENV line static (Dockerfile ENV cannot
# be computed) while `conda activate <declared-name>` still works — which matters,
# because a core's own instructions tell the agent to run exactly that. MOA's
# CLAUDE.md §7 says `conda activate moa`; hello-core declares nothing and gets the
# `harness` default. Both resolve to the same real env.
RUN . /tmp/build.env \
    && micromamba create -y -p /opt/conda/envs/core -c conda-forge \
        --override-channels python=3.12 pip \
    && micromamba clean -a -y \
    && uv pip install --no-cache --python /opt/conda/envs/core/bin/python \
        -r /tmp/platform.txt -r /tmp/core-requirements.txt \
    && find /opt/conda -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && ln -sfn /opt/conda/envs/core "/opt/conda/envs/${CONDA_ENV}" \
    && printf 'CONDA_ENV=%s\n' "${CONDA_ENV}" > /opt/conda/env-name
```

Delete the hard-coded `micromamba create -y -p /opt/conda/envs/moa` from the
earlier layer and the `python -c "import rdkit, chembl_webresource_client, …"`
verification — both name MOA specifics. The import check is now the core's
`python.import_check`, enforced by `harness.preflight` at start-up.

In the `runtime` stage, replace every literal `envs/moa` with `envs/core` — so all
the `ENV` lines (`PATH`, `CONDA_PREFIX`) stay static. The symlink and
`/opt/conda/env-name` come along with the `COPY --from=builder /opt/conda` that
already exists. Set `CONDA_DEFAULT_ENV` from the alias in `conda-init.sh` (already
sourced by every bash via `BASH_ENV`) by reading `/opt/conda/env-name`, so
`conda env list` and the shell prompt show the name the core declared.

Verify both spellings resolve to the same interpreter — add to the existing
post-conda `RUN bash -c '…'` check:

```dockerfile
    && bash -c '. /opt/conda/env-name \
        && conda run -n core --no-capture-output python -c "import sys; print(sys.prefix)" \
        && conda run -n "${CONDA_ENV}" --no-capture-output python -c "import sys; print(sys.prefix)" \
        && conda activate "${CONDA_ENV}" && command -v python'
```

Then in the `runtime` stage, replace the agent-core COPY block with:

```dockerfile
# --- the agent core (pruned + provisioned by core-stage) -------------------
# /app is the CORE'S territory, verbatim: its instructions, its .claude/, its
# packages. The harness lives at /opt/harness so nothing a core ships can
# shadow it.
COPY --from=core-stage --chown=moa:moa /stage/core/ /app/

# --- the harness ----------------------------------------------------------
COPY --chown=moa:moa harness/   /opt/harness/harness/
COPY --chown=moa:moa manifests/ /opt/harness/manifests/
COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh
```

and the env block:

```dockerfile
ENV HARNESS_CORE_ROOT=/app \
    HARNESS_RESULTS_ROOT=/data/results \
    HARNESS_MANIFEST_DIR=/opt/harness/manifests \
    PYTHONPATH=/opt/harness:/app \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
```

> `PYTHONPATH=/opt/harness:/app` puts the harness first, then the core — so
> `import harness` always resolves to the harness, and a core's own packages
> (`moa_lib`) resolve from `/app`. The core's `image.env` values are applied by
> `entrypoint.sh` at start-up rather than baked, so a core change does not need
> a Dockerfile edit.

Replace the hard-coded mirna assert in the mount-point `RUN` with just the
symlink and ownership:

```dockerfile
RUN mkdir -p /data/results \
    && ln -sfn /data/results /app/results \
    && chown -R moa:moa /data \
    && chown moa:moa /app /app/results
```

Update `CMD` to `["python", "-m", "harness.run_once", "--help"]` and the
`HEALTHCHECK` to `CMD python -m harness.preflight && claude --version || exit 1`.

- [ ] **Step 3: Apply the core's `image.env` in `entrypoint.sh`**

Insert before the preflight call:

```bash
# --- apply the core's declared environment -------------------------------
# A core may need env of its own (e.g. a CJK font path for PDF rendering).
# Declared in its manifest as image.env, applied here so a core change needs
# no Dockerfile edit. Existing values win, so an operator can always override.
while IFS='=' read -r key value; do
    [[ -n "${key}" ]] || continue
    if [[ -z "${!key:-}" ]]; then
        export "${key}=${value}"
        log "core env: ${key}=${value}"
    fi
done < <(python -c "
from harness.config import settings
for k, v in settings.manifest().image_env.items():
    print(f'{k}={v}')
" 2>/dev/null || true)
```

- [ ] **Step 4: Update `docker-compose.yml`**

```yaml
x-runner-base: &runner-base
  build:
    context: ..                                 # the repo root
    dockerfile: container/Dockerfile
    args:
      PROFILE: ${HARNESS_PROFILE:-omics}
      HARNESS_CORE: ${HARNESS_CORE:-slot}
  image: agent-harness:${HARNESS_CORE:-slot}-${HARNESS_PROFILE:-omics}
  env_file: [.env]
  volumes:
    - harness-results:/data/results
    - harness-claude-state:/home/moa/.claude
  mem_limit: ${HARNESS_MEM_LIMIT:-8g}
  cpus: ${HARNESS_CPUS:-4}
  dns_opt: ["timeout:2", "attempts:3"]
```

Change every `command:` to the `harness.` module path (`python -m harness.run_once`,
`python -m harness.worker`, `python -m harness.smoke_test`), and the volume names
at the bottom to `harness-results:` / `harness-claude-state:`.

- [ ] **Step 5: Build**

```bash
cd /d/Dev/projects/agent-harness/container
cp .env.example .env     # then paste ANTHROPIC_API_KEY
DOCKER_BUILDKIT=1 HARNESS_CORE=moa-ag HARNESS_PROFILE=omics docker compose build
```

Expected: build succeeds. Watch for `[stage_core] provisioning .claude/skills/mirna-targets/data/hsa_MTI.csv`
followed by `[stage_core] provisioned and cached: ... (33xxxxxxx bytes)` — that is
the 322 MB problem being solved. If the upstream 504s, re-run the build; the
cache mount makes the retry cheap.

- [ ] **Step 6: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add container/ 
git commit -m "feat(build): three-stage build with manifest-driven core staging

core-stage prunes per image.exclude and provisions reference data, so a fresh
clone can build. /app is the core, /opt/harness is the harness.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: manifest-driven smoke test

**Files:**
- Modify: `NEW/harness/smoke_test.py`

**Interfaces:**
- Consumes: `Manifest`, `preflight.check`
- Produces: `python -m harness.smoke_test` → exit 0/1

- [ ] **Step 1: Replace the hard-coded checks**

Keep the `check(name, ok, detail)` reporting helper and the conda/CLI/SDK
sections. Replace the MOA-specific assertions:

```python
from pathlib import Path

from harness.config import settings
from harness.manifest import load_manifest
from harness.preflight import check as preflight_check

CORE = settings.core_root
manifest = load_manifest(CORE, sidecar_dir=settings.manifest_dir)

check("manifest loads", True, f"{manifest.display_name} ({manifest.name} {manifest.version})")
check("instructions present", (CORE / manifest.instructions).is_file(), manifest.instructions)
check("milestones declared", len(manifest.milestones) > 0, f"{len(manifest.milestones)}")
check("halt gates declared", True, ", ".join(manifest.halts) or "none")

for failure in preflight_check(manifest, CORE, settings.results_root):
    check("preflight", False, failure)

# The harness's OWN agent config must never ship — a second CLAUDE.md at /app
# would be read by the agent instead of the core's and corrupt every run.
check("no harness CLAUDE.md leaked",
      not Path("/opt/harness/CLAUDE.md").exists() and not Path("/opt/harness/.claude").exists(),
      "harness agent config absent from the image")
check("core owns /app/CLAUDE.md",
      (CORE / manifest.instructions).is_file(),
      "the only instructions file is the core's")

for pkg in manifest.package_paths:
    check(f"core package {pkg}", (CORE / pkg).is_dir())
```

- [ ] **Step 2: Run the smoke profile for the MOA core**

```bash
cd /d/Dev/projects/agent-harness/container
HARNESS_CORE=moa-ag docker compose --profile smoke run --rm smoke
```

Expected: **all checks PASS, exit 0.** This costs nothing — no Claude call.

- [ ] **Step 3: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add harness/smoke_test.py
git commit -m "test(smoke): manifest-driven image validation

Also asserts the harness's own CLAUDE.md/.claude never reach the image.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Phase E — The genericity proof

### Task 18: `cores/hello-core` — a second, trivial core

**Files:**
- Create: `NEW/cores/hello-core/{CLAUDE.md,agent-core.yaml,.agent-core/prompt_run.md}`
- Create: `NEW/tests/test_hello_core.py`

**Interfaces:**
- Consumes: everything above
- Produces: proof the harness is payload-agnostic

- [ ] **Step 1: Write the core**

`NEW/cores/hello-core/CLAUDE.md`:

```markdown
# hello-core — the harness's reference agent core

A deliberately minimal agent core. It exists so the harness can prove it is
payload-agnostic: if `hello-core` runs without any harness code change, the
manifest abstraction is real.

## The task

Given a `topic`, write two files into the run directory:

1. `notes.md` — three to five sentences about the topic, with a one-line
   statement of what you are NOT confident about.
2. `done.md` — a single line: `DONE: <one-sentence summary>`.

## The gate

If the topic is empty, meaningless, or you cannot say anything substantive
about it, write `HALT_empty_topic.md` explaining why and stop. **A halt is a
valid outcome**, not a failure — do not manufacture content to avoid it.
```

`NEW/cores/hello-core/agent-core.yaml`:

```yaml
# The minimal manifest. Every key here is required; nothing else is.
schema: 1

core:
  name: hello-core
  display_name: "Hello core (harness reference payload)"
  version: "1.0"

agent:
  instructions: CLAUDE.md
  setting_sources: [project]
  run_dir_env: HELLO_RUN_DIR
  defaults:
    model: claude-haiku-4-5-20251001
    max_turns: 20
    permission_mode: bypassPermissions

inputs:
  - {name: topic, type: string, required: true, cli: --topic}

run_dir:
  template: "hello_{topic|slug}"
  fallback: "hello"
  session_suffix: "_session{n}"
  probe_base: probe

prompt:
  run: .agent-core/prompt_run.md

progress:
  milestones:
    - {artifact: notes.md, phase: write, percent: 50,  label: "Notes written"}
    - {artifact: done.md,  phase: done,  percent: 100, label: "Done"}

outcome:
  halts:
    HALT_empty_topic.md: empty_topic
  success_requires: [done.md]
  deliverable: done.md
  headline: {artifact: done.md, section: "DONE"}

image:
  required_paths: [CLAUDE.md]
```

Note what is **absent**: no `python` section (no conda env, no packages, no
requirements), no `reference_data`, no `image.exclude`, no `artifacts.exclude`,
no `prompt.probe`. If the harness needs any of them, it has a hidden default.

`NEW/cores/hello-core/.agent-core/prompt_run.md`:

```markdown
Follow CLAUDE.md exactly.

INPUTS
  Topic: {topic}

OUTPUT DIRECTORY
  Use `results/{run_dir}/` verbatim for every file. It already exists. Do not
  create any other results directory.

{extra}
ENDING THE RUN — the line below is a SWITCH, not a formality
  Write it only when the work is genuinely finished (or the gate halted it):

    RUN_COMPLETE: <completed|halted> - <one-sentence verdict>
```

- [ ] **Step 2: Write the test**

`NEW/tests/test_hello_core.py`:

```python
"""The genericity proof. If any assertion here needs a harness code change,
the manifest abstraction is incomplete."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import classify as C
from harness import naming, progress, prompt
from harness.manifest import load_manifest

CORE = Path(__file__).resolve().parents[1] / "cores" / "hello-core"
M = load_manifest(CORE)


def test_minimal_manifest_loads_with_no_python_section():
    assert M.name == "hello-core"
    assert M.conda_env == ""
    assert M.package_paths == []
    assert M.requirements == {}
    assert M.reference_data == []


def test_run_dir_naming():
    assert naming.base_name(M, {"topic": "Tardigrade Cryptobiosis"}) \
        == "hello_tardigrade_cryptobiosis"
    assert naming.base_name(M, {"topic": "七白散"}) == "hello"


def test_run_dir_session_increment(tmp_path):
    assert naming.next_session_dir(tmp_path, M, {"topic": "X"}) == "hello_x_session1"


def test_prompt_renders_from_the_core():
    out = prompt.build_prompt(M, CORE, {"topic": "Tardigrades"}, "hello_tardigrades_session1")
    assert "Topic: Tardigrades" in out
    assert "results/hello_tardigrades_session1/" in out
    assert "{topic}" not in out and "{extra}" not in out


def test_missing_required_input_raises():
    with pytest.raises(ValueError, match="topic is required"):
        prompt.build_prompt(M, CORE, {"topic": "  "}, "hello_session1")


def test_probe_prompt_falls_back_to_the_harness_template():
    # hello-core declares no prompt.probe — the harness's own template is used.
    out = prompt.build_probe_prompt(M, CORE, "probe_session1")
    assert "INFRASTRUCTURE PROBE" in out
    assert "MOA" not in out, "the default probe template must be payload-agnostic"


def test_its_own_halt_file_is_a_valid_outcome(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "HALT_empty_topic.md").write_text("nothing to say\n", encoding="utf-8")
    out = C.classify(d, M)
    assert out.status == C.STATUS_HALTED
    assert out.reason == "empty_topic"
    assert out.is_deliverable is True


def test_success_requires_its_own_artifacts(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "done.md").write_text("DONE: did the thing\n", encoding="utf-8")
    assert C.classify(d, M).status == C.STATUS_COMPLETED


def test_progress_uses_its_own_two_milestones(tmp_path):
    class Em:
        def __init__(self): self.seen = []
        def emit(self, t, m="", **f): self.seen.append(f.get("artifact"))

    d = tmp_path / "run"
    d.mkdir()
    em = Em()
    w = progress.ProgressWatcher.from_manifest(d, em, M)
    (d / "done.md").write_text("DONE: x\n", encoding="utf-8")
    w.scan()
    assert w.percent == 100
    assert "done.md" in em.seen
```

- [ ] **Step 3: Run the test**

Run: `cd /d/Dev/projects/agent-harness && conda run -n moa python -m pytest tests/test_hello_core.py -v`

Expected: **all PASS with no changes to `harness/`.** If any test requires a
harness edit, stop and fix the abstraction — that is the finding this task exists
to surface.

- [ ] **Step 4: Build and smoke the second core**

```bash
cd /d/Dev/projects/agent-harness/container
DOCKER_BUILDKIT=1 HARNESS_CORE=hello-core HARNESS_PROFILE=base docker compose build
HARNESS_CORE=hello-core docker compose --profile smoke run --rm smoke
HARNESS_CORE=hello-core docker compose run --rm runner --topic "Tardigrade cryptobiosis" --dry-run
```

Expected: build succeeds (no conda env, no reference data, no science stack),
smoke passes, dry-run prints the run directory `hello_tardigrade_cryptobiosis_session1`
and the rendered prompt without calling Claude.

- [ ] **Step 5: Confirm the MOA core still builds and smokes**

```bash
HARNESS_CORE=moa-ag docker compose --profile smoke run --rm smoke
```

Expected: PASS. Both cores from one unchanged harness is the deliverable.

- [ ] **Step 6: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add cores/hello-core tests/test_hello_core.py
git commit -m "test: add hello-core, the proof the harness is payload-agnostic

Two cores from one unchanged harness: MOA-AG (conda env, 322 MB reference data,
14 milestones) and hello-core (no python section at all, 2 milestones).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Phase F — Downstream

### Task 19: `infra/` and `backend-handler/` rewiring

**Files:**
- Modify: `NEW/infra/config.yaml`, `NEW/infra/stacks/compute-fargate.yaml`, `NEW/infra/stacks/data.yaml`, `NEW/infra/template.yaml`, `NEW/infra/scripts/{push-image.sh,verify.sh,validate_iam.py}`
- Modify: `NEW/backend-handler/config/index.js`, `NEW/backend-handler/utils/{runQueue.js,runStore.js}`

**Interfaces:**
- Consumes: the `HARNESS_*` names from Task 15
- Produces: a stack whose task definition passes `HARNESS_*` and `HARNESS_CORE`

- [ ] **Step 1: Verify Task 15's sweep reached these files**

Run: `cd /d/Dev/projects/agent-harness && grep -rn "MOA_" infra backend-handler | grep -v "MOA_RUN_DIR"`

Expected: no output. If there is any, apply the Task 15 Step 2 `sed` to those files.

- [ ] **Step 2: Make the resource prefix a configuration value**

In `infra/config.yaml`, add at the top level (keeping today's values as the default
so nothing changes shape):

```yaml
# Deployment namespace. Distinct from the harness's name on purpose: one account
# can host several harness deployments, and the resource names belong to the
# deployment, not to the software.
namespace: schollar
```

Then in `infra/scripts/config.py`, expose `namespace`, and in the templates
replace the hard-coded literals with the parameter — `schollar-moa-runs.fifo` →
`!Sub "${Namespace}-runs.fifo"`, `schollar_moa_runs` → `!Sub "${Namespace}_runs"`,
`schollar-moa-artifacts` → `!Sub "${Namespace}-artifacts"`. Add a `Namespace`
parameter to each template that uses them and thread it through the nested-stack
`Parameters` blocks.

- [ ] **Step 3: Add `HARNESS_CORE` to the task definition**

In `infra/stacks/compute-fargate.yaml`, add to the container's `Environment`:

```yaml
          - Name: HARNESS_CORE
            Value: !Ref HarnessCore
```

with a template parameter:

```yaml
  HarnessCore:
    Type: String
    Default: moa-ag
    Description: >-
      Which agent core the image was built with. Must match the image tag's core
      segment (agent-harness:<core>-<profile>) — a mismatch means the container
      preflights against a manifest the image does not contain.
```

- [ ] **Step 4: Lint the templates**

Run: `cd /d/Dev/projects/agent-harness/infra && bash scripts/lint.sh`

Expected: clean, or the same pre-existing findings as before the change. Compare
against a `git stash` run if unsure.

- [ ] **Step 5: Verify the handler against LocalStack**

Run the existing local verification path in `backend-handler/README.md`.

Expected: the same result as before the rename.

- [ ] **Step 6: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add infra backend-handler
git commit -m "refactor(infra): HARNESS_* env, HARNESS_CORE parameter, namespaced resources

Resource names move from hard-coded schollar-* literals to a Namespace
parameter: a deployment's name is not the harness's name.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 20: documentation

**Files:**
- Create: `NEW/doc/ADDING_A_CORE.md`
- Modify: `NEW/README.md`, `NEW/doc/{ARCHITECTURE.md,API_PROTOCOL.md,EVENT_SCHEMA.md,VERIFY_CONTRACT.md,DEPLOY_EC2.md,LOCAL_SETUP.md}`
- Create: `NEW/container/README.md` (replaces the old `runner/README.md`)

**Interfaces:**
- Consumes: everything
- Produces: a repo a newcomer can use

- [ ] **Step 1: Write `doc/ADDING_A_CORE.md`**

It must contain, in this order: what an agent core is; the three-step quickstart
(copy into `cores/slot/`, write `agent-core.yaml`, build); the **complete
annotated schema** with every key marked required or optional; the `hello-core`
walkthrough as a worked example; how to pin a core as a submodule; and a
troubleshooting table whose first row is the missing-manifest error and whose
second is a `required_paths` failure.

- [ ] **Step 2: Rewrite `README.md`**

Lead with what the harness is (not what Schollar is), the two-core example, the
`$0` smoke command, and the three-outcomes rule. Keep the existing boundary-rule
and halt sections — they are good and still true. Replace the folder table with
the Task 6 layout, and every `MOA_*` / `runner/` / `Schollar_System` reference.

- [ ] **Step 3: Sweep the docs for stale names**

```bash
cd /d/Dev/projects/agent-harness
grep -rn "Schollar_System\|runner/app\|service\.run_once\|moa-runner\|MOA_BUILD_PROFILE" \
    README.md doc/ container/ --include=*.md --include=*.sh --include=*.yml
```

Expected: no output when done. Each hit is a stale reference to fix.

- [ ] **Step 4: Verify every documented command actually runs**

Execute each command block in `README.md`, `doc/LOCAL_SETUP.md` and
`doc/ADDING_A_CORE.md`. A documented command that fails is a docs bug.

- [ ] **Step 5: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add README.md doc/ container/README.md
git commit -m "docs: rewrite for the harness; add ADDING_A_CORE.md

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 21: paid end-to-end validation (Layer 4)

**Files:**
- Create: `NEW/doc/VALIDATION_2026-10-01.md`

**Interfaces:**
- Consumes: the finished image
- Produces: the record that the refactor preserved real behaviour

> **This task spends real money** (one full MOA run — historically tens of
> minutes and several dollars). Confirm with the operator before starting. Every
> prior layer is `$0`; this is the only one that is not.

- [ ] **Step 1: Run the pipeline end to end**

```bash
cd /d/Dev/projects/agent-harness/container
HARNESS_CORE=moa-ag docker compose run --rm runner \
    --compounds Curcumin --disease "Atopic Dermatitis" 2>&1 | tee /tmp/e2e.jsonl
```

- [ ] **Step 2: Check the outcome and the event stream**

```bash
echo "exit: $?"
grep -o '"type":"[^"]*"' /tmp/e2e.jsonl | sort | uniq -c
grep -o '"percent":[0-9]*' /tmp/e2e.jsonl | tail -5
```

Expected: exit 0 (`completed`) **or** 10 (`halted` — equally valid). Phases
appear in milestone order, percent is monotonic and ends at 100 for a completed
run. A `halted` run stops early by design — that is a pass, not a failure.

- [ ] **Step 3: Record the result**

Write `doc/VALIDATION_2026-10-01.md` with: the image tag and
`CLAUDE_CODE_VERSION`, the `cores/moa-ag` commit SHA, the exit code and status,
wall-clock and cost, the phase/percent sequence, and a diff against a prior
session's sequence. State plainly whether it matched, and if not, exactly where
it diverged.

- [ ] **Step 4: Commit**

```bash
cd /d/Dev/projects/agent-harness
git add doc/VALIDATION_2026-10-01.md
git commit -m "docs: record the post-extraction end-to-end validation run

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §2 decisions — name, topology, one repo | 6, 7 |
| §3 target layout | 6 |
| §3 in-container paths (`/app`, `/opt/harness`) | 16 |
| §3 module name unification | 6 |
| §3 `conda_env` payload-declared | 8, 9 |
| §4 manifest schema + resolution order + fail-loud | 8 |
| §4 `run_dir` exact semantics | 10 |
| §4 core selection build arg | 16 |
| §5 service-layer table (all 13 modules) | 10, 11, 12, 13, 14, 15 |
| §5 requirements split | 8 (platform.txt), 9 (payload tiers) |
| §6 three stages | 16 |
| §6 `.dockerignore` vs staging split | 6 (ignore), 16 (stage) |
| §6 reference-data resolution order | 16 (`stage_core.provision`) |
| §7 Layer 1 golden tests | 1, 2, 3, 4, 5 |
| §7 Layer 2 smoke | 17 |
| §7 Layer 3 second core | 18 |
| §7 Layer 4 paid e2e | 21 |
| §7 rollback / `MOVED.md` | 7 |
| §8 env rename table | 15 |
| §8 downstream files | 15 (sweep), 19 (infra/handler), 20 (docs) |
| §8 AWS namespace | 19 |
| §9 risk: harness `CLAUDE.md` leak | 6 (`.dockerignore`), 17 (asserted) |
| §9 risk: template edge cases | 1, 10 |
| §10 `MOA_AG_Reserach/CLAUDE.md` unedited | Global Constraints; no task modifies it |

No gaps found.

**Fixes applied during review:**

1. **Task 4 snapshot regeneration was under-specified.** Task 13 Step 1 edits one
   sentence of the probe template, which *must* change two snapshots. Originally
   this read as a golden-test violation. Now Task 13 names exactly which two
   snapshots change, requires a `git diff` inspection, and states that
   `run_basic`/`run_extra` must remain untouched — which is the actual proof.
2. **`Milestone.filename` vs `Milestone.artifact`.** Task 3's test asserted
   `m.filename` (today's field) but Task 8's manifest `Milestone` names it
   `artifact`. Task 11 Step 2 now explicitly renames that one assertion.
3. **`collect_artifacts` signature drift.** Task 12 changed it to take `exclude`,
   but Task 2's golden test calls it with one argument. The Task 12 shim now
   supplies `_MOA.artifact_exclude`.
4. **`image.env` application was unassigned.** The manifest declares
   `MOA_CJK_FONT` but no task applied it — it would have silently vanished,
   breaking CJK PDF rendering. Added as Task 16 Step 3 in `entrypoint.sh`, with
   operator-set values winning.
5. **`run_once.build_parser` may not exist yet.** Task 5 Step 1 now instructs
   extracting it from `main()` as a separate committed refactor first, rather
   than assuming the function is already there.
6. **`PYTHONPATH` order.** Task 16 pins `/opt/harness:/app` and explains why: the
   harness must win, and `moa_lib` must still resolve from the core.

**Type consistency:** verified `Manifest` attribute names used in Tasks 10–18
against the dataclass defined in Task 8 — `milestones`, `halts`,
`success_requires`, `deliverable`, `headline_artifact`, `headline_section`,
`qa_artifact`, `qa_verdicts`, `qa_blocking`, `required_paths`, `reference_data`,
`image_exclude`, `image_env`, `artifact_exclude`, `conda_env`, `package_paths`,
`import_check`, `requirements`, `default_profile`, `prompt_run`, `prompt_probe`,
`run_dir_env`, `setting_sources`, `instructions`, `inputs`, `run_dir`. All match.
`Milestone.artifact` is used consistently after fix 2. `ProgressWatcher.from_manifest`
is used identically in Tasks 11 and 18.
