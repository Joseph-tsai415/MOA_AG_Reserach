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
    route_feasibility    — delivery feasibility for the intended route
    enrichment_integrity — non-specific-umbrella + entity-vs-gene + engagement check
    lineage_audit        — recompute headline numbers; scored vs raw never conflated
    validation_roadmap   — falsifiable experiment plan + go/no-go Lead Assessment

v10 measured-data track (conditional — real expression data only):
    transcriptomics      — GEO -> pydeseq2 DE signature + L1000CDS2 reversal

v12 exposure kernel (every modality, route and formulation — not just topical/oral):
    exposure             — modality x route x formulation -> sourced ExposureProfile
                           (compartments / systemic / CNS, each with its evidence
                           tier) + target-tissue reachability for the Step-0
                           EXPOSURE_MISMATCH gate
    route_feasibility    — three-level delivery feasibility (as_is / dds_enabled /
                           not_deliverable, plus not_assessable) with rule sets
                           keyed by (modality, route), cited thresholds, and
                           approved-product precedence. The v11
                           topical_feasible/oral_feasible/assess/screen API is
                           preserved verbatim as a compatibility layer.
    provenance           — Step-0 gate, now modality-aware and stopping ONLY on a
                           mis-specified object of study: identity per modality
                           (InChIKey parent / INN+ChEMBL+UniProt+label / sequence+
                           backbone+transcript / cell+source+construct / MISEV items),
                           FORMULA_REF as a list of sourced composition variants, a
                           four-value indication status, and the Step-3 circularity
                           control spec. Verdicts: PASS / REFRAME / HALT /
                           EXPOSURE_MISMATCH / NEEDS_INPUT. Topical no longer HALTs —
                           it sets the exposure profile. The v11
                           validate_composition/classify_route/indication_plausibility/
                           provenance_gate API still works (2-tuple returns included).

v11.2 — the text primitives the gates depend on live here, NOT in per-run scripts.
Run folders (results/, reviews/) are regenerated output and are not version
controlled, so any helper left in one is lost. Two that had to be recovered:
    lineage_audit.normalize_text        — Private-Use-Area glyph mapping. Symbol-font
                                          label PDFs encode "4-8 weeks" with a PUA dash;
                                          raw extraction reads "48 weeks" silently.
    citation_grounding.check_reference_entry
                                        — the rendered reference entry vs its resolved
                                          metadata; catches a real PMID dressed with a
                                          fabricated author/journal/volume/DOI.
"""
from . import (  # noqa: F401
    benchmark_recall,
    citation_grounding,
    directionality,
    enrichment_integrity,
    evidence_schema,
    exposure,
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
    "exposure",
]
__version__ = "0.12.0"
