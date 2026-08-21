# Research Questions — Skin→Gut Project

> **Scope:** three parallel literature/hypothesis reviews behind one experimental system
> **Last updated:** 2026-07-16

---

## Project context

One project, three questions:

- **Q3** — the biological premise: does skin inflammation act on the intestine, and by what mechanism?
- **Q2** — the expected phenotype and its published benchmarks.
- **Q1** — the method to characterise the gut immune compartment driving it.

**The experimental system:**

- **Model:** skin-specific **Regnase-1 (Zc3h12a / MCPIP1) knockout** — deletion intended to be restricted to skin.
- **Phenotype:** marked **small-intestinal elongation** — the small intestine is **~5–10 cm longer** than wild-type littermates; the colon is **~1–2 cm longer or shorter**, varying between animals. Against a typical mouse small-intestine length on the order of 30–40 cm, +5–10 cm is a large (~15–30%) elongation.
- **Goal:** characterise the gut **mucosal** immune compartment (lamina propria + intraepithelial) that accompanies the phenotype (Q1), benchmark the elongation magnitude against published remodeling models (Q2), and build a mechanistic bridge for a skin-restricted lesion producing an intestinal **growth** phenotype (Q3).

Regnase-1 is an RNase that degrades the mRNAs of pro-inflammatory cytokines (IL-6, IL-12/IL-23, IL-17-axis transcripts) via 3′UTR stem-loops; its loss stabilises those transcripts and drives inflammation. A skin-restricted knockout that nonetheless produces a striking *intestinal* phenotype makes **systemic cytokine spillover** the leading mechanistic hypothesis to prioritise.

**Phase:** mouse now; human in a later phase. Species scoping below reflects this.

## Scope

These are **literature-grounded evidence synthesis** tasks (`CLAUDE.md` §1), not runs of the compound × disease network-pharmacology pipeline — none names an active ingredient, so a literal pipeline run would halt at Step 1 with an empty List A. Output shape is question-specific tables, not the `step1_`–`step5_` structure. They live under `reviews/`, not `results/`.

**One reframed exception (Q3 Arm B):** the step1–5 *reasoning skeleton* — evidence-tiered A∩B∩pathway integration, specificity gates, citation grounding, and the E3-predicted/hypothesis tier that admits genuinely unpublished mechanisms — is repurposed with List A and List B redefined (skin-derived mediators / intestinal-growth drivers). It remains a hypothesis-generation exercise, so it also lives under `reviews/`.

## Shared rules

1. Every quantitative value traces to a real paper with a **PMID/DOI**, sourced from **full text** where the number lives in Methods/Results rather than the abstract.
2. Any field not reported in the source is written **"not reported"** — never estimated, interpolated, or inferred from a related paper.
3. Blank cells are kept, not dropped — they show what nobody has measured.
4. Where papers disagree, report the disagreement rather than picking a winner.
5. **Figures count as source data.** Where a wanted number (a CD45⁺ population percentage, a morphometry value) appears only in a flow plot, gating figure, or micrograph, read it off the figure and mark it figure-derived.
6. **PDF deliverable (final step).** When a review's markdown is finalised, render it to a fixed-house-style PDF with the **`report-pdf` skill** (single-file mode): `python .claude/skills/report-pdf/scripts/build_report_pdf.py --report reviews/{review}/{review}.md --title "{question as title}" --footer "{plain one-liner}" --out result.pdf --verify`. One shared builder for every deliverable — do **not** hand-roll a per-review `make_pdf.py`. Always pass `--verify` and read back a `_pdf_preview/page_*.png` to catch glyph/tofu boxes.

---

## Q1 — Mouse gut immune-cell isolation (mucosa: lamina propria + intraepithelial)

Summarize the published literature on mouse intestinal immune-cell isolation, focused on the **mucosa — lamina propria (LP) and intraepithelial lymphocytes (IEL)** as separate preparations, since these compartments hold the majority of gut immune cells. Cover small intestine and colon separately where the literature distinguishes them.

- **Enzyme comparison — Collagenase VIII, Collagenase D, Liberase TL** on: cell yield per unit tissue, viability, and preservation of each immune population. Critically, report **which surface epitopes each enzyme cleaves or degrades** — if a digestion destroys a marker in the panel, that is a headline finding. (Liberase TL is reported to cleave **CD8** and partially **CD19** in mouse gut and to drop **CD4** in human gut — check any digestion against the intended flow panel.)
- **CD45⁺ composition** — steady-state percentages of **T cells, B cells, macrophages, monocytes, neutrophils, eosinophils as % of CD45⁺**, per compartment and per segment, noting mouse strain, age, and sex where given, and the direction of shift under intestinal inflammation where reported. Where a percentage appears only in a gating figure, extract it and mark it figure-derived.
- **Marker panels** — the flow cytometry markers used to define each population, flagging where papers disagree on a definition.
- **Alternatives** — non-enzymatic and hybrid methods: mechanical dissociation, EDTA/DTT epithelial stripping (to release IEL), density gradients.
- **Recommendation** — for a mucosal phenotype, which enzyme and protocol to use, and what trade-off is accepted.

