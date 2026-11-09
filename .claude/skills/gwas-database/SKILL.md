---
name: gwas-database
description: Query NHGRI-EBI GWAS Catalog for SNP-trait associations. Search variants by rs ID, disease/trait, gene, retrieve p-values and summary statistics, for genetic epidemiology and polygenic risk scores.
license: Unknown
metadata:
    skill-author: K-Dense Inc.
---

# GWAS Catalog Database

## Overview

The GWAS Catalog is a comprehensive repository of published genome-wide association studies maintained by the National Human Genome Research Institute (NHGRI) and the European Bioinformatics Institute (EBI). The catalog contains curated SNP-trait associations from thousands of GWAS publications, including genetic variants, associated traits and diseases, p-values, effect sizes, and full summary statistics for many studies.

## When to Use This Skill

This skill should be used when queries involve:

- **Genetic variant associations**: Finding SNPs associated with diseases or traits
- **SNP lookups**: Retrieving information about specific genetic variants (rs IDs)
- **Trait/disease searches**: Discovering genetic associations for phenotypes
- **Gene associations**: Finding variants in or near specific genes
- **GWAS summary statistics**: Accessing complete genome-wide association data
- **Study metadata**: Retrieving publication and cohort information
- **Population genetics**: Exploring ancestry-specific associations
- **Polygenic risk scores**: Identifying variants for risk prediction models
- **Functional genomics**: Understanding variant effects and genomic context
- **Systematic reviews**: Comprehensive literature synthesis of genetic associations

## Core Capabilities

### 1. Understanding GWAS Catalog Data Structure

The GWAS Catalog is organized around four core entities:

- **Studies**: GWAS publications with metadata (PMID, author, cohort details)
- **Associations**: SNP-trait associations as published (most p ≤ 5×10⁻⁸; suggestive hits down to ~1×10⁻⁵ are also curated, so filter yourself)
- **Variants**: Genetic markers (SNPs) with genomic coordinates and alleles
- **Traits**: Phenotypes and diseases (mapped to EFO ontology terms)

**Key Identifiers:**
- Study accessions: `GCST` IDs (e.g., GCST001234)
- Variant IDs: `rs` numbers (e.g., rs7903146) or `variant_id` format
- Trait IDs: EFO **or MONDO** terms. Many diseases moved to MONDO (type 2 diabetes `MONDO_0005148`, atopic eczema `MONDO_0004980`); the field is still called `efo_id`.
- Gene symbols: HGNC approved names (e.g., TCF7L2)

### 2. Web Interface Searches

The web interface at https://www.ebi.ac.uk/gwas/ supports multiple search modes:

**By Variant (rs ID):**
```
rs7903146
```
Returns all trait associations for this SNP.

**By Disease/Trait:**
```
type 2 diabetes
Parkinson disease
body mass index
```
Returns all associated genetic variants.

**By Gene:**
```
APOE
TCF7L2
```
Returns variants in or near the gene region.

**By Chromosomal Region:**
```
10:114000000-115000000
```
Returns variants in the specified genomic interval.

**By Publication:**
```
PMID:20581827
Author: McCarthy MI
GCST001234
```
Returns study details and all reported associations.

### 3. REST API v2 (the only live API)

