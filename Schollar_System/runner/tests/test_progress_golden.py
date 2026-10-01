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
