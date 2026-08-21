---
name: cellphonedb
description: Infer cell–cell communication (ligand–receptor interactions) from single-cell RNA-seq using CellPhoneDB v5 — a curated repository of ~2,912 human L-R interactions plus a permutation-based statistical tool. Use for the RECEPTOR side of a signalling hypothesis (does the recipient cell express the receptor for a candidate ligand). HUMAN-only; needs annotated scRNA-seq. Predicted (≈ E3) evidence gated by its own permutation p-value; co-expression is not proof of functional signalling.
license: CellPhoneDB is open-source (Apache-2.0), freely available at github.com/ventolab/CellphoneDB; cite the CellPhoneDB v5 Nature Protocols paper (2024) when used.
metadata:
    skill-author: MOA-AG project (house skill)
---

# CellPhoneDB — Cell–Cell Communication (Ligand–Receptor)

## Overview

CellPhoneDB pairs a **manually curated repository of human ligand–receptor (L-R) interactions** with a statistical method that tests, from your single-cell data, whether a ligand in one cell population and its receptor in another are co-expressed more than expected by chance. It answers the **receptor-side** question a bridge hypothesis needs: *not just "is ligand X secreted", but "does the target cell actually express the receptor for X".*

- **Version:** CellPhoneDB **v5** (Nature Protocols 2024, DOI 10.1038/s41596-024-01137-1). Database **v5.0.0 = 2,912 curated interactions**, including ~1,000 non-peptidic ligands (steroid hormones, neurotransmitters, small-molecule GPCR ligands). Multi-subunit complexes are modelled explicitly (a receptor counts only if *all* subunits are expressed).
- **Directionality:** partners are ordered **ligand = partner A, receptor = partner B**, and interactions are classified into signalling pathways — so the tool gives a *direction*, useful for the pipeline's directionality check.
- **CellSign module:** prioritises high-confidence hits by checking whether a **transcription factor downstream of the receptor** is active (211 curated receptor→TF relationships) — i.e. evidence the signal was actually *received*, not just that the receptor is present.
- **Repos:** code `github.com/ventolab/CellphoneDB`; data `github.com/ventolab/cellphonedb-data`; docs `cellphonedb.readthedocs.io`.

## When to Use This Skill

Use when you have **annotated single-cell (or single-nucleus) RNA-seq** and want to test **cell–cell signalling / ligand–receptor engagement between cell populations**. For this project the primary use is the **Q3 skin→gut question** (`research_questions.md`): the reframed bridge asks how a skin-derived signal is *received* by intestinal cells — CellPhoneDB supplies the **receptor-end validation** that a ligand-only List A cannot (a mediator rising in circulation only matters if the gut expresses its receptor).

Two modes:
1. **Data-driven inference** (main use) — needs real scRNA-seq; outputs statistically-tested L-R calls between cell types.
2. **Database lookup only** — query the curated 2,912-interaction table for "what is the receptor for ligand X / what pathway" **without** any data. Useful for building the receptor column of a mechanism table even before scRNA-seq exists.

**Do NOT** use it for the core small-molecule compound→disease MOA pipeline (no cell-population communication there), and do not present a co-expression call as proof of functional signalling.

## ⚠️ Critical constraints (read before proposing it)

- **HUMAN-only.** The curated interactions are human. The Q3 project is currently in its **mouse phase** — mouse scRNA-seq must be **ortholog-mapped to human gene symbols** before running, and every cross-species mapping is a caveat, not a free lunch. Flag this explicitly; do not run mouse genes against the human DB silently.
- **Needs a real, cell-type-annotated dataset** — it is an analysis tool, not a pure query DB (except the lookup mode above). No scRNA-seq ⇒ only the reference-table use is available.
- **Co-expression ≠ functional signalling.** A significant L-R call means ligand and receptor are co-expressed in the right cell pair above chance — it is an **in-silico prediction**, not proof the pathway fires. Functional proof needs perturbation (receptor KO/blockade, ligand neutralisation, reporter readout).

## Evidence Role — predicted, but self-gated (≈ E3)

Under the project's evidence tiers (CLAUDE.md §3):

