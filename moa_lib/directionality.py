"""Step-4 guardrail (P3) — directionality from DATA + conflict log.

Fixes session8 failure mode F5: every hub target was declared "therapeutically
consistent" by assuming the direction that fit the desired anti-AD story. That is
circular — a directionality pass that finds EVERY target consistent is invalid.

CLAUDE.md §3 requires the modulation direction to come from measured data
(ChEMBL `action_type`, or a LINCS L1000 signature), never from the outcome we
want. Therapeutic consistency is then a *derived* check, and every conflict or
ambiguity must be surfaced in a conflict log.

    classify_action(action_type)                 -> ('inhibition'|'activation'|'unknown', 'down'|'up'|None)
    resolve_target(gene, actions, disease_dir)   -> TargetDirection
    build_conflict_log(resolved)                 -> [conflict dicts]
    circularity_check(resolved)                  -> {suspicious: bool, ...}
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# ChEMBL action_type -> effect on the target's activity.
_INHIBIT = {"INHIBITOR", "ANTAGONIST", "BLOCKER", "NEGATIVE ALLOSTERIC MODULATOR",
            "NEGATIVE MODULATOR", "DISRUPTING AGENT", "INVERSE AGONIST",
            "PARTIAL AGONIST"}          # partial agonist ~ net dampening in most assays
_ACTIVATE = {"AGONIST", "ACTIVATOR", "POSITIVE ALLOSTERIC MODULATOR",
             "POSITIVE MODULATOR", "OPENER"}


def classify_action(action_type: Optional[str]) -> tuple:
    """Map a ChEMBL action_type string to (effect, target_direction).

    effect            = 'inhibition' | 'activation' | 'unknown'
    target_direction  = 'down' | 'up' | None   (direction of the TARGET's activity)
    """
    if not action_type:
        return ("unknown", None)
    a = action_type.strip().upper()
    if a in _INHIBIT:
        return ("inhibition", "down")
    if a in _ACTIVATE:
        return ("activation", "up")
    return ("unknown", None)


@dataclass
class TargetDirection:
    gene: str
    effect: str                       # inhibition | activation | unknown | conflict
    target_direction: Optional[str]   # down | up | None  (compound's effect on target)
    disease_direction: Optional[str]  # up | down | None  (target's role in disease)
    direction_source: str             # 'ChEMBL:action_type' | 'L1000' | 'literature' | 'none'
    therapeutic_consistent: Optional[bool]  # None if undeterminable
    conflict_flag: bool
    n_inhibit: int = 0
    n_activate: int = 0
    rationale: str = ""


def resolve_target(gene: str, actions: list, disease_direction: Optional[str],
                   direction_source: str = "ChEMBL:action_type") -> TargetDirection:
    """Aggregate all measured action_type records for one target.

    `actions` = list of raw ChEMBL action_type strings (may be mixed/empty).
    `disease_direction` = 'up' if the gene is UP in disease (pathogenic when high),
    'down' if protective/down in disease, or None if unknown.

    Therapeutic consistency (only when both directions known):
        target UP in disease  -> compound should push it DOWN (inhibition)
        target DOWN in disease -> compound should push it UP  (activation)
    A conflict_flag is raised when the measured actions disagree with each other.
    """
    effects = [classify_action(a)[0] for a in (actions or [])]
    n_inh = sum(e == "inhibition" for e in effects)
    n_act = sum(e == "activation" for e in effects)

    conflict = n_inh > 0 and n_act > 0
    if conflict:
        effect, tdir = "conflict", None
    elif n_inh > 0:
        effect, tdir = "inhibition", "down"
    elif n_act > 0:
        effect, tdir = "activation", "up"
    else:
        effect, tdir = "unknown", None

    consistent = None
    if tdir and disease_direction:
        # consistent when compound direction OPPOSES disease direction
        consistent = (tdir == "down" and disease_direction == "up") or \
                     (tdir == "up" and disease_direction == "down")

    rationale = (f"{n_inh} inhibitory / {n_act} activatory action_type record(s); "
                 f"disease_direction={disease_direction}")
    return TargetDirection(gene, effect, tdir, disease_direction,
                           direction_source if effects else "none",
                           consistent, conflict, n_inh, n_act, rationale)


def build_conflict_log(resolved: list) -> list:
    """Every ambiguity/conflict/unknown becomes a row — a zero-conflict pass is broken."""
    log = []
    for r in resolved:
        if r.conflict_flag:
            log.append({"gene": r.gene, "type": "action_conflict",
                        "detail": f"{r.n_inhibit} inhibit vs {r.n_activate} activate",
                        "resolution": "direction unresolved; excluded from verified table"})
        elif r.effect == "unknown":
            log.append({"gene": r.gene, "type": "no_direction_data",
                        "detail": "no ChEMBL action_type; direction unmeasured",
                        "resolution": "hypothesis-only; needs L1000 or literature"})
        elif r.therapeutic_consistent is None:
            log.append({"gene": r.gene, "type": "disease_direction_unknown",
                        "detail": "target modulation known but disease role direction unknown",
                        "resolution": "consistency undeterminable"})
        elif r.therapeutic_consistent is False:
            log.append({"gene": r.gene, "type": "directional_conflict",
                        "detail": f"compound pushes {r.target_direction} but disease needs opposite",
                        "resolution": "COUNTER-therapeutic on this target; flag in report"})
    return log


def circularity_check(resolved: list) -> dict:
    """Guard against the session8 failure: if ~everything is 'consistent', suspect
    the directions were assumed to fit the story rather than read from data."""
    determinable = [r for r in resolved if r.therapeutic_consistent is not None]
    if not determinable:
        return {"suspicious": False, "n_determinable": 0,
                "note": "no target had both measured direction and disease direction"}
    frac = sum(r.therapeutic_consistent for r in determinable) / len(determinable)
    n_unknown = sum(r.effect == "unknown" for r in resolved)
    return {
        "suspicious": frac >= 0.95 and len(determinable) >= 5,
        "fraction_consistent": round(frac, 3),
        "n_determinable": len(determinable),
        "n_unknown_direction": n_unknown,
        "effect_distribution": dict(Counter(r.effect for r in resolved)),
        "note": ("almost every target 'consistent' — verify directions came from "
                 "action_type/L1000, not from the desired anti-AD outcome"
                 if frac >= 0.95 else "mixed directions — consistent with data-derived call"),
    }


if __name__ == "__main__":
    r1 = resolve_target("JAK1", ["INHIBITOR", "INHIBITOR"], disease_direction="up")
    r2 = resolve_target("NR3C1", ["AGONIST"], disease_direction="down")
    r3 = resolve_target("PTGS2", ["INHIBITOR", "AGONIST"], disease_direction="up")  # conflict
    r4 = resolve_target("BCL2", [], disease_direction="up")                          # unknown
    for r in (r1, r2, r3, r4):
        print(r.gene, r.effect, r.therapeutic_consistent, r.conflict_flag)
    print("conflicts:", build_conflict_log([r1, r2, r3, r4]))
    print("circularity:", circularity_check([r1, r2, r3, r4]))
