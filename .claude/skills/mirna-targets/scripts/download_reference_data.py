#!/usr/bin/env python3
"""
Provision the large reference flat files this skill needs.

The files are NOT in git (`.gitignore`: `.claude/skills/*/data/`) — hsa_MTI.csv is
~322 MB, over GitHub's 100 MB per-file limit. A fresh clone therefore has no data/,
and any script that needs it must call `ensure()` (or an agent runs this once).

Caches under  .claude/skills/mirna-targets/data/  :
  hsa_MTI.csv            miRTarBase 10.0 human validated MTIs  (~322 MB) — the
                         E0/E1 backbone; carries 'Support Type' + 'Experiments'.
  miRTarBase_SE_WR.csv   strong-evidence subset (Western + Reporter) — E0 gold.
                         Optional; hsa_MTI.csv alone is sufficient.

miRTarBase serves over a legacy-TLS endpoint that modern OpenSSL rejects
("unsafe legacy renegotiation" / SECLEVEL). We attach an SSL context that re-enables
legacy connect and lowers the security level for THIS host only.

Usage:
    conda activate moa
    python download_reference_data.py            # fetch anything missing
    python download_reference_data.py --check    # report status, download nothing
    python download_reference_data.py --force    # re-fetch even if present

From another script (preferred — self-provisioning):
    from download_reference_data import ensure
    path = ensure("hsa_MTI.csv")     # downloads only if missing/incomplete
"""
import argparse
import json
import os
import ssl
import sys

import requests
import urllib3
from urllib3.util import create_urllib3_context

urllib3.disable_warnings()

try:  # Windows console is cp1252; keep the em-dash/progress output readable
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

# miRTarBase 10.0 (2025) — moved to awi.cuhk.edu.cn
MIRTARBASE_BASE = "https://awi.cuhk.edu.cn/miRTarBase/downloads/files/10.0/"

# name -> (urls, required CSV header columns, required=True means callers depend on it)
FILES = {
    "hsa_MTI.csv": (
        [MIRTARBASE_BASE + "hsa_MTI.csv"],
        ["miRNA", "Target Gene", "Support Type", "Experiments", "References (PMID)"],
        True,
    ),
    "miRTarBase_SE_WR.csv": (
        [MIRTARBASE_BASE + "miRTarBase_SE_WR.csv"],
        ["miRNA", "Target Gene"],
        False,
    ),
}


class LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """Allow the old TLS renegotiation + low SECLEVEL that miRTarBase's server needs."""

    def init_poolmanager(self, *a, **k):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.options |= 0x4  # SSL_OP_LEGACY_SERVER_CONNECT
        except Exception:
            pass
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        k["ssl_context"] = ctx
        return super().init_poolmanager(*a, **k)


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", LegacyTLSAdapter())
    return s


def _meta_path(dest: str) -> str:
    return dest + ".meta.json"


def verify(name: str) -> tuple:
    """Is the cached file present AND complete AND the schema we parse?

    Returns (ok: bool, detail: str). A size-only check is not enough here: an
    interrupted 322 MB download leaves a multi-MB file that passes any naive
    "bigger than X" test and then silently yields a partial interaction table.
    So we compare against the byte count recorded when the download completed,
    and confirm the header still carries the columns query_flatfiles.py needs.
    """
    dest = os.path.join(SKILL_DATA, name)
    if not os.path.exists(dest):
        return False, "missing"

    size = os.path.getsize(dest)
    meta = {}
    if os.path.exists(_meta_path(dest)):
        try:
            meta = json.load(open(_meta_path(dest), encoding="utf-8"))
        except Exception:
            meta = {}
    expected = meta.get("bytes")
    if expected and size != expected:
        return False, f"INCOMPLETE: {size:,} bytes on disk, {expected:,} expected"

    cols = FILES.get(name, ([], [], False))[1]
    if cols:
        try:
            with open(dest, encoding="utf-8", errors="replace") as fh:
                header = fh.readline()
        except Exception as e:
            return False, f"unreadable: {e}"
        missing = [c for c in cols if c not in header]
        if missing:
            return False, f"SCHEMA: header missing {missing} — miRTarBase layout changed?"

    note = f"{size / 1e6:.0f} MB"
    if not expected:
        note += " (no completeness record — re-download with --force to certify)"
    return True, note


