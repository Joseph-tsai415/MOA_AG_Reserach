"""Tests for `moa_lib.specificity_controls` — the four defects fixed in the v12 hardening.

Each defect came out of a real run, so each test is written against the observed
failure, and EVERY test is paired with a negative control that shows the test can
fail: either a sibling assertion on the opposite input, or the pre-fix behaviour
restored verbatim and asserted to break the test's premise.

  1. determinism      — `network_proximity` iterated `set(targets)`, so seed=1234 gave
                        z_c = -5.72 and -5.44 on two runs of the same data.
                        Negative control: `_determinism_worker.py legacy` restores that
                        one line and MUST differ across two PYTHONHASHSEED values.
  2. underpowered     — a 1-2 target drug cannot reach p < 0.05; HALTing it reports
                        test power as biology (kernel design §8.1 R1 / §8.4).
                        Negative control: the same assertions on a large target set,
                        which must come back powered and must still HALT.
  3. decoy verdict    — a failed decoy was invisible to `halt_decision`.
                        Negative control: a passing decoy, and the not-run case; both
                        must be distinguishable from DECOY_FAILED, and none of them
                        may read as a pass unless the decoy actually passed.
  4. equality checks  — a checker published 94 edges for a 92-edge graph and passed
                        because it compared `a > b`.
                        Negative control: `_check_equal(94, 92)` must raise, and must
                        still raise under `python -O` (a bare assert would not).

Run:  python -m pytest moa_lib/tests/test_specificity_controls.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from moa_lib import specificity_controls as sc

WORKER = Path(__file__).resolve().parent / "_determinism_worker.py"
HASH_SEEDS = ("0", "12345")


def run_worker(mode: str, hashseed: str) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    out = subprocess.run([sys.executable, str(WORKER), mode], env=env,
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, f"worker {mode} (seed {hashseed}) failed:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


# =============================================================================== 1. determinism


def test_network_proximity_identical_under_two_hash_seeds():
    """Same input, same seed, two different PYTHONHASHSEEDs -> byte-identical output."""
    a = run_worker("fixed", HASH_SEEDS[0])
    b = run_worker("fixed", HASH_SEEDS[1])
    assert a == b, f"network_proximity is still hash-seed dependent:\n{a}\n{b}"
    assert a["z_c"] == b["z_c"]


def test_two_seed_harness_detects_the_old_nondeterminism():
    """NEGATIVE CONTROL for the test above.

    Restore the single pre-fix line (`tset = [t for t in set(targets) ...]`) and the
    same two-seed comparison must FAIL. Without this, a harness that compared two
    identical-by-accident numbers would look like a passing determinism test.
    """
    a = run_worker("legacy", HASH_SEEDS[0])
    b = run_worker("legacy", HASH_SEEDS[1])
    assert a != b, ("the pre-fix implementation came back identical across hash seeds, "
                    "so this harness cannot detect nondeterminism and the test above "
                    "proves nothing")
    assert a["z_c"] != b["z_c"]
    assert a["d_c"] == b["d_c"], "d_c is order-invariant even in the old code; only the null moved"


def test_whole_step3_chain_identical_under_two_hash_seeds():
    """overlap + proximity + decoy + halt_decision together, end to end."""
    a = run_worker("overlap", HASH_SEEDS[0])
    b = run_worker("overlap", HASH_SEEDS[1])
    assert a == b
    assert a["halt"]["outcome"] == b["halt"]["outcome"]
    assert a["halt"]["decoy_outcome"] == b["halt"]["decoy_outcome"]


def test_canonical_graph_removes_graph_node_order_sensitivity():
    """The documented residual: `graph`'s own key order feeds the degree bins.

    A graph dict assembled by iterating an unordered container is a different input in
    each process, and no amount of sorting inside the module can recover it; the module
    documents `canonical_graph()` as the fix. This test pins both halves of that
    contract, so the hazard cannot be rediscovered the hard way.
    """
    raw_a = run_worker("setbuilt", HASH_SEEDS[0])
    raw_b = run_worker("setbuilt", HASH_SEEDS[1])
    assert raw_a != raw_b, ("a set-built graph dict was expected to differ between hash "
                            "seeds; if it no longer does, this test's premise is stale")
    can_a = run_worker("setbuilt_canonical", HASH_SEEDS[0])
    can_b = run_worker("setbuilt_canonical", HASH_SEEDS[1])
    assert can_a == can_b, "canonical_graph() did not make the result reproducible"


def test_proximity_invariant_to_target_and_disease_iteration_order():
    """In-process: list, reversed list, set and duplicated input all agree."""
    graph = _chain_graph(60)
    targets = ["g5", "g9", "g2", "g31"]
    disease = ["g40", "g45", "g50"]
    base = asdict(sc.network_proximity(targets, disease, graph, n_rand=50))
    for order in (list(reversed(targets)), set(targets), targets + targets):
        assert asdict(sc.network_proximity(order, disease, graph, n_rand=50)) == base
    for order in (list(reversed(disease)), set(disease)):
        assert asdict(sc.network_proximity(targets, order, graph, n_rand=50)) == base


def test_target_order_actually_matters_to_the_null():
    """NEGATIVE CONTROL for the test above: order-invariance is not vacuous.

    Draw the null in the order the caller happened to supply (what the old code did
    once Python's hash had shuffled it) and the answer moves — so the invariance
    asserted above is a property of the fix, not of the arithmetic.
    """
    graph = _chain_graph(60)
    disease = ["g40", "g45", "g50"]
    a = _proximity_in_given_order(["g5", "g9", "g2", "g31"], disease, graph)
    b = _proximity_in_given_order(["g31", "g2", "g9", "g5"], disease, graph)
    assert a != b, ("drawing the null in two different target orders gave the same z_c, "
                    "so this input cannot demonstrate order sensitivity")


# =============================================================================== 2. underpowered


def test_minimum_achievable_p_single_target():
    """One target, 2000 disease genes, 20000-gene universe: best case p = 2000/20000."""
    p = sc.minimum_achievable_p(1, 2000, 20000)
    assert p == pytest.approx(0.1, rel=1e-12)
    assert p > 0.05


def test_minimum_achievable_p_three_targets_matches_closed_form():
    n_A, n_B, N = 3, 8000, 20000
    p = sc.minimum_achievable_p(n_A, n_B, N)
    closed = (8000 / 20000) * (7999 / 19999) * (7998 / 19998)
    assert p == pytest.approx(closed, rel=1e-9)
    assert p > 0.05


def test_minimum_achievable_p_is_tiny_for_a_large_target_set():
    """NEGATIVE CONTROL: the same function must come back powered for real set sizes."""
    assert sc.minimum_achievable_p(74, 410, 19276) < 1e-100     # results/obesity sizes
    assert sc.minimum_achievable_p(300, 650, 20000) < 1e-100    # the module's __main__ example


def test_minimum_achievable_p_includes_the_permutation_floor():
    """`halt_decision` takes the worse of the two p's, so 1/(n_perm+1) is a floor too."""
    assert sc.minimum_achievable_p(300, 650, 20000, n_perm=10) == pytest.approx(1 / 11)
    assert sc.minimum_achievable_p(300, 650, 20000, n_perm=10) > 0.05
    assert sc.minimum_achievable_p(300, 650, 20000, n_perm=10000) < 0.05


@pytest.mark.parametrize("n_A,n_B,universe,expected", [
    (1, 2000, 20000, True),     # one measured target, broad disease list
    (3, 8000, 20000, True),     # three targets: 0.4^3 = 0.064 > 0.05
    (1, 1001, 20000, True),     # just over the boundary
    (1, 1000, 20000, False),    # exactly at alpha -> p == alpha is NOT > alpha
    (74, 410, 19276, False),    # results/obesity
    (300, 650, 20000, False),   # __main__ example
])
def test_overlap_power_threshold_behaviour(n_A, n_B, universe, expected):
    """One parametrisation covering both verdicts: the boundary is p > alpha, not >=."""
    pw = sc.overlap_power(n_A=n_A, n_B=n_B, universe=universe, alpha=0.05)
    assert pw.underpowered is expected
    assert pw.rule == sc.RULE_COMPUTED_MIN_P
    assert pw.max_achievable_overlap == min(n_A, n_B)


def test_overlap_power_reads_sizes_from_an_overlap_result():
    ov = sc.overlap_significance({"HMGCR"}, {f"d{i}" for i in range(2000)},
                                 universe=20000, n_perm=100)
    pw = sc.overlap_power(ov)
    assert pw.underpowered is True
    assert (pw.n_A, pw.n_B, pw.universe) == (1, 2000, 20000)
    assert "minimum achievable p" in pw.detail


def test_engaged_target_count_fallback_when_sizes_are_unavailable():
    """§8.1 R1 as literally written, kept for callers that cannot supply the sizes."""
    for n, expected in ((1, True), (3, True), (4, False), (12, False)):
        pw = sc.overlap_power(n_engaged_targets=n)
        assert pw.underpowered is expected
        assert pw.rule == sc.RULE_ENGAGED_TARGET_COUNT
    assert sc.overlap_power().rule == sc.RULE_NOT_ASSESSABLE
    assert sc.overlap_power().underpowered is False


def test_computed_rule_wins_over_the_count_fallback():
    """A 3-target drug whose test CAN reach alpha is not underpowered (§8.4)."""
    pw = sc.overlap_power(n_A=3, n_B=200, universe=20000, n_engaged_targets=3)
    assert pw.underpowered is False and pw.rule == sc.RULE_COMPUTED_MIN_P
    assert pw.count_underpowered is True          # the fallback's verdict is still visible
    assert sc.overlap_power(n_A=3, n_B=200, universe=20000, n_engaged_targets=3,
                            rule="either").underpowered is True
    assert sc.overlap_power(n_A=3, n_B=200, universe=20000, n_engaged_targets=3,
                            rule="count").underpowered is True


def test_halt_decision_underpowered_continues_and_caps_confidence():
    ov = _overlap(n_A=1, n_B=2000, universe=20000, observed=1, hg_p=0.1, perm_p=0.11)
    res = sc.halt_decision(ov, None)
    assert res.outcome == sc.SPECIFICITY_UNDERPOWERED
    assert res.halt is False, "an underpowered overlap must not stop the run (§8.1 R1)"
    assert res.underpowered is True
    assert res.confidence_cap == sc.UNDERPOWERED_CONFIDENCE_CAP
    assert any("underpowered by construction" in r for r in res.reasons)
    halt, reasons = res                                  # still the historical 2-tuple
    assert halt is False and reasons is res.reasons


def test_halt_decision_still_halts_a_powered_non_significant_overlap():
    """NEGATIVE CONTROL: identical p, large sets -> the HALT must still fire."""
    ov = _overlap(n_A=300, n_B=2000, universe=20000, observed=20, hg_p=0.1, perm_p=0.11)
    res = sc.halt_decision(ov, None)
    assert res.outcome == sc.SPECIFICITY_HALT
    assert res.halt is True
    assert res.underpowered is False
    assert res.confidence_cap is None
    assert any("overlap not significant" in r for r in res.reasons)


def test_underpowered_run_still_halts_on_network_proximity():
    """Only the overlap-p HALT is suspended; proximity and the decoy still bite."""
    ov = _overlap(n_A=1, n_B=2000, universe=20000, observed=1, hg_p=0.1, perm_p=0.11)
    prox = sc.ProximityResult(d_c=2.0, z_c=0.3, mean_rand=2.0, std_rand=0.5,
                              n_targets_in_graph=1, n_disease_in_graph=200, n_rand=1000)
    res = sc.halt_decision(ov, prox)
    assert res.halt is True
    assert res.outcome == sc.SPECIFICITY_HALT
    assert res.underpowered is True, "the power finding must survive a proximity HALT"
    assert any("network proximity not significant" in r for r in res.reasons)
    # NEGATIVE CONTROL: a proximity that passes leaves the underpowered outcome standing
    ok = sc.halt_decision(ov, sc.ProximityResult(2.0, -3.0, 3.0, 0.3, 1, 200, 1000))
    assert ok.halt is False and ok.outcome == sc.SPECIFICITY_UNDERPOWERED


def test_underpowered_via_count_only():
    """A caller that passes only the engaged-target count still gets the outcome."""
    ov = _overlap(n_A=1, n_B=2000, universe=20000, observed=1, hg_p=0.001, perm_p=0.001)
    res = sc.halt_decision(ov, None, n_engaged_targets=2, underpowered_rule="count")
    assert res.outcome == sc.SPECIFICITY_UNDERPOWERED
    assert res.power.rule == sc.RULE_ENGAGED_TARGET_COUNT
    assert res.halt is False
    # NEGATIVE CONTROL: above the floor, the same call is a plain PROCEED
    assert sc.halt_decision(ov, None, n_engaged_targets=9,
                            underpowered_rule="count").outcome == sc.SPECIFICITY_PROCEED


# =============================================================================== 3. decoy


def _decoy_pair():
    passing = sc.decoy_delta({"T1", "T2", "T3"}, {"T1", "T2"}, {"T3"})
    failing = sc.decoy_delta({"T1", "T2", "T3"}, {"T3"}, {"T1", "T2"})
    return passing, failing


def test_failed_decoy_is_returned_as_its_own_outcome():
    """The observed defect: the decoy failed and halt_decision registered nothing.

    CLAUDE.md §3 (Step 3, decoy failure) makes it an independent gate whose default is
    to stop, so the overlap p and z_c both passing here must not carry the run.
    """
    ov, prox = _significant_overlap(), _close_proximity()
    passing, failing = _decoy_pair()
    assert failing.passes is False

    res = sc.halt_decision(ov, prox, decoy=failing)
    assert res.decoy_outcome == sc.DECOY_FAILED
    assert res.decoy is failing
    assert any("DECOY_FAILED" in r for r in res.reasons), \
        "the decoy verdict must also land in `reasons`, which is what run records print"
    # it must be impossible to read the result as a decoy pass
    assert res.decoy_passed is False
    assert sc.DECOY_PASSED not in res.decoy_outcome
    assert res.as_dict()["decoy_outcome"] == sc.DECOY_FAILED
    # independent gate: the thresholds passed, the decoy did not, so the run stops
    assert res.halt is True
    assert res.outcome == sc.SPECIFICITY_HALT


def test_failed_decoy_report_only_needs_an_explicit_pre_registration():
    """A run that pre-registered the decoy as a reported control says so explicitly.

    The verdict is still returned and still written into `reasons`, so opting out of
    the stop cannot turn a failed decoy into an invisible one.
    """
    ov, prox = _significant_overlap(), _close_proximity()
    _, failing = _decoy_pair()
    res = sc.halt_decision(ov, prox, decoy=failing, halt_on_decoy_failure=False)
    assert res.halt is False
    assert res.outcome == sc.SPECIFICITY_PROCEED
    assert res.decoy_outcome == sc.DECOY_FAILED
    assert res.decoy_passed is False
    assert any("DECOY_FAILED" in r for r in res.reasons)


def test_passing_decoy_is_distinguishable_from_a_failed_one():
    """NEGATIVE CONTROL for the test above."""
    ov, prox = _significant_overlap(), _close_proximity()
    passing, _ = _decoy_pair()
    assert passing.passes is True
    res = sc.halt_decision(ov, prox, decoy=passing)
    assert res.decoy_outcome == sc.DECOY_PASSED
    assert res.decoy_passed is True
    assert not any("DECOY_FAILED" in r for r in res.reasons)
    assert any("DECOY_PASSED" in r for r in res.reasons)


def test_decoy_not_run_is_not_a_pass():
    ov, prox = _significant_overlap(), _close_proximity()
    res = sc.halt_decision(ov, prox)
    assert res.decoy_outcome == sc.DECOY_NOT_RUN
    assert res.decoy_passed is False, "a decoy that never ran must never read as a pass"
    assert res.decoy is None


def test_require_decoy_makes_omission_an_error():
    ov, prox = _significant_overlap(), _close_proximity()
    with pytest.raises(ValueError, match="decoy"):
        sc.halt_decision(ov, prox, require_decoy=True)
    # NEGATIVE CONTROL: supplying one satisfies it
    passing, _ = _decoy_pair()
    assert sc.halt_decision(ov, prox, decoy=passing,
                            require_decoy=True).decoy_outcome == sc.DECOY_PASSED


def test_decoy_gate_is_independent_of_the_numeric_thresholds():
    """"Passing one does not excuse failing the other" — in both directions."""
    passing, failing = _decoy_pair()
    ov, prox = _significant_overlap(), _close_proximity()
    # thresholds pass, decoy fails -> stop
    assert sc.halt_decision(ov, prox, decoy=failing).halt is True
    # NEGATIVE CONTROL: thresholds pass, decoy passes -> proceed
    assert sc.halt_decision(ov, prox, decoy=passing).halt is False
    # decoy passes but z_c fails -> still a stop, and the decoy pass is still reported
    weak = sc.halt_decision(ov, sc.ProximityResult(2.0, 0.4, 2.0, 0.4, 2, 3, 10),
                            decoy=passing)
    assert weak.halt is True and weak.decoy_outcome == sc.DECOY_PASSED
    assert any("network proximity not significant" in r for r in weak.reasons)


def test_decoy_tie_fails_both_legs():
    """A signal as strong for an unrelated disease is not selectivity, on either leg."""
    tie = sc.decoy_delta({"T1", "T2"}, {"T1"}, {"T2"})       # 1 vs 1
    assert tie.passes is False
    assert any("overlap not selective" in r for r in tie.reasons)
    # NEGATIVE CONTROL: strictly better overlap passes
    assert sc.decoy_delta({"T1", "T2"}, {"T1", "T2"}, {"T2"}).passes is True


def test_decoy_proximity_tie_fails(monkeypatch):
    """The proximity leg used to let an exact tie (`delta > 0`) pass; now `>= 0` fails."""
    graph = _chain_graph(20)
    same = sc.ProximityResult(1.0, -2.5, 2.0, 0.4, 2, 3, 10)
    monkeypatch.setattr(sc, "network_proximity", lambda *a, **k: same)
    res = sc.decoy_delta({"g1", "g2"}, {"g1", "g2"}, {"g2"}, graph=graph, n_rand=10)
    assert res.zc_delta == 0.0
    assert res.passes is False
    assert any("proximity not selective" in r for r in res.reasons)

    # NEGATIVE CONTROL: a real z_c margin passes the same leg
    seq = iter([sc.ProximityResult(1.0, -3.5, 2.0, 0.4, 2, 3, 10), same])
    monkeypatch.setattr(sc, "network_proximity", lambda *a, **k: next(seq))
    ok = sc.decoy_delta({"g1", "g2"}, {"g1", "g2"}, {"g2"}, graph=graph, n_rand=10)
    assert ok.zc_delta == -1.0 and ok.passes is True


# =============================================================================== 4. equalities


def test_check_equal_rejects_the_94_for_92_case():
    """The defect verbatim: 94 edges reported for a 92-edge graph must not pass."""
    with pytest.raises(sc.ConsistencyError):
        sc._check_equal("edges", 94, 92)
    with pytest.raises(sc.ConsistencyError):
        sc._check_equal("edges", 91, 92)          # under-count must fail too
    sc._check_equal("edges", 92, 92)              # the only passing case


def test_check_equal_survives_python_O():
    """A bare `assert` vanishes under -O; this gate must not."""
    code = ("import sys; sys.path.insert(0, r'%s');"
            "from moa_lib import specificity_controls as sc;"
            "\ntry:\n sc._check_equal('edges', 94, 92)\n print('NOT_RAISED')\n"
            "except AssertionError as e:\n print('RAISED')" % str(Path(sc.__file__).parents[1].parent))
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True,
                         text=True, timeout=600)
    assert "RAISED" in out.stdout, out.stdout + out.stderr
    assert "NOT_RAISED" not in out.stdout


