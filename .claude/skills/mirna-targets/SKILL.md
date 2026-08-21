---
name: mirna-targets
description: Build the miRNA→target-gene layer (List A engine) for a miRNA/exosome-cargo MOA run — resolve which genes a miRNA represses, tiered as validated (miRTarBase / DIANA-TarBase / ENCORI-CLIP = E0/E1) vs predicted (TargetScan / miRDB = E3), normalise names via miRBase, and pull miRNA–disease priors from HMDD (incl. its exosomal-miRNA category). Use when the "active ingredient" is a miRNA set. miRNAs DOWN-regulate targets — direction is built in.
license: Aggregated resources (miRTarBase, TargetScan, miRDB, DIANA-TarBase, ENCORI/starBase, HMDD, miRBase) are free for academic/non-commercial use; cite each source database used. Some prohibit commercial redistribution — check per resource.
metadata:
    skill-author: MOA-AG project (house skill)
---

# miRNA → Target Layer (List A engine for miRNA/exosome MOA)

## Overview

When the agent under study is a **miRNA cargo** (e.g. an exosome whose payload is a defined miRNA set), *List A is not "compound→targets" but "miRNA→repressed target genes"*. This skill assembles that layer with an explicit **validated-vs-predicted evidence tier on every edge**, and normalises miRNA identities so nothing is lost to naming.

The one biological fact that shapes everything: **a miRNA down-regulates its target** (mRNA decay / translational repression). So the modulation direction is **built in** — miR-X ↓ target-gene-Y — no agonist/antagonist ambiguity. Therapeutic logic for a disease: repression is helpful when the target is **pro-pathogenic and up in the disease**.

## When to Use This Skill

Use when the pipeline's **List A** must be derived from **miRNAs rather than a small molecule** — the exosomal-miRNA-cargo × disease MOA runs (e.g. hAMSC/hAESC exosome × atopic dermatitis). It is the required engine for that reframing; without it there is no List A.

Do **not** use it for small-molecule compound→target runs (that is `chembl`/`bindingdb`/etc.), and do not present a *predicted* target as an established one.

## ⚠️ The make-or-break risk: target-space explosion

A cargo of **~40 miRNAs** predicts targets across a **huge fraction of the transcriptome** (each miRNA → hundreds of predicted targets; the union can be many thousands of genes). If List A is built from *predicted* targets naively, **every pathway will "enrich" and the result is meaningless** — the miRNA analogue of the PAINS/promiscuity problem. Mandatory countermeasures:

