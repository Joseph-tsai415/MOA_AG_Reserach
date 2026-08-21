#!/usr/bin/env python3
"""
Validated / CLIP-supported miRNA→target edges from the ENCORI (starBase) Web API.

This is the Python-native path (no download needed). ENCORI edges carry AGO-CLIP /
degradome support -> evidence of BINDING. That is E1/E2 corroboration, NOT proof of
functional repression of the specific gene (which needs a reporter/knockdown = E0/E1).
Tag accordingly downstream.

Endpoint: https://rnasysu.com/encori/api/miRNATarget/
Returns a 22-column tab-delimited table (header lines begin with '#').

Usage:
    conda activate moa
    python encori_targets.py hsa-miR-21-5p                 # single miRNA, lenient
    python encori_targets.py hsa-miR-21-5p --clip 3         # require >=3 CLIP experiments
    python encori_targets.py cargo.txt --out encori_edges.csv   # batch a normalised list

Dependencies: requests, pandas
"""
import argparse
import io
import sys
import time
from typing import List, Optional

import pandas as pd
import requests

try:  # Windows console is cp1252; keep non-ASCII glyphs readable
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENCORI_API = "https://rnasysu.com/encori/api/miRNATarget/"


def fetch_encori_targets(mirna: str, assembly: str = "hg38", clip_exp: int = 1,
                         degra_exp: int = 0, program_num: int = 0,
                         timeout: int = 60) -> pd.DataFrame:
    """Fetch mRNA targets for one miRNA. Higher clip_exp / program_num = stricter.

    CHECK: returns an EMPTY dataframe (not an error) when a miRNA has no ENCORI
    interactions — a legitimate coverage gap for novel/low-study miRNAs. Callers
    must distinguish 'no evidence' from 'fetch failed'.
    """
    params = {
        "assembly": assembly, "geneType": "mRNA", "miRNA": mirna,
        "clipExpNum": clip_exp, "degraExpNum": degra_exp,
        "pancancerNum": 0, "programNum": program_num, "program": "None",
        "target": "all", "cellType": "all",
    }
    r = requests.get(ENCORI_API, params=params, timeout=timeout)
    r.raise_for_status()
    # ENCORI prefixes the table with '#'-commented metadata lines
    lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
    if len(lines) < 2:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO("\n".join(lines)), sep="\t")
    df.insert(0, "query_miRNA", mirna)
    return df


def batch(mirnas: List[str], clip_exp: int = 1, program_num: int = 0,
          pause: float = 0.5) -> pd.DataFrame:
    frames, empty = [], []
    for m in mirnas:
        try:
            d = fetch_encori_targets(m, clip_exp=clip_exp, program_num=program_num)
        except requests.RequestException as e:
            print(f"[FETCH_FAILED] {m}: {e}", file=sys.stderr)
            continue
        if d.empty:
            empty.append(m)
        else:
            frames.append(d)
        time.sleep(pause)   # be polite to the server
    if empty:
        print(f"[INFO] {len(empty)} miRNA(s) returned 0 ENCORI targets "
              f"(coverage gap, not non-function): {', '.join(empty)}", file=sys.stderr)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_list(arg: str) -> List[str]:
    if arg.endswith(".txt"):
        with open(arg, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    return [arg]


def main() -> int:
    ap = argparse.ArgumentParser(description="Query ENCORI miRNA→mRNA targets")
    ap.add_argument("mirna", help="a miRNA name (hsa-miR-21-5p) or a .txt list")
    ap.add_argument("--clip", type=int, default=1, help="min CLIP experiments (default 1)")
    ap.add_argument("--programs", type=int, default=0, help="min prediction programs (0-7)")
    ap.add_argument("--out", default=None, help="write edges to CSV")
    a = ap.parse_args()

    df = batch(_load_list(a.mirna), clip_exp=a.clip, program_num=a.programs)
    if df.empty:
        print("No ENCORI edges returned for the given filters.")
        return 0
    print(f"Retrieved {len(df)} miRNA-target edges across "
          f"{df['query_miRNA'].nunique()} miRNAs.")
    if a.out:
        df.to_csv(a.out, index=False, encoding="utf-8")
        print(f"Wrote {a.out}")
    else:
        cols = [c for c in ("query_miRNA", "geneID", "geneName", "clipExpNum") if c in df.columns]
        print(df[cols].head(20).to_string(index=False) if cols else df.head().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