def test_overlap_significance_rejects_an_impossible_universe():
    """A background smaller than a set drawn from it was silently clamped before."""
    A = {f"g{i}" for i in range(300)}
    B = {f"g{i}" for i in range(250, 900)}
    with pytest.raises(ValueError, match="universe"):
        sc.overlap_significance(A, B, universe=100, n_perm=10)
    # NEGATIVE CONTROL: a consistent universe is accepted
    assert sc.overlap_significance(A, B, universe=20000, n_perm=10).universe == 20000


def test_degree_bins_partition_every_node_exactly_once():
    for n in (8, 50, 137):
        graph = _chain_graph(n)
        bins = sc._degree_bins(graph)
        assert len(bins["binof"]) == len(graph)
        assert sum(len(m) for m in bins["members"].values()) == len(graph)
        assert sorted(x for m in bins["members"].values() for x in m) == sorted(graph)
    # NEGATIVE CONTROL: the partition check is a real equality, not a formality
    with pytest.raises(sc.ConsistencyError):
        sc._check_equal("nodes assigned to a degree bin", len(_chain_graph(50)) + 1, 50)


def test_reported_counts_equal_the_work_actually_done():
    graph = _chain_graph(40)
    res = sc.network_proximity(["g1", "g1", "NOT_A_NODE", "g7"], ["g30"], graph, n_rand=25)
    assert res.n_targets_in_graph == 2, "duplicates and non-nodes must not be counted"
    assert res.n_disease_in_graph == 1
    assert res.n_rand == 25
    ov = sc.overlap_significance({"a", "b"}, {"b", "c"}, universe=1000, n_perm=37)
    assert ov.n_perm == 37 and ov.observed == 1 and (ov.n_A, ov.n_B) == (2, 2)


