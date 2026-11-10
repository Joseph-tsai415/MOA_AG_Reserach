# MOA kernel: one pipeline for every question type, drug modality, route and formulation

**Status:** design for approval · **Date:** 2026-11-10 · **Target pipeline version:** v12.0
**Note:** §8 records the decisions made after the builder review. Where it conflicts with §1–§7, §8 wins.
**Scope of change:** `CLAUDE.md` (§1, §2, §4 Step 0/1/5, §8), `moa_lib/` (provenance, route feasibility, two new modules), `.claude/docs/pipeline_changelog.md`, a known-answer acceptance panel under `validation/`.

---

## 1. Intent: why this exists

The service is positioned as a **research specialist**, so requests arrive in every shape and the pipeline must handle all of them correctly:
- discovery questions;
- a lab's hypothesis that needs checking;
- product and clinical-pharmacology questions.

The drugs come in every modality (herbal formula, small molecule, peptide, antibody, extracellular vesicle…), every route (oral, topical, injection, inhaled, ophthalmic…) and every formulation (cream, patch, liposome, microneedle…).

The current pipeline was built around one case, a herbal formula with a single disease. Five real failures show where it breaks:

1. **No premise check, no input mapping.**
   - A user asked "which SGLT2 inhibitors have been developed into slimming injections (瘦瘦針)…". No such product exists: SGLT2 inhibitors are oral, and 瘦瘦針 are GLP-1-class injections.
   - The false premise was corrected in chat. But the option offered for the research run merged the two ("SGLT2 inhibitors / slimming injections"), and nothing forced a confirmed run card.
   - A multi-hour run then analysed compounds the user did not mean.
2. **`provenance_gate()` HALTs anything that is not a herbal formula in its table**, and HALTs **every topical formula**.
   - A Step-0 agent had to override it by hand for four database-verified, approved single-molecule drugs.
   - It would also stop 七白散 × atopic dermatitis outright, although lab work reports an effect and the user wants its MOA found. Topical is a reason to model **skin exposure**, not a reason to stop.
3. **`route_feasibility` knows two routes (topical, oral) and one modality (small molecule).**
   - Peptides (SC GLP-1 agonists, oral semaglutide), antibodies, inhaled and ophthalmic drugs either get a meaningless Lipinski verdict or no verdict at all.
4. **A delivery-implausible constituent is treated as a dead end.**
   - For this service it is a **development path**: the mechanism may be real and reachable with an enabling delivery system (DDS). That is a new-drug R&D route the reader wants to see.
5. **Circularity for drugs trialled in the indication.**
   - A drug's own trials feed its target into the disease-gene list through Open Targets clinical-precedence evidence.
   - This was caught after Step 3. It should be flagged at intake and controlled by design.

**What the reader does with the output** (stated by the requester): decides
- whether a hypothesised MOA from an experiment holds;
- which lab validation to run next;
- which DDS/formulation direction to develop.

---

## 2. Goals

- **G1 Intake.** Every request passes an intake step before Step 0 and before any data fetch. The intake:
  - checks the question's premises;
  - maps intent onto resolvable inputs;
  - routes the question to a mode and deliverable;
  - types it (T1/T2/T3);
  - flags circularity;
  - ends with a run card the user confirms.
- **G2 Three modes**, combinable when a question mixes them:
  - **A: Mechanism discovery.** Compound(s) × disease → MOA hypotheses. This is today's Steps 0–5.
  - **B: Hypothesis check.** Compound × disease × hypothesised MOA, optionally with user data → verdict: supported / not supported / not determinable from available data, plus the experiment that would settle it.
  - **C: Product & mechanism comparison.** Product-landscape and clinical-pharmacology questions, e.g. "Which GLP-1 agonists have been developed into slimming injections; mechanism differences, population, dose, adverse effects?" Output is a label-grounded `reviews/` briefing. The mechanism-difference part uses measured receptor pharmacology from mode-A tooling.
