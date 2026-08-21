"""Step-0 guardrail (v11) — formula provenance & plausibility gate.

Motivated by the Session-9 review: 七白散 (Qibai San) is a **topical cosmetic
whitening mask** (七白膏, 太平聖惠方; 洗面七白散, 永類鈐方) — external use, a
"seven whites" powder. The pipeline analysed a WRONG 5-herb composition of it as a
**systemic** drug for **atopic dermatitis**, a disease it was never used for. Every
downstream number (ChEMBL plasma affinities, responder trial population, dupilumab
comparators) inherited that category error before a single gene was fetched.

This module validates the OBJECT OF STUDY before Steps 1-5 run:
    validate_composition(name, provided_herbs) -> CompositionCheck
    classify_route(name)                       -> ('topical'|'oral'|'unknown', source)
    indication_plausibility(name, disease)     -> ('established'|'novel'|'implausible', why)
    provenance_gate(name, herbs, disease)      -> GateVerdict  (HALT / REFRAME / PASS)

The reference table is small and explicit; extend it per formula. A formula NOT in
the table returns 'unknown' and the gate demands user confirmation rather than
silently assuming systemic exposure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Canonical reference. `herbs` lists (chinese, latin_genus_keyword). Compositions of
# the classical "seven whites" vary slightly by source; we store a canonical variant
# and match by OVERLAP, not exact identity.
FORMULA_REF = {
    "qibai san": {
        "aliases": ["七白散", "七白膏", "洗面七白散", "qibai san", "qi bai san"],
        "herb_count": 7,
        "herbs": [("白蘞", "ampelopsis"), ("白朮", "atractylodes"), ("白牽牛", "pharbitis"),
                  ("白芍藥", "paeonia"), ("白僵蠶", "bombyx"), ("白芷", "angelica"),
                  ("白附子", "typhonium")],
        "route": "topical",                        # 外用 — face wash / mask
        "route_source": "太平聖惠方 (七白膏); 永類鈐方 (洗面七白散) — 外用美白祛斑",
        "traditional_indications": ["skin whitening", "freckle/melasma (祛斑)",
                                    "facial cosmetic", "hyperpigmentation"],
        "note": "Topical cosmetic mask; sources warn it is external-use, not taken internally.",
    },
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _lookup(name: str) -> Optional[dict]:
    n = _norm(name)
    for key, rec in FORMULA_REF.items():
        if n == key or any(_norm(a) in n or n in _norm(a) for a in rec["aliases"]):
            return rec
    return None


@dataclass
class CompositionCheck:
    known: bool
    provided_count: int
    authentic_count: Optional[int]
    matched: list = field(default_factory=list)
    missing: list = field(default_factory=list)     # in authentic, absent from provided
    extra: list = field(default_factory=list)       # in provided, not in authentic
    verdict: str = "unknown"                         # match | mismatch | unknown
    reasons: list = field(default_factory=list)


def validate_composition(name: str, provided_herbs: list) -> CompositionCheck:
    rec = _lookup(name)
    prov = [_norm(h) for h in provided_herbs]
    if not rec:
        return CompositionCheck(False, len(prov), None, verdict="unknown",
                                reasons=[f"'{name}' not in provenance reference — cannot verify; "
                                         "confirm composition + route with the user"])
    matched, extra = [], []
    auth_hit = set()
    for h in provided_herbs:
        hl = _norm(h)
        hit = None
        for i, (cn, lat) in enumerate(rec["herbs"]):
            if cn in h or lat in hl:
                hit = i; break
        if hit is not None:
            matched.append(h); auth_hit.add(hit)
        else:
            extra.append(h)
    missing = [f"{cn} ({lat})" for i, (cn, lat) in enumerate(rec["herbs"]) if i not in auth_hit]
    reasons = []
    if len(prov) != rec["herb_count"]:
        reasons.append(f"herb count {len(prov)} != authentic {rec['herb_count']}")
    if missing:
        reasons.append(f"missing authentic herbs: {', '.join(missing)}")
    if extra:
        reasons.append(f"non-authentic herbs present: {', '.join(extra)}")
    verdict = "match" if (not missing and not extra and len(prov) == rec["herb_count"]) else "mismatch"
    return CompositionCheck(True, len(prov), rec["herb_count"], matched, missing, extra, verdict, reasons)


def classify_route(name: str) -> tuple:
    rec = _lookup(name)
    if not rec:
        return ("unknown", "not in reference — confirm route with user")
    return (rec["route"], rec["route_source"])


def indication_plausibility(name: str, disease: str) -> tuple:
    rec = _lookup(name)
    if not rec:
        return ("unknown", "formula not in reference")
    d = _norm(disease)
    for ind in rec["traditional_indications"]:
        if _norm(ind) in d or d in _norm(ind):
            return ("established", f"traditional indication includes '{ind}'")
    return ("novel/implausible",
            f"'{disease}' is not a traditional indication (traditional use: "
            f"{', '.join(rec['traditional_indications'])}) — treat as an explicit repurposing "
            f"hypothesis, not established use")


@dataclass
class GateVerdict:
    action: str                     # "HALT" | "REFRAME" | "PASS"
    composition: CompositionCheck
    route: str
    route_source: str
    indication: str
    indication_why: str
    reasons: list = field(default_factory=list)


def provenance_gate(name: str, provided_herbs: list, disease: str) -> GateVerdict:
    comp = validate_composition(name, provided_herbs)
    route, rsrc = classify_route(name)
    ind, ind_why = indication_plausibility(name, disease)
    reasons, action = [], "PASS"
    if comp.verdict == "mismatch":
        action = "HALT"
        reasons.append("composition mismatch — analysing the wrong formula: " + "; ".join(comp.reasons))
    if comp.verdict == "unknown":
        action = "HALT"
        reasons.append("formula/composition unverified — confirm with user before proceeding")
    if route == "topical":
        action = "HALT" if action != "HALT" else action
        reasons.append("route is TOPICAL/external — systemic pharmacology (plasma affinity, responder "
                       "trial population, systemic-drug comparators) is a category error; use a "
                       "skin-compartment model or explicitly flag the systemic view as hypothetical")
    if ind.startswith("novel") or ind == "unknown":
        if action == "PASS":
            action = "REFRAME"
        reasons.append(f"indication: {ind_why}")
    return GateVerdict(action, comp, route, rsrc, ind, ind_why, reasons)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    s9 = ["白朮 Atractylodes", "白芷 Angelica dahurica", "白及 Bletilla striata",
          "白蘞 Ampelopsis japonica", "白茯苓 Poria cocos"]
    g = provenance_gate("Qibai San (七白散)", s9, "Atopic Dermatitis")
    print("action:", g.action)
    print("composition:", g.composition.verdict, g.composition.reasons)
    print("route:", g.route)
    print("indication:", g.indication)
    for r in g.reasons: print("  -", r)
