#!/usr/bin/env python3
"""
Download reference flat files INTO the skill so runs never re-download.

Caches under  .claude/skills/mirna-targets/data/  :
  - hsa_MTI.xlsx        miRTarBase validated miRNA-target interactions (E0/E1 backbone)

miRTarBase serves over a legacy-TLS endpoint that modern OpenSSL rejects
("unsafe legacy renegotiation" / SECLEVEL). We attach an SSL context that re-enables
legacy connect and lowers the security level for THIS host only.

Usage:
    conda activate moa
    python download_reference_data.py            # fetch anything missing
    python download_reference_data.py --force    # re-fetch even if present
"""
import argparse
import os
import ssl
import sys

import requests
import urllib3
from urllib3.util import create_urllib3_context

urllib3.disable_warnings()

SKILL_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(SKILL_DATA, exist_ok=True)

# miRTarBase 10.0 (2025) — moved to awi.cuhk.edu.cn
MIRTARBASE_BASE = "https://awi.cuhk.edu.cn/miRTarBase/downloads/files/10.0/"
MIRTARBASE_URLS = [MIRTARBASE_BASE + "hsa_MTI.csv"]               # full human set (has Support Type col)
MIRTARBASE_SE_URLS = [MIRTARBASE_BASE + "miRTarBase_SE_WR.csv"]   # strong evidence: Western+Reporter = E0 gold


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


def download(urls, dest, force=False):
    if os.path.exists(dest) and os.path.getsize(dest) > 10000 and not force:
        print(f"[cached] {os.path.basename(dest)} ({os.path.getsize(dest)//1024} KB) — skip")
        return True
    s = requests.Session()
    s.mount("https://", LegacyTLSAdapter())
    for u in urls:
        try:
            r = s.get(u, timeout=180, verify=False, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) > 10000:
                with open(dest, "wb") as fh:
                    fh.write(r.content)
                print(f"[saved] {os.path.basename(dest)} ({len(r.content)//1024} KB) from {u[:55]}...")
                return True
            print(f"  {u[:60]} -> HTTP {r.status_code}, {len(r.content)} bytes")
        except Exception as e:
            print(f"  {u[:60]} -> {repr(e)[:90]}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    ok = download(MIRTARBASE_URLS, os.path.join(SKILL_DATA, "hsa_MTI.csv"), force=a.force)
    download(MIRTARBASE_SE_URLS, os.path.join(SKILL_DATA, "miRTarBase_SE_WR.csv"), force=a.force)
    print("\nReference data dir:", SKILL_DATA)
    if not ok:
        print("[WARN] miRTarBase download failed — see fallbacks in references/databases_and_tiers.md")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
