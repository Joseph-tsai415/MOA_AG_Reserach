---
name: opentargets-database
description: Query Open Targets Platform for target-disease associations, drug target discovery, tractability/safety data, genetics/omics evidence, known drugs, for therapeutic target identification.
license: Unknown
metadata:
    skill-author: K-Dense Inc.
---

# Open Targets Database

## Overview

The Open Targets Platform is a comprehensive resource for systematic identification and prioritization of potential therapeutic drug targets. It integrates publicly available datasets including human genetics, omics, literature, and chemical data to build and score target-disease associations.

**Key capabilities:**
- Query target (gene) annotations including tractability, safety, expression
- Search for disease-target associations with evidence scores
- Retrieve evidence from multiple data types (genetics, pathways, literature, etc.)
- Find known drugs for diseases and their mechanisms
- Access drug information including clinical trial phases and adverse events
- Evaluate target druggability and therapeutic potential

**Data access:** The platform provides a GraphQL API, web interface, data downloads, and Google BigQuery access. This skill focuses on the GraphQL API for programmatic access.

## When to Use This Skill

This skill should be used when:

- **Target discovery:** Finding potential therapeutic targets for a disease
- **Target assessment:** Evaluating tractability, safety, and druggability of genes
- **Evidence gathering:** Retrieving supporting evidence for target-disease associations
- **Drug repurposing:** Identifying existing drugs that could be repurposed for new indications
- **Competitive intelligence:** Understanding clinical precedence and drug development landscape
- **Target prioritization:** Ranking targets based on genetic evidence and other data types
- **Mechanism research:** Investigating biological pathways and gene functions
- **Biomarker discovery:** Finding genes differentially expressed in disease
- **Safety assessment:** Identifying potential toxicity concerns for drug targets

## Core Workflow

### 1. Search for Entities

Start by finding the identifiers for targets, diseases, or drugs of interest.

**For targets (genes):**
```python
from scripts.query_opentargets import search_entities

# Search by gene symbol or name
results = search_entities("BRCA1", entity_types=["target"])
# Returns: [{"id": "ENSG00000012048", "name": "BRCA1", ...}]
```

**For diseases:**
```python
# Search by disease name
results = search_entities("alzheimer", entity_types=["disease"])
# Returns: [{"id": "MONDO_0004975", "name": "Alzheimer disease", ...}]

# For a disease ID or name you will hand to every other call, prefer resolve_disease():
from scripts.query_opentargets import resolve_disease
ad = resolve_disease("atopic eczema")   # -> {"id": "MONDO_0004980", "obsoleteTerms": ["HP_0000964", "EFO_0000274"], ...}
```

**For drugs:**
```python
# Search by drug name
results = search_entities("aspirin", entity_types=["drug"])
# Returns: [{"id": "CHEMBL25", "name": "ASPIRIN", ...}]
```

**Identifiers used:**
- Targets: Ensembl gene IDs (e.g., `ENSG00000157764`)
- Diseases: mostly **MONDO** IDs now (e.g., `MONDO_0004975` Alzheimer disease, `MONDO_0004980` atopic eczema); some EFO/HP IDs remain. The GraphQL argument is still called `efoId`.
  **An obsolete ID returns `disease: null` with no error** — `EFO_0000274` (atopic eczema) and `EFO_0000249` (Alzheimer) are obsolete. Resolve names with `resolve_disease()`; the helpers raise `LookupError` on a null instead of returning `{}`.
- Drugs: ChEMBL IDs (e.g., `CHEMBL25`)

### 2. Query Target Information

Retrieve comprehensive target annotations to assess druggability and biology.

```python
from scripts.query_opentargets import get_target_info

target_info = get_target_info("ENSG00000157764", include_diseases=True)

# Access key fields:
# - approvedSymbol: HGNC gene symbol
# - approvedName: Full gene name
# - tractability: Druggability assessments across modalities
# - safetyLiabilities: Known safety concerns
# - geneticConstraint: Constraint scores from gnomAD
# - associatedDiseases: Top disease associations with scores
```