- **G3 Exposure model.** Each compound gets an **exposure profile** built from modality × route × formulation: which compartments it reaches, systemic exposure, and CNS access, each with a source. The profile is a run variable that propagates through Steps 0–5, generalising today's topical-only exposure gate.
- **G4 Three-level delivery feasibility**: `as_is` / `dds_enabled` / `not_deliverable` (plus `not_assessable`). `dds_enabled` compounds **stay in the analysis**; they are no longer excluded.
- **G5 Development-path output.** For every `dds_enabled` compound the report states:
  - the barrier;
  - candidate DDS classes;
  - precedent (approved products or publications with similar molecules);
  - class-level key parameters;
  - the decisive delivery experiment with a kill criterion.
  Every suggestion is evidence-tiered and citation-grounded.
- **G6 Known-answer acceptance panel** covering every modality × route the kernel claims to support (§5).

## 3. Non-goals and anti-goals

**Non-goals**
- Formulation SOPs, excipient amounts, manufacturing processes. DDS output stops at class level plus key parameters.
- PK/PBPK simulation or any predicted exposure number. The exposure profile is categorical and sourced.
- Patient-specific dosing. Mode C reports **labelled** doses as label facts; personal dosing advice stays out of scope (§1 of CLAUDE.md).
- Wet-lab work (unchanged).
- Service-layer (`Schollar_System/`) changes. Passing mode/intake variables through the hosted runner is a follow-up project, and the science/service boundary stays as-is.

**Anti-goals** (failure even if the code "works")
- A DDS suggestion with no precedent presented as established.
- An exposure profile asserted from recall instead of a label, database flag or paper.
- A silent HALT, or a silent pass, because a compound or route is "not in the table".
- Intake implemented as optional or skippable. It is the single default path (CLAUDE.md "Build essentials in as the single default").
- The broader exposure scope becoming an excuse to claim MOA through generic hubs. Specificity controls apply unchanged.
- Known-answer panel results leaking into `CLAUDE.md` or any auto-loaded context. That would contaminate future runs (CLAUDE.md §5, run independence). Panel results live only under `validation/`.

## 4. Design: the parts that are decided

### 4.1 Intake (new, runs before Step 0)

**Input:** free-text question; optional hypothesis; optional user data.

**Five checks**, written to `request_intake.md` (human-readable) and `data/intake.json` (the run card):
1. **Premise check against data, not recall.** Each factual premise in the question becomes a `{claim, verdict, source}` row. Example: "an injectable SGLT2-inhibitor weight-loss product exists" → checked against openFDA / TFDA / ChEMBL route and indication. A false premise is stated first in the reply, together with what is true instead. It is never inherited into a run.
2. **Input resolution.**
   - Product → active ingredient (Wegovy → semaglutide).
   - Class → approved members, each with PubChem CID / ChEMBL ID.
   - Lay term → the pharmacological class it denotes (瘦瘦針 → GLP-1 / GIP-GLP-1 receptor agonists for chronic weight management).
   - Disease → a **current** ontology ID; obsolete IDs are resolved (EFO_0001073 → MONDO_0011122).
   - Each compound gets `modality`, `route`, `formulation`.
3. **Conflict handling.** When what the user named and what the user means disagree, surface it and ask, with 2–4 options. Each option names the exact compounds and indication it would run. One option never merges two interpretations.
4. **Mode routing, with mixed questions split.**
   - Product facts (approved products, labelled dose, population, adverse effects) → mode C, a `reviews/` briefing.
   - "What bridges X and Y" → mode A.
   - "Does our hypothesis hold" → mode B.
5. **Typing and circularity.**
   - Assign T1/T2/T3 per `.claude/docs/user_validation_guide_zh-TW.md` §1.1.
   - Any drug approved **or trialled** for the indication gets a `circularity` flag: its target's disease association is partly its own trial evidence. This flag switches on the circularity control in §4.6.

**Run card** (confirmed before Step 0):
- mode(s), T-type, premise verdicts;
- compounds (with IDs, modality, route, formulation);
- disease (with ontology ID and the tissue of pathology);
- deliverable location;
- what the run will and will not answer;
- circularity flags;
- output directory.

**Interactive runs** wait for confirmation. **Service mode:**
- Checks 1, 2 and 5 still run on the pre-specified inputs.
- On a conflict, ask once via AskUserQuestion.
- On timeout, proceed on the literal inputs and state the conflict in the report's header note. This is consistent with the existing runner prompt contract.

