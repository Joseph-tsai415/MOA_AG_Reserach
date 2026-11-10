# TEMPLATE: copied from a real run. Update RESTRICTED, INTEXT and SUFFIX for the new sources.
"""02 — Claim-level citation gate, then render the report.

Every citation in report_src.md is a marker [[E##]] that points at data/evidence.json.
The gate fails the run unless, for each marker:
  1. the source was really retrieved (not FETCH_FAILED);
  2. the quote is verbatim in the stored source text (for ESC 2018 the stored text is itself
     fetcher-mediated, so this proves consistency only; entries flagged paraphrase are reported
     separately in citation_gate.json);
  3. every number the evidence carries also appears in the report sentence and the quote;
  4. the PMID resolves and its year matches (moa_lib.citation_grounding.check_claim).

Stricter than check_claim alone on purpose: a probe showed that with entity overlap at
min_overlap=0.5 a wrong dose ("400 mg") and a guideline with no abstract both come back
"grounded". Quotes against stored text catch both. Chinese sentences also yield no
auto-entities, so entities are never inferred here.

Run: conda run -n moa python 02_citation_grounding.py
"""
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
from moa_lib.citation_grounding import check_claim, resolve  # noqa: E402

SRC = ROOT / "data" / "sources"
DATA = ROOT / "data"
# Pages whose terms forbid keeping a copy: after verification only the quoted sentences stay.
RESTRICTED = {"afp2023", "afp2017", "cmuh_tilt", "accaha2017"}
INTEXT = {
    "afp2023": ("Bayard et al.", "2023"), "afp2017": ("Runser et al.", "2017"),
    "cmuh_tilt": ("中國醫藥大學附設醫院", "2013"), "vghtpe_gcs": ("臺北榮民總醫院護理部", "2026"),
    "medlineplus_holter": ("MedlinePlus", "2026a"), "medlineplus_fainting": ("MedlinePlus", "2026b"),
    "ninds_syncope": ("NINDS", "2026"), "nhs_fainting": ("National Health Service", "2026"),
}
SUFFIX = {"sheldon2006": "a", "post2006": "b"}  # same first author + year
WEB_YEAR_SUFFIX = {"medlineplus_holter": ("2026", "2026a"), "medlineplus_fainting": ("2026", "2026b")}


