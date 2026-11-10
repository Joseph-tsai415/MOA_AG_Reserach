---
name: pbl-report
description: Use when writing, revising or reviewing a problem-based learning (PBL) group report, tutorial write-up or case-based teaching report from a medical-school case, especially one delivered in acts (教案, 第一幕, 小組報告, 學習議題, 概念圖, concept map, learning issues).
---

# PBL Report

## Overview

A PBL report has to teach, not only be correct. Citation and number gates test whether statements are true; none of them tests whether the explanation is sufficient. A report can pass every gate and still leave a reader unable to explain the disease.

**Core test: could a reader explain the disease and defend the conclusion using only this report?**

**Route.** A PBL case has no compound, so it is a `reviews/{topic}/` deliverable under CLAUDE.md §8, not the Step 1–5 pipeline. `report-qa` runs last and uses SANRA (PRISMA is N-A). Build the PDF with `report-pdf`. Word output uses `scripts/pbl_docx.py`.

## Before writing

1. Read every case page. Transcribe its numbers into `data/case_facts.json`, by posture and time. Ask for the course's required format and word limit if you do not have them.
2. Look for missing acts. If the case stops before treatment, say so and do not guess the rest.
3. Read the case's reproduction notice. Keep the report course-internal, and ask before embedding a case image.
4. Treat example reports as format references, never as answer keys. Check any fact from them against a primary source. Student reports contain dose, unit and threshold errors.
5. Choose sources by teaching need, not ease of retrieval. Secure at least one key guideline in full and one physiology-level source. If that fails, say so in the report.

## Report shape

Write these parts, in this order:

| # | Part | Contents |
|---|---|---|
| 1 | Opening | One-sentence problem representation, the conclusion, and what would overturn it |
| 2 | Concept map | Full page. See `references/figures.md` |
| 3 | Case and issues | Case summary table, numbered learning issues |
| 4 | Physiology | Normal function, then why it fails |
| 5 | Frame | Definitions and classification |
| 6–8 | One section per act | Headed with its act and issue numbers. Use every clue |
| 9 | Central mechanism | The longest explanatory section. See below |
| 10 | Psychosocial | Labels, family, communication, what the patient and bystanders can do |
| 11 | Issue answers | Table: each learning issue, a one-line answer, the section |
| 12 | Sources and limits | Search as actually run, what could not be read, AI assistance |
| 13 | References | Then a one-line methods note |

Keep anything the case does not raise to one short paragraph.

## Explaining

Build each topic in this order: **normal physiology → what fails → this patient's data → labelled inference.**

The central mechanism section is continuous prose that walks a causal chain from trigger to symptom, states what is debated, then replays the chain through this patient's episode.

Map each symptom in the case to a mechanism, or state that the sources do not explain it. Mark what the case leaves out as things to ask next. Use one term per concept.

Apply criteria to the patient's own numbers, by posture and time. Each test gets: the question it answers, the result, and what the result cannot show. Read case images step by step, naming the feature that supports each statement, and separate what the case records from what you read off the figure.

Label every inference, using a marker defined at the top of the report. Keep a statistic only if it changes a decision.

## Evidence and gates

`scripts/templates/` holds working versions of both gates. Copy them into the run's `scripts/` and adapt them.

- **Citations:** markers `[[E12]]` in `report_src.md` point at `data/evidence.json`, where each entry holds a verbatim quote from stored source text plus the numbers it must carry. The build renders the citations and reference list. Merge consecutive same-source sentences under one citation.
- **Lineage:** recompute every derived number from `case_facts.json`.
- **Sufficiency:** list the terms a reader needs for this disease and fail the build if any is missing, require a minimum length for the mechanism section, require a stated controversy, and require an answer for every learning issue. A sufficiency failure means add the explanation, never lower the threshold.

Before `report-qa`, re-read the sources around each quote. A quote can be verbatim and still mislead if the next sentence qualifies it.

Then do a cold read: give the report to a reader who has not seen the work (a classmate, or a fresh agent with only the report) and have them explain the disease back. Rewrite wherever they stumble. Compare against any peer reports available, since gates cannot show what a better explanation looks like.

## Common mistakes

| Mistake | Fix |
|---|---|
| Report reads as a list of true claims | Write the causal chain as prose |
| Concept map repeats the differential table | Put mechanism in the map |
| Figure repeats a table | Show what the table cannot, such as a time window |
| Treatment section outruns the case | One paragraph, stated as general principles |
| Different conditions read as a trend | Compare only like with like |
| Guideline cited from a summary | Find the full text, or disclose the limit |
| "Reused nothing" written while reusing a figure | Name every direct reuse and its origin |
| Search described better than it ran | Save the queries and describe them exactly |
| A number stated as plain physiology | Say where it was measured: animal or human, whose pressure, which conditions |
| Event order assumed from logic | Take the sequence from the source, and put early symptoms in the phase the source gives |
| Symptom linked to a mechanism by default | Link only what a source supports. Mark the rest unexplained |
| Bystander advice copied step by step, losing the emergency step | Read the source's next sentence. Include when to call for help |
| "No source exists" written after a failed fetch | Try the page itself before declaring a gap |
