# Reporting-standards catalogue — essential reference for report QA

> **Purpose.** The single authoritative reference the **`report-qa` agent** (`.claude/agents/report-qa.md`) reads when reviewing a deliverable. It keeps the detailed checklists **out of `CLAUDE.md`** (which only points here) and out of the agent prompt (which carries a condensed fallback). This file lives in the **`reporting-standards` skill**; the official source checklists are bundled alongside it — `PRISMA_2020_checklist.docx` in this folder and the ARRIVE / STROBE / CONSORT / STARD / TRIPOD+AI / CARE / CHEERS / SPIRIT files in `sources/`.
>
> **How to use.** Detect the report type → apply the matching standard's items **plus** the project house-rules overlay (bottom). Mark any inapplicable item **N/A with a one-line reason** — never silently skip. Verify the exact current wording at the **EQUATOR Network**: <https://www.equator-network.org/reporting-guidelines/>.

---

## 1. Report-type router — which standard applies

| If the report is… | Primary standard | Add |
|---|---|---|
| **Network-pharmacology / MOA / drug-repurposing** (this pipeline, `results/…`) | **WFCMS 2021** network-pharmacology guidance (reliability · standardization · rationality) + PRISMA-style record-flow | GRADE (via tiers), AMSTAR-2 critical items |
| **Systematic review / literature synthesis** (`reviews/…`) | **PRISMA 2020** (+ PRISMA-S search, PRISMA-ScR scoping) | AMSTAR-2, ROBIS, GRADE |
| **Meta-analysis of observational studies** | PRISMA 2020 + **MOOSE** | GRADE |
| **Animal / in-vivo experiment, or a proposed in-vivo validation plan** | **ARRIVE 2.0 — Essential 10** | 3Rs / ethics, GRADE |
| **Randomised controlled trial** | **CONSORT 2010/2025** (+ CONSORT-AI) | — |
| **Observational study** (cohort / case-control / cross-sectional) | **STROBE** | subtype extension |
| **Diagnostic test-accuracy study** | **STARD 2015** | GRADE |
| **Clinical / ML prediction model** | **TRIPOD+AI** | PROBAST (RoB) |
| **LLM / generative-AI study** | **TRIPOD-LLM** · **MI-CLAIM** · **CLAIM** (imaging) | — |
| **Trial / experiment protocol** | **SPIRIT** (+ SPIRIT-AI) | — |
| **Case report** | **CARE** | — |
| **Qualitative study** | **COREQ** / **SRQR** | — |
| **Health-economic evaluation** | **CHEERS 2022** | — |
| **Risk-of-bias of included studies** | **RoB 2** (RCTs) · **ROBINS-I** (non-randomised) · **ROBIS** (the review) | — |
| **Certainty of the evidence body** | **GRADE** | — |

---

## 2. PRISMA 2020 — systematic reviews (27 items, 7 sections)

*Source: Page MJ et al. BMJ 2021;372:n71 (CC BY 4.0). Full official checklist: `PRISMA_2020_checklist.docx`.*

- **Title** — 1 identify as a systematic review.
- **Abstract** — 2 structured abstract (PRISMA-for-Abstracts, 12 items).
- **Introduction** — 3 rationale · 4 explicit objectives/questions.
- **Methods** — 5 eligibility criteria · 6 information sources **+ last-searched dates** · 7 full search strategy (filters/limits) · 8 selection process · 9 data-collection process · 10a outcomes / 10b other variables · 11 risk-of-bias method · 12 effect measures · 13a–f synthesis methods (eligibility grouping, data prep, tabulation, synthesis model + heterogeneity, causes of heterogeneity, sensitivity) · 14 reporting-bias method · 15 certainty method.
- **Results** — 16a record-flow identification→inclusion (**flow diagram**) / 16b excluded-but-plausible studies with reasons · 17 study characteristics · 18 risk of bias per study · 19 individual-study results · 20a–d synthesis results (+ heterogeneity, sensitivity) · 21 reporting biases · 22 certainty per outcome.
- **Discussion** — 23a interpretation · 23b limits of evidence · 23c limits of process · 23d implications.
- **Other** — 24 registration & protocol · 25 support/funding · 26 competing interests · 27 **availability of data, code & materials**.

