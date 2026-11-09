#!/usr/bin/env python3
"""
Monarch Initiative API v3 helper  (verified 2026-11)

Base URL is https://api-v3.monarchinitiative.org/v3/api  -- the "/api" segment is required;
https://api-v3.monarchinitiative.org/v3/association... returns 404.

Association items are FLAT: subject / subject_label / subject_taxon / object / object_label /
predicate / category / primary_knowledge_source are plain strings (not nested {id, name} dicts).

Coverage: Monarch is Mendelian-focused (OMIM, Orphanet, HPO, model organisms). A complex disease
can return ZERO genes on its main ID (atopic eczema MONDO:0004980 -> 0) while a few curated genes
sit on the "<disease>, susceptibility to" entry and numbered OMIM loci (FLG on MONDO:0100178).
That zero is a coverage gap, not a broken fetch - prove the fetch works with a Mendelian control.

Dependencies: requests
"""

import time
from typing import Any, Dict, List, Optional

import requests

BASE = "https://api-v3.monarchinitiative.org/v3/api"
HUMAN = "NCBITaxon:9606"


def monarch_get(path: str, params: Optional[dict] = None, retries: int = 3) -> Dict[str, Any]:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/{path.lstrip('/')}", params=params,
                             headers={"Accept": "application/json"}, timeout=90)
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
                time.sleep(0.2)
                return r.json()
            last = f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            last = repr(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Monarch {path} failed: {last}")


def associations(page_size: int = 500, max_items: Optional[int] = None, **filters) -> List[Dict[str, Any]]:
    """Paginated /association. Filters: subject, object, subject_category, object_category,
    predicate, category, subject_taxon. Asserts the row total."""
    items, offset = [], 0
    while True:
        j = monarch_get("association", {**filters, "limit": page_size, "offset": offset})
        items.extend(j.get("items", []))
        total = j.get("total", 0)
        offset += page_size
        if offset >= total or (max_items and len(items) >= max_items):
            break
    if max_items is None and len(items) != total:
        raise RuntimeError(f"pagination incomplete: {len(items)} of {total}")
    return items


def search(q: str, category: str = "biolink:Disease", limit: int = 10) -> List[Dict[str, Any]]:
    """Name search. category: biolink:Disease | biolink:Gene | biolink:PhenotypicFeature."""
    return monarch_get("search", {"q": q, "category": category, "limit": limit}).get("items", [])


def entity(curie: str) -> Dict[str, Any]:
    """id, category, name, description, xref (e.g. MONDO:0004980 xref includes EFO:0000274), synonym ..."""
    return monarch_get(f"entity/{curie}")


def disease_genes(disease_curie: str, human_only: bool = True) -> List[Dict[str, Any]]:
    """Genes linked to a disease (includes descendant diseases).
    predicate: causes (OMIM, Mendelian) > contributes_to (susceptibility) > gene_associated_with_condition (Orphanet)."""
    rows = associations(object=disease_curie, subject_category="biolink:Gene")
    if human_only:
        rows = [r for r in rows if r.get("subject_taxon") == HUMAN]
    return [{"gene_id": r["subject"], "symbol": r.get("subject_label"), "predicate": r["predicate"].split(":")[-1],
             "disease": f"{r.get('object_label')} ({r['object']})", "source": r.get("primary_knowledge_source")}
            for r in rows]


def disease_genes_with_susceptibility(disease_name: str) -> Dict[str, List[Dict[str, Any]]]:
    """For complex diseases: genes on the main entry PLUS on '<name>, susceptibility to' and numbered loci.
    Returns {curie: genes}. Report which entry each gene came from."""
    words = set(disease_name.lower().replace(",", " ").split())
    out = {}
    for i, h in enumerate(search(disease_name, "biolink:Disease", limit=25)):
        nm_words = set(h.get("name", "").lower().replace(",", " ").split())
        # top hit (the main entry, which may be named differently, e.g. "atopic eczema"),
        # plus entries whose name contains every word: "dermatitis, atopic, 2", "..., susceptibility to".
        # Syndromes that merely mention the disease ("immunodeficiency 11b with atopic dermatitis")
        # also match - keep the per-entry keys so the caller can see and exclude them.
        if i == 0 or words <= nm_words:
            g = disease_genes(h["id"])
            if g:
                out[f"{h['id']} {h.get('name')}"] = g
    return out


def disease_phenotypes(disease_curie: str) -> List[Dict[str, str]]:
    rows = associations(subject=disease_curie, category="biolink:DiseaseToPhenotypicFeatureAssociation")
    return [{"hpo": r["object"], "label": r.get("object_label")} for r in rows]


def gene_phenotypes(gene_curie: str) -> List[Dict[str, str]]:
    """gene_curie like HGNC:1884 (CFTR)."""
    rows = associations(subject=gene_curie, category="biolink:GeneToPhenotypicFeatureAssociation")
    return [{"hpo": r["object"], "label": r.get("object_label")} for r in rows]


def gene_diseases(gene_curie: str) -> List[Dict[str, str]]:
    rows = associations(subject=gene_curie, object_category="biolink:Disease")
    return [{"disease": r["object"], "label": r.get("object_label"), "predicate": r["predicate"].split(":")[-1]} for r in rows]


def phenotype_genes(hpo_id: str, human_only: bool = True, max_items: Optional[int] = None) -> List[Dict[str, str]]:
    """Genes annotated to an HPO term or any descendant term (HP:0001250 Seizure -> ~3.3k rows)."""
    f = {"object": hpo_id, "subject_category": "biolink:Gene"}
    if human_only:
        f["subject_taxon"] = HUMAN
    rows = associations(max_items=max_items, **f)
    return [{"gene_id": r["subject"], "symbol": r.get("subject_label"), "phenotype": r.get("object_label")} for r in rows]


def disease_models(disease_curie: str) -> List[Dict[str, str]]:
    """Model-organism genotypes annotated as model_of the disease (mouse etc.)."""
    rows = associations(object=disease_curie, category="biolink:GenotypeToDiseaseAssociation")
    return [{"genotype": r.get("subject_label"), "taxon": r.get("subject_taxon")} for r in rows]


def orthologs(gene_curie: str) -> List[Dict[str, str]]:
    rows = associations(subject=gene_curie, predicate="biolink:orthologous_to")
    return [{"ortholog": r["object"], "label": r.get("object_label"), "taxon": r.get("object_taxon")} for r in rows]


def compare_termsets(subject_hpo: List[str], object_hpo: List[str]) -> Dict[str, Any]:
    """Phenotype-set similarity. GET /semsim/compare/{a,b,...}/{c,d,...} (the query-param form is 405).
    Returns average_score, best_score, metric, subject_best_matches ...
    To compare two DISEASES: fetch disease_phenotypes() for each and compare the HPO lists."""
    return monarch_get(f"semsim/compare/{','.join(subject_hpo)}/{','.join(object_hpo)}")


if __name__ == "__main__":
    # Known-answer controls: a Mendelian disease proves the fetch works; a complex disease shows coverage.
    cf = disease_genes("MONDO:0009061")
    causal = [g["symbol"] for g in cf if g["predicate"] == "causes"]
    print(f"cystic fibrosis: {len(cf)} human gene links, causal = {causal}")
    assert "CFTR" in causal, "known-answer FAIL: CFTR causes cystic fibrosis"
    ad_main = disease_genes("MONDO:0004980")
    print(f"atopic eczema MONDO:0004980 main entry genes: {len(ad_main)}  (0 = coverage gap, not fetch failure)")
    sus = disease_genes_with_susceptibility("atopic dermatitis")
    print("atopic dermatitis susceptibility entries:", {k: [g['symbol'] for g in v] for k, v in sus.items()})
    print("HP:0001250 ->", entity("HP:0001250")["name"])
    s = compare_termsets(["HP:0001250", "HP:0001252"], ["HP:0001250", "HP:0002353"])
    print("semsim average_score:", round(s["average_score"], 2))
    print("OK")
