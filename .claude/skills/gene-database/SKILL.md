---
name: gene-database
description: Query NCBI Gene via E-utilities/Datasets API. Search by symbol/ID, retrieve gene info (RefSeqs, GO, locations, phenotypes), batch lookups, for gene annotation and functional analysis.
license: Unknown
metadata:
    skill-author: K-Dense Inc.
---

# Gene Database

## Overview

NCBI Gene is a comprehensive database integrating gene information from diverse species. It provides nomenclature, reference sequences (RefSeqs), chromosomal maps, biological pathways, genetic variations, phenotypes, and cross-references to global genomic resources.

## When to Use This Skill

This skill should be used when working with gene data including searching by gene symbol or ID, retrieving gene sequences and metadata, analyzing gene functions and pathways, or performing batch gene lookups.

## Quick Start

NCBI provides two main APIs for gene data access:

1. **E-utilities** (Traditional): Full-featured API for all Entrez databases with flexible querying
2. **NCBI Datasets API** (Newer): Optimized for gene data retrieval with simplified workflows

Choose E-utilities for complex queries and cross-database searches. Choose Datasets API for straightforward gene data retrieval with metadata and sequences in a single request.

## Common Workflows

### Search Genes by Symbol or Name

To search for genes by symbol or name across organisms:

1. Use the `scripts/query_gene.py` script with E-utilities ESearch
2. Specify the gene symbol and organism (e.g., "BRCA1 in human")
3. The script returns matching Gene IDs

Example query patterns:
- Gene symbol: `INS[pref] AND human[orgn]` (official symbol; `[gene]` also matches aliases)
- Gene with disease: `DMD[pref] AND "muscular dystrophy"[dis] AND human[orgn]`
- Chromosome location: `17q21[MV] AND human[orgn]` (band) or `17[chr] AND human[orgn]`

### Retrieve Gene Information by ID

To fetch detailed information for known Gene IDs:

1. Use `scripts/fetch_gene_data.py` with the Datasets API for comprehensive data
2. Alternatively, use `scripts/query_gene.py` with E-utilities EFetch for specific formats
3. Specify desired output format (JSON, XML, or text)

The Datasets API returns:
- Gene nomenclature and aliases
- Reference sequences (RefSeqs) for transcripts and proteins
- Chromosomal location and mapping
- Gene Ontology (GO) annotations
- Associated publications

### Batch Gene Lookups

For multiple genes simultaneously:

1. Use `scripts/batch_gene_lookup.py` for efficient batch processing
2. Provide a list of gene symbols or IDs
3. Specify the organism for symbol-based queries
4. The script handles rate limiting automatically (10 requests/second with API key)

This workflow is useful for:
- Validating gene lists
- Retrieving metadata for gene panels
- Cross-referencing gene identifiers
- Building gene annotation tables

### Search by Biological Context

To find genes associated with specific biological functions or phenotypes:

1. Use E-utilities with Gene Ontology (GO) terms or phenotype keywords
2. Query by pathway names or disease associations
3. Filter by organism, chromosome, or other attributes

Example searches:
- By GO term: `"apoptotic process"[GO] AND human[orgn]` (term name, not the GO ID)
- By disease/phenotype: `"diabetes"[dis] AND mouse[orgn]`
- By pathway: there is no pathway field — use a GO process (`"insulin receptor signaling pathway"[GO]`) or the KEGG/Reactome skills

### Two silent failures (read before mapping gene lists)

**1. Symbols collide with aliases.** `FLG[gene] AND human[orgn]` returns **FGFR1 first** (FLG is an
FGFR1 alias) and filaggrin second; the Datasets endpoint `symbol/FLG/taxon/9606` does the same. Taking
the first hit silently turns filaggrin into FGFR1 — in an intersection that invents or deletes a hub gene.
Resolve official symbols first and accept an alias only when it is unique:

| Step | Query | FLG | IL8 |
|---|---|---|---|
| official symbol | `FLG[pref] AND human[orgn] AND alive[prop]` | FLG (2312) | none |
| alias fallback | `IL8[gene] AND human[orgn] AND alive[prop]` | — | CXCL8 (3576), flagged `alias` |

`scripts/batch_gene_lookup.py` (`resolve_symbol`) and `fetch_gene_data.py` (`fetch_gene_by_symbol`) now do
this and report `match: official | alias | ambiguous`. Report how many inputs mapped through aliases and
list ambiguous ones; never pick among them silently.