**Extensions:** PRISMA-S (search reporting) · PRISMA-ScR (scoping reviews) · MOOSE (meta-analysis of observational studies).

---

## 3. ARRIVE 2.0 — animal / in-vivo research

*Kilkenny/Percie du Sert et al., PLOS Biol 2020. Use for any in-vivo experiment described **or proposed** (validation roadmaps).*

- **Essential 10:** 1 study design · 2 **sample size** (+ how determined) · 3 inclusion/exclusion criteria · 4 randomisation · 5 blinding/masking · 6 outcome measures · 7 statistical methods · 8 experimental animals (species, strain, **sex**, age, source) · 9 experimental procedures (what/where/when/why, reproducibly) · 10 results with variability + n per group.
- **Recommended 11:** abstract · background · objectives · ethical statement · housing & husbandry · animal care & monitoring · interpretation/scientific implications · generalisability/translation · protocol registration · data access · declaration of interests.

---

## 4. STROBE — observational studies (22 items)

Design named in title/abstract (1) · background/objectives (2–3) · **design + setting + eligibility** (4–6) · variables + potential **confounders** (7) · data sources/measurement + **bias** (8–9) · **study size** (10) · statistical methods incl. confounding, subgroups, missing data (12) · participant flow (13) · descriptive + outcome data with **precision** (14–16) · key results, **limitations, generalisability** (18–21) · funding (22). 18 items common to all three designs; 4 design-specific.

## 5. CONSORT 2010/2025 — randomised trials (25 items + flow)

Trial design (3) · eligibility + settings (4) · interventions (5) · **pre-specified primary/secondary outcomes** (6) · **sample-size calculation** (7) · randomisation: sequence generation, **allocation concealment**, implementation (8–10) · **blinding** (11) · statistical methods (12) · **participant flow diagram** (13) · baseline table (15) · outcomes + estimated effect size & precision (17) · **harms** (19) · limitations (20) · **registration** (23) · protocol access (24) · funding (25). *CONSORT-AI adds AI-intervention items.*

## 6. Other standards (apply when the type matches)

- **STARD 2015** — diagnostic accuracy: reference standard, blinding, 2×2 counts, flow.
- **TRIPOD+AI** (27) — prediction models: source of data; participants; **predictors + outcome defined a priori & assessed blind**; sample size; missing-data handling; **model development + internal/external validation**; performance = **discrimination + calibration**; **fairness/subgroup**; data & code availability. *TRIPOD-LLM (19 items/50 subitems) for LLM studies; MI-CLAIM / CLAIM for clinical & imaging AI.*
- **SPIRIT** — trial/experiment protocols: objectives, design, eligibility, interventions, outcomes, sample size, allocation, blinding, data management, monitoring. (+ SPIRIT-AI.)
- **CARE** — case reports: timeline, diagnostic assessment, intervention, outcomes, patient perspective.
- **CHEERS 2022** — economic evaluations: perspective, comparators, time horizon, discount rate, outcomes, model assumptions, uncertainty.
- **COREQ (32) / SRQR** — qualitative: research team & reflexivity, sampling, data collection, analysis, findings with quotations.

---

## 7. Certainty & risk-of-bias appraisal

**GRADE — certainty of the evidence.** Start High (experimental) or Low (observational); **down-rate** one/two levels per domain → **High / Moderate / Low / Very-low**:

| Domain | Down-rate when… |
|---|---|
| Risk of bias | study limitations (here: promiscuity / single-assay / interference-prone assay) |
| Inconsistency | unexplained heterogeneity / directional conflict |
| Indirectness | non-human organism, wrong route/compartment, tumour-vs-homeostatic or cross-tissue extrapolation |
| Imprecision | wide CI, few events; here: single source, small overlap |
| Publication/reporting bias | a `FETCH_FAILED`, a stated coverage gap, selective results |