**Key annotations to review:**
- **Tractability:** Small molecule, antibody, PROTAC druggability predictions
- **Safety:** Known toxicity concerns from multiple databases
- **Genetic constraint:** pLI and LOEUF scores indicating essentiality
- **Disease associations:** Diseases linked to the target with evidence scores

Refer to `references/target_annotations.md` for detailed information about all target features.

### 3. Query Disease Information

Get disease details and associated targets/drugs.

```python
from scripts.query_opentargets import get_disease_info

disease_info = get_disease_info("MONDO_0004975", include_targets=True)

# Access fields:
# - name: Disease name
# - description: Disease description
# - therapeuticAreas: High-level disease categories
# - associatedTargets: Top targets with association scores
```

### 4. Retrieve Target-Disease Evidence

Get detailed evidence supporting a target-disease association.

```python
from scripts.query_opentargets import get_target_disease_evidence

# Get all evidence
evidence = get_target_disease_evidence(
    ensembl_id="ENSG00000157764",
    disease_id="MONDO_0004975"
)

# Filter by evidence type
genetic_evidence = get_target_disease_evidence(
    ensembl_id="ENSG00000157764",
    disease_id="MONDO_0004975",
    data_types=["genetic_association"]        # filtered client-side on datatypeId
    # datasource_ids=["gwas_credible_sets", "gene_burden", "eva"]  # filtered server-side
)

# Each evidence record contains:
# - datasourceId: Specific data source (e.g., "gwas_catalog", "chembl")
# - datatypeId: Evidence category (e.g., "genetic_association", "clinical")
# - score: Evidence strength (0-1)
# - studyId: Original study identifier
# - literature: Associated publications
```

**Major evidence types:**
1. **genetic_association:** GWAS, rare variants, ClinVar, gene burden
2. **somatic_mutation:** Cancer Gene Census, IntOGen, cancer biomarkers
3. **clinical:** Clinical precedence from approved/clinical drugs (was `known_drug` before 2026)
4. **affected_pathway:** CRISPR screens, pathway analyses, gene signatures
5. **rna_expression:** Differential expression from Expression Atlas
6. **animal_model:** Mouse phenotypes from IMPC
7. **literature:** Text-mining from Europe PMC

Refer to `references/evidence_types.md` for detailed descriptions of all evidence types and interpretation guidelines.

### 5. Find Known Drugs

Identify drugs used for a disease and their targets.

```python
from scripts.query_opentargets import get_clinical_candidates_for_disease

cc = get_clinical_candidates_for_disease("MONDO_0004980")   # atopic eczema

# cc = {"count": 238, "rows": [...]}; each row:
# - drug: {id, name, drugType, maximumClinicalStage}
# - maxClinicalStage: furthest stage FOR THIS DISEASE
# - actionTypes: e.g. ["ANTAGONIST"]   (from the drug's mechanismsOfAction)
# - targets: e.g. ["IL4R"]
```

The `knownDrugs` field was removed from the API; `get_known_drugs_for_disease` is kept as an alias of
`get_clinical_candidates_for_disease` and returns the structure above (no `uniqueDrugs`, `phase`, `status`).

**Clinical stages** (strings, not integers): `APPROVAL`, `PHASE_3`, `PHASE_2_3`, `PHASE_2`, `PHASE_1_2`,
`PHASE_1`, `EARLY_PHASE_1`, `IND`, `PRECLINICAL`, `UNKNOWN`.

### 6. Get Drug Information

Retrieve detailed drug information including mechanisms and indications.

```python
from scripts.query_opentargets import get_drug_info

drug_info = get_drug_info("CHEMBL25")

# Access:
# - name, description, drugType: Small molecule, Antibody, etc.
# - maximumClinicalStage: "APPROVAL", "PHASE_3", ...
# - mechanismsOfAction.rows: actionType, mechanismOfAction, targets
# - indications: {count, rows: [{maxClinicalStage, disease: {id, name}}]}
# - drugWarnings: withdrawals / black-box warnings (replaces hasBeenWithdrawn + withdrawnNotice)
```

