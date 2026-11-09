---
name: monarch-database
description: Query the Monarch Initiative knowledge graph for disease-gene-phenotype associations across species. Integrates OMIM, ORPHANET, HPO, ClinVar, and model organism databases. Use for rare disease gene discovery, phenotype-to-gene mapping, cross-species disease modeling, and HPO term lookup.
license: CC0-1.0
metadata:
    skill-author: Kuan-lin Huang
---

# Monarch Initiative Database

## Overview

The Monarch Initiative (https://monarchinitiative.org/) is a multi-species integrated knowledgebase that links genes, diseases, and phenotypes across humans and model organisms. It integrates data from over 40 sources including OMIM, ORPHANET, HPO (Human Phenotype Ontology), ClinVar, MGI (Mouse Genome Informatics), ZFIN (Zebrafish), RGD (Rat), FlyBase, and WormBase.

Monarch enables:
- Mapping phenotypes across species to identify candidate disease genes
- Finding all genes associated with a disease or phenotype
- Discovering model organisms for human diseases
- Navigating the HPO hierarchy for phenotype ontology queries

**Key resources:**
- Monarch portal: https://monarchinitiative.org/
- Monarch API v3 base: https://api-v3.monarchinitiative.org/v3/api  (the `/api` segment is required — without it every call 404s)
- API docs: https://api-v3.monarchinitiative.org/v3/docs
- HPO browser: https://hpo.jax.org/

## When to Use This Skill

Use Monarch when:

> **Coverage first.** Monarch is Mendelian-focused. A complex disease (atopic dermatitis, psoriasis, obesity,
> RA) can return **zero genes** on its main ID — atopic eczema `MONDO:0004980` returns 0 — while one or two
> curated genes sit on `<disease>, susceptibility to` and numbered OMIM loci (FLG on `MONDO:0100178`,
> `MONDO:0011596`). That zero is a coverage gap: record it as *no curated gene–disease associations*, do not
> mark the fetch failed, and do not list Monarch as a contributing source. Prove the fetch itself works with
> a Mendelian control (cystic fibrosis `MONDO:0009061` → CFTR `causes`).


- **Rare disease gene discovery**: What genes are associated with my patient's phenotypes (HPO terms)?
- **Phenotype similarity**: Are two diseases similar based on their phenotypic profiles?
- **Cross-species modeling**: Are there mouse/zebrafish models for my disease of interest?
- **HPO term lookup**: Retrieve HPO term names, definitions, and ontology hierarchy
- **Disease-phenotype mapping**: List all HPO terms associated with a specific disease
- **Gene-phenotype associations**: What phenotypes are caused by variants in a gene?
- **Ortholog-phenotype mapping**: Use animal model phenotypes to infer human gene function

## Core Capabilities

All examples use `scripts/monarch_v3.py` (paginated, retrying, row totals asserted). Run
`python scripts/monarch_v3.py` for the known-answer smoke test.

### 1. API basics

```python
import sys; sys.path.insert(0, "scripts")
import monarch_v3 as m

# GET https://api-v3.monarchinitiative.org/v3/api/association?object=MONDO:0009061&subject_category=biolink:Gene
rows = m.associations(object="MONDO:0009061", subject_category="biolink:Gene")
rows[0]
# {'subject': 'HGNC:11073', 'subject_label': 'SLC9A3', 'subject_taxon': 'NCBITaxon:9606',
#  'predicate': 'biolink:gene_associated_with_condition', 'object': 'MONDO:0009061',
#  'object_label': 'cystic fibrosis', 'primary_knowledge_source': 'infores:orphanet', 'category': ...}
```

Items are **flat strings** — `item["subject_label"]`, not `item["subject"]["name"]` (that raises
`AttributeError: 'str' object has no attribute 'get'`). Filters: `subject`, `object`, `subject_category`,
`object_category`, `predicate`, `category`, `subject_taxon`. Response: `{limit, offset, total, items}`.

### 2. Disease → genes

```python
genes = m.disease_genes("MONDO:0009061")          # human genes, descendant diseases included
[g for g in genes if g["predicate"] == "causes"]  # [{'symbol': 'CFTR', 'source': 'infores:omim', ...}]
```

Predicates, strongest first: `causes` (OMIM, Mendelian) → `contributes_to` (susceptibility) →
`gene_associated_with_condition` (Orphanet; includes modifiers such as SLC9A3, HMOX1 for CF).
Keep the predicate — a modifier gene is not a causal gene.

For a complex disease, also collect the susceptibility entries and report which entry each gene came from:

```python
m.disease_genes_with_susceptibility("atopic dermatitis")
# {'MONDO:0011596 dermatitis, atopic, 2': [FLG], 'MONDO:0100178 dermatitis, atopic, susceptibility to': [FLG],
#  'MONDO:0054697 immunodeficiency 11b with atopic dermatitis': [CARD11]}   <- a distinct syndrome; exclude
```

### 3. Disease ↔ phenotypes, gene ↔ phenotypes / diseases

```python
m.disease_phenotypes("MONDO:0009061")    # 84 HPO terms   (category DiseaseToPhenotypicFeatureAssociation)
m.gene_phenotypes("HGNC:1884")           # CFTR: 38 HPO terms (category GeneToPhenotypicFeatureAssociation)
m.gene_diseases("HGNC:1884")             # CFTR: 10 diseases  (object_category biolink:Disease)
m.phenotype_genes("HP:0001250", max_items=1000)   # Seizure incl. descendant terms (~3.3k rows total)
```

### 4. Lookup and search

```python
m.entity("HP:0001250")["name"]                    # 'Seizure'
m.entity("MONDO:0004980")["xref"]                 # includes 'EFO:0000274' -> map old EFO ids to MONDO
m.search("atopic dermatitis", "biolink:Disease")  # MONDO:0004980 atopic eczema, MONDO:0011608 ...
m.search("epilepsy", "biolink:PhenotypicFeature")
```

### 5. Phenotype similarity

```python
s = m.compare_termsets(["HP:0001250", "HP:0001252"], ["HP:0001250", "HP:0002353"])
s["average_score"], s["best_score"], s["subject_best_matches"]
```

This is `GET /semsim/compare/{subjects}/{objects}` with comma-separated HPO IDs. The query-parameter form
(`/semsim/compare?subjects=...&objects=...`) returns **405**. To compare two diseases, fetch
`disease_phenotypes()` for each and compare the HPO lists.

### 6. Model organisms and orthologs

```python
m.disease_models("MONDO:0004980")   # 32 mouse genotypes 'model_of' atopic eczema (Trpv3, Casp8 ...)
m.orthologs("HGNC:1100")            # BRCA1 orthologs: dog, chicken, ...
```

Animal-model genotypes are cross-species evidence (E2/E4 in this project's tiers), never a human gene–disease
edge on their own.

### 7. Rare-disease gene ranking from patient phenotypes

```python
from collections import Counter
patient = ["HP:0001250", "HP:0004322", "HP:0001252", "HP:0000252", "HP:0001263"]
hits = Counter()
for hp in patient:
    for g in {r["symbol"] for r in m.phenotype_genes(hp, max_items=2000)}:
        hits[g] += 1
hits.most_common(20)     # genes matching the most patient phenotypes
```

`phenotype_genes` includes descendant HPO terms, so broad terms (Seizure) return thousands of rows; prefer
specific terms, or use `compare_termsets` against each candidate's phenotype set.

## Query Workflows

### Workflow 1: HPO-Based Differential Diagnosis

1. Extract HPO terms from clinical notes or genetics consultation
2. Run phenotype-to-gene query against Monarch
3. Rank candidate genes by number of matching phenotypes
4. Cross-reference with gnomAD (constraint scores) and ClinVar (variant evidence)
5. Prioritize genes with high pLI and known pathogenic variants

### Workflow 2: Disease Model Discovery

1. Identify gene or disease of interest
2. Query Monarch for cross-species orthologs
3. Find phenotype associations in model organism databases
4. Identify experimental models that recapitulate human disease features

### Workflow 3: Phenotype Annotation of Novel Genes

1. For a gene with unknown function, query all known phenotype associations
2. Map to HPO hierarchy to understand affected body systems
3. Cross-reference with OMIM and ORPHANET for disease links

## Common Identifier Prefixes

| Prefix | Namespace | Example |
|--------|-----------|---------|
| `HP:` | Human Phenotype Ontology | HP:0001250 (Seizures) |
| `MONDO:` | Monarch Disease Ontology | MONDO:0007739 |
| `OMIM:` | OMIM disease | OMIM:104300 |
| `ORPHANET:` | Orphanet rare disease | ORPHANET:558 |
| `HGNC:` | HGNC gene symbol | HGNC:7884 |
| `NCBIGene:` | NCBI gene ID | NCBIGene:4137 |
| `ENSEMBL:` | Ensembl gene | ENSEMBL:ENSG... |
| `MGI:` | Mouse gene | MGI:1338833 |
| `ZFIN:` | Zebrafish gene | ZFIN:ZDB-GENE... |

## Best Practices

- **Use MONDO IDs** for diseases — they unify OMIM/ORPHANET/MESH identifiers
- **Use HPO IDs** for phenotypes — the standard for clinical phenotype description
- **Handle pagination**: Large queries may require iterating with offset parameter
- **Semantic similarity is better than exact match**: Ancestor HPO terms catch related phenotypes
- **Cross-validate with ClinVar and OMIM**: Monarch aggregates many sources; quality varies
- **Use HGNC IDs for genes**: More stable than gene symbols across database versions

## Additional Resources

- **Monarch portal**: https://monarchinitiative.org/
- **API v3 docs**: https://api-v3.monarchinitiative.org/v3/docs
- **HPO browser**: https://hpo.jax.org/
- **MONDO ontology**: https://mondo.monarchinitiative.org/
- **Citation**: Shefchek KA et al. (2020) Nucleic Acids Research. PMID: 31701156
- **Phenomizer** (HPO-based diagnosis): https://compbio.charite.de/phenomizer/