### 4.2 Mode B: hypothesis check

**Input:** a `hypothesis` object: target(s) and/or pathway, expected direction, tissue.

**Steps 0–3 run as in mode A, plus hypothesis-specific tests, all pre-registered in `data/step3_prespec.json`:**
- (i) Is each hypothesised target engaged by the compound, and with which `engagement_type`?
- (ii) Is it disease-associated **in the exposed compartment's tissue**?
- (iii) Is the proximity of the hypothesised target set to the disease module better than degree-matched random sets and the decoy?
- (iv) If the user supplied data: does it show the predicted change?

**Verdict rules** (my call; the builder may refine them with written justification):
- **Supported:** ≥1 hypothesised target has measured_binding or experimental_direct engagement, AND it has tissue-appropriate disease evidence, AND specificity passes.
- **Not supported:** no E0/E1-direct engagement of any hypothesised target AND (a direction conflict OR specificity fails).
- **Not determinable:** everything else.

Steps 4–5 focus on the hypothesis. The validation plan leads with the experiment that would falsify it.

### 4.3 Mode C: product & mechanism comparison

**Output:** `reviews/{topic}/` in the existing §8 shape: `data/`, `scripts/01–05`, citation grounding, lineage audit, report-qa, PDF in `--report` mode.

**Content:**
- products by region (**Taiwan TFDA, US FDA, EU EMA** by default, labelled per region; my call);
- labelled dose and titration, indicated population, contraindications, adverse-event frequencies from labels and pivotal trials;
- **mechanism differences** from measured pharmacology: ChEMBL / IUPHAR receptor affinities and potencies (e.g. GLP1R vs GIPR for tirzepatide vs semaglutide), modality, half-life-extension strategy;
- an optional per-compound mode-A run when the mechanism question warrants it.

Every source is fetched and persisted. A failed source is recorded as FETCH_FAILED and never advertised. Taiwan-site quirks are already documented in `instrument_gotchas.md` §1.4.

### 4.4 Exposure model: new module `moa_lib/exposure.py`

**Inputs:**
- `modality` ∈ {small_molecule, peptide, protein_antibody, oligonucleotide, herbal_formula, extracellular_vesicle, cell, other};
- `route` ∈ {oral, topical_skin, transdermal, subcutaneous, intramuscular, intravenous, inhaled, intranasal, ophthalmic, otic, buccal_sublingual, rectal, vaginal, intra_articular, intrathecal, other};
- `formulation`: a controlled vocabulary plus free text (tablet, capsule, solution, cream, ointment, gel, patch, nanoemulsion, liposome, LNP, microneedle, hydrogel, depot, implant, DPI/MDI, nebulised, eye drop, …).

Route and formulation are independent inputs: within one route, formulation changes exposure (liposomal vs plain injection).

**Output:** `ExposureProfile`:
- `primary_compartments` (e.g. skin_epidermis, lung, eye_anterior, plasma, gut_lumen);
- `systemic` ∈ {none, low, full};
- `cns` ∈ {unlikely, possible, yes};
- per-field `source` and evidence tier.

**Source priority:**
1. the label (route + clinical-pharmacology section);
2. ChEMBL molecule flags (oral / parenteral / topical);
3. published PK;
4. rule-of-thumb defaults, which are tier E4, flagged, and never stand alone.

**Propagation:**
- **Step 1:** feasibility (§4.5) is evaluated against the profile.
- **Step 2:** genes get a `compartment_relevance` tag (disease relevance or expression in the exposed tissue, from GTEx/HPA). Tagging never silently removes a gene.
- **Step 3:** primary specificity analysis unchanged. An **exposure-restricted** re-analysis (List B limited to compartment-relevant genes) is a pre-registered secondary (my call).
- **Step 4:** pathways interpreted in the exposed tissue.
- **Step 5:** Application Context and responder claims are gated by the profile. This generalises today's topical rule to every route.

### 4.5 Delivery feasibility: refactor `moa_lib/route_feasibility.py`

