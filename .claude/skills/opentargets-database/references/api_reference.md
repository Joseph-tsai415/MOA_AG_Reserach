# Open Targets Platform API Reference

> **Schema note (verified against API 26.09, 2026-11):** `page:` needs `{index, size}`; `datatypeScores { id score }` (not `componentId`); `evidences(datasourceIds:)` (no `datatypes:`); `knownDrugs` → `drugAndClinicalCandidates`; `maximumClinicalTrialPhase` → `maximumClinicalStage`; `expressions` → `baselineExpression`. Most disease IDs are now `MONDO_…` and an obsolete ID returns `null` silently. `scripts/query_opentargets.py` holds working queries; check any field here against the schema browser before relying on it.


## API Endpoint

```
https://api.platform.opentargets.org/api/v4/graphql
```

Interactive GraphQL playground with documentation:
```
https://api.platform.opentargets.org/api/v4/graphql/browser
```

## Access Methods

The Open Targets Platform provides multiple access methods:

1. **GraphQL API** - Best for single entity queries and flexible data retrieval
2. **Web Interface** - Interactive platform at https://platform.opentargets.org
3. **Data Downloads** - FTP at https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/
4. **Google BigQuery** - For large-scale systematic queries

## Authentication

No authentication is required for the GraphQL API. All data is freely accessible.

## Rate Limits

For systematic queries involving multiple targets or diseases, use dataset downloads or BigQuery instead of repeated API calls. The API is optimized for single-entity and exploratory queries.

## GraphQL Query Structure

GraphQL queries consist of:
1. Query operation with optional variables
2. Field selection (request only needed fields)
3. Nested entity traversal

### Basic Python Example

```python
import requests
import json

# Define the query
query_string = """
  query target($ensemblId: String!){
    target(ensemblId: $ensemblId){
      id
      approvedSymbol
      biotype
      geneticConstraint {
        constraintType
        exp
        obs
        score
      }
    }
  }
"""

# Define variables
variables = {"ensemblId": "ENSG00000169083"}

# Make the request
base_url = "https://api.platform.opentargets.org/api/v4/graphql"
response = requests.post(base_url, json={"query": query_string, "variables": variables})
data = json.loads(response.text)
print(data)
```

## Available Query Endpoints

### /target
Retrieve gene annotations, tractability assessments, and disease associations.

**Common fields:**
- `id` - Ensembl gene ID
- `approvedSymbol` - HGNC gene symbol
- `approvedName` - Full gene name
- `biotype` - Gene type (protein_coding, etc.)
- `tractability` - Druggability assessment
- `safetyLiabilities` - Safety information
- `baselineExpression` - Baseline expression data
- `drugAndClinicalCandidates` - Approved/clinical drugs
- `associatedDiseases` - Disease associations with evidence

### /disease
Retrieve disease/phenotype data, known drugs, and clinical information.

**Common fields:**
- `id` - Disease identifier (mostly `MONDO_…`; the argument is still named `efoId`)
- `name` - Disease name
- `description` - Disease description
- `therapeuticAreas` - High-level disease categories
- `synonyms` - Alternative names
- `drugAndClinicalCandidates` - Drugs and clinical candidates for the disease
- `associatedTargets` - Target associations with evidence

### /drug
Retrieve compound details, mechanisms of action, and pharmacovigilance data.

**Common fields:**
- `id` - ChEMBL identifier
- `name` - Drug name
- `drugType` - Small molecule, antibody, etc.
- `maximumClinicalStage` - Development stage (`APPROVAL`, `PHASE_3`, …)
- `indications` - Disease indications
- `mechanismsOfAction` - Target mechanisms
- `adverseEvents` - Pharmacovigilance data

### /search
Search across all entities (targets, diseases, drugs).

**Parameters:**
- `queryString` - Search term
- `entityNames` - Filter by entity type(s)
- `page` - Pagination

### /associationDiseaseIndirect
Retrieve target-disease associations including indirect evidence from disease descendants in ontology.

**Key fields:**
- `rows` - Association records with scores
- `aggregations` - Aggregated statistics

## Example Queries

### Query 1: Get target information with disease associations

```python
query = """
  query targetInfo($ensemblId: String!) {
    target(ensemblId: $ensemblId) {
      approvedSymbol
      approvedName
      tractability {
        label
        modality
        value
      }
      associatedDiseases(page: {index: 0, size: 10}) {
        rows {
          disease {
            name
          }
          score
          datatypeScores {
            id
            score
          }
        }
      }
    }
  }
"""
variables = {"ensemblId": "ENSG00000157764"}
```

### Query 2: Search for diseases

```python
query = """
  query searchDiseases($queryString: String!) {
    search(queryString: $queryString, entityNames: ["disease"]) {
      hits {
        id
        entity
        name
        description
      }
    }
  }
"""
variables = {"queryString": "alzheimer"}
```

### Query 3: Get evidence for target-disease pair

```python
query = """
  query evidences($ensemblId: String!, $efoId: String!) {
    disease(efoId: $efoId) {
      evidences(ensemblIds: [$ensemblId], size: 100) {
        rows {
          datasourceId
          datatypeId
          score
          studyId
          literature
        }
      }
    }
  }
"""
variables = {"ensemblId": "ENSG00000157764", "efoId": "MONDO_0004975"}
```

### Query 4: Get drugs and clinical candidates for a disease

```python
query = """
  query candidates($efoId: String!) {
    disease(efoId: $efoId) {
      drugAndClinicalCandidates {
        count
        rows {
          maxClinicalStage
          drug {
            id
            name
            mechanismsOfAction { rows { actionType targets { approvedSymbol } } }
          }
        }
      }
    }
  }
"""
variables = {"efoId": "MONDO_0004975"}
```

## Error Handling

Schema/validation errors (unknown field, missing `page.index`) return **HTTP 400** with a JSON body whose
`errors[].message` names the bad field — read the body, don't stop at `raise_for_status()`. Execution
errors can come back as 200 with an `errors` key. An obsolete or unknown ID returns 200 with
`"disease": null` and **no** error. Check all three:

```python
if 'errors' in response_data:
    print(f"GraphQL errors: {response_data['errors']}")
else:
    print(f"Data: {response_data['data']}")
```

## Best Practices

1. **Request only needed fields** - Minimize data transfer and improve response time
2. **Use variables** - Make queries reusable and safer
3. **Handle pagination** - `page: {index: M, size: N}` — both fields are required
4. **Explore the schema** - Use the GraphQL browser to discover available fields
5. **Batch related queries** - Combine multiple entity fetches in a single query when possible
6. **Cache results** - Store frequently accessed data locally to reduce API calls
7. **Use BigQuery for bulk** - Switch to BigQuery/downloads for systematic analyses

## Data Licensing

All Open Targets Platform data is freely available. When using the data in research or commercial products, cite the latest publication:

Ochoa, D. et al. (2025) Open Targets Platform: facilitating therapeutic hypotheses building in drug discovery. Nucleic Acids Research, 53(D1):D1467-D1477.
