"""Step-4 guardrail (v11) — pathway-enrichment integrity.

Session-9 review, the serious one: Figure 4 reported Reactome enrichment "for the 14
hubs" but printed found = 17 for "Immune System" (you cannot find 17 of 14). Root
cause: Reactome `entities.found` counts mapped protein entities/isoforms, not input
genes, so it can exceed the input-gene count — printing it as "genes found" is the
integrity failure. And the "convergence on IL-4/IL-13 signalling" headline is an
ARTEFACT: the 14 hubs are generic downstream effectors (AKT1, RELA, BCL2, CASP3,
PTGS2, CCL2, HMOX1, MMP7) that populate every giant immune umbrella; NONE of the
IL-4/IL-13 *defining* genes (IL4, IL13, IL4R, IL13RA1, STAT6, JAK) is in the set, so
enrichment is not evidence of pathway engagement.

    is_nonspecific(name)                         -> bool
    engagement_supported(name, hub_genes)        -> (bool, defining_present)
    annotate(pathways, hub_genes, n_input)       -> [annotated pathway dicts]
    integrity_flags(pathways, hub_genes, n_input) -> [warning strings]
"""
from __future__ import annotations
import re

# Giant top-level Reactome umbrellas — light up for ANY inflammatory/large gene set,
# so they carry no specificity and must be suppressed or flagged non-informative.
NONSPECIFIC = [
    "immune system", "signaling by interleukins", "cytokine signaling in immune system",
    "innate immune system", "adaptive immune system", "disease", "metabolism",
    "metabolism of proteins", "metabolism of rna", "developmental biology", "gene expression",
    "signal transduction", "cellular responses to stimuli", "cellular responses to stress",
    "post-translational protein modification", "hemostasis", "programmed cell death",
    "vesicle-mediated transport", "membrane trafficking", "transport of small molecules",
]

# Genes that DEFINE engagement of specific pathways (presence required to call it
# engagement rather than downstream-effector spillover).
DEFINING_GENES = {
    "interleukin-4 and interleukin-13 signaling":
        {"IL4", "IL13", "IL4R", "IL13RA1", "IL13RA2", "IL2RG", "STAT6", "JAK1", "JAK2", "JAK3", "TYK2"},
    "interleukin-10 signaling": {"IL10", "IL10RA", "IL10RB"},
    "interleukin-6 signaling": {"IL6", "IL6R", "IL6ST", "JAK1", "JAK2", "STAT3"},
    "signaling by jak-stat": {"JAK1", "JAK2", "JAK3", "TYK2", "STAT1", "STAT3", "STAT6"},
}


def is_nonspecific(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(n == u or u in n for u in NONSPECIFIC)


def engagement_supported(name: str, hub_genes) -> tuple:
    n = (name or "").strip().lower()
    hub = {g.upper() for g in hub_genes}
    for key, defining in DEFINING_GENES.items():
        if key in n:
            present = sorted(defining & hub)
            return (bool(present), present)
    return (None, [])   # no defining-gene list for this pathway → undeterminable


def annotate(pathways: list, hub_genes: list, n_input: int) -> list:
    """Return pathways with integrity annotations added (does not drop; caller decides)."""
    out = []
    for p in pathways:
        raw_found = p.get("found") or 0
        gene_found = min(raw_found, n_input)          # gene-level cap (entities != genes)
        eng, present = engagement_supported(p.get("name", ""), hub_genes)
        out.append({**p,
                    "n_input_genes": n_input,
                    "genes_found_capped": gene_found,
                    "entity_inflation": raw_found > n_input,   # found > input ⇒ entity/isoform multiplicity
                    "nonspecific_umbrella": is_nonspecific(p.get("name", "")),
                    "engagement_supported": eng,               # True/False/None
                    "defining_genes_present": present,
                    "display": f"{gene_found} of {n_input} input genes"})
    return out


def integrity_flags(pathways: list, hub_genes: list, n_input: int) -> list:
    ann = annotate(pathways, hub_genes, n_input)
    flags = []
    if any(a["entity_inflation"] for a in ann):
        bad = [f"{a['name']} (raw found {a['found']})" for a in ann if a["entity_inflation"]][:5]
        flags.append(f"ENTITY-INFLATION: {len(bad)}+ pathways report more 'found' than the {n_input} "
                     f"input genes (Reactome counts entities/isoforms, not genes) — report as "
                     f"'X of {n_input} input genes', e.g. {', '.join(bad)}")
    ns = [a["name"] for a in ann if a["nonspecific_umbrella"]]
    if ns:
        flags.append(f"NON-SPECIFIC UMBRELLAS in top results ({len(ns)}): {', '.join(ns[:5])} — these "
                     f"enrich for any inflammatory set; do not headline them")
    for a in ann:
        if a["engagement_supported"] is False:
            flags.append(f"ARTEFACT RISK: '{a['name']}' enriched but NONE of its defining genes are in the "
                         f"hub set — this is downstream-effector spillover, NOT pathway engagement; do not "
                         f"claim the compound engages this pathway")
    return flags


if __name__ == "__main__":
    hub = ["AIFM1", "AKT1", "ALDH1A1", "BCL2", "CASP3", "CCL2", "CDH1", "COL3A1",
           "H2AX", "HMOX1", "MMP7", "PTGS2", "RELA", "SOAT1"]
    pw = [{"name": "Immune System", "found": 17, "total": 3033, "fdr": 6e-6},
          {"name": "Interleukin-4 and Interleukin-13 signaling", "found": 10, "total": 211, "fdr": 1.7e-10},
          {"name": "Signaling by Interleukins", "found": 12, "total": 646, "fdr": 1e-8}]
    for f in integrity_flags(pw, hub, 14):
        print("FLAG:", f)