**Rule sets keyed by (modality, route).** Thresholds are cited in the module and pass the citation-grounding gate. Starting set:
- small-molecule oral: Lipinski Ro5 + Veber (TPSA ≤ 140, rotatable bonds ≤ 10);
- small-molecule topical/transdermal: MW ≤ 500, LogP ≈ 1–3 (0–4 tolerated);
- ophthalmic: a corneal-permeation window;
- inhaled: flag-only;
- parenteral (SC/IM/IV), any modality: absorption rules not applicable → `as_is` for systemic exposure, with label bioavailability noted;
- peptide/protein oral: `dds_enabled` only with precedent (e.g. oral semaglutide with a permeation enhancer), otherwise `not_deliverable`;
- a CNS target with a non-penetrant modality: flagged.

**Precedence rule:** an **approved product** of that molecule by that route makes it `as_is`, whatever the rule of thumb says, citing the label as precedent. Example: tacrolimus ointment, MW 804, exceeds the 500 Da rule but is an approved topical product. Rules apply only where no product precedent exists.

**Result type:** `Feasibility{level, violations, rule_set, sources, dds_candidates}`. The existing `topical_feasible` / `oral_feasible` / `assess` / `screen` API stays as a compatibility layer, so v11 run scripts still import.

### 4.6 Provenance changes: `moa_lib/provenance.py`

- **HALT only on a mis-specified object of study:**
  - a formula composition mismatch, or a composition that cannot be sourced;
  - a single molecule whose identity cannot be verified. The InChIKey parent match across PubChem and ChEMBL becomes the module path; the hand-written override is retired.
  - **Topical no longer HALTs.** It sets the exposure profile.
- **Unknown formula** (not in the reference table): interactive runs ask the user for the composition source. Service mode writes `HALT_provenance.md` stating what is needed.
- **Indication plausibility** has four values: approved / trialled / literature-supported efficacy (E1, grounded) / none → REFRAME label.
  - A user's statement that "our lab found it works" is recorded as a user-provided claim.
  - If published, it is grounded and becomes E1. If unpublished, it stays user-provided, is reported as such, and is never presented as E1.
- **Circularity control** (triggered by the intake flag): pre-registered Step-3 sensitivity analysis that **recomputes List B scores with the Open Targets clinical-precedence / known-drug datatype removed**. Removing only genes whose *sole* support is clinical precedence did not catch the SLC5A2 case.

### 4.7 New module `moa_lib/delivery_paths.py` and the report's development-path section

For each `dds_enabled` compound:
- the barrier (size, lipophilicity, enzymatic degradation, epithelial tight junctions…);
- candidate DDS classes, from a curated, cited barrier × route → DDS-class table;
- precedent search (approved products, then published studies with similar molecules);
- class-level parameters (particle-size range, loading, excipient classes);
- the decisive delivery experiment and its kill criterion (Franz cell / ex-vivo skin or cornea / Caco-2 / PAMPA / in-vivo PK).

**Evidence tiers:**
- approved-product precedent: E0/E1;
- published precedent: E1;
- analogy only: E4, flag-only. It is shown as a hypothesis with its falsifying experiment.

**Report:** a plain **"Development path"** section. The validation plan orders **delivery first, then mechanism**, because a mechanism experiment is moot if the compound cannot reach the tissue.

### 4.8 CLAUDE.md and versioning

- **§1:** state the three modes.
- **§2:** add the Intake section (compact; details live in the module and in a new on-demand doc `.claude/docs/exposure_and_delivery.md`).
- **§4 Step 0:**
  - input becomes the confirmed run card;
  - revised HALT rule;
  - exposure profile and modality/route/formulation as run variables.
- **§4 Step 1:** three-level feasibility.
- **§4 Step 5:** Development path section; exposure-gated Application Context.
- **§8:** new fixed names `request_intake.md`, `data/intake.json`; mode C → `reviews/`.

CLAUDE.md stays light; detail lives in modules and docs.

Bump to **v12.0**, since this is a material change to Step 0, adds a step and adds modes (my call). Add a changelog row naming the five motivating failures **without** stating any run's scientific verdict.

## 5. Acceptance: known-answer panel (`validation/kernel_panel/`)

Each case states the expected kernel behaviour. Results live only here, never in auto-loaded context.

