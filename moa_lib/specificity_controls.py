"""Step-3 guardrail (P2) — overlap significance + network proximity + decoy.

Fixes session8 failure mode F3: a raw set intersection (|A n B| = 81) was reported
as meaningful WITHOUT any test that it beats random. CLAUDE.md §3 makes three
controls mandatory before any overlap may be called evidence:

  (1) overlap significance  — hypergeometric p AND a permutation p for |A n B|
                              vs random gene sets of equal size.
  (2) network proximity     — Guney-Barabasi closest measure d_c of the drug
                              targets to the disease module, with a z-score z_c
                              against degree-preserving randomisation.
  (3) decoy-disease control — the real overlap/proximity must beat that of an
                              unrelated (decoy) disease's gene set.

HALT rule (CLAUDE.md Step 3): stop the pipeline if overlap_p > 0.05 OR z_c > -0.15,
EXCEPT when the overlap test is underpowered by construction (see below).

    overlap_significance(A, B, universe, n_perm)          -> OverlapResult
    minimum_achievable_p(n_A, n_B, universe, n_perm)       -> float
    overlap_power(overlap, alpha=...)                      -> PowerResult
    network_proximity(targets, disease_genes, graph, ...) -> ProximityResult
    decoy_delta(targets, real_genes, decoy_genes, graph)  -> DecoyResult
    halt_decision(overlap, proximity, decoy=...)          -> HaltDecision
                                                             (unpacks as (halt, reasons))
    canonical_graph(graph)                                 -> dict (sorted node order)

-------------------------------------------------------------------------------
Three properties this module now guarantees, each from a defect seen in a real run
-------------------------------------------------------------------------------

1. DETERMINISM, independent of PYTHONHASHSEED.
   `network_proximity` used to iterate `set(targets)`, so the order in which the
   degree-matched null draws were taken followed Python's randomised string hash:
   the same `seed=1234` returned z_c = -5.72 on one run and -5.44 on the next, and
   the only workaround was to pin PYTHONHASHSEED externally. Every collection this
   module iterates is now canonically ordered (sorted) before use, so a given input
   gives one answer in any process.

   INPUT CONTRACT for `graph`: `graph` is an *ordered* mapping. Degree bins are cut
   from a stable degree sort, so which bin an equal-degree node lands in follows the
   graph's own key order. A dict's key order is never affected by PYTHONHASHSEED, so
   a graph built deterministically (e.g. `{k: set(adj[k]) for k in sorted(adj)}`,
   which is what `results/obesity` does) yields a reproducible answer. A graph
   assembled by iterating an unordered container does not: pass such a graph through
   `canonical_graph()` first. The node order is not re-sorted inside this function
   because that would silently change the degree bins — and therefore the published
   z_c — of every run made before this change.

2. SPECIFICITY_UNDERPOWERED (kernel design §8.1 R1, §8.4).
   A compound with one or two well-measured targets (atorvastatin -> HMGCR,
   latanoprost -> PTGFR) can be arithmetically incapable of reaching p < 0.05 on the
   overlap test; HALTing it reports a fact about test power as if it were a fact
   about biology. `halt_decision` therefore computes the SMALLEST p the overlap test
   could possibly return for the given |A|, |B| and universe (`minimum_achievable_p`
   — the best case, where every target is a disease gene) and, if even that exceeds
   alpha, returns outcome `SPECIFICITY_UNDERPOWERED`: the run CONTINUES, headline
   confidence is capped at "promising-but-unproven", and the caller MUST state the
   cap. Network proximity and the decoy control still run, are still reported, and
   the proximity HALT still applies — only the overlap-p HALT is suspended.
   §8.1's fixed rule ("<= 3 targets with measured or direct engagement") is kept as
   a documented fallback for callers that cannot supply |A|, |B| and the universe:
   pass `n_engaged_targets=`. Which rule decides is recorded in `PowerResult.rule`.

3. THE DECOY VERDICT IS RETURNED, NOT INFERRED.
   In the run that motivated this module's hardening the decoy control failed — an
   unrelated disease overlapped the drug's targets more than the real disease did —
   and nothing in `halt_decision` registered it, because CLAUDE.md names only
   `overlap_p` and `z_c` as HALT criteria. A human reading the output was the only
   thing that caught it. `halt_decision` now returns `decoy_outcome` as a distinct
   field of its result (`DECOY_PASSED` / `DECOY_FAILED` / `DECOY_NOT_RUN`) and, when
   a decoy result is supplied, writes that verdict into `reasons` as well, so it
   lands in any run record built from `reasons`.

   POLICY: CLAUDE.md §3 (Step 3, decoy failure) makes a failed decoy a stop in its
   own right — "the numeric thresholds and the decoy are independent gates; passing
   one does not excuse failing the other" — and says the run's PRE-REGISTRATION
   states in advance how a decoy failure is handled, with the default being to stop.
   `halt_decision` implements exactly that: supplying a failed `decoy=` stops the run
   (`halt_on_decoy_failure=True` is the default), and a run whose pre-registration
   says the decoy is a reported control passes `halt_on_decoy_failure=False`, which
   is then an explicit, auditable statement of that pre-registration rather than a
   silent omission. The verdict is reported either way, so a report-only run still
   cannot overlook it. `require_decoy=True` additionally makes forgetting the control
   an error. Changing the stop/continue rule of an ALREADY pre-registered run after
   its results are known would break pre-registration integrity, which is why the
   opt-out exists at all; it is not a way to make a failed decoy go away.

   The flipped default cannot alter any existing result: `decoy=` is a new parameter
   and no existing caller passes one, so every historical call is DECOY_NOT_RUN.

Internal consistency checks are EQUALITIES, never inequalities: a checker in the
same run published an arithmetically impossible edge count (94 for a 92-edge graph)
and passed, because its check was `a > b` instead of `a == b`. Every number this
module reports about its own work (permutations performed, null replicates drawn,
targets averaged into d_c, nodes assigned to degree bins, BFS seeds) is verified
`==` to the quantity it claims, with `_check_equal`, which raises a real exception
rather than a bare `assert` (bare asserts vanish under `python -O`).
"""
from __future__ import annotations

