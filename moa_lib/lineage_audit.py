"""Cross-cutting guardrail (v11) — data-lineage integrity self-audit.

Session-9 review: `step3_hub_targets.md` claimed "Hub targets: 14" in its header but
its table listed all 81 rows of the RAW intersection — including HRH1/IL6/FASLG/IL1R1
that the main text says were PAINS-gated out. The raw (81) and scored (14) sets shared
one container (`hub_rows`) and the markdown writer pulled the wrong one. No check ever
asserted "the set shown == the set claimed."

This module makes every headline number self-verifying. A run with any FAIL is not a
valid deliverable.

    check_count(label, stated, recomputed)             -> Finding
    check_table_len(name, header_count, table_rows)     -> Finding
    check_no_gated_leak(name, gated, table_genes)       -> Finding
    check_set_equesls(name, claimed, actual)            -> Finding
    audit(findings) / summarize                          -> (ok: bool, report)

Text primitives an audit needs before it can compare anything (v11.2):

    normalize_text(s, keep_lines=False)                 -> str
    section(md, start, end=None)                        -> str
    count_table_rows(block) / count_numbered(block)     -> int
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str = ""


def check_count(label: str, stated, recomputed) -> Finding:
    ok = (stated == recomputed)
    return Finding(f"count::{label}", ok,
                   f"stated {stated} vs recomputed {recomputed}" + ("" if ok else "  <-- MISMATCH"))


def check_table_len(name: str, header_count: int, table_rows: int) -> Finding:
    ok = (header_count == table_rows)
    return Finding(f"table::{name}", ok,
                   f"header claims {header_count}, table has {table_rows} rows"
                   + ("" if ok else "  <-- TABLE/HEADER MISMATCH (wrong set rendered)"))


def check_no_gated_leak(name: str, gated_genes, table_genes) -> Finding:
    leak = sorted(set(gated_genes) & set(table_genes))
    return Finding(f"leak::{name}", not leak,
                   ("no gated genes present" if not leak else
                    f"GATED genes leaked into '{name}': {', '.join(leak)} — this table claims to be the "
                    f"scored/controlled set but contains genes the controls removed"))


def check_set_equals(name: str, claimed, actual) -> Finding:
    a, b = set(claimed), set(actual)
    ok = (a == b)
    d = ""
    if not ok:
        only_claimed = sorted(a - b); only_actual = sorted(b - a)
        d = f"claimed-only {only_claimed[:6]}  actual-only {only_actual[:6]}"
    return Finding(f"set::{name}", ok, ("identical" if ok else "SET MISMATCH: " + d))


# ---------------------------------------------------------------------------
# Text primitives — a lineage audit is only as good as its string comparison.
# ---------------------------------------------------------------------------

# Symbol-font PDFs (drug labels, many regulatory documents) encode >= <= - > and
# bullets in the Unicode Private Use Area rather than as real characters. Raw
# extraction therefore turns "4-8 weeks" into "48 weeks" — silently, with no
# error and nothing a text diff can see. This is not hypothetical: exactly that
# corruption put "48 weeks" into a shipped briefing before the audit caught it.
# ALWAYS map these before any numeric comparison against label-derived text.
PUA_MAP = {
    "": "-",   "": ">=",  "": "<=",
    "": ">",   "": "<",   "": "*",
    "": "->",  "": " ",   "": "+",
}


def normalize_text(s: str, keep_lines: bool = False) -> str:
    """Normalise text for substring search before comparing numbers or claims.

    Handles, in order: PUA symbol glyphs (see PUA_MAP), the middle-dot decimal
    that Lancet-family journals typeset instead of a period (1·33, not 1.33 —
    without this every Lancet number false-FAILs), dash variants, and the
    full-width punctuation that CJK typesetting introduces.

    keep_lines=True preserves newlines, which is REQUIRED for any line-based
    (table/list) parsing — a blanket \\s+ collapse silently destroys row
    structure and every table count then comes back as 0 or 1.
    """
    s = s or ""
    for k, v in PUA_MAP.items():
        s = s.replace(k, v)
    s = s.replace("·", ".").replace("–", "-").replace("—", "-").replace("−", "-")
    s = s.replace("／", "/").replace("％", "%").replace("，", ",")
    return re.sub(r"[ \t]+", " ", s) if keep_lines else re.sub(r"\s+", " ", s)


def section(md: str, start: str, end: str | None = None) -> str:
    """Slice the markdown between two literal anchors (end exclusive, optional)."""
    i = md.find(start)
    if i < 0:
        return ""
    j = md.find(end, i + len(start)) if end else -1
    return md[i: j if j > 0 else len(md)]


def count_table_rows(block: str) -> int:
    """Count rendered markdown table body rows (header and separator excluded)."""
    rows = [
        ln for ln in block.splitlines()
        if ln.strip().startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", ln.strip())
    ]
    return max(0, len(rows) - 1)


def count_numbered(block: str) -> int:
    """Count rendered `1.` `2.` ... list items — the 'stated N items' counterpart."""
    return len(re.findall(r"^\d+\.\s", block, re.M))


def audit(findings: list) -> tuple:
    fails = [f for f in findings if not f.ok]
    lines = [f"[{'PASS' if f.ok else 'FAIL'}] {f.check} — {f.detail}" for f in findings]
    report = "\n".join(lines)
    ok = not fails
    header = ("LINEAGE AUDIT: PASS (all headline numbers self-consistent)" if ok else
              f"LINEAGE AUDIT: FAIL ({len(fails)} inconsistencies — deliverable INVALID until fixed)")
    return ok, header + "\n" + report


if __name__ == "__main__":
    # replicate the Session-9 defect
    scored = ["MMP7", "CASP3", "PTGS2", "AKT1", "HMOX1", "BCL2", "ALDH1A1", "RELA",
              "CCL2", "CDH1", "COL3A1", "AIFM1", "H2AX", "SOAT1"]
    raw81 = scored + ["HRH1", "IL6", "FASLG", "IL1R1"]  # gated genes still present
    gated = ["HRH1", "IL6", "FASLG", "IL1R1"]
    findings = [
        check_count("hub_scored", 14, len(scored)),
        check_table_len("step3_hub_targets", 14, len(raw81)),          # FAIL (81 != 14)
        check_no_gated_leak("step3_hub_targets", gated, raw81),         # FAIL (leak)
    ]
    ok, rep = audit(findings)
    print(rep)
