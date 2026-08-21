"""v10 Transcriptomics Track — measured disease signature + L1000 reversal.

The pipeline's first *measured* evidence layer (CLAUDE.md §3, 🧬 callouts). Two jobs:

  1. Data-driven disease signature (Step 2): GEO dataset (lesional vs control) ->
     bulk differential expression via pydeseq2 -> up/down gene signature that
     AUGMENTS List B (genes both database-associated AND measured-DE are up-weighted;
     direction_in_disease confirmed from data).

  2. Connectivity-map signature reversal (Step 4): does a compound REVERSE the
     disease signature? Uses the key-free **L1000CDS2** API (aggravate=False finds
     reversers). CMap convention: a therapeutic compound down-regulates disease-UP
     genes and up-regulates disease-DOWN genes.

CONDITIONAL & opportunistic: run only with REAL expression data (user-provided
counts or a named GEO dataset); never simulate a signature. Report L1000 coverage
honestly — many TCM natural products have NO L1000 signature.

Environment: pydeseq2, GEOparse, pandas, numpy, requests (all in env `moa`).
No cmapPy / CLUE key needed — reversal goes through the L1000CDS2 REST API.

    fetch_geo(gse_id, destdir)                             -> GeoFetch (metadata, best-effort)
    disease_signature(counts, metadata, cond, test, ref)  -> Signature (up/dn genes)
        engine='welch' (default, robust) | 'pydeseq2' (opt-in; segfaults on some Windows envs)
    l1000_reversers(up_genes, dn_genes)                   -> [Reverser] (perturbagens that reverse)
    compound_reversal(name, up_genes, dn_genes)           -> ReversalResult (is `name` a reverser?)
    reversal_score(dis_up, dis_dn, cmpd_up, cmpd_dn)      -> float  (CMap: -1 reversal .. +1 mimic)

DE engine note: `engine='welch'` (log2-CPM + Welch t-test + BH-FDR) is the DEFAULT
because full `pydeseq2` NB modeling segfaults on some Windows setups; it is offered
as an opt-in engine when the environment supports it.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Optional

import requests

L1000CDS2 = "https://maayanlab.cloud/L1000CDS2/query"
_UA = {"User-Agent": "moa_lib-transcriptomics/1.0", "content-type": "application/json"}


# ============================================================ 1. disease signature
@dataclass
class Signature:
    up_genes: list                 # significantly UP in disease (padj<a, log2FC>+lfc)
    dn_genes: list                 # significantly DOWN in disease
    n_tested: int
    engine: str = "welch"
    results_df: object = None      # full results (pandas DataFrame: log2FoldChange, padj)
    params: dict = field(default_factory=dict)
    note: str = ""


def _bh_fdr(p):
    import numpy as np
    p = np.nan_to_num(np.asarray(p, float), nan=1.0)
    m = len(p); order = np.argsort(p); q = np.empty(m); c = 1.0
    for i in range(m - 1, -1, -1):
        c = min(c, p[order[i]] * m / (i + 1)); q[order[i]] = c
    return q


def _welch_signature(counts, metadata, cond_col, test, ref, padj, lfc, max_genes):
    import numpy as np, pandas as pd
    from scipy import stats
    md = metadata.loc[[s for s in counts.index if s in metadata.index]]
    counts = counts.loc[md.index]
    cond = md[cond_col].astype(str).values
    cpm = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0) * 1e6
    logv = np.log2(cpm.fillna(0) + 1)
    a = logv[cond == test].values; b = logv[cond == ref].values
    l2fc = pd.Series(a.mean(0) - b.mean(0), index=logv.columns)
    _, p = stats.ttest_ind(a, b, axis=0, equal_var=False)
    res = pd.DataFrame({"log2FoldChange": l2fc,
                        "padj": pd.Series(_bh_fdr(p), index=logv.columns)}).dropna()
    sig = res[(res.padj < padj) & (res.log2FoldChange.abs() > lfc)]
    up = sig[sig.log2FoldChange > 0].sort_values("padj")
    dn = sig[sig.log2FoldChange < 0].sort_values("padj")
    return Signature([str(g) for g in up.index[:max_genes]], [str(g) for g in dn.index[:max_genes]],
                     int(res.shape[0]), "welch", res,
                     {"condition": cond_col, "test": test, "ref": ref, "padj": padj, "lfc": lfc},
                     "Welch t-test on log2-CPM + BH-FDR (robust default; not full DESeq2 NB modeling)")


def _pydeseq2_signature(counts, metadata, cond_col, test, ref, padj, lfc, max_genes):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    md = metadata.copy(); md[cond_col] = md[cond_col].astype(str)
    inf = DefaultInference(n_cpus=1)
    dds = DeseqDataSet(counts=counts.loc[md.index].round().astype(int), metadata=md,
                       design=f"~{cond_col}", inference=inf, quiet=True)
    dds.deseq2()
    st = DeseqStats(dds, contrast=[cond_col, test, ref], inference=inf, quiet=True)
    st.summary()
    res = st.results_df.dropna(subset=["padj", "log2FoldChange"])
    up = res[(res.padj < padj) & (res.log2FoldChange > lfc)].sort_values("padj")
    dn = res[(res.padj < padj) & (res.log2FoldChange < -lfc)].sort_values("padj")
    return Signature([str(g) for g in up.index[:max_genes]], [str(g) for g in dn.index[:max_genes]],
                     int(res.shape[0]), "pydeseq2", res,
                     {"condition": cond_col, "test": test, "ref": ref, "padj": padj, "lfc": lfc},
                     "pydeseq2 DESeq2 negative-binomial (opt-in; can segfault on some Windows envs)")


def disease_signature(counts, metadata, condition_col: str, test_level: str, ref_level: str,
                      engine: str = "welch", padj: float = 0.05, lfc: float = 1.0,
                      max_genes: int = 150) -> Signature:
    """Bulk differential-expression disease signature (up/down genes).

    counts   : DataFrame **samples x genes** (raw counts).
    metadata : DataFrame indexed by samples, with `condition_col`.
    contrast : test_level vs ref_level (e.g. 'lesional' vs 'control').
    engine   : 'welch' (DEFAULT — pure numpy/scipy: log2-CPM + Welch t-test + BH-FDR;
               robust, always runs) or 'pydeseq2' (full DESeq2 NB modeling; opt-in
               because it segfaults on some Windows envs, so it is NOT the default).
    Returns up/down gene lists (padj < `padj`, |log2FC| > `lfc`), capped per
    direction at `max_genes` (L1000 queries take ≤ ~150 genes well).
    """
    if engine == "pydeseq2":
        return _pydeseq2_signature(counts, metadata, condition_col, test_level, ref_level, padj, lfc, max_genes)
    return _welch_signature(counts, metadata, condition_col, test_level, ref_level, padj, lfc, max_genes)


# back-compat: original name maps to the opt-in pydeseq2 engine
def deseq2_signature(counts, metadata, condition_col, test_level, ref_level, **kw):
    return disease_signature(counts, metadata, condition_col, test_level, ref_level, engine="pydeseq2", **kw)


# ============================================================ GEO fetch (best-effort)
@dataclass
class GeoFetch:
    gse_id: str
    title: str = ""
    n_samples: int = 0
    samples: list = field(default_factory=list)   # [{gsm, title, characteristics}]
    counts: object = None                          # DataFrame if a table was parseable
    note: str = ""


def fetch_geo(gse_id: str, destdir: str = ".") -> Optional[GeoFetch]:
    """Fetch GEO series metadata (+ expression table if present) via GEOparse.

    NOTE: for RNA-seq, raw counts usually live in a SUPPLEMENTARY file, not the
    series matrix — GEOparse gets metadata + (for microarray) a value table. When
    only metadata is available, pair the sample condition labels with a counts
    matrix downloaded separately, then call deseq2_signature().
    """
    try:
        import GEOparse
    except Exception:
        return None
    try:
        gse = GEOparse.get_GEO(geo=gse_id, destdir=destdir, silent=True)
    except Exception as e:
        return GeoFetch(gse_id, note=f"GEO fetch failed: {e}")
    samples = []
    for gsm_id, gsm in gse.gsms.items():
        ch = gsm.metadata.get("characteristics_ch1", [])
        samples.append({"gsm": gsm_id, "title": (gsm.metadata.get("title", [""]) or [""])[0],
                        "characteristics": ch})
    counts = None
    try:
        counts = gse.pivot_samples("VALUE")   # microarray value table (T if RNA-seq counts absent)
    except Exception:
        pass
    return GeoFetch(gse_id, (gse.metadata.get("title", [""]) or [""])[0], len(samples), samples,
                    counts, "metadata ok; verify counts source (RNA-seq counts are usually supplementary)")


# ============================================================ 2. L1000 reversal
@dataclass
class Reverser:
    pert_name: str
    score: float
    pert_id: str = ""


def l1000_reversers(up_genes, dn_genes, timeout: int = 60) -> list:
    """Query L1000CDS2 for perturbagens that REVERSE the disease signature.

    aggravate=False -> reversers (therapeutic direction). Returns ranked Reversers.
    up_genes / dn_genes: HGNC symbols (≤ ~150 each works best). [] on failure.
    """
    up = [g for g in (up_genes or [])][:150]
    dn = [g for g in (dn_genes or [])][:150]
    if not up and not dn:
        return []
    payload = {"data": {"upGenes": up, "dnGenes": dn},
               "config": {"aggravate": False, "searchMethod": "geneSet",
                          "share": False, "combination": False, "db-version": "latest"},
               "metadata": []}
    import time
    for attempt in range(3):
        try:
            r = requests.post(L1000CDS2, headers=_UA, data=json.dumps(payload), timeout=timeout)
            if "json" in r.headers.get("content-type", ""):
                out = []
                for t in r.json().get("topMeta", []):
                    name = t.get("pert_desc")
                    if not name or str(name) == "-666":   # L1000CDS2 null-name marker
                        name = t.get("pert_id", "?")
                    out.append(Reverser(str(name), round(float(t.get("score", 0)), 4), t.get("pert_id", "")))
                return out
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return []


@dataclass
class ReversalResult:
    compound: str
    in_l1000_reversers: bool
    score: Optional[float]
    rank: Optional[int]
    n_reversers: int
    note: str = ""


def compound_reversal(compound: str, up_genes, dn_genes) -> ReversalResult:
    """Is `compound` among the L1000 perturbagens that reverse the disease signature?

    Honest coverage: if the compound name is not matched, we report 'no L1000
    signature / not among top reversers' rather than inventing a score (TCM natural
    products are frequently absent from the L1000 library).
    """
    revs = l1000_reversers(up_genes, dn_genes)
    if not revs:
        return ReversalResult(compound, False, None, None, 0, "L1000CDS2 returned no result")
    c = compound.strip().lower()
    for i, rv in enumerate(revs, 1):
        if c and (c in rv.pert_name.strip().lower() or rv.pert_name.strip().lower() in c):
            return ReversalResult(compound, True, rv.score, i, len(revs),
                                  f"reverses disease signature (rank {i}/{len(revs)})")
    return ReversalResult(compound, False, None, None, len(revs),
                          "not among top L1000 reversers — likely no L1000 signature for this compound "
                          "(common for TCM natural products); coverage gap, not evidence of non-efficacy")


def reversal_score(dis_up, dis_dn, cmpd_up, cmpd_dn) -> float:
    """Pure CMap-style connectivity score for a compound's OWN signature vs disease.

    Returns a value in [-1, +1]:  **-1 = full reversal (therapeutic)**, +1 = mimics
    the disease. A therapeutic compound down-regulates disease-UP genes and
    up-regulates disease-DOWN genes.
    """
    du, dd = set(dis_up), set(dis_dn)
    cu, cd = set(cmpd_up), set(cmpd_dn)
    reversal = len(cd & du) + len(cu & dd)     # compound opposes disease
    mimic = len(cu & du) + len(cd & dd)        # compound mimics disease
    total = reversal + mimic
    if total == 0:
        return 0.0
    return round((mimic - reversal) / total, 3)   # +1 mimic .. -1 reversal


if __name__ == "__main__":
    import numpy as np, pandas as pd
    # 1) pure reversal score
    print("reversal(reverser):", reversal_score(["A", "B"], ["C", "D"], ["C", "D"], ["A", "B"]), "(want -1.0)")
    print("reversal(mimic):   ", reversal_score(["A", "B"], ["C", "D"], ["A", "B"], ["C", "D"]), "(want +1.0)")
    # 2) welch disease signature on synthetic counts
    rng = np.random.default_rng(0)
    g = [f"G{i}" for i in range(200)]; s = [f"S{i}" for i in range(8)]
    counts = pd.DataFrame(rng.poisson(200, size=(8, 200)).astype(float), index=s, columns=g)
    counts.iloc[4:, :15] += 1500
    meta = pd.DataFrame({"condition": ["control"] * 4 + ["disease"] * 4}, index=s)
    sig = disease_signature(counts, meta, "condition", "disease", "control")
    print("signature:", sig.note, "| up:", sig.up_genes[:6])
    # 3) live L1000 reversal
    revs = l1000_reversers(["STAT1", "IRF1", "CXCL10", "IFIT1", "GBP1"], ["FLG", "LOR", "KRT10"])
    print("L1000 reversers:", len(revs), "| top:", [(r.pert_name, r.score) for r in revs[:3]])
