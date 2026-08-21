---
name: exocarta-database
description: Verify whether a protein/RNA/lipid has been reported as extracellular-vesicle (exosome) cargo, using curated EV repositories — ExoCarta, Vesiclepedia, exoRBase. Use ONLY when an extracellular-vesicle / exosome route is being pursued (e.g. the skin→gut EV arm). Corroboration-grade (≈ E2) evidence: a hit means "observed in EVs", never proof of a functional mechanism.
license: ExoCarta and Vesiclepedia are freely available for academic/non-commercial research; cite the source database and its publication when using data. Commercial use may require permission — check each resource.
metadata:
    skill-author: MOA-AG project (house skill)
---

# ExoCarta / EV-Cargo Databases

## Overview

Curated repositories that catalogue the molecular cargo (proteins, RNAs, lipids, and now DNA) of **extracellular vesicles (EVs) / exosomes**. They answer one specific question: *has molecule X been experimentally reported inside EVs, and in which studies/species?* They do **not** establish that an EV-borne molecule drives any downstream phenotype.

- **ExoCarta** — `exocarta.org` — small-EV / exosome-specific, manually curated. 2024 version: ~119k protein, ~15.9k RNA, ~3.9k lipid entries (DNA recently added) across **1,249 sEV studies**, 10 species, annotated to ISEV/MISEV minimal requirements. Downloadable flat files; importable into **FunRich** for enrichment.
- **Vesiclepedia** — `microvesicles.org` — **broader**: all EV subtypes + extracellular particles. 2024 version: ~567k protein, ~50k RNA, ~3.8k lipid, plus metabolite and DNA entries across **3,533 EV studies**. Use when you want cargo beyond exosomes specifically.
- **exoRBase** — human body-fluid EV **long RNAs (exLRs)** from RNA-seq (blood, urine, bile, CSF, …). Use when working with circulating-EV RNA-seq rather than the mixed-study catalogues above.

## When to Use This Skill

Use **only when an extracellular-vesicle / exosome route is actively on the table** — for this project, that is the secondary EV arm of the Q3 skin→gut question (`research_questions.md`; skin-restricted Regnase-1 KO → intestinal growth, EV as a candidate carrier). Do **not** invoke it for the core compound→disease MOA pipeline (small-molecule pharmacology has no EV component), and do not invoke it speculatively when cytokine-spillover or trafficking routes are the ones being tested.

Typical triggers:
- "Is [protein/miRNA] reported as exosome/EV cargo?"
- "Which of these skin-derived mediators have been detected in EVs?"
- Building the EV column of the Q3 Arm A mechanism table, or checking an EV-carrier hypothesis in Q3 Arm B.

## Evidence Role — corroboration only (≈ E2)

Under the project's evidence tiers (CLAUDE.md §3), a database record of EV presence is **annotation-grade (≈ E2)**:

- A hit means the molecule **has been observed in EVs** in ≥1 curated study — it raises source-convergence for an EV-cargo claim.
- It **never stands alone** and **never proves a functional skin→gut (or any) bridge**. Functional proof needs orthogonal evidence: EV depletion / GW4869 blockade, labelled-EV transfer, cargo-loading manipulation, recipient-cell readout.
- It **cannot upgrade the EV route above the cytokine-spillover lead** in the Q3 ranking on its own.
- Record the supporting **study PMIDs and species** (both DBs store them) so the claim stays traceable — a mouse-only skin→gut hypothesis should prefer mouse EV evidence and flag human-only records as indirect.
- Never cite an ExoCarta/Vesiclepedia entry as evidence of mechanism or efficacy.

## Access

**No public REST API** (as with several curated resources here) — access is the **web interface plus curated downloadable flat files**. Two practical paths:

1. **Web lookup** — search a gene/protein/RNA on `exocarta.org` (or `microvesicles.org`) to see the studies, species, and content type reporting it. Cloudflare may block automated fetches (HTTP 403); this is a browser/manual-download resource, not a scriptable endpoint.
2. **Bulk flat files** — download the curated tables and query them locally (pandas). ExoCarta publishes separate tables for **protein/mRNA details, miRNA, lipid, sEV study details, gene details, and the top-100 most-reported proteins**; Vesiclepedia offers an equivalent bulk download. Column layouts are defined on each download page — read the header row rather than assuming field names. For a repeat cross-check, download once and cache under the run's `data/` directory, then intersect your candidate list against the EV-cargo gene column.

**FunRich** (desktop tool) imports ExoCarta downloads directly for enrichment/interaction analysis if a set-level EV-enrichment read is wanted.

## Workflow — EV-cargo verification for a candidate mediator list

1. Take the candidate skin-derived mediators / RNAs (e.g. the Q3 Regnase-1-regulon List A, or a measured DE set).
2. Look each up in ExoCarta (exosome-specific) and, if broader EV subtypes are in scope, Vesiclepedia. For circulating-EV RNA, check exoRBase.
3. For every hit, capture: content type (protein/mRNA/miRNA/lipid), reporting **study PMIDs**, and **species**.
4. Annotate the candidate as **EV-cargo: reported (E2, n studies, species)** or **not reported**. "Not reported" is informative — keep the blank, don't infer absence means it cannot be EV-borne (curation is incomplete).
5. Feed the annotation into the Q3 EV column as corroboration only, and pair every retained EV hypothesis with the functional experiment (EV depletion / transfer) that would actually test it in the validation roadmap.

## Best Practices

- **State the version/access date** — these DBs update; note which release the counts came from.
- **Prefer species-matched evidence** and flag cross-species records as indirect.
- **Curation is incomplete** — absence from the DB is not evidence of absence from EVs.
- **Keep the tier honest** — EV-presence is E2 corroboration; the mechanism claim lives or dies on functional data, not on a catalogue hit.