import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from scipy.stats import hypergeom

# ----------------------------------------------------------------------------- outcomes

#: `HaltDecision.outcome` — the specificity gate's verdict on the run.
SPECIFICITY_PROCEED = "SPECIFICITY_PROCEED"
SPECIFICITY_HALT = "SPECIFICITY_HALT"
SPECIFICITY_UNDERPOWERED = "SPECIFICITY_UNDERPOWERED"

#: `HaltDecision.decoy_outcome` — the decoy control's verdict, always set.
DECOY_PASSED = "DECOY_PASSED"
DECOY_FAILED = "DECOY_FAILED"
DECOY_NOT_RUN = "DECOY_NOT_RUN"

#: `PowerResult.rule` — which power rule decided `underpowered`.
RULE_COMPUTED_MIN_P = "computed_min_p"
RULE_ENGAGED_TARGET_COUNT = "engaged_target_count"
RULE_NOT_ASSESSABLE = "not_assessable"

#: Confidence cap a caller MUST state when the overlap test could not be powered.
UNDERPOWERED_CONFIDENCE_CAP = "promising-but-unproven"


class ConsistencyError(AssertionError):
    """An internal number did not equal the quantity it claims to describe."""


def _check_equal(label: str, got, want) -> None:
    """Assert an EQUALITY (not an inequality) between a reported number and its source.

    Used for every self-describing count this module emits. A bare `assert` is not
    used: `python -O` strips asserts, and a gate that can be switched off is not a
    gate (CLAUDE.md §5, "build essentials in as the single default").
    """
    if got != want:
        raise ConsistencyError(f"{label}: reported {got!r} != actual {want!r}")


def canonical_graph(graph: dict) -> dict:
    """Return the same adjacency with a canonical (sorted) node order.

    Apply this when an interactome dict was assembled by iterating an unordered
    container; see the INPUT CONTRACT in the module docstring. It is a no-op for a
    graph whose keys were already inserted in sorted order.
    """
    return {n: set(graph[n]) for n in sorted(graph)}


# ----------------------------------------------------------------------------- overlap


@dataclass
class OverlapResult:
    observed: int
    expected: float
    enrichment: float          # observed / expected
    hypergeom_p: float
    perm_p: float
    n_A: int
    n_B: int
    universe: int
    n_perm: int


