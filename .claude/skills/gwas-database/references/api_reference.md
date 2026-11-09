# GWAS Catalog REST API v2 Reference

> Verified live 2026-11. The v1 API (`/gwas/rest/api/...` without `/v2`) and the Summary Statistics API
> (`/gwas/summary-statistics/api`) return **HTTP 410 Gone**; this file documents v2 only.
> Official docs: https://www.ebi.ac.uk/gwas/rest/api/v2/docs

## Base URL, auth, limits

```
https://www.ebi.ac.uk/gwas/rest/api/v2
```

- No authentication. Send `Accept: application/json`.
- No published rate limit, but the service is slow (large pages take tens of seconds) and sometimes closes the
  connection without a response. Use timeouts of at least 180 s, retry with exponential backoff, and cache pages
  to disk.
- Pagination: `size` (500 works) and `page` (0-based). Response `page` = `{size, totalElements, totalPages, number}`.
  Loop `page < totalPages` and assert `len(rows) == totalElements`.
- Sorting: `sort=p_value&direction=asc|desc`.

## Endpoints

| Endpoint | Parameters | Notes |
|---|---|---|
| `GET /associations` | `efo_id`, `rs_id`, `mapped_gene`, `pubmed_id`, `sort`, `direction`, `size`, `page` | rows in `_embedded.associations` |
| `GET /efo-traits` | `efo_trait` (name), `size`, `page` | rows in `_embedded.efo_traits` → `{efo_trait, efo_id, uri}` |
| `GET /efo-traits/{efo_id}` |  | 404 for an obsolete or unknown ID |
| `GET /single-nucleotide-polymorphisms/{rs_id}` |  | `rs_id, functional_class, locations[{chromosome_name, chromosome_position, region{name}}], mapped_genes, alleles, most_severe_consequence` |
| `GET /studies/{accession_id}` |  | `initial_sample_size, replication_sample_size, snp_count, imputed, gxe, gxg, pubmed_id, ...` |
| `GET /studies` | `efo_id`, `size`, `page` | rows in `_embedded.studies` |
| `GET /genes/{symbol}` |  | `gene_name, gene_description, location, cytogenic_region, biotype, ...` |

Not available: `/single-nucleotide-polymorphisms/{rs}/associations` (404; use `/associations?rs_id=`).
`include_child_traits=true` on `/associations` had no effect in testing (AD returned 796 either way).

## Association record fields

| Field | Meaning |
|---|---|
| `association_id` | numeric ID |
| `p_value` | float; **underflows to 0.0** for very small p |
| `pvalue_mantissa`, `pvalue_exponent` | exact p = mantissa × 10^exponent; use these for ranking and thresholds |
| `pvalue_description` | qualifier text, often empty |
| `efo_traits` | `[{efo_id, efo_trait}]` mapped ontology traits |
| `reported_trait` | author-reported trait strings |
| `bg_efo_traits` | background traits |
| `mapped_genes` | genes mapped to the locus (may include lncRNAs and read-throughs) |
| `snp_allele` | `[{rs_id, effect_allele}]`; `snp_effect_allele` = `["rs…-T"]` |
| `or_value`, `or_per_copy_num`, `beta`, `range`, `ci_lower`, `ci_upper` | effect size and CI as published (strings or numbers; `beta` may be `"-"`) |
| `risk_frequency` | effect-allele frequency as published (`"NR"` = not reported) |
| `accession_id` | GCST study accession |
| `pubmed_id`, `first_author` | publication |
| `locations` | `["chr:pos"]` |
| `multi_snp_haplotype`, `snp_interaction` | flags |
| `_links` | `self`, `loci`, `snp` |

## v1 → v2 mapping

| v1 (410 Gone) | v2 |
|---|---|
| `/efoTraits/{id}/associations` | `/associations?efo_id={id}` |
| `/efoTraits/{id}` | `/efo-traits/{id}` |
| `/efoTraits/search/findByEfoUri?uri=` | `/efo-traits?efo_trait={name}` |
| `/singleNucleotidePolymorphisms/{rs}` | `/single-nucleotide-polymorphisms/{rs}` |
| `/singleNucleotidePolymorphisms/{rs}/associations` | `/associations?rs_id={rs}` |
| `/singleNucleotidePolymorphisms/search/findByGene?geneName=` | `/associations?mapped_gene={symbol}` |
| `/studies/{GCST}` | `/studies/{GCST}` |
| `/associations/search/findByPubmedId?pubmedId=` | `/associations?pubmed_id={pmid}` |
| camelCase fields `rsId, pvalue, strongestAllele, orPerCopyNum, betaNum, efoTrait, pubmedId` | snake_case `snp_allele[].rs_id, p_value, snp_effect_allele, or_value, beta, efo_traits, pubmed_id` |
| Summary Statistics API `/summary-statistics/api/...` | download only: `https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics/` |

## Trait ID migration (EFO → MONDO)

Disease traits were remapped to MONDO. An old EFO ID is not redirected:

| Disease | Old ID (0 rows) | Current ID |
|---|---|---|
| atopic eczema / atopic dermatitis | `EFO_0000274` | `MONDO_0004980` |
| type 2 diabetes mellitus | `EFO_0001360` | `MONDO_0005148` |

Resolve by name (`/efo-traits?efo_trait=`), take the exact-name match, and record the ID used.

## Error handling

| Status | Meaning |
|---|---|
| 200 + `totalElements: 0` | valid query, no rows; for a well-studied disease this usually means a stale trait ID |
| 404 | unknown ID or unsupported path (JSON body with `errorMessage`) |
| 410 | retired v1 or Summary Statistics endpoint |
| connection reset / 5xx | transient; retry with backoff |

## Downloads

- Summary statistics: `https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics/`
- Catalogue releases (all associations, studies, ancestry TSVs): `https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/`
- Download docs: https://www.ebi.ac.uk/gwas/docs/file-downloads

## Citation

Cerezo M, et al. (2025) The NHGRI-EBI GWAS Catalog: standards for reusability, sustainability and diversity.
*Nucleic Acids Research* 53(D1):D998–D1005. PMID 39530240, doi:10.1093/nar/gkae1070. Record the access date and the resolved trait ID with every query.