**Evidence-tier ↔ GRADE bridge** (project mapping): **E0 Measured ≈ High** · **E1 Literature (grounded) ≈ Moderate** · **E2 Annotation ≈ Low** (corroboration only) · **E3 Predicted ≈ Low/Very-low** (hypothesis; tag *"no prior report; refutable by [assay]"*) · **E4 Inferred ≈ Very-low** (flag only). Report each claim at the **lowest** certainty any domain forces.

**AMSTAR-2** — appraises SR conduct; 7 **critical** items: a-priori protocol/methods · comprehensive search · **justified study exclusions** · **RoB assessed** · appropriate synthesis · **RoB used in interpretation** · **publication bias considered**. Any critical flaw ⇒ confidence *low / critically-low*. (**ROBIS** is the alternative SR risk-of-bias tool.)

**Cochrane risk-of-bias tools:** **RoB 2** (RCTs) — 5 domains: randomisation, deviations from intended interventions, missing outcome data, outcome measurement, selection of reported result. **ROBINS-I** (non-randomised interventions) — + confounding, participant selection, intervention classification. **PROBAST** — prediction-model RoB.

---

## 8. Project house-rules overlay (ALWAYS applied, on top of the type-matched standard)

Even for a CONSORT/STROBE report, these keep this project honest — the `report-qa` agent runs them every time:

1. **Evidence tier ↔ GRADE** on every headline claim (§7); no E2/E3/E4 as established fact.
2. **Citation grounding** — PMID/DOI resolves **and** abstract supports the *specific* sentence; no orphan/unused refs; zero fabrication/misattribution.
3. **Number / lineage reconciliation** — every stated count == the actual row count; raw/gated ≠ scored containers.
4. **Specificity / risk-of-bias** — overlap p ≤ 0.05 **and** z_c ≤ −0.15 (or a HALT), decoy control, promiscuity/interference demotion (MOA); per-source causal grading (reviews).
5. **Directionality non-circularity** — from data or a falsifiable hypothesis + assay; not "every target conveniently therapeutic"; conflict log present.
6. **Exposure realism** — no systemic claim for a topical/external object of study.
7. **No-silent-zero** — an advertised source must have returned >0, else marked `FETCH_FAILED`.
8. **Figure completeness** — colorbar where colour encodes data, category legend, un-clipped title; verified by reading the PNG back.
9. **Honest limitations + Bottom line** — where direction/efficacy is unmeasured, say so; report opens & closes with a plain verdict + cheapest decisive experiment + kill criterion.
10. **Report voice** — no pipeline-version / module-name / benchmark branding in the report body (methods footer only).

---

## 9. Sources

- PRISMA 2020 — Page MJ et al., *BMJ* 2021;372:n71 · <https://www.prisma-statement.org/>
- ARRIVE 2.0 — Percie du Sert N et al., *PLoS Biol* 2020;18(7):e3000410 · <https://arriveguidelines.org/>
- STROBE — von Elm E et al., 2007 · <https://www.strobe-statement.org/>
- CONSORT 2010 / 2025 — Schulz KF et al.; Hopewell S et al. 2025 · <https://www.consort-spirit.org/>
- STARD 2015 · SPIRIT 2013 · CARE · CHEERS 2022 · COREQ / SRQR — via EQUATOR
- TRIPOD+AI — Collins GS et al., *BMJ* 2024;385:e078378 · TRIPOD-LLM — *Nat Med* 2024
- GRADE — Guyatt GH et al., *J Clin Epidemiol* series · <https://www.gradeworkinggroup.org/>
- AMSTAR-2 — Shea BJ et al., *BMJ* 2017;358:j4008 · Cochrane RoB 2 / ROBINS-I — <https://methods.cochrane.org/>
- **EQUATOR Network (master catalogue):** <https://www.equator-network.org/reporting-guidelines/>