def overlap_significance(A: Iterable[str], B: Iterable[str], universe: int,
                         n_perm: int = 1000, seed: int = 1234) -> OverlapResult:
    """Test whether |A n B| exceeds what equal-sized random sets would overlap.

    `universe` = size of the sampling background (e.g. ~20000 protein-coding
    genes, or the union of all databases queried). Both an analytic hypergeometric
    p and an empirical permutation p are returned; report both (CLAUDE.md §3).

    Raises ValueError if `universe` is smaller than either input set: a background
    smaller than a set drawn from it is a data-lineage error, and the previous
    silent `universe = max(universe, |A|, |B|)` clamp hid it while still returning a
    number (CLAUDE.md §3, mechanism 5).
    """
    A, B = set(A), set(B)                       # membership/size only; order never used
    a, b = len(A), len(B)
    observed = len(A & B)
    _check_equal("observed overlap", observed, len(A & B))
    if universe < max(a, b):
        raise ValueError(
            f"universe ({universe}) is smaller than the largest input set "
            f"(|A|={a}, |B|={b}): the background cannot be smaller than a set drawn "
            f"from it. Fix the gene universe rather than clamping it."
        )
    universe = max(universe, 1)

    # analytic: P(X >= observed) for X ~ Hypergeom(M=universe, n=a, N=b)
    hg_p = float(hypergeom.sf(observed - 1, universe, a, b))
    expected = a * b / universe
    enrichment = observed / expected if expected > 0 else float("inf")

    # empirical permutation: resample a random 'A' of size a from the universe,
    # count overlap with the real B. B is held fixed as universe indices 0..b-1.
    rng = random.Random(seed)
    pool = list(range(universe))                # deterministic: range, not a set
    b_idx = set(range(b))                       # fixed reference set of size b
    _check_equal("permutation reference set size", len(b_idx), b)
    ge, done = 0, 0
    for _ in range(max(0, n_perm)):
        sample = rng.sample(pool, a)
        done += 1
        if len(b_idx.intersection(sample)) >= observed:
            ge += 1
    _check_equal("permutations performed", done, max(0, n_perm))
    perm_p = (ge + 1) / (done + 1)              # add-one (never reports p=0)

    return OverlapResult(observed, round(expected, 2), round(enrichment, 2),
                         hg_p, perm_p, a, b, universe, n_perm)


# ----------------------------------------------------------------------------- power


@dataclass
class PowerResult:
    """Can the overlap test reach `alpha` at all, for sets of these sizes?"""
    underpowered: bool
    rule: str                                   # RULE_* constant that decided it
    alpha: float
    min_achievable_p: Optional[float] = None    # smallest p the test could return
    max_achievable_overlap: Optional[int] = None
    n_A: Optional[int] = None
    n_B: Optional[int] = None
    universe: Optional[int] = None
    n_perm: Optional[int] = None
    perm_floor: Optional[float] = None          # 1/(n_perm+1), the permutation p floor
    computed_underpowered: Optional[bool] = None
    n_engaged_targets: Optional[int] = None
    engaged_target_floor: int = 3
    count_underpowered: Optional[bool] = None
    detail: str = ""


def minimum_achievable_p(n_A: int, n_B: int, universe: int,
                         n_perm: Optional[int] = None) -> float:
    """Smallest p the overlap test could possibly return for these set sizes.

    The best case is `observed = min(|A|, |B|)` — every target is a disease gene —
    so the floor on the hypergeometric p is `P(X >= min(|A|,|B|))`, which for
    |A| <= |B| is prod_i (|B|-i)/(universe-i) over i < |A|. `halt_decision` compares
    the WORSE of the analytic and permutation p against alpha, and the permutation p
    can never fall below `1/(n_perm+1)`, so when `n_perm` is given the floor is the
    larger of the two. The value returned is therefore a true lower bound on the p
    the gate will see: if it already exceeds alpha, no data can make the test
    significant and the test is underpowered by construction.
    """
    n_A, n_B = int(n_A), int(n_B)
    k_max = min(n_A, n_B)
    if k_max <= 0 or universe <= 0:
        return 1.0
    hg_floor = float(hypergeom.sf(k_max - 1, max(universe, n_A, n_B), n_A, n_B))
    perm_floor = 1.0 / (int(n_perm) + 1) if n_perm else 0.0
    return max(hg_floor, perm_floor)


