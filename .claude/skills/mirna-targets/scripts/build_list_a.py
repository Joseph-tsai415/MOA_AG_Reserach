#!/usr/bin/env python3
"""
Assemble the tiered List A from validated + predicted edge tables, and run the
anti-promiscuity / target-space CHECKS that keep a 40-miRNA cargo from enriching
everything.

Inputs: one or more edge CSVs with at least columns [miRNA, gene, evidence_tier]
(produced by encori_targets.py and query_flatfiles.py, or hand-built).

Output: list_a.csv with per-gene rows:
    gene, evidence_tier (best), sources, n_supporting_miRNAs, supporting_miRNAs, direction

Direction is always 'down' — a miRNA represses its target. This column feeds Step 4's
directionality check directly.

Usage:
    python build_list_a.py validated_edges.csv predicted_edges.csv --out list_a.csv

Dependency: pandas
"""
import argparse
import sys
from typing import List

import pandas as pd

try:  # Windows console is cp1252; keep non-ASCII glyphs readable
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TIER_RANK = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}   # lower = stronger


def load_edges(paths: List[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        d = pd.read_csv(p)
        # tolerate the different column names the source scripts emit
        d = d.rename(columns={"Target Gene": "gene", "geneName": "gene", "query_miRNA": "miRNA"})
        if not {"miRNA", "gene", "evidence_tier"}.issubset(d.columns):
            print(f"[WARN] {p}: needs miRNA/gene/evidence_tier; has {list(d.columns)[:8]}",
                  file=sys.stderr)
            continue
        frames.append(d[["miRNA", "gene", "evidence_tier"]])
    if not frames:
        raise SystemExit("[FAIL] no usable edge tables.")
    return pd.concat(frames, ignore_index=True).dropna(subset=["gene"]).drop_duplicates()


def build_list_a(edges: pd.DataFrame, cargo_size: int) -> pd.DataFrame:
    edges = edges.copy()
    edges["rank"] = edges["evidence_tier"].map(TIER_RANK).fillna(9)
    grp = edges.groupby("gene")
    out = pd.DataFrame({
        "evidence_tier": grp["rank"].min().map({v: k for k, v in TIER_RANK.items()}),
        "n_supporting_miRNAs": grp["miRNA"].nunique(),
        "supporting_miRNAs": grp["miRNA"].apply(lambda s: ";".join(sorted(set(s)))),
        "sources": grp["evidence_tier"].apply(lambda s: ";".join(sorted(set(s)))),
    }).reset_index()
    out["direction"] = "down"
    # multi-miRNA hits rank higher (analogous to a multi-compound hit)
    out = out.sort_values(["evidence_tier", "n_supporting_miRNAs"],
                          ascending=[True, False]).reset_index(drop=True)
    return out


def specificity_report(edges: pd.DataFrame, list_a: pd.DataFrame, cargo_size: int) -> None:
    """The make-or-break CHECK: is List A a validated backbone, or a predicted blob?"""
    n_validated = (list_a["evidence_tier"].isin(["E0", "E1"])).sum()
    n_predicted_only = (list_a["evidence_tier"] == "E3").sum()
    total = len(list_a)
    print("\n================= List A specificity report =================")
    print(f"Cargo miRNAs .............. {cargo_size}")
    print(f"Unique target genes ....... {total}")
    print(f"  validated (E0/E1) ....... {n_validated}")
    print(f"  predicted-only (E3) ..... {n_predicted_only}")
    if total:
        frac = n_predicted_only / total
        print(f"  predicted-only fraction . {frac:.0%}")
        if total > 3000:
            print("[WARN] target space > 3000 genes — near-certain to enrich "
                  "non-specifically. Anchor Step 3/4 on the validated backbone and "
                  "let the permutation-p + decoy gate cull the rest.")
        if frac > 0.7:
            print("[WARN] >70% of List A is predicted-only. Headline pathways MUST be "
                  "driven by the validated subset; tag predicted claims E3/hypothesis.")
    # promiscuity flag: a gene hit by nearly the whole cargo is likely non-specific
    hub = list_a[list_a["n_supporting_miRNAs"] >= max(3, cargo_size // 3)]
    print(f"Genes hit by >= {max(3, cargo_size // 3)} cargo miRNAs (multi-hit hubs): {len(hub)}")
    print("=============================================================\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("edges", nargs="+", help="edge CSVs (miRNA, gene, evidence_tier)")
    ap.add_argument("--cargo-size", type=int, default=40)
    ap.add_argument("--out", default="list_a.csv")
    a = ap.parse_args()

    edges = load_edges(a.edges)
    list_a = build_list_a(edges, a.cargo_size)
    specificity_report(edges, list_a, a.cargo_size)
    list_a.to_csv(a.out, index=False, encoding="utf-8")
    print(f"Wrote {a.out} ({len(list_a)} genes). Top validated targets:")
    print(list_a[list_a['evidence_tier'].isin(['E0', 'E1'])].head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
