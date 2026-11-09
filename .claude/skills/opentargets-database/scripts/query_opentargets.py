#!/usr/bin/env python3
"""
Open Targets Platform GraphQL Query Helper  (schema verified against API 26.09, 2026-11)

Reusable functions for the Open Targets Platform GraphQL API.

Schema changes this file already handles (older snippets elsewhere will 400 or return null):
  * `page:` requires BOTH `index` and `size`         -> page: {index: 0, size: N}
  * datatypeScores { componentId } -> { id }
  * evidences(datatypes: ...)      -> evidences(datasourceIds: ...)   (filter datatypeId client-side)
  * Disease.knownDrugs             -> Disease.drugAndClinicalCandidates
  * Drug.maximumClinicalTrialPhase -> Drug.maximumClinicalStage ("APPROVAL", "PHASE_3", ...)
  * Drug.hasBeenWithdrawn / withdrawnNotice -> Drug.drugWarnings
  * Most disease IDs moved EFO_ -> MONDO_ (atopic eczema EFO_0000274 -> MONDO_0004980).
    disease(efoId: <obsolete id>) returns null with NO error. Use resolve_disease().

Dependencies: requests
"""

import time
from typing import Any, Dict, List, Optional

import requests

BASE_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def execute_query(query: str, variables: Optional[Dict[str, Any]] = None,
                  retries: int = 3, timeout: int = 90) -> Dict[str, Any]:
    """POST a GraphQL query. Raises with the server's GraphQL error message (not just '400')."""
    payload = {"query": query, "variables": variables or {}}
    last = None
    for attempt in range(retries):
        try:
            response = requests.post(BASE_URL, json=payload, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2 ** attempt)
            continue
        try:
            data = response.json()
        except ValueError:
            data = {}
        if data.get("errors"):
            # Schema errors come back as HTTP 400 + a message naming the bad field. Surface it.
            raise RuntimeError("GraphQL errors: " + "; ".join(e.get("message", "") for e in data["errors"]))
        if response.status_code >= 500 or response.status_code == 429:
            last = RuntimeError(f"HTTP {response.status_code}")
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return data.get("data", {})
    raise RuntimeError(f"API request failed after {retries} attempts: {last}")


def api_version() -> str:
    """Release string such as '26.09'. Record it with every fetch for provenance."""
    m = execute_query("{ meta { dataVersion { year month } } }")["meta"]["dataVersion"]
    return f"{m['year']}.{m['month']}"


def search_entities(query_string: str, entity_types: Optional[List[str]] = None,
                    size: int = 10) -> List[Dict[str, Any]]:
    """Search targets/diseases/drugs by name. entity_types: ["target"], ["disease"], ["drug"]."""
    query = """
      query search($queryString: String!, $entityNames: [String!], $size: Int!) {
        search(queryString: $queryString, entityNames: $entityNames, page: {index: 0, size: $size}) {
          hits { id entity name description }
        }
      }
    """
    variables = {"queryString": query_string, "size": size}
    if entity_types:
        variables["entityNames"] = entity_types
    return execute_query(query, variables).get("search", {}).get("hits", [])


def resolve_disease(term: str) -> Dict[str, Any]:
    """Return the CURRENT disease record for a name or an ID (including obsolete EFO IDs).

    An obsolete ID (e.g. EFO_0000274) makes disease(efoId:) return null silently, and
    mapIds/search do not index obsolete IDs. So: try the ID directly; if null, require a
    name and resolve it via mapIds, then confirm the old ID is listed in obsoleteTerms.
    """
    q = """query d($id: String!) { disease(efoId: $id) { id name obsoleteTerms dbXRefs } }"""
    if "_" in term and " " not in term:
        rec = execute_query(q, {"id": term}).get("disease")
        if rec:
            return rec
        raise LookupError(
            f"disease(efoId: '{term}') returned null - the ID is obsolete or unknown in this release. "
            "Call resolve_disease('<disease name>') and use the returned id (usually MONDO_...).")
    m = execute_query(
        """query m($t: [String!]!) { mapIds(queryTerms: $t, entityNames: ["disease"]) { mappings { term hits { id name } } } }""",
        {"t": [term]})
    hits = m["mapIds"]["mappings"][0]["hits"] if m.get("mapIds") else []
    if not hits:
        hits = search_entities(term, ["disease"], size=1)
    if not hits:
        raise LookupError(f"No disease matches '{term}'")
    return execute_query(q, {"id": hits[0]["id"]})["disease"]