def test_halt_flag_equals_the_presence_of_a_halt_reason():
    """`halt` is recomputed from the halting reasons, not tracked beside them."""
    for res in (sc.halt_decision(_significant_overlap(), _close_proximity()),
                sc.halt_decision(_significant_overlap(),
                                 sc.ProximityResult(2.0, 0.5, 2.0, 0.4, 2, 3, 10))):
        halting = [r for r in res.reasons
                   if "not significant" in r or r.startswith(sc.DECOY_FAILED)]
        assert res.halt == bool(halting)


# =============================================================================== regression guard

# Captured from the module as it stood BEFORE the hardening, under PYTHONHASHSEED 0, 1,
# 2 and 12345 (all four agreed). These are the values any existing caller gets today.
MAIN_OVERLAP = {"observed": 50, "expected": 9.75, "enrichment": 5.13,
                "hypergeom_p": 1.0219856787491517e-21, "perm_p": 0.001996007984031936,
                "n_A": 300, "n_B": 650, "universe": 20000, "n_perm": 500}
MAIN_PROXIMITY = {"d_c": 38.5, "z_c": -0.014, "mean_rand": 38.505, "std_rand": 0.35,
                  "n_targets_in_graph": 2, "n_disease_in_graph": 2, "n_rand": 100,
                  "unreachable_penalty": None}
