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

HALT rule (CLAUDE.md Step 3): stop the pipeline if overlap_p > 0.05 OR z_c > -0.15.

    overlap_significance(A, B, universe, n_perm)          -> OverlapResult
    network_proximity(targets, disease_genes, graph, ...) -> ProximityResult
    decoy_delta(targets, real_genes, decoy_genes, graph)  -> DecoyResult
    halt_decision(overlap, proximity)                     -> (halt: bool, reasons)
"""
from __future__ import annotations

import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from scipy.stats import hypergeom

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
    """
    A, B = set(A), set(B)
    a, b = len(A), len(B)
    observed = len(A & B)
    universe = max(universe, a, b, observed, 1)

    # analytic: P(X >= observed) for X ~ Hypergeom(M=universe, n=a, N=b)
    hg_p = float(hypergeom.sf(observed - 1, universe, a, b))
    expected = a * b / universe
    enrichment = observed / expected if expected > 0 else float("inf")

    # empirical permutation: resample a random 'A' of size a from the universe,
    # count overlap with the real B. B is held fixed as universe indices 0..b-1.
    rng = random.Random(seed)
    pool = list(range(universe))
    b_idx = set(range(b))                       # fixed reference set of size b
    ge = 0
    for _ in range(n_perm):
        sample = rng.sample(pool, a)
        if len(b_idx.intersection(sample)) >= observed:
            ge += 1
    perm_p = (ge + 1) / (n_perm + 1)            # add-one (never reports p=0)

    return OverlapResult(observed, round(expected, 2), round(enrichment, 2),
                         hg_p, perm_p, a, b, universe, n_perm)


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


def _multi_source_bfs(graph: dict, sources: set) -> dict:
    """Distance from the NEAREST source to every reachable node (unweighted)."""
    dist = {s: 0 for s in sources if s in graph}
    dq = deque(dist.keys())
    while dq:
        u = dq.popleft()
        for v in graph[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                dq.append(v)
    return dist


def _degree_bins(graph: dict, n_bins: int = 20) -> dict:
    """Map each node to a degree-bin key so randomisation is degree-preserving."""
    degs = {n: len(graph[n]) for n in graph}
    if not degs:
        return {}
    order = sorted(degs, key=lambda n: degs[n])
    per = max(1, len(order) // n_bins)
    binof, members = {}, defaultdict(list)
    for i, n in enumerate(order):
        b = i // per
        binof[n] = b
        members[b].append(n)
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
    """
    disease = set(disease_genes) & set(graph)
    dist = _multi_source_bfs(graph, disease)

    def _dc(nodes):
        vals = [dist.get(n, unreachable) for n in nodes if n in graph]
        return sum(vals) / len(vals) if vals else unreachable

    tset = [t for t in set(targets) if t in graph]
    d_c = _dc(tset)

    bins = _degree_bins(graph)
    binof, members = bins.get("binof", {}), bins.get("members", {})
    excl = set(exclude_from_null)
    if excl:  # drop excluded (disease-module) nodes from each degree-bin sampling pool
        members = {b: [n for n in ns if n not in excl] for b, ns in members.items()}
    all_nodes = [n for n in graph.keys() if n not in excl] or list(graph.keys())
    rng = random.Random(seed)
    null = []
    for _ in range(n_rand):
        sample = []
        for t in tset:
            pool = members.get(binof.get(t)) or all_nodes
            if not pool: pool = all_nodes
            sample.append(rng.choice(pool))
        null.append(_dc(sample))

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
    artefact of a promiscuous target list, not a real drug-disease link.
    """
    T = set(targets)
    real_ov = len(T & set(real_genes))
    decoy_ov = len(T & set(decoy_genes))
    res = DecoyResult(real_ov, decoy_ov, real_ov - decoy_ov)

    if graph is not None:
        rp = network_proximity(T, real_genes, graph, n_rand=n_rand)
        dp = network_proximity(T, decoy_genes, graph, n_rand=n_rand)
        res.real_zc, res.decoy_zc = rp.z_c, dp.z_c
        res.zc_delta = round(rp.z_c - dp.z_c, 3)

    # Pass if the real disease is at least as enriched AND (if computed) more
    # proximal (more negative z_c) than the decoy.
    if real_ov <= decoy_ov:
        res.passes = False
        res.reasons.append(f"overlap not selective: real {real_ov} <= decoy {decoy_ov}")
    if res.zc_delta is not None and res.zc_delta > 0:
        res.passes = False
        res.reasons.append(f"proximity not selective: real z_c not below decoy (delta {res.zc_delta})")
    return res


# ----------------------------------------------------------------------------- HALT


def halt_decision(overlap: OverlapResult,
                  proximity: Optional[ProximityResult],
                  alpha: float = 0.05, zc_cut: float = -0.15) -> tuple:
    """CLAUDE.md Step 3 HALT: stop if overlap_p > alpha OR z_c > zc_cut."""
    reasons, halt = [], False
    p = max(overlap.hypergeom_p, overlap.perm_p)   # be conservative: worse of the two
    if p > alpha:
        halt = True
        reasons.append(f"overlap not significant: p={p:.3g} > {alpha}")
    if proximity is not None and proximity.z_c > zc_cut:
        halt = True
        reasons.append(f"network proximity not significant: z_c={proximity.z_c} > {zc_cut}")
    if not halt:
        reasons.append(f"overlap p={p:.3g} <= {alpha}"
                       + (f" and z_c={proximity.z_c} <= {zc_cut}" if proximity else ""))
    return halt, reasons


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