- **Anchor List A on VALIDATED targets (E0/E1)** as the backbone; treat predicted targets as hypothesis-only.
- For predicted edges, require **≥2 independent predictors agreeing** (e.g. TargetScan ∩ miRDB) **and** a score threshold (see below) — never a single-tool prediction alone.
- Carry the **per-edge tier** into Step 3 so the specificity gate (permutation-p, decoy disease) and the v11 **enrichment-integrity** check (are the disease's *defining* genes actually hit, not just generic umbrellas) can do their job.
- **Log how many targets were dropped** by each filter — silent inclusion of the full predicted union reads as "comprehensive" when it is just noise.

## Evidence tiers — map every miRNA→target edge

| Source | What it is | Tier | Notes |
|---|---|---|---|
| **miRTarBase** "Functional MTI" — **strong** evidence (luciferase reporter + Western/qPCR) | experimentally validated | **E0/E1** | strongest; the backbone of List A |
| **DIANA-TarBase v9** experimentally supported (now cell-type resolved) | experimentally validated | **E0/E1** | good second validated source; can be tissue/cell filtered |
| **miRTarBase / ENCORI CLIP-seq / degradome** (AGO-CLIP, CLASH) | high-throughput evidence of binding | **E1/E2** | binding ≠ functional repression on its own — corroboration |
| **TargetScan 8.0** (conserved sites; weighted context++ score, aggregate PCT) | computational prediction | **E3** | hypothesis-only; keep the score, prefer conserved sites |
| **miRDB v6.0** (MirTarget score 0–100, ≥80 = high-confidence) | computational prediction | **E3** | hypothesis-only; use ≥80 for a stringent set |
| **HMDD v4.0** miRNA–disease association | prior on the miRNA–disease axis (not a target) | context / E1-lit leg | see below |

**Rule:** a target may enter List A at the confidence its *highest independently-corroborated* source supports. A predicted-only target is **E3 (hypothesis, "no validated MTI; refutable by luciferase/knockdown")** — never dressed as established.

## Databases & access (Python-first)

The project env is Python (`moa`, 3.12). None of these has a single unified Python client, so combine:

1. **ENCORI / starBase Web API** — `rnasysu.com/encori` — **Python-native** programmatic access (Shell/Python/curl); >1M miRNA–mRNA interactions with **AGO-CLIP support**. Best scriptable validated/CLIP source. Fetch into the run's `data/`.
2. **Downloaded flat files → query locally with pandas** (the exocarta/hmdb pattern):
   - **miRTarBase** (release **9.0**, 2022; a **10.0/2025** release exists) — per-species MTI table (miRNA, target gene, experiment type, support type, PMID). Filter `Support Type = "Functional MTI"` for the E0/E1 backbone.
   - **TargetScan 8.0** — `Predicted_Targets_Context_Scores` (human, hg19); columns include miRNA family, gene, context++ score, weighted context++, conserved/PCT.
   - **miRDB v6.0** — prediction table (miRNA, gene, MirTarget score).
3. **miRBase** (release 22.1) — **name normalisation**: the 40 cargo names are mature miRNAs (`-5p`/`-3p`); prefix species (`hsa-`), resolve to MIMAT accessions, and reconcile TargetScan's *miRNA-family* naming vs the mature-name naming the others use (a frequent silent-mismatch bug). Reachable via `bioservices` or the miRBase download.
4. **HMDD v4.0** (`cuilab.cn/hmdd`) — experimentally supported human miRNA–disease associations (53,530 entries, 2,360 diseases). **Two uses here:** (a) an **E1 literature leg** on the miRNA–disease axis — is this cargo miR already linked to the disease? (b) HMDD v4.0 added a dedicated **exosomal-miRNA-in-disease category** — directly relevant to an exosome-cargo study; use it to see which cargo miRNAs have prior exosomal-disease evidence.

**Comprehensive alternative (R):** **multiMiR** (Bioconductor) aggregates 14 DBs (validated: miRTarBase, TarBase, miRecords; predicted: TargetScan, miRDB, DIANA-microT, miRanda/PITA/PicTar…; + disease/drug) behind one query and auto-splits validated vs predicted. It is **R**, not Python — use it via `rpy2` **only if** R/Bioconductor is set up in the env; otherwise stay on the Python-first path above. It is the fastest way to a tiered table if R is available.

## Workflow — build List A from an exosome's miRNA cargo

1. **Normalise** the cargo miRNA names in miRBase (`hsa-` prefix, `-5p/-3p`, MIMAT accessions); note any that don't resolve.
2. **Validated backbone (E0/E1)** — pull miRTarBase "Functional MTI (strong)" + DIANA-TarBase targets for each miRNA; add ENCORI CLIP-supported hits as E1/E2.
3. **Predicted layer (E3)** — TargetScan ∩ miRDB with thresholds (miRDB ≥ 80; TargetScan conserved / strong context++); tag hypothesis-only, record scores, count what was dropped.
4. **Assemble List A** = union with per-edge `source, evidence_tier, score/PMID, n_supporting_miRNAs` (a gene hit by several cargo miRNAs ranks higher, analogous to a multi-compound hit).
5. **Direction** — every edge is `miRNA ↓ gene`; this feeds Step 4's directionality check directly (repression is therapeutic when the gene is up-in-disease / pro-pathogenic).
6. **Disease prior** — annotate each cargo miRNA with its HMDD disease links (and exosomal-miRNA evidence) as an E1 leg / novelty check.
7. Hand List A to Step 3 **with tiers intact** so the specificity + enrichment-integrity gates run on it.

## Bundled scripts (runnable) & reference

Each script carries its own CHECKS (the `[WARN]`/`[FAIL]`/`[SCHEMA FAIL]` guards) so a broken input or a promiscuous target space fails loudly instead of silently producing a wrong List A. Run in the `moa` env; they use `if __name__ == "__main__"` guards (Windows-safe, §7).

| Script | Usage | Built-in checks |
|---|---|---|
| `scripts/normalize_mirnas.py` | normalise cargo miRNA names (`hsa-`, `-5p/-3p`), first step | flags arm-less names, malformed names, duplicates; non-zero exit on FAIL so a driver can gate |
| `scripts/encori_targets.py` | validated/CLIP edges from the ENCORI Web API (Python-native, no download) | distinguishes "0 targets = coverage gap" from "fetch failed"; per-miRNA empty report |
| `scripts/query_flatfiles.py` | query downloaded miRTarBase (validated) + TargetScan/miRDB (predicted) | asserts expected columns exist (schema drift → loud fail); miRTarBase strong-functional filter → E0/E1; TargetScan ∩ miRDB intersection as the anti-promiscuity filter |
| `scripts/build_list_a.py` | assemble the tiered List A from edge CSVs | **specificity report**: target-space size, predicted-only fraction, multi-hit hub count — the make-or-break guard against a 40-miRNA blob |

Reference: `references/databases_and_tiers.md` — versions, download schemas, score thresholds, the evidence-tier decision table, HMDD usage, and how the scripts connect into one pipeline.

## Best Practices

- **Validated-first, predicted-as-hypothesis** — never let a predicted-only union drive the headline pathways.
- **Keep names reconciled** — TargetScan family vs mature-name mismatches silently drop real edges; verify against miRBase.
- **Species honesty** — most validated data is human; if working from mouse cargo, map orthologs and flag it.
- **Record thresholds & drops** — state miRDB/TargetScan cutoffs and how many predicted targets were filtered out.
- **Version/date** — note miRTarBase 9.0 (or 10.0), TargetScan 8.0, miRDB v6.0, HMDD v4.0, miRBase 22.1 and access date.
- **Binding ≠ repression** — CLIP/degradome shows binding; functional repression of the *specific* gene still needs a reporter/knockdown, so keep those E1/E2 not E0.