MAIN_HALT = (True, ["network proximity not significant: z_c=-0.014 > -0.15"])


def _main_example():
    A = {f"g{i}" for i in range(300)}
    B = {f"g{i}" for i in range(250, 900)}
    ov = sc.overlap_significance(A, B, universe=20000, n_perm=500)
    g = {f"g{i}": set() for i in range(50)}
    for i in range(49):
        g[f"g{i}"].add(f"g{i+1}")
        g[f"g{i+1}"].add(f"g{i}")
    pr = sc.network_proximity({"g1", "g2"}, {"g40", "g45"}, g, n_rand=100)
    return ov, pr


def test_main_examples_are_bit_for_bit_unchanged():
    """REGRESSION GUARD: the module's own examples were never underpowered, so every
    number an existing caller reads must be exactly what it was before the change."""
    ov, pr = _main_example()
    assert asdict(ov) == MAIN_OVERLAP
    assert asdict(pr) == MAIN_PROXIMITY
    res = sc.halt_decision(ov, pr)
    assert res == MAIN_HALT, "the (halt, reasons) tuple must compare equal to the old one"
    assert tuple(res) == MAIN_HALT
    assert res.outcome == sc.SPECIFICITY_HALT
    assert res.underpowered is False, "this example is powered; nothing may be capped"


