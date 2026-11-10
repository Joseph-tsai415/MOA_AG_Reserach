# TEMPLATE: copied from a real run. Replace the case-specific checks before use.
"""03 — Lineage audit: recompute every headline number from data/ and assert it in the report.

Writes data_integrity_check.md. Any FAIL makes the deliverable invalid.

Run: conda run -n moa python 03_lineage_audit.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
md = (ROOT / "pbl_case4_syncope.md").read_text(encoding="utf-8")
facts = json.loads((DATA / "case_facts.json").read_text(encoding="utf-8"))
man = json.loads((DATA / "sources_manifest.json").read_text(encoding="utf-8"))
gate = json.loads((DATA / "citation_gate.json").read_text(encoding="utf-8"))
checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))


def has(s):
    return s in md


# --- case facts appear unchanged -------------------------------------------------------
for s in (f"{facts['age']} 歲", f"近 {facts['stood_minutes']} 分鐘", f"約 {facts['recovery_seconds']} 秒",
          f"{facts['family_history_cutoff_age']} 歲前", f"門診血壓 {facts['vitals_clinic']['sbp']}/{facts['vitals_clinic']['dbp']} mmHg",
          f"門診脈搏 {facts['vitals_clinic']['pulse']} 次/分"):
    check(f"case fact present: {s}", has(s))

# --- orthostatic table: rows, values and recomputed deltas ------------------------------
o = facts["orthostatic"]
base = o[0]
sec = md.split("本案站立測試結果")[1].split("→ 本案推論")[0]
rows = [r for r in sec.splitlines() if r.startswith("|") and "---" not in r][1:]
check("站立表 row count equals source", len(rows) == len(o), f"{len(rows)} vs {len(o)}")
for p, r in zip(o, rows):
    cells = [c.strip() for c in r.strip("|").split("|")]
    check(f"站立表 {p['pos']} BP/HR", cells[0] == p["pos"] and cells[1] == f"{p['sbp']}/{p['dbp']}" and cells[2] == str(p["hr"]), r)
    if p is not base:
        want = [f"−{base['sbp'] - p['sbp']}", f"−{base['dbp'] - p['dbp']}", f"+{p['hr'] - base['hr']}"]
        check(f"站立表 {p['pos']} deltas recomputed", cells[3:6] == want, f"{cells[3:6]} vs {want}")
d = o[2]
ds, dd, dh = base["sbp"] - d["sbp"], base["dbp"] - d["dbp"], d["hr"] - base["hr"]
check("narrative 3-min change", has(f"血壓下降 {ds}/{dd} mmHg、心率上升 {dh} 次/分"))
check("sub-threshold claim is true", ds < 20 and dd < 10 and dh < 40, f"Δ{ds}/{dd}, +{dh}")

# --- ECG measurement recomputed ---------------------------------------------------------
e = facts["ecg_figure_measurement"]
px = e["r_peaks_px"]
rr = [b - a for a, b in zip(px, px[1:])]
mean_rr = sum(rr) / len(rr)
boxes = mean_rr / e["large_box_px"]
rate = 60 / (boxes * e["large_box_seconds"])
check("ECG beats", has(f"連續 {len(px)} 個 R 波"), str(len(px)))
check("ECG R-R in large boxes", has(f"約 {boxes:.2f} 大格"), f"{boxes:.2f}")
check("ECG rate", has(f"約 {rate:.0f} 次/分"), f"{rate:.1f}")

# --- reference list <-> citations -------------------------------------------------------
used = gate["sources_cited"]
tiers = gate["source_tiers"]
counts = f"實際引用 {len(used)} 筆來源：全文 {tiers['FULL_TEXT']} 筆、僅摘要 {tiers['ABSTRACT_ONLY']} 筆、網頁全文 {tiers['WEB_TEXT']} 筆、指引節錄 {tiers['PAGE_EXCERPT']} 筆"
check("source count sentence", has(counts), counts)
check("tiers sum to sources", sum(tiers.values()) == len(used))
refs = md.split("## 12. 參考資料")[1].split("---")[0]
entries = [r for r in refs.split("\n\n") if r.strip()]
check("reference entries == sources cited", len(entries) == len(used), f"{len(entries)} vs {len(used)}")
for k in used:
    check(f"reference present: {k}", gate["refs"][k] in md)
failed = [k for k, v in man.items() if v["status"] == "FETCH_FAILED"]
check("no FETCH_FAILED source cited", not (set(failed) & set(used)), ",".join(failed))
check("citation gate clean", not gate["fails"], str(len(gate["fails"])))

# --- in-text citations resolve to an entry ---------------------------------------------
body = md.split("## 12. 參考資料")[0]
pairs = set()
for group in re.findall(r"\(([^()]*?\d{4}[ab]?[^()]*?)\)", body):
    for part in group.split(";"):
        m = re.match(r"\s*([^,]+),\s*(\d{4}[ab]?)\s*$", part)
        if m:
            pairs.add((m.group(1).strip(), m.group(2)))
for name, year in sorted(pairs):
    first = name.replace(" et al.", "").split(" & ")[0].split()[0]
    check(f"in-text resolves: {name}, {year}", any(first in r and f"({year}" in r for r in entries))

# --- numbering, figures, residue --------------------------------------------------------
tables = [int(x) for x in re.findall(r"\*\*表 (\d+)\.\*\*", md)]
figs = [int(x) for x in re.findall(r"\*\*圖 (\d+)\.\*\*", md)]
check("tables numbered consecutively", tables == list(range(1, len(tables) + 1)), str(tables))
check("figures numbered consecutively", figs == list(range(1, len(figs) + 1)), str(figs))
for f in re.findall(r"\]\((figures/[^)]+)\)", md):
    check(f"figure exists: {f}", (ROOT / f).exists())
check("no unrendered markers", "[[" not in md and "{{" not in md)
check("ESC limits disclosed", "原文未存檔" in md and "僅能對回上述節錄" in md)
check("every paraphrased entry is an ESC entry", set(gate["paraphrased_not_verbatim"]) <= set(gate["esc_cited"]))
check("AI assistance disclosed", "協作揭露" in md)

# Sufficiency, not truth: can a reader explain the disease from this report alone?
for term in ():  # the terms a reader needs for THIS disease
    check(f"explains: {term}", term in md)
mech = md.split("### 8.2 機轉")[1].split("**圖 5.**")[0]
mech_cn = re.sub(r"\([^()]*\d{4}[ab]?[^()]*\)|!\[.*?\]\(.*?\)", "", mech)
check("mechanism section is developed", len(mech_cn) >= 600, str(len(mech_cn)))
check("mechanism states what is debated", "爭議" in mech)
for i in range(1, 7):
    check(f"learning issue {i} answered", f"| {i}. " in md.split("## 10. 學習議題回答")[1].split("## 11.")[0])
check("first-episode trigger reported", "廟會" in md and "喝止" in md)
check("ECG image source disclosed", "Ashley & Niebauer (2004)" in md and "唯一直接沿用的是圖 4" in md)

# Must not inherit from last year's report: its people, its plot, its errors.
for bad in ():  # anything that must not leak in from an example report
    check(f"absent: {bad}", bad not in md)

fails = [c for c in checks if not c[1]]
out = ["# data_integrity_check.md — lineage self-audit", "",
       f"**Result: {'PASS' if not fails else 'FAIL'}** · {len(checks) - len(fails)}/{len(checks)} checks passed", "",
       "| Check | Result | Detail |", "|---|---|---|"]
for name, ok, detail in checks:
    out.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {str(detail).replace('|', '/')[:70]} |")
(ROOT / "data_integrity_check.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"{len(checks) - len(fails)}/{len(checks)} passed")
for name, _, detail in fails:
    print("  FAIL", name, "::", str(detail)[:110])
sys.exit(1 if fails else 0)