def get_target_info(ensembl_id: str, include_diseases: bool = False) -> Dict[str, Any]:
    """Target annotation: tractability, safety liabilities, genetic constraint (+ top diseases)."""
    disease_fragment = """
      associatedDiseases(page: {index: 0, size: 10}) {
        count
        rows { disease { id name } score datatypeScores { id score } }
      }
    """ if include_diseases else ""
    query = f"""
      query targetInfo($ensemblId: String!) {{
        target(ensemblId: $ensemblId) {{
          id approvedSymbol approvedName biotype functionDescriptions
          tractability {{ label modality value }}
          safetyLiabilities {{
            event datasource
            effects {{ direction dosing }}
            biosamples {{ tissueLabel cellLabel }}
          }}
          geneticConstraint {{ constraintType score exp obs }}
          {disease_fragment}
        }}
      }}
    """
    rec = execute_query(query, {"ensemblId": ensembl_id}).get("target")
    if rec is None:
        raise LookupError(f"target(ensemblId: '{ensembl_id}') returned null")
    return rec


def get_disease_info(disease_id: str, include_targets: bool = False) -> Dict[str, Any]:
    """Disease record (+ top 10 targets). Raises instead of silently returning {} on an obsolete ID."""
    target_fragment = """
      associatedTargets(page: {index: 0, size: 10}) {
        count
        rows { target { id approvedSymbol approvedName } score datatypeScores { id score } }
      }
    """ if include_targets else ""
    query = f"""
      query diseaseInfo($efoId: String!) {{
        disease(efoId: $efoId) {{
          id name description obsoleteTerms
          therapeuticAreas {{ id name }}
          synonyms {{ relation terms }}
          {target_fragment}
        }}
      }}
    """
    rec = execute_query(query, {"efoId": disease_id}).get("disease")
    if rec is None:
        raise LookupError(f"disease(efoId: '{disease_id}') returned null - obsolete ID? use resolve_disease()")
    return rec


def get_associated_targets(disease_id: str, page_size: int = 500,
                           max_rows: Optional[int] = None) -> Dict[str, Any]:
    """ALL targets associated with a disease, paginated. Returns {count, rows} and asserts completeness.

    rows: [{target:{id, approvedSymbol, biotype}, score, datatypeScores:[{id, score}]}]
    datatypeScores ids seen in 26.09: genetic_association, genetic_literature, somatic_mutation,
    clinical, affected_pathway, rna_expression, literature, animal_model.
    """
    query = """
      query at($id: String!, $index: Int!, $size: Int!) {
        disease(efoId: $id) {
          associatedTargets(page: {index: $index, size: $size}) {
            count
            rows { target { id approvedSymbol biotype } score datatypeScores { id score } }
          }
        }
      }
    """
    rows, index, count = [], 0, None
    while True:
        d = execute_query(query, {"id": disease_id, "index": index, "size": page_size}).get("disease")
        if d is None:
            raise LookupError(f"disease(efoId: '{disease_id}') returned null - obsolete ID? use resolve_disease()")
        at = d["associatedTargets"]
        count = at["count"]
        rows.extend(at["rows"])
        index += 1
        if not at["rows"] or len(rows) >= count or (max_rows and len(rows) >= max_rows):
            break
    if max_rows is None and len(rows) != count:
        raise RuntimeError(f"pagination incomplete: {len(rows)} of {count}")
    return {"count": count, "rows": rows}


def get_target_disease_evidence(ensembl_id: str, disease_id: str,
                                data_types: Optional[List[str]] = None,
                                datasource_ids: Optional[List[str]] = None,
                                page_size: int = 500) -> List[Dict[str, Any]]:
    """Evidence rows linking a target to a disease (cursor-paginated).

    datasource_ids filters server-side (e.g. ["gwas_credible_sets", "gene_burden", "eva"]).
    data_types filters client-side on datatypeId (e.g. ["genetic_association"]) because the
    API no longer accepts a datatypes argument.
    """
    query = """
      query ev($ensemblId: String!, $efoId: String!, $ds: [String!], $size: Int!, $cursor: String) {
        disease(efoId: $efoId) {
          evidences(ensemblIds: [$ensemblId], datasourceIds: $ds, size: $size, cursor: $cursor) {
            count cursor
            rows { datasourceId datatypeId score targetFromSourceId studyId literature cohortPhenotypes }
          }
        }
      }
    """
    rows, cursor = [], None
    while True:
        v = {"ensemblId": ensembl_id, "efoId": disease_id, "ds": datasource_ids, "size": page_size, "cursor": cursor}
        d = execute_query(query, v).get("disease")
        if d is None:
            raise LookupError(f"disease(efoId: '{disease_id}') returned null - obsolete ID? use resolve_disease()")
        ev = d["evidences"]
        rows.extend(ev["rows"])
        cursor = ev.get("cursor")
        if not cursor or not ev["rows"]:
            break
    if data_types:
        rows = [r for r in rows if r.get("datatypeId") in set(data_types)]
    return rows


