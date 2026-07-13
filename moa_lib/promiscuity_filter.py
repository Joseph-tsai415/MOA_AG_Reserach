"""Step-1 guardrail (P1) — organism filter + PAINS + promiscuity cap.

Fixes session8 failure modes F1/F2:
  F1  non-human targets (fba, norA, PA, mdeA) leaked into the human target list.
  F2  polyphenol PAINS inflation (gallic acid = 221/317 targets).

Public API
    is_human(uniprot_id)            -> True / False / None(unknown)
    pains_flags(smiles)             -> [matched PAINS filter names]  (None if bad SMILES)
    screen_targets(targets)         -> (kept, rejected)   by organism
    promiscuity_flags(compounds, cap=100) -> {name: {...}}  polyphenol / high-count flags
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import requests
from rdkit import Chem
from rdkit.Chem import FilterCatalog

# ----------------------------------------------------------------------------- PAINS
_pains_params = FilterCatalog.FilterCatalogParams()
for _cat in (FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_A,
             FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_B,
             FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_C):
    _pains_params.AddCatalog(_cat)
_PAINS = FilterCatalog.FilterCatalog(_pains_params)

# Known frequent-hitter substructures the PAINS catalog under-flags but the
# network-pharmacology literature repeatedly warns about (catechol / pyrogallol
# polyphenols). Used as a supplementary structural alert.
_POLYPHENOL_ALERTS = {
    "catechol": "c1cc(O)c(O)cc1",
    "pyrogallol": "c1cc(O)c(O)c(O)c1",
}


def pains_flags(smiles: str) -> Optional[list]:
    """Return list of matched PAINS/alert names for a SMILES ([] = clean, None = unparseable)."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    hits = [e.GetDescription() for e in _PAINS.GetMatches(mol)]
    for name, smarts in _POLYPHENOL_ALERTS.items():
        patt = Chem.MolFromSmarts(smarts)
        if patt is not None and mol.HasSubstructMatch(patt):
            hits.append(f"alert:{name}")
    return sorted(set(hits))


# ----------------------------------------------------------------------------- organism
_UNIPROT = "https://rest.uniprot.org/uniprotkb/{acc}.json?fields=organism_id,organism_name"
_HUMAN_TAXON = 9606


@lru_cache(maxsize=4096)
def _organism(acc: str) -> tuple:
    """(taxon_id, scientific_name) or (None, None) if unknown/unreachable."""
    if not acc:
        return (None, None)
    try:
        r = requests.get(_UNIPROT.format(acc=acc), timeout=20,
                         headers={"Accept": "application/json"})
        if r.status_code != 200:
            return (None, None)
        org = r.json().get("organism", {})
        return (org.get("taxonId"), org.get("scientificName"))
    except Exception:
        return (None, None)


def is_human(uniprot_id: str) -> Optional[bool]:
    """True if the accession is human, False if another organism, None if unknown."""
    taxon, _ = _organism(uniprot_id)
    if taxon is None:
        return None
    return taxon == _HUMAN_TAXON


def screen_targets(targets: list) -> tuple:
    """Partition target dicts (each with 'uniprot_id') into (kept_human, rejected).

    Rejected entries gain a 'reject_reason'. Unknown-organism entries are KEPT
    but tagged organism_status='unknown' for review (fail-open, not fail-closed).
    """
    kept, rejected = [], []
    for t in targets:
        acc = t.get("uniprot_id") or ""
        taxon, name = _organism(acc)
        rec = dict(t)
        if taxon is None:
            rec["organism_status"] = "unknown"
            kept.append(rec)
        elif taxon == _HUMAN_TAXON:
            rec["organism_status"] = "human"
            kept.append(rec)
        else:
            rec["organism_status"] = "nonhuman"
            rec["reject_reason"] = f"organism {name} (taxon {taxon}) != Homo sapiens"
            rejected.append(rec)
    return kept, rejected


# ----------------------------------------------------------------------------- promiscuity
def promiscuity_flags(compounds: dict, cap: int = 100) -> dict:
    """Flag compounds whose target count exceeds `cap` and/or carry PAINS alerts.

    `compounds` maps name -> {'smiles': ..., 'target_count': int}. Flagged
    compounds' E2 (annotation) hits must be corroborated at E0/E1 before counting
    toward hub scoring (CLAUDE.md Step 1 controls).
    """
    out = {}
    for name, c in compounds.items():
        n = c.get("target_count", len(c.get("targets", []) or []))
        pf = pains_flags(c.get("smiles", "")) or []
        over_cap = n > cap
        if over_cap or pf:
            out[name] = {
                "target_count": n,
                "over_promiscuity_cap": over_cap,
                "cap": cap,
                "pains": pf,
                "action": "E2 hits require E0/E1 corroboration before hub scoring",
            }
    return out
