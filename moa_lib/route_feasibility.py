"""Step-1 guardrail (v11) — drug-likeness FOR THE INTENDED ROUTE.

Session-9 review: the pipeline filters targets but never asks whether the MOLECULE
can reach them by the intended route. For a topical formula, a compound must cross
the stratum corneum; for an oral one it must be systemically bioavailable. Pachymic
acid (MW 528, LogP 7.2) and militarine (MW 727, LogP -0.5) fail BOTH windows — yet
they anchored the Session-9 mechanism. A compound that cannot be delivered should be
flagged before it defines a hypothesis.

    topical_feasible(mw, logp)                 -> Feasibility
    oral_feasible(mw, logp, hbd, hba)          -> Feasibility
    assess(compound, route)                    -> Feasibility (route-aware)
    screen(compounds, route)                   -> {name: Feasibility}

Rules of thumb (report them, don't over-claim precision):
  Topical / stratum-corneum permeation: MW <= 500 Da AND LogP ~ 1-3 (0-4 tolerated).
    Too polar (LogP<0) or too lipophilic (LogP>4-5) partition poorly; MW>500 is the
    classic upper cutoff for passive skin permeation.
  Oral (Lipinski Ro5): MW<=500, LogP<=5, HBD<=5, HBA<=10.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Feasibility:
    route: str
    feasible: bool
    violations: list = field(default_factory=list)
    note: str = ""


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def topical_feasible(mw, logp) -> Feasibility:
    mw, logp = _num(mw), _num(logp)
    v = []
    if mw is None or logp is None:
        return Feasibility("topical", False, ["missing MW/LogP"], "cannot assess")
    if mw > 500:
        v.append(f"MW {mw:.0f} > 500 (poor stratum-corneum permeation)")
    if logp < 1:
        v.append(f"LogP {logp} < 1 (too polar to partition into skin lipids)")
    if logp > 4:
        v.append(f"LogP {logp} > 4 (too lipophilic — stays in stratum corneum, poor flux)")
    return Feasibility("topical", not v, v,
                       "permeation window MW<=500, LogP~1-3" if v else "within topical permeation window")


def oral_feasible(mw, logp, hbd, hba) -> Feasibility:
    mw, logp, hbd, hba = _num(mw), _num(logp), _num(hbd), _num(hba)
    v = []
    if None in (mw, logp, hbd, hba):
        return Feasibility("oral", False, ["missing property"], "cannot assess")
    if mw > 500: v.append(f"MW {mw:.0f} > 500")
    if logp > 5: v.append(f"LogP {logp} > 5")
    if hbd > 5: v.append(f"HBD {hbd:.0f} > 5")
    if hba > 10: v.append(f"HBA {hba:.0f} > 10")
    # Lipinski allows one violation
    return Feasibility("oral", len(v) <= 1, v,
                       "Lipinski Ro5" + (" (>=2 violations → poor oral bioavailability)" if len(v) > 1 else ""))


def assess(compound: dict, route: str) -> Feasibility:
    """compound: {name?, mw, logp, hbd, hba}. route: 'topical' | 'oral' | 'unknown'."""
    if route == "topical":
        return topical_feasible(compound.get("mw"), compound.get("logp"))
    if route == "oral":
        return oral_feasible(compound.get("mw"), compound.get("logp"),
                             compound.get("hbd"), compound.get("hba"))
    # unknown route: fail if it clears NEITHER window (delivery-implausible by any route)
    t = topical_feasible(compound.get("mw"), compound.get("logp"))
    o = oral_feasible(compound.get("mw"), compound.get("logp"),
                      compound.get("hbd"), compound.get("hba"))
    ok = t.feasible or o.feasible
    return Feasibility("unknown", ok, (t.violations + o.violations) if not ok else [],
                       "delivery-implausible by BOTH topical and oral routes" if not ok
                       else "feasible by at least one route")


def screen(compounds: list, route: str) -> dict:
    """compounds: list of dicts with name/mw/logp/hbd/hba. Returns {name: Feasibility}."""
    out = {}
    for c in compounds:
        out[c.get("name", "?")] = assess(c, route)
    return out


if __name__ == "__main__":
    comps = [
        {"name": "Pachymic acid", "mw": 528.8, "logp": 7.2, "hbd": 2, "hba": 5},
        {"name": "Militarine", "mw": 726.7, "logp": -0.5, "hbd": 9, "hba": 17},
        {"name": "Imperatorin", "mw": 270.28, "logp": 3.4, "hbd": 0, "hba": 4},
    ]
    for route in ("topical", "oral"):
        print(f"--- {route} ---")
        for name, f in screen(comps, route).items():
            print(f"  {name:16s} feasible={f.feasible}  {f.violations}")