def test_regression_guard_is_sensitive():
    """NEGATIVE CONTROL: the frozen values are not matched by accident."""
    A = {f"g{i}" for i in range(300)}
    B = {f"g{i}" for i in range(250, 900)}
    assert asdict(sc.overlap_significance(A, B, universe=20000, n_perm=501)) != MAIN_OVERLAP
    assert asdict(sc.overlap_significance(A, B, universe=19999, n_perm=500)) != MAIN_OVERLAP
    g = {f"g{i}": set() for i in range(50)}
    for i in range(49):
        g[f"g{i}"].add(f"g{i+1}")
        g[f"g{i+1}"].add(f"g{i}")
    assert asdict(sc.network_proximity({"g1", "g2"}, {"g40", "g45"}, g, n_rand=101)) != MAIN_PROXIMITY
    assert asdict(sc.network_proximity({"g1", "g3"}, {"g40", "g45"}, g, n_rand=100)) != MAIN_PROXIMITY


def test_dataclass_fields_unchanged_so_stored_json_still_reconciles():
    """Existing runs `asdict()` these and audit the JSON; no field may move or vanish."""
    assert [f.name for f in fields(sc.OverlapResult)] == list(MAIN_OVERLAP)
    assert [f.name for f in fields(sc.ProximityResult)] == list(MAIN_PROXIMITY)
    assert [f.name for f in fields(sc.DecoyResult)] == [
        "real_overlap", "decoy_overlap", "overlap_delta", "real_zc", "decoy_zc",
        "zc_delta", "passes", "reasons"]