| # | Case | Modality × route | Pass when |
|---|---|---|---|
| 1 | "SGLT2 inhibitors developed into slimming injections…" | — (intake) | Premise flagged false with sources; options offered; **no run starts** until confirmed; no merged option label |
| 2 | "GLP-1 agonists developed into slimming injections; mechanism differences, population, dose, AEs" | peptide × SC (+ oral semaglutide) | Routed to mode C (+ A for mechanism); products per region; GLP1R vs GIPR difference from measured data; circularity flagged; oral semaglutide = `dds_enabled` with approved precedent |
| 3 | Atorvastatin × hypercholesterolaemia | small molecule × oral | HMGCR recovered as E0 hub; systemic profile |
| 4 | Ruxolitinib cream × atopic dermatitis | small molecule × topical | JAK1/JAK2 E0; skin-only profile; no systemic responder population |
| 5 | Tacrolimus ointment × atopic dermatitis | small molecule × topical (edge) | `as_is` via label precedent despite MW 804; calcineurin/FKBP12 axis |
| 6 | Semaglutide × obesity | peptide × SC | GLP1R E0; circularity control runs; mechanism near the hypothalamic melanocortin axis is assessed, not assumed |
| 7 | Dupilumab × atopic dermatitis | antibody × SC | IL4R engagement from label/IUPHAR; IL-4/IL-13 engagement check passes on defining genes |
| 8 | Tiotropium × COPD | small molecule × inhaled | CHRM3; lung-compartment profile |
| 9 | Latanoprost eye drops × glaucoma | small molecule × ophthalmic | PTGFR; anterior-eye profile |
| 10 | 七白散 (authentic 7-herb) × atopic dermatitis | herbal formula × topical | **No HALT**; skin profile; REFRAME unless grounded efficacy evidence is found; delivery-implausible constituents become `dds_enabled` development paths |
| 11 | 七白散 with a wrong 5-herb list × atopic dermatitis | herbal formula × topical | HALT on composition mismatch |
| 12 | Ruxolitinib **cream** × myelofibrosis (same molecule, wrong route) | small molecule × topical | Intake flags route ≠ approved oral use; exposure profile blocks any systemic-efficacy claim |

Panel 1–2 and 10–12 are the regression tests for the failures in §1. The panel is the definition of done for v12.0.

## 6. Constraints

- Scientific code only in `moa_lib/` and `results/{…}/scripts/`. `Schollar_System/` is untouched.
- No session-memory writes. Durable knowledge goes to the repo (CLAUDE.md §5).
- Conda env `moa`, Windows, single-threaded heavy stats, `if __name__ == '__main__'` guards. Pin `PYTHONHASHSEED` where set iteration affects seeded results. This is a known `network_proximity` nondeterminism, worth fixing in passing.
- v11 runs stay reproducible: the old API is kept as a compatibility layer; runs are stamped with their version.
- Every new threshold, DDS table entry and exposure default carries a citation that passes `citation_grounding`.

## 7. Left to the builder

- Exact rule thresholds per (modality, route), and their citations.
- The compartment vocabulary.
- GTEx vs HPA for compartment relevance.
- Refinements to the mode-B verdict rules, with written justification.
- Access paths for TFDA and EMA data; FETCH_FAILED handling where blocked.
- Test layout (pytest under `moa_lib/tests/`) and fixtures.
- How the panel is executed: scripted vs agent-run, and how pass/fail is recorded.
- Build order across the parts.

## 8. Decisions after the builder review (2026-11-10)

A builder review of §1–§7 returned ten open questions. Three were taken to the requester; the rest are settled here. Where this section conflicts with §1–§7, this section wins.

### 8.1 Requester decisions

**R1 — Small target sets get an "underpowered" Step-3 outcome, not a HALT.**
- A drug with few targets cannot reach p < 0.05 on the overlap test: one shared gene out of one or two targets is arithmetically incapable of it. Atorvastatin, latanoprost and tiotropium would all stop for a reason that is about test power, not about biology.
- When a compound set has ≤ 3 targets with `measured_binding`, `experimental_direct` or `label_mechanism` engagement, Step 3 returns `SPECIFICITY_UNDERPOWERED`: the run continues, and the report states that the specificity test could not be powered and that confidence rests on the measured engagement instead. Headline confidence is capped at "promising-but-unproven".
- Network proximity and the decoy control still run and are still reported; only the overlap-p HALT is suspended.
- The HALT rule is unchanged for larger target sets.
- Panel cases 3, 5, 8 and 9 pass only if the known target and axis are recovered. A reported HALT is not a pass.