- The **curated L-R pair itself** is a bona-fide, literature-reviewed interaction — it gives the *biological plausibility* of the pairing (reference-grade).
- The **cell-type-specific communication call from your data** is an **E3 predicted** claim — but it arrives **already gated by CellPhoneDB's own permutation test** (default 1,000 shuffles of cell labels → an empirical p-value per L-R per cell-pair). That permutation p < 0.05 **doubles as the specificity control** §3 demands for an intersection — keep p < 0.05 and, per house rules, still sanity-check against a decoy cell-pair / random-label expectation.
- **CellSign TF activity**, when it agrees, is an extra independent leg that raises convergence toward "the receptor's downstream programme is on".
- It **never stands alone as mechanism** — pair every retained L-R hypothesis with the functional experiment that would kill it, in the validation roadmap.

## Installation & Environment

Install into the project's conda env (`moa`, Python 3.12 — CLAUDE.md §7):

```
conda activate moa
pip install cellphonedb        # v5.x (PyPI: cellphonedb 5.0.x)
```

Download the database (v5.0.0) once via the tool's `notebooks/T0_DownloadDB.ipynb` flow or `cellphonedb.utils.db_utils` and cache it under the run's `data/` directory.

**Windows note (per CLAUDE.md §7):** the statistical method spawns worker processes for permutations — run it from a **script file with an `if __name__ == "__main__":` guard** (not `python -c`), and set threads/cpus low if joblib/loky misbehaves on Windows.

## Inputs

- **Counts** — normalised (log or CPM/TPM-normalised, **not** raw) expression as an **AnnData `.h5ad`** (or a counts matrix). Use human gene symbols / Ensembl IDs matching the DB.
- **Metadata** — a table mapping each barcode to a **`cell_type`** annotation (the populations to test between).
- **DEGs file (method 3 only, mandatory)** — a table with columns **`cell_type`** and **`gene`** listing per-cell-type differentially expressed genes.
- **(Optional) microenvironments** — restrict tested cell-pairs to those that physically co-occur, cutting false pairs.

## Methods (pick by question)

| Method | What it does | When |
|---|---|---|
| **1 — simple analysis** | mean L-R expression per cell-pair, no test | quick scan |
| **2 — statistical_analysis** | permutation test (label shuffling) → empirical p per L-R × cell-pair | **default** — gives the specificity-gated calls |
| **3 — degs_analysis** | uses your DEG list to call interactions | when you already have DE per cell type |
| **CellSign** | adds receptor→TF activity prioritisation | to rank high-confidence "signal received" hits |

## Workflow — receptor-side validation for a skin→gut bridge

1. Assemble candidate **ligands** = the skin-derived mediators of Q3 List A (Regnase-1 regulon: IL-6, IL-23/IL-17-axis, etc.) — or their measured-DE version.
2. Get **intestinal scRNA-seq** (KO gut, human-mapped) with cell-type annotations.
3. Run **method 2 (statistical_analysis)** to test which gut cell types significantly express the **receptors** for those ligands (e.g. IL6R/IL6ST on crypt/epithelial cells; IL22RA1 on enterocytes).
4. Keep only **p < 0.05** L-R calls; sanity-check against a decoy cell-pair. Add **CellSign** to flag where the downstream TF (e.g. STAT3) is active.
5. Record each surviving pair as **E3 predicted (ligand→receptor, cell-pair, p, TF-active?)** and feed it into the Step-3 intersection / Step-4 directional MOA — then attach the killing experiment (receptor blockade / ligand neutralisation) to the validation roadmap.

## Best Practices

- **State species handling** — if mouse data, document the ortholog-mapping step and treat cross-species calls as indirect.
- **Report the p-value and permutation count** — a bare L-R arrow without its statistic is not a specificity-gated result.
- **Multi-subunit honesty** — CellPhoneDB requires all complex subunits expressed; don't override that to force a hit.
- **Keep the tier honest** — an L-R call is an E3 co-expression prediction; the mechanism claim lives or dies on functional perturbation, not on a significant arrow.
- **Version/date** — note DB version (v5.0.0) and access date; the repository updates.