> **v1 and the Summary Statistics API are gone.** Every v1 URL (`/gwas/rest/api/efoTraits/...`,
> `/singleNucleotidePolymorphisms/...`, `/studies/...`) and `https://www.ebi.ac.uk/gwas/summary-statistics/api`
> return **HTTP 410 Gone**. Use `https://www.ebi.ac.uk/gwas/rest/api/v2` (docs: https://www.ebi.ac.uk/gwas/rest/api/v2/docs).
> v2 field names are snake_case (`p_value`, `mapped_genes`, `accession_id`), not v1 camelCase (`pvalue`, `rsId`).

`scripts/gwas_v2.py` wraps it (retries, pagination, completeness assertion, exact p-values). Run
`python scripts/gwas_v2.py` for the known-answer smoke test.

| Need | v2 call (verified 2026-11) |
|---|---|
| Trait name → current ID | `GET /efo-traits?efo_trait=atopic eczema` → `MONDO_0004980` |
| Trait record | `GET /efo-traits/{id}` (404 = obsolete or unknown ID) |
| Associations for a trait | `GET /associations?efo_id=MONDO_0004980&sort=p_value&direction=asc&size=500&page=0` |
| Associations for a variant | `GET /associations?rs_id=rs7903146` |
| Associations by mapped gene | `GET /associations?mapped_gene=FLG` |
| Associations from a paper | `GET /associations?pubmed_id=37794016` |
| Variant record | `GET /single-nucleotide-polymorphisms/rs7903146` → `mapped_genes: ["TCF7L2"]` |
| Study record / studies for a trait | `GET /studies/GCST001795` · `GET /studies?efo_id=MONDO_0004980` |
| Gene record | `GET /genes/FLG` |

`/single-nucleotide-polymorphisms/{rs}/associations` is **404** in v2; use `/associations?rs_id=`.
Responses are HAL: rows under `_embedded.<collection>`, paging under `page.{totalElements,totalPages,number}`.

### 4. Two silent-zero traps

1. **Obsolete trait IDs return HTTP 200 with zero rows.** `associations?efo_id=EFO_0000274` (the old atopic
   dermatitis ID) gives `totalElements: 0`; `MONDO_0004980` gives 796. Always resolve the trait by **name**
   first and record the resolved ID. A zero for a well-studied disease is a broken query, not missing genetics.
2. **`p_value` underflows to `0.0`** for very strong hits (TCF7L2 in T2D: `p_value: 0.0`, true −log10 p ≈ 1314).
   Rank and threshold on `pvalue_mantissa` × 10^`pvalue_exponent`; `gwas_v2.neg_log10_p()` does this.

### 5. Query examples

```python
import sys; sys.path.insert(0, "scripts")
import gwas_v2 as gw

trait = gw.resolve_trait("atopic eczema")[0]          # {'efo_id': 'MONDO_0004980', 'efo_trait': 'atopic eczema', ...}
assoc = gw.get_associations(efo_id=trait["efo_id"])   # all 796, best p first; asserts len == totalElements
genes = gw.genes_from_associations(assoc)             # {gene: {n_assoc, n_gws, best_neg_log10_p, top_snp, studies, pmids}}
genes["FLG"]["n_gws"], genes["IL13"]["n_gws"]         # 8, 14

gw.get_variant("rs7903146")["mapped_genes"]           # ['TCF7L2']
gw.get_associations(rs_id="rs7903146", max_records=50)   # pleiotropy: every trait for one SNP
gw.get_study("GCST001795")["initial_sample_size"]
```

One association record (abridged):

```json
{"association_id": 118712324, "p_value": 1e-228, "pvalue_mantissa": 1, "pvalue_exponent": -228,
 "efo_traits": [{"efo_id": "MONDO_0004980", "efo_trait": "atopic eczema"}], "reported_trait": ["Atopic dermatitis"],
 "mapped_genes": ["CCDST"], "snp_allele": [{"rs_id": "rs12123821", "effect_allele": "T"}],
 "or_value": "1.27", "ci_lower": 1.25, "ci_upper": 1.29, "beta": "-", "risk_frequency": "0.05",
 "accession_id": "GCST90244787", "pubmed_id": "37794016", "first_author": "Budu-Aggrey A", "locations": ["1:152206676"]}
```

**Mapped genes are not all protein targets.** The top atopic-dermatitis loci map to `CCDST`, `LINC01527` and
`TH2LCRR` (lncRNAs) and to read-throughs such as `RTEL1-TNFRSF6B`. Before intersecting with a drug-target list,
normalise symbols to HGNC, keep protein-coding genes, and report how many mapped genes were dropped. A mapped
gene is the nearest or overlapping gene, not a proven causal gene; use Open Targets L2G or credible sets for
causal-gene assignment.

### 6. Summary statistics

Full summary statistics are **download only** (the query API is retired):
`https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics/` (per-study `GCSTxxxxxx/` folders, harmonised files
where available). Access notes: https://www.ebi.ac.uk/gwas/docs/methods/summary-statistics. Bulk catalogue
releases: `https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/` and https://www.ebi.ac.uk/gwas/docs/file-downloads.

### 7. Cross-referencing

- Ensembl / dbSNP / gnomAD for variant consequence and frequency
- Open Targets for locus-to-gene (L2G) and target–disease scores
- PGS Catalog for polygenic scores built on these associations

## Query Workflows

### Workflow 1: Genetic evidence for a disease (MOA pipeline, Step 2)

1. `resolve_trait("<disease name>")` → record the resolved ID **and** the access date.
2. `get_associations(efo_id=...)` → all rows; completeness is asserted.
3. Filter genome-wide significance on `neg_log10_p() >= 7.3`, never on `p_value`.
4. `genes_from_associations()` → per-gene `n_gws`, best p, PMIDs; normalise to HGNC protein-coding.
5. Known-answer control: a gene that must be present (FLG or IL13 for atopic dermatitis, TCF7L2 for T2D,
   FTO/MC4R for obesity). If it is absent, or the trait returns 0 rows, mark the source `FETCH_FAILED`.

### Workflow 2: One variant across traits (pleiotropy)

`get_variant(rs)` for location and mapped genes, then `get_associations(rs_id=rs)` for every trait. Compare
effect alleles before comparing directions.

### Workflow 3: One gene across traits

`get_associations(mapped_gene="FLG")` lists every curated association whose mapped genes include the symbol.
This is proximity-based mapping, not proof that the gene drives the association.

### Workflow 4: Systematic review of genetic evidence

Pull all associations for the resolved trait, group by `accession_id` (study) and `pubmed_id`, record sample
size and ancestry from `get_study()`, separate discovery from replication, and document the query, resolved
trait ID and access date.

## Best Practices


### Query Strategy
- Resolve trait IDs by name through `/efo-traits?efo_trait=` (IDs migrate between EFO and MONDO)
- Use API for bulk data extraction and automated analyses
- Implement pagination handling for large result sets
- Cache API responses to minimize redundant requests

### Data Interpretation
- Always check p-value thresholds (genome-wide: 5×10⁻⁸)
- Review ancestry information for population applicability
- Consider sample size when assessing evidence strength
- Check for replication across independent studies
- Be aware of winner's curse in effect size estimates

### Rate Limiting and Ethics
- Respect API usage guidelines (no excessive requests)
- Use summary statistics downloads for genome-wide analyses
- v2 is slow (tens of seconds for a large page) and occasionally drops connections; use timeouts of at least 180 s and retries (`gwas_v2._get` does both)
- Cache results locally when performing iterative analyses
- Cite the GWAS Catalog in publications

### Data Quality Considerations
- GWAS Catalog curates published associations (may contain inconsistencies)
- Effect sizes reported as published (may need harmonization)
- Some studies report conditional or joint associations
- Check for study overlap when combining results
- Be aware of ascertainment and selection biases

## Resources

### scripts/gwas_v2.py
`resolve_trait`, `get_associations`, `neg_log10_p`, `genes_from_associations`, `get_variant`, `get_study`,
`get_studies_for_trait`. `python scripts/gwas_v2.py` runs the known-answer smoke test (atopic eczema, rs7903146, T2D).

### references/api_reference.md
v2 endpoint and field reference, with the v1 → v2 mapping.

## Important Notes

### Data Updates
- The GWAS Catalog is updated regularly with new publications
- Re-run queries periodically for comprehensive coverage
- Summary statistics are added as studies release data
- EFO mappings may be updated over time

### Citation Requirements
When using GWAS Catalog data, cite:
- Cerezo M, et al. (2025) The NHGRI-EBI GWAS Catalog: standards for reusability, sustainability and diversity. Nucleic Acids Research 53(D1):D998-D1005. PMID: 39530240
- Sollis E, et al. (2023) The NHGRI-EBI GWAS Catalog: knowledgebase and deposition resource. Nucleic Acids Research 51(D1):D977-D985. PMID: 36350656
- Include access date and version when available
- Cite original studies when discussing specific findings

### Limitations
- Not all GWAS publications are included (curation criteria apply)
- Full summary statistics available for subset of studies
- Effect sizes may require harmonization across studies
- Population diversity is growing but historically limited
- Some associations represent conditional or joint effects

### Data Access
- Web interface: Free, no registration required
- REST API v2: Free, no API key needed
- FTP downloads: Open access
- Rate limiting applies to API (be respectful)

## Additional Resources

- **GWAS Catalog website**: https://www.ebi.ac.uk/gwas/
- **REST API v2 docs**: https://www.ebi.ac.uk/gwas/rest/api/v2/docs
- **Summary statistics access**: https://www.ebi.ac.uk/gwas/docs/methods/summary-statistics
- **FTP (HTTPS)**: https://ftp.ebi.ac.uk/pub/databases/gwas/
- **Training materials**: https://github.com/EBISPOT/GWAS_Catalog-workshop
- **PGS Catalog** (polygenic scores): https://www.pgscatalog.org/
- **Help and support**: gwas-info@ebi.ac.uk
