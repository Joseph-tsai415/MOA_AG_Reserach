"""Evidence tiers and confidence scoring — CLAUDE.md §3, mechanism 1.

Every compound->target edge, disease->gene edge, and report claim MUST carry an
explicit evidence tier. A claim may appear in a report only at the confidence its
*highest independently-corroborated* tier supports — never at the confidence the
prose sounds.

    confidence = tier_weight x source-convergence x directional-consistency

E2 annotations and E3/E4 predictions may NOT stand alone as established fact.
Novel mechanisms are tagged "no prior report; refutable by [assay]" (see
`ClaimConfidence.label == "hypothesis"`), never dressed as an E1 citation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


class Tier(str, Enum):
    """Evidence tiers, strongest to weakest. REJECT = disqualified."""
    E0 = "E0"   # measured: ChEMBL pChEMBL>=6, BindingDB Ki/Kd/IC50, patient DE
    E1 = "E1"   # grounded literature: PMID whose abstract supports the claim
    E2 = "E2"   # annotation / DB cross-reference / text-mined co-occurrence
    E3 = "E3"   # predicted in-silico: SwissTarget/SEA, docking w/ decoy control
    E4 = "E4"   # inferred heuristic / analogy
    REJECT = "REJECT"


# Relative weight of each tier and whether it can support a claim on its own.
_TIER_WEIGHT = {Tier.E0: 1.0, Tier.E1: 0.9, Tier.E2: 0.4,
                Tier.E3: 0.5, Tier.E4: 0.2, Tier.REJECT: 0.0}
_STANDS_ALONE = {Tier.E0: True, Tier.E1: True, Tier.E2: False,
                 Tier.E3: False, Tier.E4: False, Tier.REJECT: False}


@dataclass
class Edge:
    """One piece of evidence linking a subject to an object.

    e.g. compound->target, or gene->disease. `direction` is 'up'/'down'/None
    (for target modulation or disease DE). `organism` defaults to human; a
    non-human organism is a REJECT signal handled by promiscuity_filter.
    """
    subject: str
    object: str
    tier: Tier
    source_id: str = ""              # PMID / DOI / ChEMBL id / dataset id
    organism: str = "Homo sapiens"
    assay_type: Optional[str] = None
    affinity: Optional[float] = None  # pChEMBL or -log10(Ki/Kd/IC50)
    direction: Optional[str] = None   # 'up' | 'down' | None
    direction_source: Optional[str] = None
    pains_flag: bool = False
    notes: str = ""

    def stands_alone(self) -> bool:
        return _STANDS_ALONE[self.tier]


@dataclass
class ClaimConfidence:
    """Result of scoring a set of edges that support one claim."""
    score: float                       # 0.0 - 1.0
    label: str                         # established | novel-plausible | hypothesis | reject
    best_tier: Tier
    n_independent_sources: int
    directional_consistency: float     # 1.0 = all agree, 0.5 = conflict
    reasons: list = field(default_factory=list)


def _rank(t: Tier) -> float:
    return _TIER_WEIGHT[t]


def confidence(edges: Iterable[Edge]) -> ClaimConfidence:
    """Score the confidence a claim earns from its supporting edges.

    Rules (CLAUDE.md §3):
      * all-REJECT  -> label 'reject', score 0.
      * best tier that STANDS ALONE (E0/E1) -> can be 'established'.
      * best tier is only E2/E3/E4 -> capped at 'hypothesis' / 'novel-plausible'
        no matter how many sources agree (annotation/prediction never becomes fact).
      * more independent sources -> higher score (convergence).
      * directional conflict -> halved score.
    """
    edges = [e for e in edges if e is not None]
    if not edges:
        return ClaimConfidence(0.0, "reject", Tier.REJECT, 0, 1.0, ["no evidence"])

    live = [e for e in edges if e.tier is not Tier.REJECT]
    if not live:
        return ClaimConfidence(0.0, "reject", Tier.REJECT, 0,
                               1.0, ["all evidence rejected (non-human / PAINS)"])

    best = max(live, key=lambda e: _rank(e.tier)).tier
    sources = {e.source_id for e in live if e.source_id} or {id(e) for e in live}
    n_sources = len(sources)

    # directional consistency
    dirs = {e.direction for e in live if e.direction}
    directional_consistency = 0.5 if len(dirs) > 1 else 1.0

    reasons = []
    convergence = min(1.0, 0.6 + 0.2 * (n_sources - 1))
    score = _rank(best) * convergence * directional_consistency

    standalone = _STANDS_ALONE[best]
    if not standalone:
        # E2/E3/E4 only — cannot be 'established'
        reasons.append(f"best tier {best.value} cannot stand alone; needs E0/E1 corroboration")
        label = "novel-plausible" if best is Tier.E3 else "hypothesis"
        score = min(score, 0.5)
    else:
        label = "established" if score >= 0.7 else "novel-plausible"

    if directional_consistency < 1.0:
        reasons.append(f"directional conflict among sources: {sorted(dirs)}")

    return ClaimConfidence(round(score, 3), label, best, n_sources,
                           directional_consistency, reasons)


if __name__ == "__main__":
    # tiny smoke test
    strong = [Edge("imperatorin", "JAK1", Tier.E0, "CHEMBL_ACT_1", affinity=7.2, direction="down"),
              Edge("imperatorin", "JAK1", Tier.E1, "PMID:123", direction="down")]
    weak = [Edge("imperatorin", "JAK1", Tier.E2, "PubChem_xref")]
    print("strong:", confidence(strong))
    print("weak  :", confidence(weak))
    print("rejected:", confidence([Edge("x", "fba", Tier.REJECT, organism="Bacteria")]))