### 7. Get All Associations for a Target

Find all diseases associated with a target, optionally filtering by score.

```python
from scripts.query_opentargets import get_target_associations

# Get associations with score >= 0.5
associations = get_target_associations(
    ensembl_id="ENSG00000157764",
    min_score=0.5
)

# Each association contains:
# - disease: {id, name}
# - score: Overall association score (0-1)
# - datatypeScores: Breakdown by evidence type
```

**Association scores:**
- Range: 0-1 (higher = stronger evidence)
- Aggregate evidence across all data types using harmonic sum
- NOT confidence scores but relative ranking metrics
- Under-studied diseases may have lower scores despite good evidence

## Known-Answer Control (run before trusting a disease fetch)

Open Targets fails **silently**: an obsolete disease ID returns `null`, not an error, and an empty
result looks like "no associated targets". Before using a disease's targets:

1. `resolve_disease(name)` and record the resolved ID **and** `api_version()`.
2. Check a gene that must be there, e.g. FLG in the atopic eczema top 10, APOE for Alzheimer disease.
3. `count == len(rows)` after pagination (`get_associated_targets()` asserts this).

If any check fails, mark the source `FETCH_FAILED` — never report "Open Targets found no targets".
`python scripts/query_opentargets.py` runs these checks for atopic eczema.

## GraphQL API Details

**For custom queries beyond the provided helper functions**, use the GraphQL API directly or modify `scripts/query_opentargets.py`.

Key information:
- **Endpoint:** `https://api.platform.opentargets.org/api/v4/graphql`
- **Interactive browser:** `https://api.platform.opentargets.org/api/v4/graphql/browser`
- **No authentication required**
- **Request only needed fields** to minimize response size
- **Pagination:** `page:` needs **both** `index` and `size` — `page: {size: 10}` alone is a 400 error. `get_associated_targets()` paginates a full disease and asserts the row total.
- **Errors:** a schema mismatch returns HTTP 400 with a message naming the bad field; `execute_query()` raises that message. Read it before guessing.

Refer to `references/api_reference.md` for:
- Complete endpoint documentation
- Example queries for all entity types
- Error handling patterns
- Best practices for API usage

## Best Practices

### Target Prioritization Strategy

When prioritizing drug targets:

1. **Start with genetic evidence:** Human genetics (GWAS, rare variants) provides strongest disease relevance
2. **Check tractability:** Prefer targets with clinical or discovery precedence
3. **Assess safety:** Review safety liabilities, expression patterns, and genetic constraint
4. **Evaluate clinical precedence:** Known drugs indicate druggability and therapeutic window
5. **Consider multiple evidence types:** Convergent evidence from different sources increases confidence
6. **Validate mechanistically:** Pathway evidence and biological plausibility
7. **Review literature manually:** For critical decisions, examine primary publications

### Evidence Interpretation

**Strong evidence indicators:**
- Multiple independent evidence sources
- High genetic association scores (especially GWAS with L2G > 0.5)
- Clinical precedence from approved drugs
- ClinVar pathogenic variants with disease match
- Mouse models with relevant phenotypes

**Caution flags:**
- Single evidence source only
- Text-mining as sole evidence (requires manual validation)
- Conflicting evidence across sources
- High essentiality + ubiquitous expression (poor therapeutic window)
- Multiple safety liabilities

**Score interpretation:**
- Scores rank relative strength, not absolute confidence
- Under-studied diseases have lower scores despite potentially valid targets
- Weight expert-curated sources higher than computational predictions
- Check evidence breakdown, not just overall score

### Common Workflows

