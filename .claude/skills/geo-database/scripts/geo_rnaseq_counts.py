#!/usr/bin/env python3
"""
GEO RNA-seq raw counts -> samples x genes matrix + sample metadata  (verified 2026-11)

Why this exists: for RNA-seq series, GEOparse sample tables are EMPTY and gse.pivot_samples("VALUE")
raises KeyError: 'ID_REF'; the series-matrix file has 0 data rows (GSE121212: 147 samples, 0 rows).
The counts live elsewhere:

  1. NCBI-generated raw counts (human/mouse RNA-seq processed by GEO since ~2023):
       https://www.ncbi.nlm.nih.gov/geo/download/?type=rnaseq_counts&acc=GSE...
     lists  GSE..._raw_counts_GRCh38.p13_NCBI.tsv.gz  (rows = NCBI GeneID, columns = GSM IDs)
  2. Otherwise the submitter's supplementary files (/geo/series/GSEnnn/GSE.../suppl/), format varies.

Trap: www.ncbi.nlm.nih.gov/geo/download can answer HTTP 200 with a reCAPTCHA HTML page instead of the
file or the listing (seen 2026-11 after a burst of requests). Every response here is checked: a CAPTCHA
raises GeoCaptchaError - it never becomes "no counts available". Do not try to get past the CAPTCHA;
retry later or save the file from a browser (downloads are cached in destdir and reused).
GeneID -> symbol uses NCBI gene_info from the HTTPS FTP mirror (ftp.ncbi.nlm.nih.gov), which is not gated.

Dependencies: requests, pandas, GEOparse
"""

import gzip
import html
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests

GEO_DL = "https://www.ncbi.nlm.nih.gov/geo/download/"
GENE_INFO = {"human": "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz",
             "mouse": "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Mus_musculus.gene_info.gz"}
UA = {"User-Agent": "geo-rnaseq-counts/1.0 (python-requests)"}


class GeoCaptchaError(RuntimeError):
    """GEO answered with a reCAPTCHA page. The data's existence is UNKNOWN - never read this as 'no counts'.
    Do not try to get around it: wait and retry later, or download the file in a browser and pass the path."""


def _is_captcha(text: str) -> bool:
    return "recaptcha" in text.lower()


