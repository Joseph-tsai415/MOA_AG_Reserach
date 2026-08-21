"""Step-5 guardrail (P4) — recall / precision vs a ground truth.

CLAUDE.md §3: "Benchmark when a ground truth exists — report recall + precision."
For drug repurposing in a well-studied disease, the natural ground truth is the
set of molecular targets of APPROVED or late-phase therapeutics for that disease.
A hub list that recovers those targets (recall) without drowning them in noise
(precision) is trustworthy; one that misses them or is mostly artefacts is not.

This module also powers the Session-9 objective: quantifying how much the v9
controls (organism filter, PAINS gate, specificity test) improve reliability over
the uncontrolled v8 Session-8 run.

    recall_precision(predicted, truth)        -> ScoreCard
    compare_runs(run_a, run_b, truth)         -> {a, b, deltas}
    AD_TARGET_GROUND_TRUTH                     -> curated dict {gene: drug/evidence}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# --------------------------------------------------------------------------- ground truth
# Molecular targets of APPROVED or late-phase (>=Ph3) atopic-dermatitis drugs.
# Each entry cites the therapeutic that validates the target. This is a
# conservative, mechanism-level truth set (not every associated gene) so that
# recall/precision reflect actionable target discovery, not disease-gene mining.
AD_TARGET_GROUND_TRUTH = {
    "IL4R":   "dupilumab (approved, anti-IL-4Ra)",
    "IL13":   "tralokinumab / lebrikizumab (approved, anti-IL-13)",
    "IL31RA": "nemolizumab (approved, anti-IL-31RA)",
    "IL31":   "nemolizumab axis (approved)",
    "JAK1":   "upadacitinib / abrocitinib (approved JAK1i)",
    "JAK2":   "baricitinib (approved JAK1/2i)",
    "JAK3":   "JAK-family inhibitors (approved class)",
    "TYK2":   "JAK/TYK2 inhibitor class (clinical)",
    "TSLP":   "tezepelumab (Ph2/approved in asthma; AD trials)",
    "PDE4B":  "crisaborole / roflumilast / difamilast (approved PDE4i topical)",
    "AHR":    "tapinarof (approved AhR agonist)",
    "NR3C1":  "topical corticosteroids (glucocorticoid receptor, standard of care)",
    "HRH1":   "antihistamines (approved symptomatic)",
    "HRH4":   "H4R antagonists (clinical, anti-pruritic)",
    "PTGDR2": "CRTH2/DP2 antagonists (clinical)",
    "SYK":    "topical SYK inhibitors (clinical)",
    "S1PR1":  "etrasimod / S1P modulators (clinical)",
    "IL5":    "eosinophil axis (clinical adjacent)",
    "KIT":    "mast-cell axis (clinical adjacent)",
}


@dataclass
class ScoreCard:
    recall: float
    precision: float
    f1: float
    tp: int
    fp: int
    fn: int
    n_predicted: int
    n_truth: int
    tp_list: list = field(default_factory=list)
    fn_list: list = field(default_factory=list)


def recall_precision(predicted: Iterable[str],
                     truth: Optional[Iterable[str]] = None) -> ScoreCard:
    """Recall/precision of a predicted target/hub set against `truth`.

    Precision here is measured against the ground-truth targets only, so it is a
    *lower bound* (a predicted gene absent from the small truth set is not
    necessarily wrong). Recall is the headline metric for target discovery.
    """
    truth = set(truth) if truth is not None else set(AD_TARGET_GROUND_TRUTH)
    pred = set(predicted)
    tp = pred & truth
    fn = truth - pred
    n_tp, n_fn = len(tp), len(fn)
    n_fp = len(pred) - n_tp
    recall = n_tp / len(truth) if truth else 0.0
    precision = n_tp / len(pred) if pred else 0.0
    f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0
    return ScoreCard(round(recall, 3), round(precision, 3), round(f1, 3),
                     n_tp, n_fp, n_fn, len(pred), len(truth),
                     sorted(tp), sorted(fn))


def contamination(targets: Iterable[str], nonhuman: Iterable[str] = (),
                  pains_only: Iterable[str] = ()) -> dict:
    """Reliability defects present in a target set (lower is better)."""
    T = set(targets)
    nh = T & set(nonhuman)
    pp = T & set(pains_only)
    n = len(T) or 1
    return {
        "n_targets": len(T),
        "n_nonhuman": len(nh), "nonhuman": sorted(nh),
        "n_pains_only": len(pp), "pains_only": sorted(pp),
        "contamination_rate": round((len(nh) + len(pp)) / n, 3),
    }


def compare_runs(run_a: dict, run_b: dict,
                 truth: Optional[Iterable[str]] = None) -> dict:
    """Head-to-head of two runs. Each run dict:
        {'name', 'hubs':[...], 'nonhuman':[...], 'pains_only':[...]}
    Returns per-run scorecards + contamination + signed deltas (b relative to a).
    """
    def _score(run):
        sc = recall_precision(run.get("hubs", []), truth)
        cont = contamination(run.get("hubs", []), run.get("nonhuman", []),
                             run.get("pains_only", []))
        return {"name": run.get("name", "?"), "scorecard": sc, "contamination": cont}

    a, b = _score(run_a), _score(run_b)
    deltas = {
        "recall": round(b["scorecard"].recall - a["scorecard"].recall, 3),
        "precision": round(b["scorecard"].precision - a["scorecard"].precision, 3),
        "f1": round(b["scorecard"].f1 - a["scorecard"].f1, 3),
        "contamination_rate": round(b["contamination"]["contamination_rate"]
                                    - a["contamination"]["contamination_rate"], 3),
        "n_hubs": b["contamination"]["n_targets"] - a["contamination"]["n_targets"],
    }
    return {"a": a, "b": b, "deltas": deltas}


if __name__ == "__main__":
    v8_like = {"name": "v8/session8", "hubs": ["JAK1", "NR3C1", "VDR", "STAT3", "BCL2",
               "fba", "norA", "CA2", "CA9", "PON1"],
               "nonhuman": ["fba", "norA"], "pains_only": ["CA2", "CA9"]}
    v9_like = {"name": "v9/session9", "hubs": ["JAK1", "JAK2", "IL4R", "STAT3",
               "NR3C1", "TSLP", "PDE4B"], "nonhuman": [], "pains_only": []}
    import json
    cmp = compare_runs(v8_like, v9_like)
    print("recall v8:", cmp["a"]["scorecard"].recall, "v9:", cmp["b"]["scorecard"].recall)
    print("deltas:", json.dumps(cmp["deltas"]))
