"""moa_lib — shared reusable modules for the MOA-AG pipeline (v9/v10).

Governing policy: CLAUDE.md §3 (Governing Scientific Policy). These modules
enforce, in code, the rules that CLAUDE.md documents as prose:

    evidence_schema     — evidence tiers (E0-E4/REJECT) + confidence scoring
    promiscuity_filter  — organism filter + PAINS + promiscuity cap        (P1)
    citation_grounding  — resolve PMID/DOI + verify the claim is supported (P1)
    specificity_controls— permutation p + network proximity d_c/z_c        (P2, TODO)
    directionality      — ChEMBL action_type + conflict log                (P3, TODO)
    benchmark_recall    — recall/precision vs ground truth                 (P4, TODO)
    transcriptomics     — GEO -> pydeseq2 DE + L1000 reversal              (v10, TODO)

Only evidence_schema, promiscuity_filter and citation_grounding are implemented
so far (the P1 guardrails). The rest are stubs to be filled in per the rollout.
"""
from . import evidence_schema  # noqa: F401

__all__ = ["evidence_schema"]
__version__ = "0.1.0"