def download(name: str, force: bool = False) -> bool:
    """Stream the file to <name>.part, then atomically move it into place.

    Streaming matters: requests' r.content would hold all ~322 MB in memory, and
    a single flat timeout cannot cover a file this size on a slow legacy-TLS
    link. Writing to .part and renaming only after the byte count checks out
    means an interrupted run can never leave a corrupt file that looks cached.
    """
    urls, _cols, _req = FILES[name]
    dest = os.path.join(SKILL_DATA, name)

    if not force:
        ok, detail = verify(name)
        if ok:
            print(f"[cached] {name} — {detail}")
            return True
        if detail != "missing":
            print(f"[stale]  {name} — {detail} — re-downloading")

    os.makedirs(SKILL_DATA, exist_ok=True)
    part = dest + ".part"
    s = _session()

    for u in urls:
        try:
            with s.get(u, timeout=(30, 120), verify=False, stream=True,
                       headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status_code != 200:
                    print(f"  {u[:60]} -> HTTP {r.status_code}")
                    continue
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                with open(part, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        got += len(chunk)
                        if total:
                            pct = 100 * got / total
                            print(f"\r  {name}: {got / 1e6:7.1f} / {total / 1e6:.1f} MB "
                                  f"({pct:5.1f}%)", end="", file=sys.stderr, flush=True)
                        elif got % (32 << 20) < (1 << 20):
                            print(f"\r  {name}: {got / 1e6:7.1f} MB",
                                  end="", file=sys.stderr, flush=True)
                print("", file=sys.stderr)

            if total and got != total:
                print(f"  TRUNCATED: got {got:,} of {total:,} bytes — discarding")
                os.remove(part)
                continue
            if got < 10000:
                print(f"  too small ({got} bytes) — discarding")
                os.remove(part)
                continue

            os.replace(part, dest)
            json.dump({"url": u, "bytes": got}, open(_meta_path(dest), "w", encoding="utf-8"))
            ok, detail = verify(name)
            if not ok:
                print(f"  [FAIL] downloaded but did not verify: {detail}")
                return False
            print(f"[saved]  {name} — {detail} from {u[:55]}...")
            return True

        except Exception as e:
            print(f"  {u[:60]} -> {repr(e)[:90]}")
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
    return False


def ensure(name: str = "hsa_MTI.csv", force: bool = False) -> str:
    """Return the local path to `name`, downloading it if missing/incomplete.

    Call this from any script that needs the flat file, so a fresh clone
    provisions itself instead of dying on FileNotFoundError.
    """
    if name not in FILES:
        raise KeyError(f"unknown reference file {name!r}; known: {list(FILES)}")
    ok, _ = verify(name)
    if not ok or force:
        if not download(name, force=force):
            raise SystemExit(
                f"[FATAL] could not provision {name}.\n"
                f"  Expected at: {os.path.join(SKILL_DATA, name)}\n"
                f"  Fetch manually:  python {os.path.relpath(__file__)}\n"
                f"  Fallbacks (ENCORI REST, etc.) are listed in "
                f"references/databases_and_tiers.md"
            )
    return os.path.join(SKILL_DATA, name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--force", action="store_true", help="re-fetch even if cached")
    ap.add_argument("--check", action="store_true", help="report status, download nothing")
    a = ap.parse_args()

    print("Reference data dir:", SKILL_DATA)

    if a.check:
        rc = 0
        for name, (_u, _c, required) in FILES.items():
            ok, detail = verify(name)
            tag = "OK  " if ok else ("MISS" if not required else "FAIL")
            print(f"  [{tag}] {name:<24} {detail}")
            if not ok and required:
                rc = 1
        if rc:
            print("\nRun without --check to download.")
        return rc

    ok = download("hsa_MTI.csv", force=a.force)
    download("miRTarBase_SE_WR.csv", force=a.force)  # optional; failure is not fatal

    if not ok:
        print("\n[WARN] miRTarBase download failed — see fallbacks in "
              "references/databases_and_tiers.md")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