**Workflow 1: Target Discovery for a Disease**
1. `resolve_disease(name)` → current disease ID (usually MONDO)
2. Query disease info with `include_targets=True`
3. Review top targets sorted by association score
4. For promising targets, get detailed target info
5. Examine evidence types supporting each association
6. Assess tractability and safety for prioritized targets

**Workflow 2: Target Validation**
1. Search for target → get Ensembl ID
2. Get comprehensive target info
3. Check tractability (especially clinical precedence)
4. Review safety liabilities and genetic constraint
5. Examine disease associations to understand biology
6. Look for chemical probes or tool compounds
7. Check known drugs targeting gene for mechanism insights

**Workflow 3: Drug Repurposing**
1. `resolve_disease(name)` → current disease ID
2. `get_clinical_candidates_for_disease()`
3. For each drug, get detailed drug info
4. Examine mechanisms of action and targets
5. Look for related disease indications
6. Assess clinical trial phases and status
7. Identify repurposing opportunities based on mechanism

**Workflow 4: Competitive Intelligence**
1. Search for target of interest
2. Get associated diseases with evidence
3. For each disease, get known drugs
4. Review clinical phases and development status
5. Identify competitors and their mechanisms
6. Assess clinical precedence and market landscape

## Resources

### Scripts

**scripts/query_opentargets.py**
Helper functions for common API operations:
- `search_entities()` - Search for targets, diseases, or drugs
- `get_target_info()` - Retrieve target annotations
- `get_disease_info()` - Retrieve disease information
- `get_target_disease_evidence()` - Get supporting evidence
- `resolve_disease()` - Name or ID → current disease record; raises on an obsolete ID
- `get_associated_targets()` - All targets for a disease, paginated, completeness asserted
- `get_clinical_candidates_for_disease()` - Drugs/candidates for a disease (alias: `get_known_drugs_for_disease`)
- `api_version()` - Release string (e.g. "26.09") to record with every fetch
- `get_drug_info()` - Retrieve drug details
- `get_target_associations()` - Get all associations for a target
- `execute_query()` - Execute custom GraphQL queries

### References

**references/api_reference.md**
Complete GraphQL API documentation including:
- Endpoint details and authentication
- Available query types (target, disease, drug, search)
- Example queries for all common operations
- Error handling and best practices
- Data licensing and citation requirements

**references/evidence_types.md**
Comprehensive guide to evidence types and data sources:
- Detailed descriptions of all 7 major evidence types
- Scoring methodologies for each source
- Evidence interpretation guidelines
- Strengths and limitations of each evidence type
- Quality assessment recommendations

**references/target_annotations.md**
Complete target annotation reference:
- 12 major annotation categories explained
- Tractability assessment details
- Safety liability sources
- Expression, essentiality, and constraint data
- Interpretation guidelines for target prioritization
- Red flags and green flags for target assessment

## Data Updates and Versioning

The Open Targets Platform is updated **quarterly** with new data releases. Record `api_version()` with every fetch. The helper script was last verified against release **26.09** (2026-11); `python scripts/query_opentargets.py` re-runs its known-answer smoke test.

**Release information:** Check https://platform-docs.opentargets.org/release-notes for the latest updates.

**Citation:** When using Open Targets data, cite:
Ochoa, D. et al. (2025) Open Targets Platform: facilitating therapeutic hypotheses building in drug discovery. Nucleic Acids Research, 53(D1):D1467-D1477.

## Limitations and Considerations

1. **API is for exploratory queries:** For systematic analyses of many targets/diseases, use data downloads or BigQuery
2. **Scores are relative, not absolute:** Association scores rank evidence strength but don't predict clinical success
3. **Under-studied diseases score lower:** Novel or rare diseases may have strong evidence but lower aggregate scores
4. **Evidence quality varies:** Weight expert-curated sources higher than computational predictions
5. **Requires biological interpretation:** Scores and evidence must be interpreted in biological and clinical context
6. **No authentication required:** All data is freely accessible, but cite appropriately

