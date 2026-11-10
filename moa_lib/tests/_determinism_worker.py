"""Subprocess worker for the two-hash-seed determinism test.

Run as:  python _determinism_worker.py <mode>
Modes:
    fixed              network_proximity on a deterministically built graph
    legacy             the SAME computation with the pre-fix ordering restored
                       (iterate `set(targets)`) — the negative control: this one
                       MUST differ between hash seeds, which proves the harness can
                       detect nondeterminism at all
    setbuilt           deterministic target ordering, but the GRAPH dict assembled by
                       iterating a set (the documented input-contract violation)
    setbuilt_canonical the same graph passed through canonical_graph() first
    overlap            overlap_significance + halt_decision + decoy_delta end to end

Prints one JSON object to stdout. Nothing else may be printed to stdout.
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from moa_lib import specificity_controls as sc  # noqa: E402

N_RAND = 300
SEED = 1234


def build(set_built: bool = False):
    """A 1200-node scale-free-ish interactome + 40 targets + a 200-gene disease module."""
    rng = random.Random(7)
    nodes = [f"GENE{i:04d}" for i in range(1200)]
    adj = {n: set() for n in nodes}
    for i, n in enumerate(nodes):
        if i == 0:
            continue
        for _ in range(1 + rng.randrange(3)):
            m = nodes[rng.randrange(i)]
            if m != n:
                adj[n].add(m)
                adj[m].add(n)
    if set_built:
        graph = {k: set(adj[k]) for k in set(adj)}      # hash-ordered insertion
    else:
        graph = {k: set(adj[k]) for k in sorted(adj)}   # what results/obesity does
    targets = set(rng.sample(nodes, 40))
    disease = set(rng.sample(nodes, 200))
    return graph, targets, disease


def legacy_network_proximity(targets, disease_genes, graph, n_rand=1000, seed=1234,
                             unreachable=10.0, exclude_from_null=()):
    """The pre-fix target ordering, everything else identical to the current module.

    Isolates the defect under test: `tset` follows `set(targets)` iteration order, so
    the sequence of degree-matched null draws depends on PYTHONHASHSEED.
    """
    disease = set(disease_genes) & set(graph)
    dist = sc._multi_source_bfs(graph, disease)

    def _dc(nodes):
        vals = [dist.get(n, unreachable) for n in nodes if n in graph]
        return sum(vals) / len(vals) if vals else unreachable

    tset = [t for t in set(targets) if t in graph]        # <-- THE BUG
    d_c = _dc(tset)
    bins = sc._degree_bins(graph)
    binof, members = bins.get("binof", {}), bins.get("members", {})
    excl = set(exclude_from_null)
    if excl:
        members = {b: [n for n in ns if n not in excl] for b, ns in members.items()}
    all_nodes = [n for n in graph.keys() if n not in excl] or list(graph.keys())
    rng = random.Random(seed)
    null = []
    for _ in range(n_rand):
        sample = []
        for t in tset:
            pool = members.get(binof.get(t)) or all_nodes
            if not pool:
                pool = all_nodes
            sample.append(rng.choice(pool))
        null.append(_dc(sample))
    mean_rand = sum(null) / len(null)
    var = sum((x - mean_rand) ** 2 for x in null) / len(null)
    std = var ** 0.5
    z = (d_c - mean_rand) / std if std > 0 else 0.0
    return sc.ProximityResult(round(d_c, 3), round(z, 3), round(mean_rand, 3),
                              round(std, 3), len(tset), len(disease), n_rand)


def main(mode: str) -> dict:
    if mode in ("fixed", "legacy"):
        graph, targets, disease = build(set_built=False)
        fn = sc.network_proximity if mode == "fixed" else legacy_network_proximity
        return asdict(fn(targets, disease, graph, n_rand=N_RAND, seed=SEED,
                         exclude_from_null=disease))
    if mode in ("setbuilt", "setbuilt_canonical"):
        graph, targets, disease = build(set_built=True)
        if mode == "setbuilt_canonical":
            graph = sc.canonical_graph(graph)
        return asdict(sc.network_proximity(targets, disease, graph, n_rand=N_RAND,
                                           seed=SEED, exclude_from_null=disease))
    if mode == "overlap":
        graph, targets, disease = build(set_built=False)
        decoy = {f"GENE{i:04d}" for i in range(1100, 1200)}
        ov = sc.overlap_significance(targets, disease, universe=20000, n_perm=500, seed=SEED)
        pr = sc.network_proximity(targets, disease, graph, n_rand=N_RAND, seed=SEED,
                                  exclude_from_null=disease)
        dd = sc.decoy_delta(targets, disease, decoy, graph=graph, n_rand=100)
        hd = sc.halt_decision(ov, pr, decoy=dd)
        return {"overlap": asdict(ov), "proximity": asdict(pr), "decoy": asdict(dd),
                "halt": hd.as_dict()}
    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), sort_keys=True))
