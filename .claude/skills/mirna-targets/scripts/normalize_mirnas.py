#!/usr/bin/env python3
"""
Step 1 of the miRNA→target layer: NORMALISE + CHECK cargo miRNA names.

Why this exists: the downstream databases disagree on naming. miRTarBase / miRDB /
ENCORI use the mature name (hsa-miR-181a-5p); TargetScan keys on the miRNA *family*
(miR-181-5p). An unnormalised or arm-less name (miR-199a vs miR-199a-5p/-3p) silently
drops real edges. Run this first and resolve every WARN before building List A.

Usage:
    conda activate moa
    python normalize_mirnas.py                 # runs on the built-in example cargo
    python normalize_mirnas.py my_cargo.txt     # one miRNA per line

Dependency: none (stdlib). miRBase accession resolution is optional (see resolve_mirbase()).
"""
import re
import sys
from typing import List, Dict

try:  # Windows console is cp1252; keep the '-p'/arrow/warn glyphs readable
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- Example cargo: the hAMSC/hAESC exosome miRNA set (edit or pass a file) -------------
EXAMPLE_CARGO = [
    "miR-181a-5p", "miR-199a", "miR-1246", "miR-152-3p", "miR-320a-3p",
    "let-7f-5p", "let-7i-5p", "let-7g-5p", "let-7a-5p", "let-7b-5p",
    "miR-10a-5p", "miR-20a-5p", "miR-21-5p", "miR-23a-3p", "miR-24-3p",
    "miR-26a-5p", "miR-27a-3p", "miR-29a-3p", "miR-30d-5p", "miR-92a-3p",
    "miR-99a-5p", "miR-100-5p", "miR-125b-5p", "miR-143-3p", "miR-146a-5p",
    "miR-191-5p", "miR-199a-5p", "miR-199a-3p", "miR-199b-5p", "miR-221-3p",
    "miR-222-3p", "miR-335-5p", "miR-378a-3p", "miR-423-3p", "miR-424-5p",
    "miR-486-5p", "miR-503-5p", "miR-3195", "miR-7110-5p", "miR-12136",
]

MATURE_RE = re.compile(r"^hsa-(miR|let)-\d+[a-z]*(-\d+)?(-[35]p)?$")


def normalize_name(name: str, species: str = "hsa") -> str:
    """Add species prefix and tidy casing. Does NOT invent an arm suffix."""
    n = name.strip()
    if not n.lower().startswith(species + "-"):
        n = f"{species}-{n}"
    # canonical casing: 'miR' / 'let'
    n = re.sub(r"(?i)^%s-mir-" % species, f"{species}-miR-", n)
    n = re.sub(r"(?i)^%s-let-" % species, f"{species}-let-", n)
    return n


def check_cargo(names: List[str], species: str = "hsa") -> Dict[str, List[str]]:
    """Return categorised issues so nothing is silently mis-mapped downstream."""
    report = {"ok": [], "missing_arm": [], "malformed": [], "duplicates": []}
    seen = set()
    for raw in names:
        n = normalize_name(raw, species)
        if n in seen:
            report["duplicates"].append(n)
            continue
        seen.add(n)
        if not MATURE_RE.match(n):
            report["malformed"].append(f"{raw} -> {n}")
        elif not re.search(r"-[35]p$", n):
            # e.g. miR-199a / miR-1246 / miR-3195 — no arm. Some are legitimately
            # single-arm in miRBase; others need -5p/-3p disambiguation. FLAG, don't guess.
            report["missing_arm"].append(n)
        else:
            report["ok"].append(n)
    return report


def resolve_mirbase(name: str):
    """Optional: resolve a mature name to its MIMAT accession via bioservices.
    Returns None if bioservices/miRBase is unavailable — do not hard-fail the pipeline."""
    try:
        from bioservices import miRBase  # type: ignore
    except Exception:
        return None
    try:
        return miRBase().get_mirna(name)
    except Exception:
        return None


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as fh:
            cargo = [ln.strip() for ln in fh if ln.strip()]
    else:
        cargo = EXAMPLE_CARGO

    rep = check_cargo(cargo)
    print(f"Cargo size: {len(cargo)}  |  unique OK: {len(rep['ok'])}")
    if rep["missing_arm"]:
        print(f"\n[WARN] {len(rep['missing_arm'])} name(s) have NO arm (-5p/-3p) — "
              f"confirm the intended mature strand in miRBase before use:")
        for n in rep["missing_arm"]:
            print(f"   - {n}")
    if rep["malformed"]:
        print(f"\n[FAIL] {len(rep['malformed'])} malformed name(s) — fix before proceeding:")
        for n in rep["malformed"]:
            print(f"   - {n}")
    if rep["duplicates"]:
        print(f"\n[WARN] duplicate(s) collapsed: {sorted(set(rep['duplicates']))}")
    print("\nNormalised list (feed to encori_targets.py / query_flatfiles.py):")
    for n in rep["ok"] + rep["missing_arm"]:
        print(n)
    # non-zero exit if anything is malformed, so a driver script can gate on it
    return 1 if rep["malformed"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