def overlap_power(overlap: Optional[OverlapResult] = None, *,
                  alpha: float = 0.05,
                  n_A: Optional[int] = None, n_B: Optional[int] = None,
                  universe: Optional[int] = None, n_perm: Optional[int] = None,
                  n_engaged_targets: Optional[int] = None,
                  engaged_target_floor: int = 3,
                  rule: str = "computed") -> PowerResult:
    """Decide whether the overlap test could reach `alpha` at all.

    Primary rule (`rule="computed"`, the default and the better test — kernel design
    §8.4): the test is underpowered iff `minimum_achievable_p(...) > alpha`.
    Fallback rule (`rule="count"`, design §8.1 R1 as literally written): underpowered
    iff `n_engaged_targets <= engaged_target_floor`. The fallback is for callers that
    know only how many targets carry measured/direct/label engagement and cannot
    supply |A|, |B| and the universe; it is used automatically when the sizes are
    unavailable. `rule="either"` flags underpowered if either rule does.

    Sizes come from `overlap` when given, else from the `n_A`/`n_B`/`universe`
    keywords.
    """
    if rule not in ("computed", "count", "either"):
        raise ValueError(f"rule must be 'computed', 'count' or 'either', got {rule!r}")
    if overlap is not None:
        n_A = overlap.n_A if n_A is None else n_A
        n_B = overlap.n_B if n_B is None else n_B
        universe = overlap.universe if universe is None else universe
        n_perm = overlap.n_perm if n_perm is None else n_perm

    sizes_ok = (n_A is not None and n_B is not None and universe is not None
                and n_A >= 1 and n_B >= 1 and universe >= 1)
    computed = min_p = max_ov = perm_floor = None
    if sizes_ok:
        min_p = minimum_achievable_p(n_A, n_B, universe, n_perm)
        max_ov = min(n_A, n_B)
        perm_floor = 1.0 / (int(n_perm) + 1) if n_perm else 0.0
        computed = bool(min_p > alpha)

    count = None
    if n_engaged_targets is not None:
        count = bool(int(n_engaged_targets) <= int(engaged_target_floor))

    if rule == "either" and (sizes_ok or count is not None):
        verdict = bool(computed) or bool(count)
        if computed:                        # name the rule that actually fired
            used = RULE_COMPUTED_MIN_P
        elif count:
            used = RULE_ENGAGED_TARGET_COUNT
        else:
            used = RULE_COMPUTED_MIN_P if sizes_ok else RULE_ENGAGED_TARGET_COUNT
    elif rule == "count" and count is not None:
        verdict, used = count, RULE_ENGAGED_TARGET_COUNT
    elif sizes_ok:
        verdict, used = computed, RULE_COMPUTED_MIN_P
    elif count is not None:
        verdict, used = count, RULE_ENGAGED_TARGET_COUNT
    else:
        verdict, used = False, RULE_NOT_ASSESSABLE

    if used == RULE_COMPUTED_MIN_P:
        detail = (f"best-case overlap {max_ov} of |A|={n_A} vs |B|={n_B} in a universe of "
                  f"{universe} gives a minimum achievable p of {min_p:.3g} "
                  f"({'>' if verdict else '<='} alpha={alpha})")
    elif used == RULE_ENGAGED_TARGET_COUNT:
        detail = (f"{n_engaged_targets} target(s) with measured/direct/label engagement "
                  f"{'<=' if verdict else '>'} floor of {engaged_target_floor} "
                  f"(set sizes unavailable, so the fixed-count fallback decided)")
    else:
        detail = "power not assessable: no set sizes and no engaged-target count supplied"

    return PowerResult(underpowered=verdict, rule=used, alpha=alpha,
                       min_achievable_p=min_p, max_achievable_overlap=max_ov,
                       n_A=n_A, n_B=n_B, universe=universe, n_perm=n_perm,
                       perm_floor=perm_floor, computed_underpowered=computed,
                       n_engaged_targets=n_engaged_targets,
                       engaged_target_floor=engaged_target_floor,
                       count_underpowered=count, detail=detail)


# ----------------------------------------------------------------------------- proximity


@dataclass
class ProximityResult:
    d_c: float                 # mean closest distance, targets -> disease module
    z_c: float                 # (d_c - mean_rand) / std_rand
    mean_rand: float
    std_rand: float
    n_targets_in_graph: int
    n_disease_in_graph: int
    n_rand: int
    unreachable_penalty: Optional[float] = None


def _multi_source_bfs(graph: dict, sources: Iterable[str]) -> dict:
    """Distance from the NEAREST source to every reachable node (unweighted).

    Seeds and neighbour expansion are visited in sorted order so the traversal — and
    hence this dict's insertion order — is identical in every process. The distance
    VALUES are order-invariant either way (all seeds enter the queue at depth 0).
    """
    seeds = sorted({s for s in sources if s in graph})
    dist = {s: 0 for s in seeds}
    dq = deque(seeds)
    while dq:
        u = dq.popleft()
        for v in sorted(graph[u]):
            if v not in dist:
                dist[v] = dist[u] + 1
                dq.append(v)
    return dist