**R2 — All three further modalities ship in v12.0:** extracellular vesicles, cell therapies and oligonucleotides.
- Identity verification per modality, replacing the InChIKey parent match:
  - **antibody / protein:** INN, ChEMBL biotherapeutic record, UniProt target, label;
  - **oligonucleotide:** sequence and backbone chemistry, with the target transcript resolved from the sequence;
  - **cell therapy:** cell type, source, and engineered construct such as a CAR target;
  - **EV:** source cell type, isolation method, and characterisation reported against MISEV minimum-information items. Cargo claims are checked with the `exocarta-database` skill and are E2 at most, never proof of a functional mechanism.
- EVs have no textbook mechanism, so EV runs are hypothesis-level (T3) and say so.
- Oligonucleotides and cell therapies do have known answers, and the panel gains one case each (§8.3).

**R3 — For a herbal formula, the question is which constituents are active and by what mechanism.**
- The requester's case is a formula a lab has already seen work: what is needed is attribution, not a yes/no on the formula.
- Mode A therefore reports, for every herbal-formula run:
  - which constituents anchor which hubs, each with evidence tier and engagement type;
  - per-constituent delivery feasibility and, where relevant, development path;
  - a ranked list of candidate active constituents, with what makes each one a candidate.
- The validation plan must open with constituent deconvolution: LC-MS of the preparation the lab actually tested, then fractionation or single-constituent testing in that lab's own model. Attribution cannot be settled from databases alone, and the report says so.
- **Composition handling:** `FORMULA_REF` holds a list of sourced variants per formula, not one canonical list. A provided list that matches any sourced variant passes, naming the variant it matched. A list matching none is a mismatch and HALTs, which keeps panel case 11 working. A lab's own preparation that matches no classical source is recorded as a **user-provided variant** with the lab as its source: the run proceeds and the report states that the composition is the lab's, not a classical one.
- Panel case 10 is amended: the pass criterion is constituent-level attribution plus a deconvolution plan, not merely "no HALT".

### 8.2 Builder questions settled here

**B1 — What a pre-registered secondary analysis does.** Report-only, plus a confidence cap. A secondary never creates a new HALT branch and never silently replaces the primary. The panel's expected hub is judged under the **primary** analysis; the circularity-controlled result is reported beside it. Where a hub survives only the primary and not the circularity control, the report must say that its disease association rests on the drug's own trial evidence.

**B2 — What the circularity control strips.** Both legs, reported separately: (i) the Open Targets clinical-precedence / known-drug datatype, and (ii) the literature leg restricted to publications that are themselves trials or reviews of the compound under study, identified from the stored PMIDs. Stripping only the datatype leaves the drug's own trial papers carrying the gene through text-mining, which is how SLC5A2 survived. Panel case 6 is amended: the control must be shown to **change** the GLP1R result, not merely to run.

**B3 — Exposure mismatch with the tissue of pathology.** Delivery feasibility is judged against the **tissue of pathology**, not the route's own compartment. A route that cannot reach it yields `not_deliverable_to_target_tissue`, and Step 0 returns a new **EXPOSURE_MISMATCH** verdict: the run stops before Step 1 with `HALT_exposure_mismatch.md`, stating the route, its compartments, the tissue of pathology and the source for each. This keeps panel case 12 cheap rather than a full run. Where a DDS could plausibly bridge the gap, the stop report says so and routes to the development path instead of claiming systemic efficacy.

**B4 — What `dds_enabled` means.**
- `dds_enabled` compounds **stay in the analysis and may anchor a hub**, but every mechanism they anchor is labelled `delivery_dependent`, and the Bottom line cannot rest on such a hub alone. This replaces CLAUDE.md §3.4's blanket rule that a delivery-implausible compound may not anchor a mechanism.
- Level assignment requires precedent at E1 or better: an approved product or a published study delivering a similar molecule by that route. Analogy-only (E4) support is **not** sufficient; such a compound is `not_deliverable` with the analogy recorded as a speculative note. This keeps `not_deliverable` reachable.

