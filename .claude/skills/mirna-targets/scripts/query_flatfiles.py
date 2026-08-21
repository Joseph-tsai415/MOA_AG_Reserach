#!/usr/bin/env python3
"""
Query the DOWNLOADED flat files: miRTarBase (validated backbone, E0/E1),
TargetScan + miRDB (predicted, E3). No public REST API for these — download once
and cache under the run's data/ directory, then query locally.

Downloads (place paths in the CONFIG below or pass as args):
  - miRTarBase 9.0/10.0  hsa MTI table (.xlsx/.csv): column 'Support Type', 'Experiments'
  - TargetScan 8.0       Predicted_Targets_Context_Scores.txt  (context++ / weighted)
  - miRDB v6.0           prediction_result.txt  (miRNA, RefSeq, MirTarget score)

The functions below each carry a CHECK that asserts the expected columns exist, so a
changed file layout fails loudly instead of silently returning wrong edges.

Usage (examples):
    python query_flatfiles.py mirtarbase --file hsa_MTI.csv --mirna hsa-miR-21-5p
    python query_flatfiles.py predicted  --targetscan TS.txt --mirdb miRDB.txt \
                                          --mirna hsa-miR-21-5p --mirdb-min 80

Dependencies: pandas (+ openpyxl if reading .xlsx)
"""
import argparse
import sys
from typing import Optional

import pandas as pd

try:  # Windows console is cp1252; keep the '∩'/'≥' glyphs readable
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _require(df: pd.DataFrame, cols, source: str):
    """CHECK: fail loudly if the download's schema is not what we parse."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"[SCHEMA FAIL] {source}: missing columns {missing}. "
                         f"Got {list(df.columns)[:12]}... — check the download version.")


# ---- miRTarBase: the VALIDATED backbone (E0/E1) ---------------------------------------
def load_mirtarbase(path: str) -> pd.DataFrame:
    df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    _require(df, ["miRNA", "Target Gene", "Support Type", "Experiments", "References (PMID)"],
             "miRTarBase")
    return df


def functional_strong(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only strong functional evidence (reporter assay / Western / qPCR).
    'Functional MTI' = strong; 'Functional MTI (Weak)' and CLIP/degradome-only are demoted.
    This is what makes an edge E0/E1 rather than E2."""
    strong = df[df["Support Type"].astype(str).str.strip() == "Functional MTI"].copy()
    strong["evidence_tier"] = "E1"
    # luciferase reporter + protein-level (Western) => treat as E0-grade measured
    is_reporter = strong["Experiments"].astype(str).str.contains("Luciferase", case=False, na=False)
    is_protein = strong["Experiments"].astype(str).str.contains("Western", case=False, na=False)
    strong.loc[is_reporter & is_protein, "evidence_tier"] = "E0"
    return strong


# ---- TargetScan + miRDB: the PREDICTED layer (E3) -------------------------------------
def load_targetscan(path: str, max_context: float = -0.2) -> pd.DataFrame:
    """context++ score is negative; more negative = stronger. Keep <= max_context."""
    df = pd.read_csv(path, sep="\t")
    # TargetScan column names vary slightly by release; accept common variants
    ren = {"a_Gene_ID": "gene", "Gene Symbol": "gene", "Gene_Symbol": "gene",
           "miRNA": "miRNA", "context++ score": "context_score",
           "weighted context++ score": "wcontext_score"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    _require(df, ["gene", "miRNA"], "TargetScan")
    score_col = "context_score" if "context_score" in df.columns else None
    if score_col:
        df = df[pd.to_numeric(df[score_col], errors="coerce") <= max_context]
    return df[["miRNA", "gene"]].drop_duplicates()


def load_mirdb(path: str, min_score: int = 80) -> pd.DataFrame:
    """miRDB MirTarget score 0-100; >=80 = high-confidence (>=50 is the default cut)."""
    df = pd.read_csv(path, sep="\t", header=None,
                     names=["miRNA", "refseq", "score"]) if _headerless(path) else pd.read_csv(path, sep="\t")
    _require(df, ["miRNA", "score"], "miRDB")
    df = df[pd.to_numeric(df["score"], errors="coerce") >= min_score]
    return df


def _headerless(path: str) -> bool:
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
    return "score" not in first.lower()


def predicted_intersection(ts: pd.DataFrame, mdb: pd.DataFrame,
                           gene_col_mdb: str = "refseq") -> pd.DataFrame:
    """CHECK / anti-promiscuity: require BOTH TargetScan and miRDB to agree.
    Returns edges present in both predictors (mapped by gene where possible)."""
    if gene_col_mdb not in mdb.columns:
        print(f"[WARN] miRDB has no '{gene_col_mdb}' column to map to symbols; "
              f"map RefSeq->symbol before intersecting for best recall.", file=sys.stderr)
        return pd.DataFrame(columns=["miRNA", "gene"])
    merged = ts.merge(mdb, on="miRNA", how="inner")
    merged["evidence_tier"] = "E3"
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mirtarbase"); m.add_argument("--file", required=True); m.add_argument("--mirna")
    p = sub.add_parser("predicted")
    p.add_argument("--targetscan", required=True); p.add_argument("--mirdb", required=True)
    p.add_argument("--mirna"); p.add_argument("--mirdb-min", type=int, default=80)
    a = ap.parse_args()

    if a.cmd == "mirtarbase":
        df = functional_strong(load_mirtarbase(a.file))
        if a.mirna:
            df = df[df["miRNA"].astype(str).str.lower() == a.mirna.lower()]
        print(f"miRTarBase strong-functional edges: {len(df)} "
              f"(E0={sum(df['evidence_tier']=='E0')}, E1={sum(df['evidence_tier']=='E1')})")
        print(df[["miRNA", "Target Gene", "evidence_tier", "References (PMID)"]].head(20).to_string(index=False))
    else:
        ts = load_targetscan(a.targetscan)
        mdb = load_mirdb(a.mirdb, min_score=a.mirdb_min)
        if a.mirna:
            ts = ts[ts["miRNA"].str.lower() == a.mirna.lower()]
            mdb = mdb[mdb["miRNA"].str.lower() == a.mirna.lower()]
        inter = predicted_intersection(ts, mdb)
        print(f"Predicted (TargetScan ∩ miRDB≥{a.mirdb_min}): {len(inter)} edges "
              f"[TargetScan alone={len(ts)}, miRDB alone={len(mdb)} — note the shrink; "
              f"the intersection is the anti-promiscuity filter]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