def test_existing_caller_call_shapes_still_work():
    """The exact call shapes in results/obesity/scripts/step3_hubs.py."""
    ov, pr = _main_example()
    graph = _chain_graph(50)
    dd = sc.decoy_delta({"g1", "g2"}, {"g40", "g45"}, {"g10", "g11"},
                        graph=graph, n_rand=20)
    assert set(asdict(dd)) == {"real_overlap", "decoy_overlap", "overlap_delta", "real_zc",
                               "decoy_zc", "zc_delta", "passes", "reasons"}
    halt, reasons = sc.halt_decision(ov, pr, alpha=0.05, zc_cut=-0.15)   # positional kwargs
    assert isinstance(halt, bool) and isinstance(reasons, list)
    res = sc.halt_decision(ov, pr, 0.05, -0.15)                          # fully positional
    assert res[0] is True and isinstance(res[1], list) and len(res) == 2
    assert json.loads(json.dumps({"halt": res[0], "reasons": res[1]}))["halt"] is True


# =============================================================================== helpers


def _chain_graph(n: int) -> dict:
    g = {f"g{i}": set() for i in range(n)}
    for i in range(n - 1):
        g[f"g{i}"].add(f"g{i+1}")
        g[f"g{i+1}"].add(f"g{i}")
    return g


