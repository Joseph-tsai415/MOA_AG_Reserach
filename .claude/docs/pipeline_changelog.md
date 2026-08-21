# Pipeline methodology changelog

*On-demand reference (NOT auto-loaded). Pointer lives in CLAUDE.md → Versioning Convention.*

This is the history of the **methodology**, not of the software. It records what
changed between pipeline generations and, more usefully, **which real failure
motivated each change** — a gate is easier to apply correctly when you know the
defect it exists to catch.

A run does **not** need this file. A run needs its pipeline version stamped in the
report's methods footer; that is what makes two runs of the same compound/disease
comparable. Read this only when you need to know *why* a control exists, or when
bumping the version.

**Current: v11.2.** Bump only when the governing policy or a step's methodology
changes materially, then add a row here.

| Version | Date | Summary |
|---|---|---|
| **v11.2** | 2026-07-31 | Extended the §3 evidence burden to **non-MOA `reviews/` deliverables** (literature syntheses, domain briefings) with a required `data/` + `scripts/` + `figures/` shape — see §8. Motivated by a HER2-breast-cancer CRA briefing that shipped as a bare `.md` + `.pdf`: unauditable and unreproducible. Retrofitting the gates immediately caught **two real defects that prose review had missed** — (1) a *fabricated attribution* (PMID 37770765 dressed with a wrong author, journal, volume and DOI; the reference list alone would have passed, only claim-level grounding caught it), and (2) a *transcription error* (a symbol-font label PDF encodes "4–8 weeks" with a Private-Use-Area dash; extraction read it as "48 weeks" and that number reached the report). Adds the PUA-normalisation rule for label PDFs and the figures-derived-from-`data/` rule. **No change to Steps 0–5.** |
| **v11.1** | 2026-07-17 | Added a **Final-report quality gate** (§3): every deliverable is QA'd before shipping by a read-only **`report-qa` agent** (`.claude/agents/report-qa.md`) running as the orchestrator's QA teammate — it routes by report type to the matching EQUATOR standard (**PRISMA 2020 / ARRIVE 2.0 / STROBE / CONSORT / TRIPOD+AI / …**), grades certainty with **GRADE**, appraises conduct with **AMSTAR-2 / Cochrane RoB**, and overlays the project house rules (evidence tiers ≈ GRADE, specificity ≈ risk-of-bias, citation grounding, lineage audit). Fix-until-**SHIP** loop; writes `report_qa_review.md`. Detailed criteria + bundled official source checklists live in the **`reporting-standards` skill** (`.claude/skills/reporting-standards/`) — **no new Steps 0–5 methodology, and `CLAUDE.md` stays light**. |
| **v11.0** | 2026-07-14 | Added **Step 0 — Provenance & Plausibility Gate** and four reliability upgrades after the Session-9 external review: (1) **provenance** — validate authentic formula composition, **route of administration**, and indication plausibility before Steps 1–5 (a topical cosmetic mask must not be modelled as a systemic drug); (2) **route-feasibility** drug-likeness *for the intended route* (skin permeation vs Lipinski) so delivery-implausible constituents can't anchor a mechanism; (3) **data-lineage integrity** — every headline number self-verifies, raw vs scored sets never share a container (fixes the 81-vs-14 leak); (4) **enrichment integrity** — non-specific-umbrella suppression, entity-vs-gene reconciliation, engagement-vs-spillover check (fixes "17 of 14" and the IL-4/IL-13 artefact). Extends the PAINS gate to **E0 by assay type** (AlphaScreen/qHTS interference), makes GWAS/L1000 **no-silent-zero**, and makes the deliverable a **route-matched Validation Roadmap + go/no-go Lead Assessment**. New modules: `provenance`, `route_feasibility`, `enrichment_integrity`, `lineage_audit`, `validation_roadmap`. |
| **v10.0** | 2026-07-13 | Added the **Transcriptomics Track** (first measured-data layer): data-driven disease signature from patient RNA-seq (`geo-database` → `pydeseq2`; optional single-cell `scanpy`) that **augments** List B, plus **connectivity-map signature reversal** in Step 4 as a measured efficacy signal. Conditional — runs when a suitable expression dataset is available, else documented as absent. Builds on (does not replace) the v9 framework. |
| **v9.0** | 2026-07-13 | Added **Governing Scientific Policy**: evidence tiers (E0–E4 / REJECT), specificity controls (permutation *p*, network proximity z_c ≤ −0.15, decoy disease), citation-grounding gate, data-derived directionality + L1/L2/L3 validation, per-step mandatory controls, and a significance-based HALT. Motivated by the session8 reliability audit (fabricated citations, PAINS contamination, no specificity test). |
| v8 | ≤ 2026-03 | Baseline 5-step network-pharmacology pipeline (Drug→Target · Disease→Gene · Intersection · Pathway · Hypothesis); Qibai San / Atopic Dermatitis sessions. |

## Notes that outlive their version

- **Session 8 predates the versioning policy** and ran under v8 methodology — do
  not retro-label it.
- **Retired:** `benchmark_recall.py` (the v8-vs-v9 recall/precision "benchmark").
  It compared pipeline versions, not biology, so it does not inform a research
  decision. The file remains in `moa_lib` for methods work but is **not** a Step-5
  control and produces **no** report section.
- **Why the version is stamped but never branded.** Sessions 9 and 10 analysed the
  same compound and the same disease and reached different framings — the whole
  difference was the Step-0 provenance gate, not new data. Without the stamp those
  two reports are an unexplained contradiction. With it, they are a methodology
  change. That is the entire reason the version is recorded; it is also why it
  belongs in the methods footer and nowhere else (CLAUDE.md §5, *Report voice*).
