# Measuring this agent — accuracy, stability, and safety-coverage protocol

> **Status:** proposal / outline · **Written:** 2026-08-25 · **Scope:** how to test the MOA-AG
> research agent, not how to run it. On-demand reference (NOT auto-loaded), like
> `pipeline_changelog.md`.
> **中文版：** `.claude/docs/agent_evaluation_zh-TW.md` — a superset: it additionally carries the
> **tester's handbook** (what the person setting a question must prepare: sealed answer key,
> pre-registration and fixture-card templates, question-quality self-check) and a **10-minute
> report-reading checklist**.

---

## 0. What a number here has to mean

Three things get conflated under "is the agent good". Keep them apart; never average them.

| Axis | Question | Measurable where? |
|---|---|---|
| **Accuracy** | Is the answer right? | **Only** where truth exists |
| **Stability** | Does the same question give the same answer? | **Always** |
| **Process compliance** | Did the gates actually run and pass? | Always, and free |

A system can be **stably wrong** or **unstably right**. Compliance is the cheap leading
indicator for the other two: a run missing its citation-grounding output is not "probably fine",
it is unmeasured.

The fourth thing this project needs and does not yet have as a first-class metric: **safety
coverage** (§8). It is scored inside the Accuracy/Stability frame, but it deserves its own headline
because it is currently produced by luck.

---

## 1. Truth-availability tiers — mapping `research_questions.md`

The three questions in `research_questions.md` are not three topics; they are three *epistemic
regimes*, and each admits a different measurement. This is the backbone of the protocol.

| Tier | Truth status | Corresponds to | What you may score | What you must NOT score |
|---|---|---|---|---|
| **T1 — Sealed ground truth** | Tester knows the answer; it is withheld from the agent | **Q1** (gut immune isolation: the enzyme × epitope facts are established and the tester holds them) | recall, fabrication rate, precision, calibration | — |
| **T2 — Prospective** | Direction expected; experiment still running | **Q2** (SI elongation, benchmarked against published models) | pre-registered directional hit, interval coverage, Brier score — *scored later* | absolute accuracy *now* |
| **T3 — Open hypothesis** | No truth exists yet | **Q3 Arm B**, all exosome-cargo runs, most `results/` MOA runs | traceability, falsifiability, **safety coverage**, internal consistency, decision usefulness, stability | **correctness** |