def norm(s):
    s = html.unescape(s)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[‐‑‒–—−]", "-", s)
    s = re.sub(r"[‘’′]", "'", s).replace("“", '"').replace("”", '"')
    s = re.sub(r"\s*\[\s*\d+(\s*[,–-]\s*\d+)*\s*\]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def label(key, man):
    if key in INTEXT:
        name, year = INTEXT[key]
    else:
        name, year = man[key]["intext"], man[key]["year"]
    return name, f"{year}{SUFFIX.get(key, '')}"


def span_before(text, pos):
    """The sentence (or table cell) that a marker closes."""
    start = max(text.rfind(c, 0, pos) for c in "。；\n|")
    return text[start + 1:pos]


def main():
    man = json.loads((DATA / "sources_manifest.json").read_text(encoding="utf-8"))
    ev = json.loads((DATA / "evidence.json").read_text(encoding="utf-8"))
    src = (ROOT / "report_src.md").read_text(encoding="utf-8")
    fails, rows = [], []

    texts = {}
    for key in {e["s"] for e in ev.values()}:
        f = SRC / ("esc2018_excerpts.txt" if key == "esc2018" else f"{key}.txt")
        texts[key] = norm(f.read_text(encoding="utf-8"))

    for eid, e in ev.items():
        key = e["s"]
        status = man.get(key, {}).get("status", "MISSING")
        q = norm(e["q"])
        ok_status = status not in ("FETCH_FAILED", "MISSING")
        ok_quote = q in texts[key]
        missing_n = [n for n in e.get("n", []) if norm(n) not in q]
        if not ok_status:
            fails.append(f"{eid}: source {key} status {status}")
        if not ok_quote:
            fails.append(f"{eid}: quote not verbatim in {key}: {e['q'][:70]}")
        if missing_n:
            fails.append(f"{eid}: numbers {missing_n} not in its own quote")
        rows.append({"id": eid, "source": key, "status": status, "quote_verbatim": ok_quote})

    markers = list(re.finditer(r"\[\[([^\]]+)\]\]", src))
    cited = set()
    for m in markers:
        for eid in m.group(1).split(","):
            eid = eid.strip()
            if eid not in ev:
                fails.append(f"marker {eid} has no evidence entry")
                continue
            cited.add(eid)
            sentence = norm(span_before(src, m.start()))
            for n in ev[eid].get("n", []):
                if norm(n) not in sentence:
                    fails.append(f"{eid}: number '{n}' missing from report sentence: {sentence[:60]}")
    unused = sorted(set(ev) - cited)

    # PMID resolves + year matches, one call per source actually cited.
    used = sorted({ev[e]["s"] for e in cited})
    live = []
    for key in used:
        pmid = man[key].get("pmid")
        if not pmid:
            continue
        title_word = re.findall(r"[A-Za-z]{5,}", man[key].get("title") or "syncope")[0]
        v = check_claim("", pmid, [title_word], expected_year=man[key]["year"], min_overlap=1.0)
        for wait in (3, 8, 20):  # NCBI throttles bursts; "unresolved" may be a 429, a mismatch never is
            if v.verdict != "unresolved":
                break
            time.sleep(wait)
            resolve.cache_clear()  # resolve() is lru_cached, None included
            v = check_claim("", pmid, [title_word], expected_year=man[key]["year"], min_overlap=1.0)
        live.append({"source": key, "pmid": pmid, "verdict": v.verdict, "resolved_year": v.resolved_year, "reasons": v.reasons})
        if v.verdict != "grounded":
            fails.append(f"{key}: live resolve {v.verdict} {v.reasons}")
        time.sleep(0.4)

    def render(m):
        keys, seen = [], set()
        for eid in m.group(1).split(","):
            k = ev[eid.strip()]["s"]
            if k not in seen:
                seen.add(k)
                keys.append(k)
        return "(" + "; ".join("%s, %s" % label(k, man) for k in keys) + ")"

    body = re.sub(r"\[\[([^\]]+)\]\]", render, src)

    zh = [k for k in used if not re.match(r"[A-Za-z]", man[k]["apa"])]
    en = [k for k in used if k not in zh]
    order = sorted(zh, key=lambda k: man[k]["apa"]) + sorted(en, key=lambda k: man[k]["apa"].lower())
    rendered = {}
    for k in order:
        entry = man[k]["apa"]
        if k in SUFFIX:
            entry = entry.replace(f"({man[k]['year']})", f"({man[k]['year']}{SUFFIX[k]})", 1)
        if k in WEB_YEAR_SUFFIX:
            old, new = WEB_YEAR_SUFFIX[k]
            entry = entry.replace(f"({old})", f"({new})", 1)
        if man[k]["status"] == "ABSTRACT_ONLY":
            entry += " ［僅摘要層級］"
        rendered[k] = entry
    refs = "\n\n".join(rendered[k] for k in order)

    tiers = {"FULL_TEXT": 0, "ABSTRACT_ONLY": 0, "WEB_TEXT": 0, "PAGE_EXCERPT": 0}
    for k in used:
        tiers[man[k]["status"]] += 1
    counts = (f"本報告實際引用 {len(used)} 筆來源：全文 {tiers['FULL_TEXT']} 筆、僅摘要 {tiers['ABSTRACT_ONLY']} 筆、"
              f"網頁全文 {tiers['WEB_TEXT']} 筆、指引節錄 {tiers['PAGE_EXCERPT']} 筆。")
    body = body.replace("{{SOURCE_COUNTS}}", counts).replace("{{REFERENCES}}", refs)
    (ROOT / "pbl_case4_syncope.md").write_text(body, encoding="utf-8")

    if not any("quote not verbatim" in f for f in fails):
        for key in RESTRICTED & set(texts):
            f = SRC / f"{key}.txt"
            if not man[key].get("trimmed_after_verification"):
                man[key]["sha256_full_text"] = hashlib.sha256(f.read_bytes()).hexdigest()
                man[key]["trimmed_after_verification"] = True
            quotes = sorted({html.unescape(e["q"]) for e in ev.values() if e["s"] == key})
            f.write_text("\n".join(quotes), encoding="utf-8")
        (DATA / "sources_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")

    paraphrased = sorted(e for e in cited if ev[e].get("paraphrase"))
    esc_cited = sorted(e for e in cited if ev[e]["s"] == "esc2018")
    out = {"markers": len(markers), "evidence_cited": len(cited), "evidence_unused": unused, "sources_cited": used,
           "refs": rendered, "paraphrased_not_verbatim": paraphrased, "esc_cited": esc_cited,
           "source_tiers": tiers, "live_checks": live, "fails": fails}
    (DATA / "citation_gate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"markers={len(markers)} evidence_cited={len(cited)} sources={len(used)} tiers={tiers}")
    print("unused:", unused)
    print(f"ESC citations: {len(esc_cited)} (fetcher-mediated); paraphrase, not printed text: {paraphrased}")
    print("FAILS:", len(fails))
    for f in fails[:40]:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