def _overlap(*, n_A, n_B, universe, observed, hg_p, perm_p, n_perm=1000):
    return sc.OverlapResult(observed=observed, expected=round(n_A * n_B / universe, 2),
                            enrichment=1.0, hypergeom_p=hg_p, perm_p=perm_p,
                            n_A=n_A, n_B=n_B, universe=universe, n_perm=n_perm)


def _significant_overlap():
    return _overlap(n_A=74, n_B=410, universe=19276, observed=9, hg_p=1e-8, perm_p=1e-4)


def _close_proximity():
    return sc.ProximityResult(d_c=1.3, z_c=-5.5, mean_rand=1.7, std_rand=0.07,
                              n_targets_in_graph=74, n_disease_in_graph=400, n_rand=1000)


def _proximity_in_given_order(targets, disease, graph, n_rand=50, seed=1234):
    """d_c/z_c with the null drawn in the caller's target order (the old behaviour)."""
    import random
    dist = sc._multi_source_bfs(graph, set(disease) & set(graph))
    tset = [t for t in targets if t in graph]

    def dc(nodes):
        vals = [dist.get(n, 10.0) for n in nodes]
        return sum(vals) / len(vals) if vals else 10.0

    bins = sc._degree_bins(graph)
    rng = random.Random(seed)
    null = [dc([rng.choice(bins["members"][bins["binof"][t]]) for t in tset])
            for _ in range(n_rand)]
    mean = sum(null) / len(null)
    std = (sum((x - mean) ** 2 for x in null) / len(null)) ** 0.5
    return round((dc(tset) - mean) / std, 3) if std > 0 else 0.0