**B5 — Mode B control flow.**
- A Step-3 specificity failure does not stop a mode-B run: "not supported" is a valid and useful verdict, so the run continues to deliver it with its evidence.
- The HALT and specificity tests are driven by the **hypothesised target set** as the primary for mode B, with the full A∩B reported as context. The pre-registration states both.
- `engagement_type` is the field Step 1 already writes (`measured_binding`, `experimental_direct`, `in_silico`, `pathway_level`, `expression_only`). v12.0 adds `label_mechanism` for biologics and other drugs whose mechanism is stated in an approved label or in IUPHAR rather than in a binding assay; it ranks with `measured_binding`.
- Mode B gains a panel case (§8.3). Test (iv) accepts an expression matrix with metadata, and a tabular assay result with units and controls. Anything else is recorded as unsupported input and the test is reported as not run.

**B6 — Exposure profiles whose only source is a rule of thumb.** A rule-of-thumb default is E4 and cannot alone support a systemic or responder claim; such a profile is `provisional`. For a herbal formula, the **formula-level** route from its classical or pharmacopoeia source is a legitimate E1 source for the compartment, and applies to its constituents; constituent-level systemic exposure remains provisional unless a constituent has its own PK. Step 5's Application Context is written at whatever level the sourced profile supports, and states the level. This keeps oral herbal runs usable without asserting exposure from recall.

**B7 — Mixed-mode deliverables (mode C + A).** One `reviews/{topic}/` deliverable owns the answer. A mode-A sub-run lives at `reviews/{topic}/moa_runs/{compound}_{disease}/` with the full Step 0–5 shape, and the briefing cites it. `request_intake.md` and `data/intake.json` sit at the deliverable root. Intake decides whether a sub-run is warranted and records the reason in the run card; "the mechanism question needs measured target data that the labels do not carry" is the test. The lineage audit reconciles across both levels, and report-qa routes on the root deliverable.

**B8 — Service mode in v12.0 is mode A only.** `Schollar_System/` is untouched, so it cannot pass a mode, a hypothesis or user data, and its terminal-state classifier expects the mode-A file names in `MOA_RUN_DIR`. Intake still runs in service mode for premise checking, input resolution and circularity flagging, and writes `request_intake.md` into the run directory. A service request that intake routes to mode B or C stops with `HALT_mode_unsupported.md` naming the mode and what a local run would produce. Reaching modes B and C through the service is a follow-up project.

### 8.3 Panel amendments

- **Case 6** (semaglutide × obesity): the circularity control must change the GLP1R result, not merely run.
- **Case 10** (七白散 × atopic dermatitis): pass requires constituent-level attribution and a deconvolution plan.
- **Case 13, new** (mode B): a hypothesis check with a known answer — "dupilumab works in atopic dermatitis by blocking IL-13 signalling" should come back supported, and a deliberately wrong hypothesis on the same drug, e.g. "by inhibiting JAK1", should come back not supported. One case, two directions, so the verdict rules are tested both ways.
- **Case 14, new** (oligonucleotide × systemic): inclisiran × hypercholesterolaemia. Expected: PCSK9 transcript target recovered from the sequence; hepatocyte compartment via GalNAc conjugation.
- **Case 15, new** (cell therapy): tisagenlecleucel × B-cell acute lymphoblastic leukaemia. Expected: CD19 (CAR target) recovered; identity verified by construct, not by InChIKey.
- **Case 16, new** (EV, hypothesis-level): an ADSC-exosome run. Expected: T3 framing, MISEV reporting items checked, cargo claims capped at E2, and no mechanism asserted as established.
- **Case 17, new** (herbal × oral): an oral classical formula, to exercise B6's formula-level exposure path, which the original panel did not cover.

### 8.4 Still left to the builder, added by this review

- The exact power rule behind the ≤ 3-target threshold in R1: whether to compute the minimum achievable p from |A|, |B| and the universe instead of a fixed count.
- Which trial and review publication types count as "the compound's own literature" in B2.
- MISEV item selection for EV identity in R2.
- The `label_mechanism` extraction path: which label section and which IUPHAR field.