def _degree_bins(graph: dict, n_bins: int = 20) -> dict:
    """Map each node to a degree-bin key so randomisation is degree-preserving.

    `graph` is iterated in its own key order (a dict's order is deterministic and is
    never affected by PYTHONHASHSEED); the degree sort is stable, so equal-degree
    nodes are cut into bins in that order. See the INPUT CONTRACT in the module
    docstring: canonicalise the graph (`canonical_graph`) if it was built from an
    unordered container. Each bin's member list is returned in sorted order, so the
    pool a null draw indexes into is canonical.
    """
    degs = {n: len(graph[n]) for n in graph}
    if not degs:
        return {}
    order = sorted(degs, key=lambda n: degs[n])      # stable: ties keep graph key order
    per = max(1, len(order) // n_bins)
    binof, members = {}, defaultdict(list)
    for i, n in enumerate(order):
        b = i // per
        binof[n] = b
        members[b].append(n)
    members = {b: sorted(ns) for b, ns in members.items()}
    _check_equal("nodes assigned to a degree bin", len(binof), len(graph))
    _check_equal("nodes across degree-bin members",
                 sum(len(ns) for ns in members.values()), len(graph))
    return {"binof": binof, "members": members}


def network_proximity(targets: Iterable[str], disease_genes: Iterable[str],
                      graph: dict, n_rand: int = 1000, seed: int = 1234,
                      unreachable: float = 10.0,
                      exclude_from_null: Iterable[str] = ()) -> ProximityResult:
    """Guney-Barabasi closest measure d_c + degree-preserving z_c.

    `graph` is an adjacency dict {node: set(neighbours)} built from an interactome
    (e.g. STRING combined_score >= 700). d_c = mean over drug targets of the
    shortest-path distance to the nearest disease gene. The null model draws
    random target sets matched by degree bin. Targets/disease genes absent from
    the graph are dropped from d_c; if a target cannot reach the disease module,
    `unreachable` hops are charged so a disconnected drug is not rewarded.

    `exclude_from_null`: nodes removed from the random sampling pool — normally the
    disease-module genes themselves, so a random draw cannot land ON a disease gene
    (distance 0) and spuriously depress the null mean. A real target that IS a
    disease gene still legitimately contributes distance 0 to the observed d_c.

    DETERMINISM: the target list, the disease list, the sampling pools and the BFS
    traversal are all canonically ordered, so a given (targets, disease_genes, graph,
    seed) returns one answer regardless of PYTHONHASHSEED. The earlier version
    iterated `set(targets)`, which made the null draw order hash-dependent and the
    same seed return z_c = -5.72 and -5.44 on successive runs. See the INPUT
    CONTRACT in the module docstring for the one remaining ordering input (`graph`).
    """
    disease = sorted(set(disease_genes) & set(graph))
    dist = _multi_source_bfs(graph, disease)
    _check_equal("BFS seeds", sum(1 for d in dist.values() if d == 0), len(disease))

    def _dc_n(nodes):
        vals = [dist.get(n, unreachable) for n in nodes if n in graph]
        return (sum(vals) / len(vals) if vals else unreachable), len(vals)

    def _dc(nodes):
        return _dc_n(nodes)[0]

    tset = sorted(t for t in set(targets) if t in graph)   # sorted: see DETERMINISM
    d_c, n_used = _dc_n(tset)
    _check_equal("targets averaged into d_c", n_used, len(tset))

    bins = _degree_bins(graph)
    binof, members = bins.get("binof", {}), bins.get("members", {})
    excl = set(exclude_from_null)                          # membership only
    if excl:  # drop excluded (disease-module) nodes from each degree-bin sampling pool
        members = {b: [n for n in ns if n not in excl] for b, ns in members.items()}
    all_nodes = sorted(n for n in graph if n not in excl) or sorted(graph)
    rng = random.Random(seed)
    null = []
    for _ in range(max(0, n_rand)):
        sample = []
        for t in tset:
            pool = members.get(binof.get(t)) or all_nodes
            if not pool: pool = all_nodes
            sample.append(rng.choice(pool))
        _check_equal("null sample size", len(sample), len(tset))
        null.append(_dc(sample))
    _check_equal("null replicates drawn", len(null), max(0, n_rand))

    mean_rand = sum(null) / len(null) if null else 0.0
    var = sum((x - mean_rand) ** 2 for x in null) / len(null) if null else 0.0
    std_rand = var ** 0.5
    z_c = (d_c - mean_rand) / std_rand if std_rand > 0 else 0.0

    return ProximityResult(round(d_c, 3), round(z_c, 3), round(mean_rand, 3),
                           round(std_rand, 3), len(tset), len(disease), n_rand)


# ----------------------------------------------------------------------------- decoy


@dataclass
class DecoyResult:
    real_overlap: int
    decoy_overlap: int
    overlap_delta: int
    real_zc: Optional[float] = None
    decoy_zc: Optional[float] = None
    zc_delta: Optional[float] = None
    passes: bool = True
    reasons: list = field(default_factory=list)


def decoy_delta(targets: Iterable[str], real_genes: Iterable[str],
                decoy_genes: Iterable[str], graph: Optional[dict] = None,
                n_rand: int = 500) -> DecoyResult:
    """Real disease overlap/proximity must beat an unrelated decoy disease.

    A specificity signal that is just as strong for an unrelated disease is an
    artefact of a promiscuous target list, not a real drug-disease link. Both legs
    require the real disease to be STRICTLY better than the decoy: a tie is not
    selectivity, and the two legs are tested the same way (the proximity leg used to
    let an exact tie pass while the overlap leg failed it).
    """
    T = set(targets)
    real_ov = len(T & set(real_genes))
    decoy_ov = len(T & set(decoy_genes))
    res = DecoyResult(real_ov, decoy_ov, real_ov - decoy_ov)
    _check_equal("overlap_delta", res.overlap_delta, res.real_overlap - res.decoy_overlap)

    if graph is not None:
        rp = network_proximity(T, real_genes, graph, n_rand=n_rand)
        dp = network_proximity(T, decoy_genes, graph, n_rand=n_rand)
        res.real_zc, res.decoy_zc = rp.z_c, dp.z_c
        res.zc_delta = round(rp.z_c - dp.z_c, 3)
        _check_equal("zc_delta", res.zc_delta, round(rp.z_c - dp.z_c, 3))

    # Pass only if the real disease is MORE enriched AND (if computed) MORE proximal
    # (z_c strictly below the decoy's) than the decoy.
    if real_ov <= decoy_ov:
        res.passes = False
        res.reasons.append(f"overlap not selective: real {real_ov} <= decoy {decoy_ov}")
    if res.zc_delta is not None and res.zc_delta >= 0:
        res.passes = False
        res.reasons.append(f"proximity not selective: real z_c not below decoy (delta {res.zc_delta})")
    _check_equal("decoy passes flag", res.passes, len(res.reasons) == 0)
    return res


# ----------------------------------------------------------------------------- HALT


class HaltDecision(tuple):
    """The Step-3 gate's verdict.

    Backward compatible: this IS the `(halt, reasons)` 2-tuple every existing caller
    unpacks, compares and indexes. It additionally carries the fields a caller must
    not be able to overlook:

      .outcome        SPECIFICITY_PROCEED | SPECIFICITY_HALT | SPECIFICITY_UNDERPOWERED
      .decoy_outcome  DECOY_PASSED | DECOY_FAILED | DECOY_NOT_RUN   (always set)
      .decoy          the DecoyResult that produced it, or None
      .power          the PowerResult behind .underpowered
      .underpowered   bool — if True the caller MUST state .confidence_cap
      .confidence_cap the cap to state, or None
    """

    # No __slots__: CPython forbids a non-empty __slots__ on a tuple subclass, and
    # the extras live in the instance dict.

    def __new__(cls, halt: bool, reasons: list, *, outcome: str,
                decoy_outcome: str, decoy=None, power=None,
                confidence_cap: Optional[str] = None,
                alpha: float = 0.05, zc_cut: float = -0.15,
                overlap_p: Optional[float] = None, z_c: Optional[float] = None):
        self = super().__new__(cls, (bool(halt), list(reasons)))
        self._extra = {
            "outcome": outcome, "decoy_outcome": decoy_outcome, "decoy": decoy,
            "power": power, "confidence_cap": confidence_cap,
            "alpha": alpha, "zc_cut": zc_cut, "overlap_p": overlap_p, "z_c": z_c,
        }
        return self

    # --- 2-tuple view (unchanged for every existing caller) -------------------
    @property
    def halt(self) -> bool:
        return self[0]

    @property
    def reasons(self) -> list:
        return self[1]

    # --- the fields a caller must consume ------------------------------------
    @property
    def outcome(self) -> str:
        return self._extra["outcome"]

    @property
    def decoy_outcome(self) -> str:
        return self._extra["decoy_outcome"]

    @property
    def decoy(self):
        return self._extra["decoy"]

    @property
    def power(self):
        return self._extra["power"]

    @property
    def underpowered(self) -> bool:
        return self._extra["outcome"] == SPECIFICITY_UNDERPOWERED or bool(
            getattr(self._extra["power"], "underpowered", False))

    @property
    def confidence_cap(self) -> Optional[str]:
        return self._extra["confidence_cap"]

    @property
    def alpha(self) -> float:
        return self._extra["alpha"]

    @property
    def zc_cut(self) -> float:
        return self._extra["zc_cut"]

    @property
    def decoy_passed(self) -> bool:
        """True ONLY for an actually-passed decoy; a decoy that did not run is False."""
        return self._extra["decoy_outcome"] == DECOY_PASSED

    def describe(self) -> str:
        return (f"{self.outcome} / {self.decoy_outcome}"
                + (f" [confidence capped at {self.confidence_cap}]" if self.confidence_cap else "")
                + ": " + "; ".join(self.reasons))

    def as_dict(self) -> dict:
        from dataclasses import asdict, is_dataclass
        d = {"halt": self.halt, "reasons": list(self.reasons), "outcome": self.outcome,
             "decoy_outcome": self.decoy_outcome, "underpowered": self.underpowered,
             "confidence_cap": self.confidence_cap, "alpha": self.alpha, "zc_cut": self.zc_cut,
             "overlap_p": self._extra["overlap_p"], "z_c": self._extra["z_c"]}
        for k in ("power", "decoy"):
            v = self._extra[k]
            d[k] = asdict(v) if is_dataclass(v) else v
        return d


def halt_decision(overlap: OverlapResult,
                  proximity: Optional[ProximityResult],
                  alpha: float = 0.05, zc_cut: float = -0.15,
                  *,
                  decoy: Optional[DecoyResult] = None,
                  n_engaged_targets: Optional[int] = None,
                  engaged_target_floor: int = 3,
                  underpowered_rule: str = "computed",
                  require_decoy: bool = False,
                  halt_on_decoy_failure: bool = True) -> HaltDecision:
    """CLAUDE.md Step 3 HALT: stop if overlap_p > alpha OR z_c > zc_cut.

    Returns a `HaltDecision`, which unpacks exactly as the historical
    `(halt, reasons)` 2-tuple and additionally carries `.outcome`, `.decoy_outcome`,
    `.power`, `.underpowered` and `.confidence_cap`.

    Two departures from the bare rule, both from observed defects (see the module
    docstring):

    * `SPECIFICITY_UNDERPOWERED` — when the overlap test cannot reach `alpha` for
      these set sizes at all, the overlap-p HALT is SUSPENDED and the run continues
      with `.confidence_cap` set; the caller must state the cap. The proximity HALT
      and the decoy control are unaffected. Pass `n_engaged_targets=` to enable the
      fixed-count fallback rule when set sizes are unavailable, or
      `underpowered_rule="count"` / `"either"` to change which rule decides.
    * `decoy=` — the decoy verdict is returned in `.decoy_outcome` and written into
      `reasons`. A failed decoy STOPS the run by default (CLAUDE.md §3, Step 3 decoy
      failure: an independent gate, default stop); a run whose pre-registration makes
      the decoy a reported control passes `halt_on_decoy_failure=False`, and the
      verdict is still reported. Not supplying a decoy at all leaves
      `.decoy_outcome == DECOY_NOT_RUN`, which never reads as a pass;
      `require_decoy=True` makes forgetting it an error.
    """
    if require_decoy and decoy is None:
        raise ValueError(
            "require_decoy=True but no DecoyResult was supplied: the decoy-disease "
            "control is mandatory (CLAUDE.md §3, mechanism 2) and its verdict must be "
            "registered in the Step-3 decision, not computed and forgotten."
        )

    reasons: list = []
    halt_reasons: list = []
    p = max(overlap.hypergeom_p, overlap.perm_p)   # be conservative: worse of the two

    power = overlap_power(overlap, alpha=alpha, n_engaged_targets=n_engaged_targets,
                          engaged_target_floor=engaged_target_floor,
                          rule=underpowered_rule)

    overlap_fails = p > alpha
    if overlap_fails and not power.underpowered:
        halt_reasons.append(f"overlap not significant: p={p:.3g} > {alpha}")
    elif overlap_fails and power.underpowered:
        reasons.append(f"overlap HALT suspended - test underpowered by construction: {power.detail}")
    elif power.underpowered:
        reasons.append(f"overlap p={p:.3g} <= {alpha} but the test is underpowered "
                       f"by construction: {power.detail}")

    if proximity is not None and proximity.z_c > zc_cut:
        halt_reasons.append(f"network proximity not significant: z_c={proximity.z_c} > {zc_cut}")

    # decoy verdict — always determined, never inferred by the caller
    if decoy is None:
        decoy_outcome = DECOY_NOT_RUN
    elif decoy.passes:
        decoy_outcome = DECOY_PASSED
    else:
        decoy_outcome = DECOY_FAILED
    if decoy is not None:
        why = "; ".join(decoy.reasons) if decoy.reasons else (
            f"real overlap {decoy.real_overlap} > decoy {decoy.decoy_overlap}"
            + (f", z_c delta {decoy.zc_delta}" if decoy.zc_delta is not None else ""))
        line = f"{decoy_outcome}: {why}"
        if decoy_outcome == DECOY_FAILED and halt_on_decoy_failure:
            halt_reasons.append(line)
        else:
            reasons.append(line)

    halt = bool(halt_reasons)
    _check_equal("halt flag", halt, len(halt_reasons) > 0)
    reasons = halt_reasons + reasons

    if halt:
        outcome = SPECIFICITY_HALT
    elif power.underpowered:
        outcome = SPECIFICITY_UNDERPOWERED
    else:
        outcome = SPECIFICITY_PROCEED
        reasons.insert(0, f"overlap p={p:.3g} <= {alpha}"
                       + (f" and z_c={proximity.z_c} <= {zc_cut}" if proximity else ""))

    return HaltDecision(
        halt, reasons, outcome=outcome, decoy_outcome=decoy_outcome, decoy=decoy,
        power=power,
        confidence_cap=UNDERPOWERED_CONFIDENCE_CAP if power.underpowered else None,
        alpha=alpha, zc_cut=zc_cut, overlap_p=p,
        z_c=None if proximity is None else proximity.z_c)


if __name__ == "__main__":
    A = {f"g{i}" for i in range(300)}
    B = {f"g{i}" for i in range(250, 900)}       # 50 shared
    ov = overlap_significance(A, B, universe=20000, n_perm=500)
    print("overlap:", ov)
    g = {f"g{i}": set() for i in range(50)}
    for i in range(49):
        g[f"g{i}"].add(f"g{i+1}"); g[f"g{i+1}"].add(f"g{i}")
    pr = network_proximity({"g1", "g2"}, {"g40", "g45"}, g, n_rand=100)
    print("proximity:", pr)
    print("halt:", halt_decision(ov, pr))

    # --- added with the v12 hardening ----------------------------------------
    # a one-target drug against a broad disease gene list: the overlap test cannot
    # reach alpha whatever the data say, so the run continues, capped.
    ov1 = overlap_significance({"HMGCR"}, {f"d{i}" for i in range(2000)}, universe=20000,
                               n_perm=200)
    hd1 = halt_decision(ov1, None)
    print("underpowered:", hd1.outcome, "|", hd1.confidence_cap, "|", hd1.power.detail)
    # a failed decoy is an independent gate: it stops the run by default, and a
    # pre-registered report-only run still cannot overlook the verdict
    bad = decoy_delta({"T1", "T2"}, {"T1"}, {"T1", "T2"})
    close = ProximityResult(1.3, -5.5, 1.7, 0.07, 2, 2, 1000)   # proximity passes here
    hd2 = halt_decision(ov, close, decoy=bad)
    print("decoy (default):", hd2.decoy_outcome, "| halt:", hd2.halt)
    hd3 = halt_decision(ov, close, decoy=bad, halt_on_decoy_failure=False)
    print("decoy (pre-registered report-only):", hd3.decoy_outcome, "| halt:", hd3.halt,
          "|", hd3.describe())