**2. Unknown field tags are ignored without an error.** ESearch treats an unrecognised tag as All Fields:
`diabetes[disease]`, `diabetes[phenotype]`, `MAPK signaling pathway[pathway]` and `9606[taxid]` return
exactly the same counts as a made-up tag. Use only fields from `einfo.fcgi?db=gene`:

| Want | Correct (verified 2026-11) | Wrong (silently ignored or empty) |
|---|---|---|
| Official symbol | `INS[pref]` | `insulin[gene name]` (0: "insulin" is not a symbol) |
| Symbol or alias | `IL8[gene]` | |
| Disease/phenotype | `"diabetes"[dis]` (quote phrases) | `[disease]`, `[phenotype]` |
| GO term | `"apoptotic process"[GO]` (term name) | `GO:0006915[biological process]` (0) |
| Pathway | no pathway field — use a GO process name, or the KEGG/Reactome skills | `[pathway]` |
| Chromosome / band | `17[chr]` · `17q21[MV]` | `17q21[chromosome]` (0) |
| Organism | `human[orgn]` or `txid9606[orgn]` | `9606[taxid]` |
| Live protein-coding genes | `alive[prop] AND genetype_protein_coding[prop]` (human: 20,600) | `protein coding[gene type]` (0) |
| Genes with ClinVar records | `gene_clinvar[filter]` | `has variants[filter]` (0) |

When adding a new tag, compare its count with the same term under `[ALL]` and under a made-up tag — equal
counts mean the tag was ignored.

### API Access Patterns

**Rate Limits:**
- Without API key: 3 requests/second for E-utilities, 5 requests/second for Datasets API
- With API key: 10 requests/second for both APIs

**Authentication:**
Register for a free NCBI API key at https://www.ncbi.nlm.nih.gov/account/ to increase rate limits.

**Error Handling:**
Both APIs return standard HTTP status codes. Common errors include:
- 400: Malformed query or invalid parameters
- 429: Rate limit exceeded
- 404: Gene ID not found

Retry failed requests with exponential backoff.

## Script Usage

### query_gene.py

Query NCBI Gene using E-utilities (ESearch, ESummary, EFetch).

```bash
python scripts/query_gene.py --search "BRCA1" --organism "human"
python scripts/query_gene.py --id 672 --format json
python scripts/query_gene.py --search 'INS[pref] AND "diabetes"[dis] AND human[orgn]'
```

### fetch_gene_data.py

Fetch comprehensive gene data using NCBI Datasets API.

```bash
python scripts/fetch_gene_data.py --gene-id 672
python scripts/fetch_gene_data.py --symbol BRCA1 --taxon human
python scripts/fetch_gene_data.py --symbol TP53 --taxon "Homo sapiens" --output json
```

### batch_gene_lookup.py

Process multiple gene queries efficiently.

```bash
python scripts/batch_gene_lookup.py --file gene_list.txt --organism human
python scripts/batch_gene_lookup.py --ids 672,7157,5594 --output results.json
```

## API References

For detailed API documentation including endpoints, parameters, response formats, and examples, refer to:

- `references/api_reference.md` - Comprehensive API documentation for E-utilities and Datasets API
- `references/common_workflows.md` - Additional examples and use case patterns

Search these references when needing specific API endpoint details, parameter options, or response structure information.

## Data Formats

NCBI Gene data can be retrieved in multiple formats:

- **JSON**: Structured data ideal for programmatic processing
- **XML**: Detailed hierarchical format with full metadata
- **GenBank**: Sequence data with annotations
- **FASTA**: Sequence data only
- **Text**: Human-readable summaries

Choose JSON for modern applications, XML for legacy systems requiring detailed metadata, and FASTA for sequence analysis workflows.

## Best Practices

1. **Always specify organism** when searching by gene symbol to avoid ambiguity
2. **Use Gene IDs** for precise lookups when available
3. **Batch requests** when working with multiple genes to minimize API calls
4. **Cache results** locally to reduce redundant queries
5. **Include API key** in scripts for higher rate limits
6. **Handle errors gracefully** with retry logic for transient failures
7. **Validate gene symbols** before batch processing to catch typos

## Resources

This skill includes:

### scripts/
- `query_gene.py` - Query genes using E-utilities (ESearch, ESummary, EFetch)
- `fetch_gene_data.py` - Fetch gene data using NCBI Datasets API
- `batch_gene_lookup.py` - Handle multiple gene queries efficiently

### references/
- `api_reference.md` - Detailed API documentation for both E-utilities and Datasets API
- `common_workflows.md` - Examples of common gene queries and use cases

