# miRNA→target databases — versions, schemas, thresholds, evidence tiers

Reference for the `scripts/` in this skill. Keep the version + access date in any run's methods footer.

## Evidence-tier decision (the rule the scripts encode)

| Evidence you have for a miRNA→gene edge | Tier | Where it comes from |
|---|---|---|
| Luciferase reporter **and** Western/qPCR (functional repression proven) | **E0** | miRTarBase "Functional MTI" with reporter+protein experiments |
| Functional MTI (strong) — reporter *or* protein-level | **E1** | miRTarBase "Functional MTI"; DIANA-TarBase experimentally supported |
| Binding only (AGO-CLIP / degradome / CLASH) — no functional proof of *this* gene | **E1/E2** | ENCORI CLIP support; miRTarBase "Functional MTI (Weak)" / NGS |
| Prediction, ≥2 tools agree + score threshold | **E3** | TargetScan ∩ miRDB |
| Prediction, single tool | **E3 (weak)** | one predictor — avoid; do not let it drive headlines |

Tag novel predicted edges as *"no validated MTI; refutable by luciferase/knockdown"* — never present a predicted target as established.

## Databases

### miRTarBase — validated backbone (E0/E1)
- Version: **9.0 (2022)**; **10.0 (2025)** exists. NAR 2022, PMID 34850920.
- Access: **download flat file** (per-species; hsa MTI as .xlsx/.csv). No public REST API.
- Key columns: `miRNA`, `Target Gene`, `Target Gene (Entrez ID)`, `Species (miRNA)`, `Experiments`, `Support Type`, `References (PMID)`.
- **Filter:** `Support Type == "Functional MTI"` for the strong set. `Functional MTI (Weak)` and CLIP-only rows are corroboration, not backbone.

### DIANA-TarBase v9 — validated, cell-type resolved (E0/E1)
- NAR 2024. Experimentally supported; now resolves interactions to cell types — usable to keep only skin/keratinocyte-relevant edges.
- Access: web + download (registration).

### ENCORI / starBase — CLIP-supported (E1/E2), scriptable
- API: `https://rnasysu.com/encori/api/miRNATarget/` (see `encori_targets.py`).
- Params: `assembly` (hg38), `geneType=mRNA`, `miRNA`, `clipExpNum`, `degraExpNum`, `pancancerNum`, `programNum` (0–7), `program`, `target`, `cellType`. Returns 22-col TSV (header lines start with `#`).
- Meaning: CLIP shows **binding**; keep it E1/E2 unless functional data corroborates.

### TargetScan 8.0 — predicted (E3)
- `Predicted_Targets_Context_Scores.txt` (human, hg19). Score = **context++** (negative; more negative = stronger) and **weighted context++**; conserved-site / aggregate PCT available.
- Naming caveat: keyed on **miRNA family** (miR-181-5p), not the mature name — reconcile against miRBase (see `normalize_mirnas.py`).

### miRDB v6.0 — predicted (E3)
- MirTarget score 0–100; **≥50** default cut, **≥80** high-confidence. 7,000 miRNAs, 5 species.
- Download prediction file (miRNA, RefSeq, score). Map RefSeq→symbol before intersecting with TargetScan.

### HMDD v4.0 — miRNA–disease prior (context / E1-lit leg)
- NAR 2024, PMID 37650649. 53,530 experimentally supported miRNA–disease associations; 2,360 diseases.
- **Two uses:** (a) is a cargo miRNA already linked to the disease (E1 literature leg / novelty check)? (b) v4.0 added an **exosomal-miRNA-in-disease** category — directly relevant to an exosome-cargo study.

### miRBase 22.1 — nomenclature
- Normalise mature names (`hsa-` prefix, `-5p`/`-3p`), resolve MIMAT accessions, reconcile family vs mature naming. Reachable via `bioservices`.

## Comprehensive alternative: multiMiR (R/Bioconductor)
Aggregates 14 DBs (validated: miRTarBase, TarBase, miRecords; predicted: TargetScan, miRDB, DIANA-microT, miRanda, PITA, PicTar…; + disease/drug) and auto-splits validated vs predicted. **R only** — use via `rpy2` if R is set up; otherwise use the Python-first scripts here. NAR 2014 (Ru et al.).

## Script pipeline (how the pieces connect)

```
normalize_mirnas.py   cargo names ─► normalised list (+ WARN/FAIL checks)
        │
        ├─► encori_targets.py       ─► validated_edges.csv   (E1/E2, CLIP)
        └─► query_flatfiles.py      ─► validated_edges.csv   (E0/E1, miRTarBase)
              (mirtarbase | predicted)  predicted_edges.csv  (E3, TS ∩ miRDB)
        │
        ▼
build_list_a.py  validated_edges.csv predicted_edges.csv ─► list_a.csv
                 + specificity report (target-space / predicted-fraction / hub checks)
```
