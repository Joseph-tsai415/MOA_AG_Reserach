#!/usr/bin/env python3
"""
GWAS Catalog REST API v2 helper  (verified 2026-11)

The v1 API (https://www.ebi.ac.uk/gwas/rest/api/efoTraits/..., /singleNucleotidePolymorphisms/...)
and the Summary Statistics API (https://www.ebi.ac.uk/gwas/summary-statistics/api) both return
HTTP 410 Gone. Everything here uses https://www.ebi.ac.uk/gwas/rest/api/v2.

Silent-zero traps this file guards against:
  * Trait IDs migrated EFO -> MONDO. associations?efo_id=EFO_0000274 returns HTTP 200 with
    totalElements 0; atopic eczema is MONDO_0004980 (796 associations). Resolve by NAME first.
  * p_value underflows to 0.0 for very strong hits (TCF7L2 in T2D). Use pvalue_mantissa and
    pvalue_exponent, exposed here as neg_log10_p().
  * The server is slow and sometimes drops the connection; requests retry with backoff.

Dependencies: requests
"""

import math
import time
from typing import Any, Dict, List, Optional

import requests

BASE = "https://www.ebi.ac.uk/gwas/rest/api/v2"
HEADERS = {"Accept": "application/json"}
GWS = 5e-8


def _get(path: str, params: Optional[dict] = None, retries: int = 4, timeout: int = 180) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(BASE + path, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
            else:
                time.sleep(0.2)
                return r
        except requests.exceptions.RequestException as e:   # incl. RemoteDisconnected
            last = repr(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"GWAS v2 {path} failed after {retries} attempts: {last}")


def resolve_trait(term: str) -> List[Dict[str, str]]:
    """Name or ID -> list of current trait records [{efo_id, efo_trait, uri}], exact name match first.

    An ID that 404s is obsolete or wrong: resolve the disease NAME instead (IDs migrated EFO -> MONDO).
    """
    if "_" in term and " " not in term:
        r = _get(f"/efo-traits/{term}")
        if r.status_code == 404:
            raise LookupError(f"trait {term} not found in GWAS v2 (obsolete EFO id?) - call resolve_trait('<name>')")
        r.raise_for_status()
        j = r.json()
        return [{"efo_id": j["efo_id"], "efo_trait": j["efo_trait"], "uri": j.get("uri", "")}]
    r = _get("/efo-traits", {"efo_trait": term, "size": 50})
    r.raise_for_status()
    hits = [{"efo_id": t["efo_id"], "efo_trait": t["efo_trait"], "uri": t.get("uri", "")}
            for t in r.json().get("_embedded", {}).get("efo_traits", [])]
    if not hits:
        raise LookupError(f"no GWAS trait matches '{term}'")
    hits.sort(key=lambda h: h["efo_trait"].lower() != term.lower())   # exact match first
    return hits


def get_associations(efo_id: Optional[str] = None, rs_id: Optional[str] = None,
                     mapped_gene: Optional[str] = None, page_size: int = 500,
                     max_records: Optional[int] = None) -> List[Dict[str, Any]]:
    """All associations for a trait / variant / mapped gene, best p first. Asserts completeness.

    Record fields (snake_case): association_id, p_value, pvalue_mantissa, pvalue_exponent,
    efo_traits[{efo_id, efo_trait}], reported_trait, mapped_genes, snp_allele[{rs_id, effect_allele}],
    snp_effect_allele, or_value, beta, ci_lower, ci_upper, range, risk_frequency, accession_id (GCST),
    pubmed_id, first_author, locations ["chr:pos"].
    """
    params = {k: v for k, v in {"efo_id": efo_id, "rs_id": rs_id, "mapped_gene": mapped_gene}.items() if v}
    if not params:
        raise ValueError("give efo_id, rs_id or mapped_gene")
    out, page, total = [], 0, None
    while True:
        r = _get("/associations", {**params, "size": page_size, "page": page, "sort": "p_value", "direction": "asc"})
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("_embedded", {}).get("associations", []))
        total = j["page"]["totalElements"]
        page += 1
        if page >= j["page"]["totalPages"] or (max_records and len(out) >= max_records):
            break
    if max_records is None and len(out) != total:
        raise RuntimeError(f"pagination incomplete: {len(out)} of {total}")
    return out


