"""moa_lib — shared reusable modules for the MOA-AG pipeline (v9/v10/v11).

Governing policy: CLAUDE.md §3 (Governing Scientific Policy). These modules enforce,
in code, the rules that CLAUDE.md documents as prose.

v9 knowledge-driven core (P1-P4):
    evidence_schema      — evidence tiers (E0-E4/REJECT) + confidence scoring
    promiscuity_filter   — organism + PAINS + promiscuity cap + E0 assay scrutiny (v11)
    citation_grounding   — resolve PMID/DOI + verify the claim is supported
    specificity_controls — permutation p + network proximity d_c/z_c + decoy
    directionality       — ChEMBL action_type + conflict log + circularity
    benchmark_recall     — recall/precision vs ground truth + run comparison

v11 reliability upgrade (motivated by the Session-9 review — provenance, exposure,
lineage, enrichment integrity, and a falsifiable output):
    provenance           — Step-0 formula composition / route / indication gate
    route_feasibility    — drug-likeness FOR THE INTENDED ROUTE (topical/oral)
    enrichment_integrity — non-specific-umbrella + entity-vs-gene + engagement check
    lineage_audit        — recompute headline numbers; scored vs raw never conflated
    validation_roadmap   — falsifiable experiment plan + go/no-go Lead Assessment

v10 measured-data track (conditional — real expression data only):
    transcriptomics      — GEO -> pydeseq2 DE signature + L1000CDS2 reversal
"""
from . import (  # noqa: F401
    benchmark_recall,
    citation_grounding,
    directionality,
    enrichment_integrity,
    evidence_schema,
    lineage_audit,
    promiscuity_filter,
    provenance,
    route_feasibility,
    specificity_controls,
    transcriptomics,
    validation_roadmap,
)

__all__ = [
    "evidence_schema", "promiscuity_filter", "citation_grounding", "specificity_controls",
    "directionality", "benchmark_recall",
    "provenance", "route_feasibility", "enrichment_integrity", "lineage_audit", "validation_roadmap",
    "transcriptomics",
]
__version__ = "0.11.0"
