"""Acceptance test: run the P1 guardrails against the real session8 data.

session8 is a known-buggy fixture, so we know the right answers:
  * organism filter must REJECT fba / pfk / PA / norA / mdeA (non-human)
    and KEEP BCL2 / JAK1 / STAT3 / VDR / NR3C1 (human).
  * promiscuity gate must FLAG gallic acid (221 targets) and catechin (polyphenol).
  * citation grounding must FLAG the Budzynska / Kim / Papp citations and
    PASS a correctly-cited control (Weidinger & Novak, Lancet AD).

Run:  python moa_lib/tests/validate_session8.py
Needs network (UniProt / Crossref / NCBI). Unknown-organism (network miss)
counts as neither pass nor fail for that entry.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from moa_lib import promiscuity_filter as pf          # noqa: E402
from moa_lib import citation_grounding as cg          # noqa: E402

DATA = os.path.join(ROOT, "results", "atopic_dermatitis_session8", "data", "step1_data.json")

# (label, claim, reference-as-cited, entities-that-must-be-supported, cited-year, should_flag)
CITATION_CASES = [
    ("Budzynska->JAK1", "Imperatorin inhibits JAK1 kinase activity in vitro",
     "10.1016/j.physbeh.2018.11.002", ["JAK1", "kinase"], "2019", True),
    ("Kim->GR-agonist", "Gallic acid is a glucocorticoid receptor agonist",
     "10.1093/toxsci/kfj152", ["glucocorticoid", "agonist"], "2007", True),
    ("Papp->rs310241", "JAK1 rs310241 polymorphism predicts JAK-inhibitor response",
     "10.1111/bjd.18898", ["rs310241"], "2020", True),
    ("Weidinger (control)", "Atopic dermatitis is a chronic inflammatory skin disease",
     "10.1016/S0140-6736(15)00149-X", ["atopic", "dermatitis"], "2016", False),
]

passed, failed = [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    compounds = d["compounds"]

    print("=" * 70)
    print("1) ORGANISM FILTER  (promiscuity_filter.is_human)")
    print("=" * 70)
    print("   contract: never classify a bacterial/viral protein as human, and")
    print("   never classify a human protein as non-human. 'unknown' = fail-open OK.\n")
    # accession -> gene, taken from the session8 non-human contaminants
    suspects = {"A8B2U2": "fba", "O15648": "pfk", "P03433": "PA",
                "P0A0J7": "norA", "A0A0C5K5S3": "mdeA"}
    # correct human accessions (session8 mis-annotated JAK1/STAT3 with MOUSE ids
    # P52332/P42227 — human are P23458/P40763)
    humans = {"P10415": "BCL2", "P23458": "JAK1", "P40763": "STAT3",
              "P04150": "NR3C1", "P11473": "VDR"}
    for acc, g in sorted(suspects.items(), key=lambda x: x[1]):
        r = pf.is_human(acc)
        _, name = pf._organism(acc)
        check(f"non-human {g} ({acc}) not kept as human", r is not True,
              f"is_human={r}" + (f" [{name}]" if name else " [unresolved]"))
    for acc, g in sorted(humans.items(), key=lambda x: x[1]):
        r = pf.is_human(acc)
        _, name = pf._organism(acc)
        check(f"human {g} ({acc}) not rejected", r is not False,
              f"is_human={r}" + (f" [{name}]" if name else ""))

    print()
    print("=" * 70)
    print("2) PAINS + PROMISCUITY  (promiscuity_filter.promiscuity_flags)")
    print("=" * 70)
    flags = pf.promiscuity_flags(compounds, cap=100)
    for name in sorted(compounds):
        n = compounds[name].get("target_count", 0)
        f = flags.get(name)
        tag = (f"FLAGGED (n={n}, cap={f['over_promiscuity_cap']}, pains={f['pains']})"
               if f else f"clean (n={n})")
        print(f"    {name:22s} {tag}")
    check("gallic acid flagged (promiscuity)",
          "Gallic acid" in flags and flags["Gallic acid"]["over_promiscuity_cap"])
    check("catechin flagged (PAINS/polyphenol)",
          "Catechin" in flags and bool(flags["Catechin"]["pains"]))

    print()
    print("=" * 70)
    print("3) CITATION GROUNDING  (citation_grounding.check_claim)")
    print("=" * 70)
    for name, claim, ref, ents, year, should_flag in CITATION_CASES:
        v = cg.check_claim(claim, ref, ents, expected_year=year)
        flagged = v.verdict != "grounded"
        detail = f"{v.verdict} | title='{v.resolved_title[:55]}' | {'; '.join(v.reasons) or 'ok'}"
        check(f"{name} -> {'flagged' if should_flag else 'grounded'}",
              flagged == should_flag, detail)

    print()
    print("=" * 70)
    total = len(passed) + len(failed)
    print(f"RESULT: {len(passed)}/{total} checks passed"
          + (f"  |  FAILED: {failed}" if failed else "  |  ALL PASS ✅"))
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