**Design note.** Canonical mouse "LP" protocols remove the epithelium (EDTA/DTT) and digest the entire remaining wall — LP + submucosa + muscularis externa + serosa — without naming the muscularis. A plain "LP" CD45⁺ breakdown is therefore not a pure mucosal read; a clean mucosal characterisation is best served by handling **LP and IEL as separate preparations**.

**Deliverable:** `reviews/q1_gut_immune_isolation/`

---

## Q2 — Animal models of intestinal remodeling (small-intestinal elongation / overgrowth)

Summarize published animal models showing **increased small-intestinal length, increased bowel-wall thickness, or layer-specific hypertrophy** — growth/overgrowth phenotypes — prioritising those whose magnitude is comparable to a **~5–10 cm small-intestine elongation vs wild-type**. Include developmental, genetic, regenerative/adaptive, and inflammatory models that meet that bar.

- **Benchmark against the model in hand** — state each model's magnitude next to the reference phenotype (**small intestine +5–10 cm; colon ±1–2 cm**) so the comparison is explicit; give absolute values **and** % change vs control where both are reported.
- **Contrast set** — a compact block of **colon-shortening/atrophy** models (colitis, and colitis + genetic modifier) purely as a magnitude yardstick (typical colitis colon shortening is ~1–2 cm; a genetic modifier often adds ~1 cm, cancels it, or does nothing).
- **Species** — mouse is primary; rat, pig, and zebrafish go in a separate secondary table, included only where they document a phenotype mouse models don't.
- **Table columns:** Animal/model · Gene/pathway · SI length · Colon length · Villus height · Crypt depth · Mucosal thickness · Submucosal thickness · Inner circular muscle · Outer longitudinal muscle · Total wall thickness · **How length/thickness was measured** · **n per group** · Main phenotype/mechanism · Reference (journal, year, PMID).

Length is highly sensitive to fixed vs fresh tissue and to tension during measurement — the measurement-method column is what makes the numbers comparable.

**Deliverable:** `reviews/q2_intestinal_remodeling/`

---

## Q3 — Skin inflammation → gut

Skin-restricted Regnase-1 loss producing intestinal elongation is the reverse of the well-studied gut→skin axis, and the specific skin→gut **growth** mechanism is unpublished. The question runs as two complementary arms.

> **EV-route verification databases (conditional — only when the extracellular-vesicle route is being pursued).** The EV route is a *secondary* candidate here (ranked below cytokine spillover and immune-cell trafficking). **If — and only if — a skin-derived EV/exosome mechanism is on the table**, corroborate EV-cargo claims against curated exosome repositories rather than asserting them:
> - **ExoCarta** (`exocarta.org`) — manually curated small-EV / exosomal cargo (~119k protein, ~15.9k RNA, ~3.9k lipid entries; 1,249 sEV studies; MISEV/ISEV-compliant). Downloadable flat files (protein/mRNA, miRNA, lipid, top-100); importable into FunRich for enrichment.
> - **Vesiclepedia** (`microvesicles.org`) — broader: all EV subtypes + extracellular particles (~567k protein, ~50k RNA entries).
> - **exoRBase** — human body-fluid EV **long-RNAs** from RNA-seq; use if circulating-EV RNA-seq for the KO becomes available.
>
> **Role = corroboration only, not discovery.** A hit means "this molecule has been *observed* in exosomes" — it does **not** establish a functional skin→gut bridge. Under the evidence tiers it is annotation-grade (≈ **E2**) support: it can raise convergence for an EV-cargo claim but never stands alone, and never upgrades the EV route above the cytokine-spillover lead without independent functional evidence (EV depletion, labelled-EV transfer, etc.). Access is via the **`exocarta-database` skill** (`.claude/skills/exocarta-database/`) — invoke it only when the EV route is actually in play; these are web/flat-file resources (no REST API). Never cite an ExoCarta entry as proof of mechanism.

### Arm A — Literature synthesis

What is *published* on skin→gut communication.

- **Mouse/animal mechanism table:** Model (including skin-specific genetic models: K14-/K5-driven, filaggrin-null, **Regnase-1/Zc3h12a and related RNA-decay / innate-inflammation regulators**) · Skin phenotype · Intestinal phenotype observed (**flag any intestinal length/growth phenotype**) · Proposed mechanism (systemic cytokines · immune-cell trafficking · extracellular vesicles · microbiota · neural · metabolite) · **Strength of causal evidence** (correlative / blocked by intervention / transferable) · Reference.
- **Mechanism ranking for skin-specific Regnase-1 KO:** lead with **systemic cytokine spillover** (IL-6, IL-23/IL-17 axis — the transcripts Regnase-1 normally degrades), then immune-cell trafficking, then EV/microbiota/metabolite/neural routes. State explicitly which routes have any published support for an intestinal **growth/elongation** (as opposed to inflammatory) phenotype — elongation is unusual and may point away from a colitis-type mechanism.
- **Human section (phase-2 groundwork, kept separate):** skin–gut comorbidity epidemiology (psoriasis↔IBD, atopic dermatitis↔IBD) and any human mechanistic work.
- Report **negative and null findings explicitly**; where support is only correlative, say so plainly.

