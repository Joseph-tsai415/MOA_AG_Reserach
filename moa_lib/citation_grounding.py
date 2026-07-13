"""Step-5 guardrail (P1) — citation-grounding gate.

Fixes session8 failure mode F4: real papers cited for claims they do not make
(Budzynska 2019 -> actually 2013 nicotine/anxiety, not JAK1; Kim -> histamine,
not GR-agonism; Papp -> psoriasis, not rs310241).

A `(claim, citation)` pair passes only if BOTH hold:
  (1) the PMID/DOI resolves, and
  (2) the retrieved title+abstract supports the *specific* claim (entity overlap).

The module does the MECHANICAL half (resolve + entity check + year check). The
agent-in-loop still makes the final semantic judgment on borderline cases — but
a hard entity miss or year mismatch is auto-FLAGGED here.

    resolve(ref)                      -> {title, abstract, year, authors, source}
    check_claim(claim, ref, entities) -> Verdict(grounded|flagged, reasons)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import requests

_CROSSREF = "https://api.crossref.org/works/{doi}"
_EUTILS_SUM = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
               "?db=pubmed&retmode=json&id={pmid}")
_EUTILS_ABS = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
               "?db=pubmed&rettype=abstract&retmode=text&id={pmid}")
_UA = {"User-Agent": "moa_lib-citation-grounding/0.1 (mailto:btruhealth@gmail.com)"}


def _strip_jats(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


@lru_cache(maxsize=2048)
def resolve(ref: str) -> Optional[tuple]:
    """Resolve a DOI (contains '/') or PMID (all digits). Returns a hashable tuple
    (title, abstract, year, authors, source) or None if unresolvable."""
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        if ref.isdigit():                       # PMID
            s = requests.get(_EUTILS_SUM.format(pmid=ref), timeout=20, headers=_UA).json()
            doc = s.get("result", {}).get(ref, {})
            if not doc or "error" in doc:
                return None
            title = doc.get("title", "")
            year = (doc.get("pubdate", "")[:4] or None)
            authors = ", ".join(a.get("name", "") for a in doc.get("authors", [])[:3])
            abs_txt = requests.get(_EUTILS_ABS.format(pmid=ref), timeout=20,
                                   headers=_UA).text
            return (title, abs_txt, year, authors, "pubmed")
        else:                                   # DOI
            doi = ref.replace("https://doi.org/", "").replace("http://doi.org/", "")
            m = requests.get(_CROSSREF.format(doi=doi), timeout=20,
                             headers=_UA).json().get("message", {})
            if not m:
                return None
            title = " ".join(m.get("title", []) or [])
            abstract = _strip_jats(m.get("abstract", ""))
            parts = (m.get("published", {}) or m.get("issued", {})).get("date-parts", [[None]])
            year = str(parts[0][0]) if parts and parts[0] else None
            authors = ", ".join(f"{a.get('family','')}" for a in m.get("author", [])[:3])
            return (title, abstract, year, authors, "crossref")
    except Exception:
        return None


@dataclass
class Verdict:
    verdict: str                    # "grounded" | "flagged" | "unresolved"
    ref: str = ""
    resolved_title: str = ""
    resolved_year: Optional[str] = None
    entity_overlap: float = 0.0
    missing_entities: list = field(default_factory=list)
    reasons: list = field(default_factory=list)


def check_claim(claim: str, ref: str, key_entities: list,
                expected_year: Optional[str] = None, min_overlap: float = 0.5) -> Verdict:
    """Verify that `ref` supports `claim`.

    key_entities: the terms the citation MUST support (e.g. ['JAK1','inhibit']).
    Passing them explicitly keeps the check deterministic; if omitted, capitalised
    tokens in `claim` are used as a fallback.
    """
    if not key_entities:
        key_entities = sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9]{2,}\b", claim)))

    resolved = resolve(ref)
    if resolved is None:
        return Verdict("unresolved", ref, reasons=[f"could not resolve reference '{ref}'"])

    title, abstract, year, _authors, _src = resolved
    haystack = f"{title} {abstract}".lower()
    present = [e for e in key_entities if e.lower() in haystack]
    missing = [e for e in key_entities if e.lower() not in haystack]
    overlap = len(present) / len(key_entities) if key_entities else 0.0

    reasons = []
    ok = True
    if overlap < min_overlap:
        ok = False
        reasons.append(f"claim entities not supported by source (missing {missing})")
    if expected_year and year and expected_year != year:
        ok = False
        reasons.append(f"year mismatch: cited {expected_year} but source is {year}")

    return Verdict("grounded" if ok else "flagged", ref, title, year,
                   round(overlap, 2), missing, reasons)