def _download(url: str, dest: Path, params: Optional[dict] = None) -> Path:
    """Download once to dest (cached); refuse anything that is not gzip (reCAPTCHA pages arrive as HTTP 200)."""
    if dest.exists() and dest.stat().st_size > 0 and dest.read_bytes()[:2] == b"\x1f\x8b":
        return dest
    r = requests.get(url, params=params, headers=UA, timeout=600)
    r.raise_for_status()
    if r.content[:2] != b"\x1f\x8b":
        if _is_captcha(r.text[:50000]):
            raise GeoCaptchaError(f"{r.url}: GEO served a CAPTCHA page (HTTP {r.status_code}). Retry later, or save the "
                                  f"file from a browser to {dest} and re-run (cached files are used as-is).")
        raise RuntimeError(f"not a gzip file from {r.url} (HTTP {r.status_code}, {r.headers.get('Content-Type')})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def list_ncbi_count_files(gse: str) -> List[str]:
    """File names GEO offers for this series. [] = GEO's page loaded and lists no NCBI-generated counts
    (use the supplementary files). A CAPTCHA page raises GeoCaptchaError instead of returning []."""
    r = requests.get(GEO_DL, params={"acc": gse, "type": "rnaseq_counts"}, headers=UA, timeout=120)
    r.raise_for_status()
    if _is_captcha(r.text):
        raise GeoCaptchaError(f"{gse}: GEO served a CAPTCHA instead of the download page - existence of counts unknown")
    return sorted({html.unescape(m) for m in re.findall(rf"file=({re.escape(gse)}_[A-Za-z0-9_.\-]+\.gz)", r.text)})


def ncbi_raw_counts(gse: str, destdir: str = "./data", organism: str = "human"):
    """Return (counts samples x genes [int], symbol_map GeneID->symbol). Columns are gene SYMBOLS where
    mappable; unmapped GeneIDs are kept as 'GeneID:<n>' so nothing is silently dropped."""
    import pandas as pd
    files = [f for f in list_ncbi_count_files(gse) if "_raw_counts_" in f]
    if not files:
        raise LookupError(f"{gse}: no NCBI-generated raw counts - use the series' supplementary files")
    dest = Path(destdir)
    p = _download(GEO_DL, dest / files[0], {"type": "rnaseq_counts", "acc": gse, "format": "file", "file": files[0]})
    raw = pd.read_csv(p, sep="\t", index_col=0)                     # GeneID x GSM
    gi = _download(GENE_INFO[organism], dest / Path(GENE_INFO[organism]).name)
    info = pd.read_csv(gi, sep="\t", usecols=["GeneID", "Symbol", "type_of_gene"], dtype={"GeneID": int})
    sym = dict(zip(info.GeneID, info.Symbol))
    cols = [sym.get(int(g), f"GeneID:{g}") for g in raw.index]
    counts = raw.T
    counts.columns = cols
    counts = counts.T.groupby(level=0).sum().T                     # merge rare duplicate symbols
    counts.attrs.update(source=f"{GEO_DL}?type=rnaseq_counts&acc={gse}&file={files[0]}",
                        n_unmapped=sum(c.startswith("GeneID:") for c in cols),
                        protein_coding=set(info.loc[info.type_of_gene == "protein-coding", "Symbol"]))
    return counts.astype(int), sym


def sample_metadata(gse: str, destdir: str = "./data"):
    """samples x fields from GSM characteristics_ch1 ('key: value' pairs) + title."""
    import GEOparse
    import pandas as pd
    g = GEOparse.get_GEO(geo=gse, destdir=destdir, silent=True)
    rows = {}
    for gsm, s in g.gsms.items():
        d = {"title": (s.metadata.get("title") or [""])[0]}
        for c in s.metadata.get("characteristics_ch1", []):
            k, _, v = c.partition(":")
            d[k.strip()] = v.strip()
        rows[gsm] = d
    return pd.DataFrame.from_dict(rows, orient="index")


if __name__ == "__main__":
    # Known-answer test: GSE121212 (AD / psoriasis / healthy skin RNA-seq). Lesional AD vs healthy
    # skin must show the epidermal-inflammation genes UP (S100A8/S100A9, KRT16, SERPINB4).
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))      # project root -> moa_lib
    from moa_lib.transcriptomics import disease_signature
    dd = sys.argv[1] if len(sys.argv) > 1 else "./data"
    print("NCBI count files:", list_ncbi_count_files("GSE121212"))
    counts, _ = ncbi_raw_counts("GSE121212", dd)
    md = sample_metadata("GSE121212", dd)
    print("counts", counts.shape, "| unmapped GeneIDs:", counts.attrs["n_unmapped"], "| metadata fields:", list(md.columns))
    md["group"] = md["patient's condition"] + "_" + md["skin type"]
    print(md["group"].value_counts().to_dict())
    keep = md.index[md.group.isin(["AD_lesional", "CTRL_healthy"])]
    sig = disease_signature(counts.loc[counts.index.intersection(keep)], md.loc[keep], "group", "AD_lesional", "CTRL_healthy")
    print(f"tested={sig.n_tested} up={len(sig.up_genes)} down={len(sig.dn_genes)} | top up: {sig.up_genes[:15]}")
    res = sig.results_df
    for g in ["S100A8", "S100A9", "KRT16", "SERPINB4"]:
        print(f"  {g}: log2FC={res.loc[g, 'log2FoldChange']:.2f} padj={res.loc[g, 'padj']:.1e}")
        assert res.loc[g, "log2FoldChange"] > 1 and res.loc[g, "padj"] < 0.05, f"known-answer FAIL: {g}"
    print("OK")