**Deliverable:** `reviews/q3_skin_to_gut/`

### Arm B — Reframed-MOA growth-bridge hypothesis

The step1–5 pipeline cannot take this literally (no active ingredient → empty List A), but its reasoning skeleton is the right tool for a bridge nobody has published: a pure literature search returns "not found", whereas this arm generates a disciplined, falsifiable hypothesis. The governing principle applies directly — *a novel bridge and a hallucination look identical to a literature check and completely different to this framework.*

**Input remapping — skeleton unchanged, List A / List B redefined:**

| Pipeline step | Reframed for skin-Regnase-1-KO → intestinal growth |
|---|---|
| **Step 0** — provenance / route | Perturbation = skin-specific **Regnase-1 (Zc3h12a) KO**; "route" = how the signal *leaves the skin* — circulating cytokines / immune-cell trafficking / extracellular vesicles / metabolites. This is the analysis-defining variable. |
| **Step 1** — List A *(was compound→targets)* | **Regnase-1 regulon = skin-derived systemic mediators.** The mRNAs Regnase-1 normally degrades (IL-6, IL-12/IL-23, IL-17-axis transcripts, and other validated substrates) → mediators expected to rise in circulation once skin loses Regnase-1. Evidence-tiered: E0/E1 for validated substrates, E3 for inferred ones. |
| **Step 2** — List B *(was disease→genes)* | **Intestinal growth / elongation drivers — NOT colitis genes.** Trophic and proliferative programs: IL-22–STAT3, IL-6–STAT3, IGF-1, GLP-2 / GLP2R, Wnt/β-catenin, YAP–Hippo, intestinal-stem-cell / crypt-villus expansion. |
| **Step 3** — intersection + specificity | Which skin-derived mediators feed intestinal-growth pathways (e.g. IL-6→STAT3→epithelial proliferation; IL-22→STAT3→crypt expansion). Keep the permutation-*p* / decoy specificity gate — the overlap must beat random and a decoy phenotype. |
| **Step 4** — pathway + direction | Rebuild the causal chain, but **invert the directionality check**: not "does a drug therapeutically reverse a disease" but "does this mediator **causally drive the growth phenotype**." Flag every directional ambiguity. |
| **Step 5** — hypothesis + experiments | A skin→circulation→gut **falsifiable hypothesis** + decisive experiments: systemic anti-IL-6 / anti-IL-22 neutralisation, parabiosis / serum transfer, skin-KO × intestinal reporter — each with a kill criterion. |

**Measured-evidence upgrade (transcriptomics track).** With RNA-seq of the KO skin *and* the elongated gut, run a signature-**concordance** test (shared up-regulated trophic pathways — concordance, *not* the therapeutic reversal used in a drug run) to lift a candidate bridge from E3-predicted toward measured — the strongest available validation for a non-consensus path.

**Boundaries (state up front).**
- Output is a **hypothesis**, not proof — a falsifiable mechanism + experiment roadmap, in-silico only.
- The phenotype is **growth/elongation**, which is unusual: most inflammation→gut literature is colitis (damage/shortening). **List B must be trophic-gene-anchored** or the bridge lands on the wrong biology — the single biggest failure mode of this arm.
- Uses the **mechanism-hypothesis + validation-roadmap** template, not the responder / trial-population template (no drug, no patients).

Reuses `moa_lib` (`evidence_schema`, `citation_grounding`, `specificity_controls`, `transcriptomics`) with List A / List B redefined per the table above.

**Deliverable:** `reviews/q3_skin_to_gut_moa_bridge/`

---

## Optional inputs that would sharpen the output

None of these block a run; each only refines it.

- **Q1 — flow panel constraints.** Which markers are locked into the panel? If CD8, CD19, or CD4 is fixed, the Liberase TL conflicts above make the enzyme choice a constraint rather than a preference.
- **Q2 — table density and full-text access.** Depth preference (a focused ~15–20-model table with mostly-filled cells vs a broad survey) and whether PDFs can be supplied — most morphometry (villus height, crypt depth, muscle-layer thickness) sits in figures and supplements, not abstracts.
- **Q3 Arm B — RNA-seq availability.** Expression data for the KO skin and/or the elongated gut enables the measured signature-concordance upgrade; without it, Arm B runs on the knowledge-driven (E3-predicted) path.
