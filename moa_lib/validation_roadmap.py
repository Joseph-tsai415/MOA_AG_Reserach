"""Step-5 output guardrail (v11) — Validation Roadmap + Lead Assessment.

Session-9 review (the reframe): this pipeline generates HYPOTHESES; it cannot be the
foundation for a lead. Its honest output is a route-matched, falsifiable experiment
plan plus a go/no-go — not a mechanism paragraph. Every field the report marks
"undetermined" (direction, potency, efficacy) is the deliverable, and each ships with
the specific assay that settles it and the criterion that would kill the lead.

    build_roadmap(ctx)      -> [Experiment]   (prioritised, decisive-first)
    lead_assessment(ctx)    -> LeadAssessment  (go / no-go + single most decisive test)

ctx keys (all optional, best-effort):
    formula, disease, route ('topical'|'oral'|'unknown'),
    provenance_action ('HALT'|'REFRAME'|'PASS'),
    hypothesis_axis (e.g. 'anti-inflammatory NF-kB/COX-2'),
    extract_characterized (bool), has_l1000 (bool),
    delivery_failures (list of compound names), direction_measured (bool)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Experiment:
    priority: int
    question: str          # the 'undetermined' it resolves
    method: str
    readout: str
    kill_criterion: str
    tier: str              # 'in-silico' | 'bench-cheap' | 'bench-medium'
    resolves: str


@dataclass
class LeadAssessment:
    verdict: str           # 'GO' | 'CONDITIONAL' | 'NO-GO'
    single_most_decisive: str
    kill_criterion: str
    rationale: list = field(default_factory=list)


def build_roadmap(ctx: dict) -> list:
    route = ctx.get("route", "unknown")
    disease = ctx.get("disease", "the disease")
    axis = ctx.get("hypothesis_axis", "the proposed mechanism")
    exps = []

    # 1. chemical reality — a DB compound list is not the extract
    if not ctx.get("extract_characterized"):
        exps.append(Experiment(
            1, "What is actually in the preparation? (a database compound list is not the extract)",
            "LC-MS / LC-MS-MS characterization of the ACTUAL preparation (correct authentic formula)",
            "Identity + relative abundance of constituents; presence/absence of the assumed actives",
            "If the assumed active constituents are absent or trace-level, the in-silico hypothesis is void",
            "bench-cheap", "extract identity"))

    # 2. delivery feasibility — can the actives reach the target by the intended route?
    df = ctx.get("delivery_failures") or []
    if route == "topical" or df:
        who = f" (esp. delivery-implausible: {', '.join(df)})" if df else ""
        exps.append(Experiment(
            2, f"Can the actives cross skin to reach the target?{who}",
            "Franz-diffusion-cell permeation across human/porcine skin or reconstructed epidermis, "
            "LC-MS-quantified receptor-compartment levels",
            "Steady-state flux / receptor-phase concentration vs the in-vitro active concentration",
            "If permeated concentration << active concentration, topical efficacy is implausible",
            "bench-medium", "route delivery"))

    # 3. direction + potency — the single cheapest decisive wet experiment
    if not ctx.get("direction_measured", False):
        if "nf" in axis.lower() or "inflamm" in axis.lower() or route == "topical":
            exps.append(Experiment(
                3, f"Does the extract actually suppress (not merely 'modulate') {axis} in disease-relevant cells?",
                "NF-kB luciferase reporter in IL-4/IL-13-stimulated keratinocytes (HaCaT/NHEK) or "
                "reconstructed epidermis; dose-response",
                "TSLP, CCL17 (TARC), CCL22 by qPCR/ELISA; NF-kB reporter luminescence",
                "If no dose-dependent suppression of TSLP/CCL17/CCL22, the anti-inflammatory hypothesis fails",
                "bench-cheap", "direction + potency"))
        else:
            exps.append(Experiment(
                3, f"What is the direction and potency of modulation on the hub targets for {axis}?",
                "Target-specific functional assay (reporter / enzymatic) with dose-response + orthogonal readout",
                "IC50/EC50 and direction (inhibition vs activation)",
                "If no dose-dependent effect at achievable concentrations, the target link is not therapeutic",
                "bench-cheap", "direction + potency"))

    # 4. efficacy signature reversal — cheapest measured efficacy signal
    if not ctx.get("has_l1000"):
        exps.append(Experiment(
            4, "Does the extract REVERSE the disease transcriptional signature (measured efficacy)?",
            "LINCS L1000 connectivity (in-silico) OR RNA-seq of treated vs untreated stimulated keratinocytes "
            "compared to the lesional-vs-control disease signature",
            "Connectivity/reversal score (-1 = full reversal → therapeutic)",
            "If connectivity is >= 0 (mimics or fails to reverse the disease signature), efficacy is unsupported",
            "in-silico", "efficacy reversal"))

    for i, e in enumerate(exps, 1): e.priority = i
    return exps


def lead_assessment(ctx: dict) -> LeadAssessment:
    reasons = []
    prov = ctx.get("provenance_action", "PASS")
    route = ctx.get("route", "unknown")
    df = ctx.get("delivery_failures") or []
    verdict = "GO"

    if prov == "HALT":
        verdict = "NO-GO"
        reasons.append("provenance gate HALT — wrong formula composition and/or route/indication mismatch; "
                       "the analysed object is not the real formula-in-context")
    if route == "topical" and ctx.get("modelled_systemic", True):
        verdict = "NO-GO" if verdict != "NO-GO" else verdict
        reasons.append("topical formula modelled with systemic pharmacology — category error")
    if df:
        reasons.append(f"active principle(s) delivery-implausible by the intended route: {', '.join(df)}")
        if verdict == "GO": verdict = "CONDITIONAL"
    if not ctx.get("direction_measured", False):
        reasons.append("modulation direction unmeasured — efficacy direction unproven")
        if verdict == "GO": verdict = "CONDITIONAL"
    if not ctx.get("has_l1000"):
        reasons.append("no measured reversal signature (L1000/RNA-seq) — efficacy unvalidated")

    roadmap = build_roadmap(ctx)
    # single most decisive = the cheapest bench experiment that resolves direction/efficacy,
    # unless provenance must be fixed first
    if prov == "HALT":
        decisive = ("Fix the object of study first: obtain the authentic formula and LC-MS the actual "
                    "preparation; the in-silico run cannot proceed on the wrong formula.")
        kill = "Assumed active constituents absent/trace in the real extract → hypothesis void."
    else:
        direction_exp = next((e for e in roadmap if e.resolves == "direction + potency"), None)
        if direction_exp:
            decisive = f"{direction_exp.method} — {direction_exp.readout}"
            kill = direction_exp.kill_criterion
        else:
            decisive = roadmap[0].method if roadmap else "N/A"
            kill = roadmap[0].kill_criterion if roadmap else "N/A"
    return LeadAssessment(verdict, decisive, kill, reasons)


if __name__ == "__main__":
    ctx = {"formula": "Qibai San", "disease": "Atopic Dermatitis", "route": "topical",
           "provenance_action": "HALT", "hypothesis_axis": "anti-inflammatory NF-kB/COX-2",
           "extract_characterized": False, "has_l1000": False,
           "delivery_failures": ["Pachymic acid", "Militarine"], "direction_measured": False}
    la = lead_assessment(ctx)
    print("VERDICT:", la.verdict)
    print("Most decisive:", la.single_most_decisive)
    for r in la.rationale: print("  -", r)
    print("--- roadmap ---")
    for e in build_roadmap(ctx):
        print(f"  [{e.priority}] ({e.tier}) {e.question}")