def neg_log10_p(a: Dict[str, Any]) -> float:
    """-log10(p) from mantissa/exponent; exact even when p_value has underflowed to 0.0."""
    m, e = a.get("pvalue_mantissa"), a.get("pvalue_exponent")
    if m is not None and e is not None and m > 0:
        return -(math.log10(m) + e)
    p = a.get("p_value")
    return float("inf") if p == 0 else -math.log10(p)


def genes_from_associations(assocs: List[Dict[str, Any]], p_threshold: float = GWS) -> Dict[str, Dict[str, Any]]:
    """Per mapped gene: n associations, n genome-wide significant, best -log10 p, top SNP, studies, PMIDs."""
    thr = -math.log10(p_threshold)
    genes: Dict[str, Dict[str, Any]] = {}
    for a in assocs:
        lp = neg_log10_p(a)
        rs = ",".join(x.get("rs_id", "") for x in (a.get("snp_allele") or []))
        for g in a.get("mapped_genes") or []:
            d = genes.setdefault(g, {"n_assoc": 0, "n_gws": 0, "best_neg_log10_p": 0.0, "top_snp": "",
                                     "studies": set(), "pmids": set()})
            d["n_assoc"] += 1
            d["n_gws"] += lp >= thr
            if lp > d["best_neg_log10_p"]:
                d["best_neg_log10_p"], d["top_snp"] = lp, rs
            d["studies"].add(a.get("accession_id"))
            if a.get("pubmed_id"):
                d["pmids"].add(str(a["pubmed_id"]))
    return genes


def get_variant(rs_id: str) -> Dict[str, Any]:
    """rs_id, functional_class, locations[{chromosome_name, chromosome_position, region}], mapped_genes, alleles."""
    r = _get(f"/single-nucleotide-polymorphisms/{rs_id}")
    r.raise_for_status()
    return r.json()


def get_study(accession: str) -> Dict[str, Any]:
    """GCST study: initial/replication sample size, ancestry, snp_count, imputed, pubmed_id ..."""
    r = _get(f"/studies/{accession}")
    r.raise_for_status()
    return r.json()


def get_studies_for_trait(efo_id: str, page_size: int = 200) -> List[Dict[str, Any]]:
    out, page = [], 0
    while True:
        r = _get("/studies", {"efo_id": efo_id, "size": page_size, "page": page})
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("_embedded", {}).get("studies", []))
        page += 1
        if page >= j["page"]["totalPages"]:
            break
    return out


if __name__ == "__main__":
    # Known-answer smoke test. A failure means the instrument is broken, not the biology.
    trait = resolve_trait("atopic eczema")[0]
    print("atopic eczema ->", trait)
    stale = _get("/associations", {"efo_id": "EFO_0000274", "size": 1}).json()["page"]["totalElements"]
    print("obsolete EFO_0000274 associations:", stale, "(0 = the silent-zero trap)")
    assoc = get_associations(efo_id=trait["efo_id"])
    genes = genes_from_associations(assoc)
    gws = sorted((g for g, d in genes.items() if d["n_gws"]), key=lambda g: -genes[g]["best_neg_log10_p"])
    print(f"associations={len(assoc)}  genes={len(genes)}  GWS genes={len(gws)}  top={gws[:12]}")
    assert len(assoc) > 0 and gws, "known-answer FAIL: AD must have genome-wide significant loci"
    v = get_variant("rs7903146")
    print("rs7903146 ->", v["mapped_genes"])
    assert "TCF7L2" in v["mapped_genes"], "known-answer FAIL: rs7903146 -> TCF7L2"
    t2d = get_associations(efo_id=resolve_trait("type 2 diabetes mellitus")[0]["efo_id"], max_records=5)
    print("T2D best hit:", t2d[0]["mapped_genes"], "p_value field =", t2d[0]["p_value"],
          "| -log10 p from mantissa/exponent =", round(neg_log10_p(t2d[0]), 1))
    print("OK")