> **Governing rule.** Never score a T3 output for correctness. There is nothing to score it
> against, so any such score is really a plausibility score — and optimising for plausibility is
> precisely how you build a confident hallucinator. This is the same principle CLAUDE.md §3
> already states for reports ("a novel bridge and a hallucination look identical to a literature
> check"); it applies to the evaluator too.

For T3 the target is **decision usefulness**: after reading it, does a bench scientist know what
to do on Monday, and what result would kill the idea?

---

## 2. The test corpus

Every fixture is a card: verbatim input prompt · tier · modality · sealed answer key (T1) ·
expected terminal state (PROCEED / HALT) · date of key.

**T1 — sealed ground truth (build ~8–10)**
- **Q1-style factual retrieval**, where the tester holds the facts: e.g. "Liberase TL cleaves CD8,
  partially CD19" — atomic, PMID-backed, falsifiable.
- **Back-test MOA pairs** — compound × disease whose mechanism is textbook, run blind through
  Steps 0–5: tofacitinib × RA (JAK1/JAK3), celecoxib × OA (PTGS2), imatinib × CML (ABL1/KIT/PDGFRA).
  The known primary target *must* surface in the hub set.
- **Negative controls** — compound × disease pairs with no plausible link. The system must **HALT**
  at Step 3. **This is the single most important fixture class**: a system that never says "no"
  produces a positive result for anything and is worth nothing. Score it separately from recall.
- **Known-defect replays** — session8 (fabricated citations, non-human targets) is already a fixture
  in `moa_lib/tests/validate_session8.py`; formalise it as a permanent regression fixture.

**T2 — prospective (1–3, running continuously)**
- Q2 / the skin→gut elongation work: pre-register the agent's prediction before the readout (§6).

**T3 — open (6–10)**
- Q3 Arm B growth-bridge; the three EV cargo runs; a fresh TCM formula × disease.
- Each is run **×5** for stability (§4) and rubric-scored (§7).

---

## 3. Separating agent variance from world variance — the replay harness

A re-run can differ because the *model* rolled differently or because *ChEMBL changed*. Without
separating these you cannot attribute anything.

Two modes:

- **Live mode** — hits real APIs. Measures end-to-end reality: DB drift, rate limits, outages.
  Run periodically; this is what the hosted service actually experiences.
- **Replay mode** — every HTTP response is served from a frozen cache, so the **only** varying
  input is model stochasticity. **All stability numbers must come from replay mode.**

Implementation is small because runs already persist every fetch under `results/{run}/data/`:

- `moa_lib/eval/cache.py` — a `requests` shim keyed by `(method, url, sorted params, body-hash)` →
  JSON on disk, with `record` / `replay` / `strict` modes (`strict` fails on a cache miss so a
  silent live call cannot contaminate a replay).
- Pin and record per run: model id, pipeline version, cache snapshot date, skill versions,
  `MOA_RUN_DIR`. Two runs are only comparable when these match.

---

## 4. Stability metrics — N = 5 replays per fixture

Grouped by pipeline layer, most-important first. Thresholds are opening proposals to calibrate
against the first round, not laws.

| Layer | Metric | Proposed threshold |
|---|---|---|
| **Decision** | HALT vs PROCEED concordance across 5 runs | **5/5** — anything less is a blocker |
| **Decision** | Bottom-line verdict category (worth pursuing / promising / not yet / no), Fleiss κ | κ ≥ 0.8 |
| **Set** | Hub-gene set Jaccard, pairwise mean (Step 3) | ≥ 0.80 |
| **Set** | List A / List B Jaccard; top-10 rank agreement (RBO) | ≥ 0.75 / ≥ 0.80 |
| **Number** | \|A\|, \|B\|, \|A∩B\| coefficient of variation | ≤ 10 % |
| **Number** | `z_c` absolute spread; `log10(overlap_p)` spread | Δ ≤ 0.05 · ≤ 1 decade |
| **Claim** | Mechanism triples `(target, direction, pathway)` — set Jaccard; identity of the **top-ranked** mechanism | ≥ 0.7 · identical in ≥ 4/5 |
| **Citation** | Reference-set Jaccard | ≥ 0.7 |
| **Citation** | Fabricated-citation count | **0 in every run — variance must be zero** |
| **Safety** | Hazard-coverage score spread across replays (§8) | ≤ 1 point |
| **Cost** | tokens · wall-clock · $ per run, CV | ≤ 25 % (matters: `Schollar_System` bills per job) |

Report the **actual disagreements**, not only the coefficients. With N=5, "runs 2 and 4 dropped
STAT3" is more informative than "Jaccard = 0.82".

---

## 5. Accuracy metrics — T1 only

**Answer-key format.** Atomic, falsifiable, PMID-anchored, date-stamped, and **sealed** — stored
outside the working tree (or committed as a hash only) so no session can read it (§11).

**Per-fact scoring**, 4 outcomes:

| Outcome | Meaning | Weight |
|---|---|---|
| **HIT** | Stated, correct, correctly cited | +1 |
| **MISS** | Not mentioned | −1 |
| **CONTRADICTION** | Stated and wrong | **−10** |
| **UNSUPPORTED** | Stated, cite does not support it (fabrication) | **−10** |

The asymmetry is deliberate and is the core of the whole scheme: **an omission costs a literature
search; an invention costs an experiment.** Any metric that treats them equally will push the
system toward saying more.

Derived headlines:
- **Recall** = HIT / (HIT + MISS)
- **Fabrication rate** = (CONTRADICTION + UNSUPPORTED) per 100 claims — *the* headline number
- **Citation-grounding pass rate** — automatic, `moa_lib.citation_grounding` (claim-level, not
  reference-level; the v11.2 changelog records that reference-level checking passed a fabrication)
- **Number fidelity** — automatic, `moa_lib.lineage_audit` FAIL count
- **Hub-target recall / precision** for back-test pairs — reuse `moa_lib/benchmark_recall.py`.
  It was correctly retired as a *report section* (it compares pipeline versions, not biology);
  it is exactly the right tool **here**, where comparing versions is the whole point.
- **Negative-control specificity** = fraction of no-link fixtures that correctly HALT. Own headline.
- **Calibration** — bin every claim by its stated evidence tier / GRADE certainty, plot observed
  correctness per bin, report **expected calibration error** + a reliability diagram. A system
  whose "Moderate" claims are right 40 % of the time is miscalibrated even if its recall is high,
  and miscalibration is what makes a report dangerous rather than merely incomplete.

---

## 6. T2 — prospective scoring (the Q2 regime)

The only unbiased accuracy signal available for genuinely novel work. Slow, so start it now and
let it accrue alongside the lab's real experiments.

1. **Pre-registration.** Before unblinding, write `prereg.md`: the prediction, a numeric interval,
   the direction, the kill criterion, the readout that decides it, and the date. Hash it and record
   the hash in the run folder. A prediction not registered before the readout does not count.
2. **Score on readout:** directional hit/miss · interval coverage (did the true value fall inside
   the stated interval) · **Brier score** for any probabilistic call.
3. **Publish misses.** A prospective miss with a pre-registration is worth more than ten
   retrospective hits — it is the only thing that calibrates §5's confidence bins for novel biology.

---

## 7. T3 — the rubric when there is no truth

Scored by an **independent** reviewer — the `report-qa` agent driven by this rubric, *never* the
session that wrote the report — plus a human spot-check on a sample of ~20 %.

Five dimensions, 0–3 each:

1. **Traceability / explainability** — can every headline number and mechanistic claim be
   reconstructed from `data/` by re-running `scripts/`? (Largely automatable — this is
   `lineage_audit` plus a folder audit.) Can a reader follow cargo/compound → target → pathway →
   phenotype without trusting the author?
2. **Falsifiability** — % of unmeasured claims carrying **assay + readout + kill criterion**.
   CLAUDE.md already mandates this in Step 4/5; measure whether it happened.
3. **Safety & liability coverage** — the modality hazard checklist, §8.
4. **Internal consistency** — bottom line, tables, and limitations agree; the conflict log is
   non-empty (a directionality pass with zero conflicts is broken by construction); no gated set
   leaks into a scored table.
5. **Decision usefulness** — is the *cheapest decisive* experiment named, and is it actually the
   cheapest and actually decisive?

Plus an **adversarial probe**: a second, independent agent is asked to *refute* the report's top
three claims. Metric = how many survive. This is the T3 substitute for ground truth, and it is the
only cheap instrument that distinguishes a novel bridge from a confident invention.

---

## 8. Safety-check measurement — and the exosome finding

**Measured state (2026-08-25), across three runs of the same modality (EV biologic × AD):**

| Hazard class | `adsc_exosome…` | `…_session2` | `hamsc_haesc_exosome…` |
|---|---|---|---|
| Counter-therapeutic direction | fibrosis, kill-criterion line only | **angiogenesis — headline + own experiment** | TNFAIP3 target conflict only |
| Product / drug interaction | — | **GAS5 × topical corticosteroid, + experiment 7** | — |
| Identity & batch characterisation | — | **MISEV / NTA / CD63-Alix-TSG101** | — |
| Sterility · endotoxin · immunogenicity · tumorigenicity | 0 | 0 | 0 |

Session 2 is genuinely strong — it found a drug-interaction liability no efficacy endpoint would
surface. But its sibling runs did not, and **no run addresses EV product-quality hazards at all**.
The cause is structural, not a lapse: **the Step-5 report template has no safety section**
(Hypothesis · MOA table · Application context · Validation experiments · Limitations · References).
Safety appears when the biology happens to force it through the directionality/conflict gate.
So the honest answer to "does the review contain safety checks" is: *sometimes, by luck, at the
target level only — and that variance is itself a measurable instability.*

**The instrument.** Score each deliverable against a hazard checklist chosen by modality.
Per hazard: **2** = addressed with a named experiment · **1** = named only · **0** = absent.
`safety coverage = achieved / applicable`.

- **Universal** — counter-therapeutic direction · on-target liability · off-target / promiscuity ·
  drug–drug or product interaction · population contraindication · route & exposure realism.
- **EV / cell-derived biologic** — donor & batch variability, identity (MISEV) · sterility,
  endotoxin, mycoplasma · immunogenicity · pro-proliferative / tumorigenic cargo · pro-angiogenic
  cargo · biodistribution / ectopic delivery · regulatory class (ATMP / HCT-P).
- **Small molecule & TCM formula** — PAINS / frequent-hitter artefact · herb-induced liver injury ·
  CYP/UGT interaction · contact sensitisation and phototoxicity (topicals) · adulteration and
  heavy metals · pregnancy/paediatric exclusions.
- **Genetic perturbation (Q3-type)** — tissue-restriction confound (is the lesion truly local) ·
  KO off-target effects · growth vs neoplasia.

**Recommendation — promote this out of the evaluator and into the pipeline.** Add a
*"Liabilities and safety questions"* subsection to Step 5 plus `moa_lib/safety_checklist.py`
(modality → hazard list → coverage score, written to `step5_confidence_dashboard.md`). Then this
metric measures **compliance** instead of luck, and the evaluator's job shrinks to verifying it ran.
That is a methodology change → new row in `pipeline_changelog.md` (v11.3).

---

## 9. Process compliance — free, automatic, run on every deliverable

Machine-checkable from the folder alone, no model in the loop.

- **Required-artifact presence** per CLAUDE.md §8. *Current baseline (19 deliverables):* only
  **4** carry `report_qa_review.md`; `adsc_exosome_atopic_dermatitis_session2` lacks one although
  its predecessor has one; 6 `results/` runs have neither QA nor `data_integrity_check.md`.
- **Gate-execution evidence** — provenance verdict present · specificity numbers present
  (`overlap_p`, `z_c`, decoy) · citation-grounding output present · lineage audit = PASS ·
  QA verdict = SHIP.
- **Report-voice violations** — grep the report body for version branding / module names
  (CLAUDE.md §5).
- **Figure completeness** — legend for categories, colourbar for continuous colour,
  `bbox_inches='tight'`, glyph/tofu gate on the PNG.

Wire this into `Schollar_System` as a post-run check so **every production job** is scored, not just
eval fixtures. It stays inside the service-layer boundary: it inspects and classifies artifacts,
it never computes or interprets a scientific result.

---

## 10. The scorecard and the release rule

One page per evaluation round:

| Headline | Source | Proposed gate |
|---|---|---|
| Decision reproducibility (HALT/PROCEED, verdict κ) | §4 | 5/5 and κ ≥ 0.8 |
| Fabrication rate per 100 claims | §5 | **0** |
| Negative-control specificity | §5 | 100 % HALT |
| T1 recall | §5 | track trend, no absolute gate |
| Calibration error | §5 | ≤ 0.15 |
| Safety coverage | §8 | ≥ 0.8 of applicable hazards |
| Process compliance | §9 | 100 % |

**Release rule.** A pipeline-version bump ships only if every gated headline holds and no headline
regressed against the previous version on the frozen fixture suite. **Regression rule.** Re-run the
suite on any change to CLAUDE.md §3 or to `moa_lib/`; a regression blocks the change and, if
accepted anyway, gets its own changelog row explaining the trade.

---

## 11. Threats to the evaluation itself

- **Contamination.** The agent may have seen the answer key in an earlier session, or the key may
  sit in the repo it can read. Seal keys outside the working tree; commit hashes only; rotate
  fixtures.
- **Scorer bias.** The QA agent shares the model with the author. Never let the authoring session
  grade itself; cross-check a sample with a human, and where possible score with a *different*
  model.
- **Ground-truth rot.** "Established" facts move. Date-stamp every key and re-verify annually.
- **Goodhart.** Optimise hub-recall and the system widens List A. Every recall metric must be
  paired with precision/fabrication so widening is penalised. Never publish recall alone.
- **Small N.** Five replays gives a coarse estimate. Report raw disagreements alongside every
  summary statistic.
- **The evaluator is not the science.** This measures whether the agent is reliable, not whether a
  hypothesis is true. Only §6 touches truth for novel work.

---

## 12. Minimal first increment

Roughly one working session each, in dependency order.

1. **`moa_lib/eval/compliance.py`** — §9 folder + gate audit across all 19 existing deliverables.
   Zero model calls, immediate baseline, and it retro-scores work already done.
2. **`moa_lib/eval/safety_checklist.py`** — §8 hazard checklist; retro-score the three EV runs and
   the two most recent MOA runs. Directly answers the exosome question with a number.
3. **`moa_lib/eval/cache.py`** — record/replay shim (§3). Without it, no stability number is
   attributable.
4. **Fixture suite** — 3 negative controls + 3 MOA back-tests + the session8 regression; each ×5 in
   replay; emit the §4 stability scorecard.
5. **`prereg.md`** for the ongoing Q2 elongation readout (§6) — cheap now, impossible to backfill.

**Where the output lives.** An evaluation round is a `reviews/`-shaped deliverable, not a MOA run:
`reviews/agent_eval_{YYYY-MM-DD}/` with `data/` (raw per-run metrics), `scripts/` (numbered,
re-runnable), `figures/`, the report, and its own `report_qa_review.md`. The evaluator is held to
the same evidence burden as everything else it grades — otherwise it is exactly the unauditable
`.md` + `.pdf` that motivated v11.2.