def get_clinical_candidates_for_disease(disease_id: str) -> Dict[str, Any]:
    """Drugs and clinical candidates for a disease (replaces the removed knownDrugs field).

    Returns {count, rows:[{drug:{id,name,drugType,maximumClinicalStage}, maxClinicalStage,
    actionTypes:[...], targets:[symbols]}]}. Stages: APPROVAL, PHASE_3, PHASE_2_3, PHASE_2,
    PHASE_1_2, PHASE_1, EARLY_PHASE_1, IND, PRECLINICAL, UNKNOWN.
    """
    query = """
      query cc($efoId: String!) {
        disease(efoId: $efoId) {
          drugAndClinicalCandidates {
            count
            rows {
              maxClinicalStage
              drug {
                id name drugType maximumClinicalStage
                mechanismsOfAction { rows { actionType mechanismOfAction targets { approvedSymbol } } }
              }
            }
          }
        }
      }
    """
    d = execute_query(query, {"efoId": disease_id}).get("disease")
    if d is None:
        raise LookupError(f"disease(efoId: '{disease_id}') returned null - obsolete ID? use resolve_disease()")
    cc = d["drugAndClinicalCandidates"]
    rows = []
    for r in cc["rows"]:
        drug = r.get("drug") or {}
        moa = (drug.get("mechanismsOfAction") or {}).get("rows", [])
        rows.append({
            "drug": {k: drug.get(k) for k in ("id", "name", "drugType", "maximumClinicalStage")},
            "maxClinicalStage": r["maxClinicalStage"],
            "actionTypes": sorted({m["actionType"] for m in moa if m.get("actionType")}),
            "targets": sorted({t["approvedSymbol"] for m in moa for t in m.get("targets", [])}),
        })
    return {"count": cc["count"], "rows": rows}


# Backward-compatible name used in older docs. Returns the new structure (see above).
get_known_drugs_for_disease = get_clinical_candidates_for_disease


def get_drug_info(chembl_id: str) -> Dict[str, Any]:
    """Drug record: stage, warnings (withdrawals/black box), mechanisms, indications."""
    query = """
      query drugInfo($chemblId: String!) {
        drug(chemblId: $chemblId) {
          id name drugType maximumClinicalStage description
          drugWarnings { warningType description country year }
          mechanismsOfAction { rows { actionType mechanismOfAction targetName targets { id approvedSymbol } } }
          indications { count rows { maxClinicalStage disease { id name } } }
        }
      }
    """
    rec = execute_query(query, {"chemblId": chembl_id}).get("drug")
    if rec is None:
        raise LookupError(f"drug(chemblId: '{chembl_id}') returned null")
    return rec


def get_target_associations(ensembl_id: str, min_score: float = 0.0, size: int = 100) -> List[Dict[str, Any]]:
    """Top `size` disease associations for a target, filtered by minimum overall score."""
    query = """
      query ta($ensemblId: String!, $size: Int!) {
        target(ensemblId: $ensemblId) {
          associatedDiseases(page: {index: 0, size: $size}) {
            count
            rows { disease { id name } score datatypeScores { id score } }
          }
        }
      }
    """
    t = execute_query(query, {"ensemblId": ensembl_id, "size": size}).get("target")
    if t is None:
        raise LookupError(f"target(ensemblId: '{ensembl_id}') returned null")
    return [a for a in t["associatedDiseases"]["rows"] if a.get("score", 0) >= min_score]


if __name__ == "__main__":
    # Known-answer smoke test: atopic eczema must resolve to a live ID, FLG must rank top-10,
    # dupilumab must be an approved candidate. Any failure = broken instrument, not biology.
    print("Open Targets release", api_version())
    ad = resolve_disease("atopic eczema")
    print("atopic eczema ->", ad["id"], "| obsolete IDs:", ad.get("obsoleteTerms"))
    top = [r["target"]["approvedSymbol"] for r in get_disease_info(ad["id"], include_targets=True)["associatedTargets"]["rows"]]
    print("top targets:", top)
    assert "FLG" in top, "known-answer FAIL: FLG not in AD top 10"
    cc = get_clinical_candidates_for_disease(ad["id"])
    dup = [r for r in cc["rows"] if r["drug"]["name"] == "DUPILUMAB"]
    print("candidates:", cc["count"], "| dupilumab:", dup[:1])
    assert dup and dup[0]["maxClinicalStage"] == "APPROVAL", "known-answer FAIL: dupilumab"
    print("OK")
