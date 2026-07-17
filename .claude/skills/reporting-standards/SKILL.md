---
name: reporting-standards
description: >-
  Academic reporting-standards catalogue with the official source checklists bundled — PRISMA 2020
  (systematic reviews), ARRIVE 2.0 (animal/in-vivo), STROBE (observational), CONSORT 2025 (RCTs),
  SPIRIT 2025 (protocols), STARD 2015 (diagnostic accuracy), TRIPOD+AI (prediction/ML models), CARE
  (case reports), CHEERS 2022 (economic), plus GRADE / AMSTAR-2 / Cochrane RoB appraisal. Use when
  writing, reviewing, or QA-ing any scientific report or manuscript: pick the right standard for the
  study type and check it item-by-item. Backs the report-qa agent.
---

# Reporting standards — catalogue + official source checklists

Use this skill to (1) **route** a report to the correct reporting guideline by study type, (2) **check** it against that guideline's items, and (3) **grade** certainty (GRADE) and **appraise** conduct (AMSTAR-2 / Cochrane RoB).

**How to use:**
1. Read `references/REPORTING_STANDARDS.md` — the report-type router, condensed items per standard, the evidence-tier↔GRADE bridge, and the project house-rules overlay.
2. For a standard's **authoritative full checklist**, open its bundled official source below (or the official URL in the catalogue's *Sources* section).

## Bundled official source checklists — `references/sources/`

| Standard | Study type | Bundled file |
|---|---|---|
| **PRISMA 2020** | systematic reviews / evidence syntheses | `references/PRISMA_2020_checklist.docx` |
| **ARRIVE 2.0** | animal / in-vivo experiments | `references/sources/ARRIVE_2.0_guidelines.pdf` |
| **STROBE** | observational (cohort/case-control/cross-sectional) | `references/sources/STROBE_checklist_v4_combined.pdf` |
| **CONSORT 2025** | randomised controlled trials | `references/sources/CONSORT_2025_checklist.pdf` |
| **SPIRIT 2025** | trial / experiment protocols | `references/sources/SPIRIT_2025_checklist.pdf` |
| **STARD 2015** | diagnostic test-accuracy | `references/sources/STARD_2015_checklist.pdf` |
| **TRIPOD+AI** | clinical / ML prediction models | `references/sources/TRIPOD+AI_checklist.pdf` |
| **CARE** | case reports | `references/sources/CARE_checklist.pdf` |
| **CHEERS 2022** | health-economic evaluations | `references/sources/CHEERS_2022_checklist.pdf` |
| GRADE · AMSTAR-2 · ROBIS · Cochrane RoB 2 / ROBINS-I | certainty & risk-of-bias appraisal | not bundled (web tools / handbooks) — official URLs in the catalogue |

Source files were downloaded from the official sites (arriveguidelines.org, equator-network.org, consort-spirit.org, tripod-statement.org, care-statement.org) — see `references/REPORTING_STANDARDS.md` §9 for citations and licences. Verify the current version at the **EQUATOR Network** (<https://www.equator-network.org/reporting-guidelines/>) before relying on any item.

The **`report-qa` agent** (`.claude/agents/report-qa.md`) uses this skill to QA the project's deliverables.
