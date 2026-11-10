# Instrument gotchas — known-broken tools and their workarounds

> **On-demand reference** (NOT auto-loaded), like `pipeline_changelog.md` and `pdf_generation.md`.
> **Read this when** a fetch returns zero, a figure or PDF looks wrong, or an identifier match
> comes back empty.

**What belongs here, and why it is in the repo rather than in a session memory store.**
Every entry below is *instrument* knowledge: this tool is broken in this specific way, here is the
workaround. None of it says what any run concluded. That distinction is load-bearing —

- **Instrument knowledge makes a run better** and does not bias it: knowing that a PubMed `[tiab]`
  zero is a broken search rather than absent literature stops you from drawing a wrong conclusion
  from a broken reading. It does not tell you what the answer is.
- **A run's findings must never be ambient.** They live in `results/…` and `reviews/…`, and a
  session reads them only when the task explicitly says to (e.g. "compare against session 9").
  Injecting a prior verdict into every session destroys run independence and contaminates any
  attempt to measure the agent (see `agent_evaluation.md` §13 / 中文版 §13, *Contamination*).

Every one of these failed **silently** — plausible output, wrong content — and was caught by a
known-answer control, not by reading the numbers.

---

## 1. Literature retrieval

### 1.1 PubMed abstract search cannot see Methods

`"collagenase VIII"[tiab]` returns **0** hits on PubMed; the same phrase in Europe PMC full text
returns **200+**. Enzyme identity, concentration, digestion time, viability %, yield, "% of CD45+"
all live in Methods/Results, which PubMed does not index. **A zero here is a broken instrument, not
absent literature** — never report it as "no evidence exists".

- **Europe PMC REST:**
  `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json&resultType=core&cursorMark=*`
  (paginate via `nextCursorMark`; `isOpenAccess` / `inEPMC` flag full-text-minable records).
- **Full text XML:** `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML` —
  **no `/PMC/` path segment**. `…/rest/PMC/PMC123…/fullTextXML` 404s; `…/rest/PMC123…/fullTextXML`
  is correct.
- Expect roughly **1/3** full-text fetch success on a broad OA set. Cell Press / ScienceDirect
  return HTTP 403.
- **Ranking by citation count finds the wrong papers** for a methods question — it surfaces famous
  biology that merely used the reagent. Filter to methods journals (Nat Protoc, STAR Protoc,
  Curr Protoc, J Immunol Methods, JoVE, Cytometry) or to titles matching
  protocol / isolation / comparison / optimization.

Working implementations: `reviews/q1_gut_immune_isolation/scripts/`.

### 1.2 NCBI efetch DOIs — the reference-list trap

**Never extract DOIs from NCBI efetch XML with a greedy `.//ArticleId` search.** A
`<PubmedArticle>` embeds a `<ReferenceList>` whose entries carry their own
`<ArticleId IdType="doi">`, so a greedy match returns a **cited** paper's DOI.

Observed: PMID 25756877 (*PLoS One*) came back with `10.1172/JCI43271` (a *J Clin Invest* DOI).
Titles and PMIDs stayed correct, so the citation gate **passed** — only the DOIs were wrong, which
is exactly the class of error that ships.

```python
doi = ""
for aid in art.findall("./PubmedData/ArticleIdList/ArticleId"):   # the article's OWN ids
    if aid.get("IdType") == "doi":
        doi = aid.text or ""; break
if not doi:
    for el in art.findall("./MedlineCitation/Article/ELocationID"):
        if el.get("EIdType") == "doi":
            doi = el.text or ""; break
```

Same fix for `pmc` ids. **Post-check:** the DOI prefix must match the journal's publisher
(`10.1016/j.xpro` = STAR Protocols, `10.1371/journal.pone` = PLoS One, `10.1038/s41598` = Sci Rep,
`10.1002/…` = Wiley). A prefix/journal mismatch means this bug.

### 1.3 Reading a number that exists only in a figure

The JATS `fullTextXML` gives `<graphic xlink:href="…">` per `<fig>`, but the obvious
`https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/bin/{href}.jpg` **404s** — the on-disk blob name is
hashed, not the href.

1. GET the article HTML `https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/` with a browser User-Agent.
2. Regex the real image URLs: `<img[^>]+src="(https://cdn\.ncbi\.nlm\.nih\.gov/pmc/blobs/[^"]+)"`.
   Match the wanted figure by href substring (`Fig3_HTML`, `gr4.jpg`, `fig2.jpg`); download that
   CDN blob (JPEG magic bytes `\xff\xd8\xff`).
3. **Read the `.jpg` with the Read tool** and transcribe. Mark every such value
   **[figure-derived]**, give rank order and approximate magnitude, **never invented decimals**.

`europepmc.org` / `www.ebi.ac.uk` show transient DNS blips (retry); `cdn.ncbi.nlm.nih.gov` is stable.

### 1.4 Taiwanese government health sites

Each fails a different way:

- **hpa.gov.tw / mohw.gov.tw** — WebFetch dies on `certificate has expired`. Fix:
  `requests.get(url, verify=False, headers={"User-Agent": "Mozilla/5.0 …"})` in a script.
- **nhi.gov.tw HTML** — Cloudflare challenge → 403 for both WebFetch and `requests`. Not worth
  fighting; use the mirrored announcement, news coverage, or the linked PDF.
- **nhi.gov.tw PDFs** (`/ch/dl-NNNNN-….pdf`) — WebFetch retrieves the file but cannot read the
  compressed stream. The PDF **is** saved to the session `tool-results/` dir (path printed in the
  tool result); open that local file with `fitz` (pymupdf) `get_text()` — extracts cleanly, CJK
  included. Same trick works for FDA / manufacturer drug labels.
- The 「藥品給付規定」修訂對照表 PDFs are authoritative for NHI reimbursement rules (revised-vs-original
  text, effective date, rule numbers). Prefer them over news when the number matters.
- **PUA hazard:** symbol-font PDFs (drug labels) encode `≥ ≤ – >` in the Unicode Private Use Area.
  Normalise the PUA range **before** any numeric comparison — a label encoding "4–8 weeks" extracted
  as "48 weeks" once reached a report. (Also recorded in CLAUDE.md §8.)

### 1.5 A 200 is not content

- **NCBI Bookshelf (`/books/NBK…`, StatPearls)** returns **200 with a reCAPTCHA page** of about
  21 KB to scripts and to WebFetch. A status-code or length check counts it as full text. One
  retrievability tally overstated its full-text count by five sources this way. Check for
  `checking your browser` and for a topic keyword before accepting any page.
- **Guideline publishers** (ahajournals.org, jacc.org, heartrhythmjournal.com, academic.oup.com PDFs,
  hrsonline.org) return 403 to scripts. `academic.oup.com` article HTML opens in WebFetch, but
  WebFetch is model-mediated, caps quotes at about 125 characters, and keeps no raw text. Fragments
  from it can come back reworded, so label them as such and do not call them verbatim.
- **Europe PMC `isOpenAccess=N` does not mean no text.** PMC author manuscripts can have `pmcid` set,
  `fullTextXML` empty, and NCBI `efetch db=pmc rettype=xml` returning the whole article (HRS 2015
  syncope consensus: 113 K characters). Try `efetch` before writing a source off.
- **Scanned PMC back issues** (e.g. BMJ 2002 "ABC of clinical electrocardiography") return only
  metadata from `efetch`, about 800 characters.
- **Institutional repositories** can sit behind AWS WAF "Human Verification", which may pass one
  request and block the next. Do not try to bypass it. Save bytes to disk the first time, because a
  run that discards a successful download may not get a second one.

### 1.6 `citation_grounding.check_claim` false passes

- Entity overlap uses `min_overlap=0.5` by default. With two entities, a wrong dose (`"400 mg"` against
  a source saying 400 micrograms) and a guideline with **no abstract** both returned `grounded`, one
  title word being enough.
- The auto-entity fallback regex `\b[A-Z]…\b` finds nothing inside Chinese text, because CJK characters
  are word characters, so `\b` never fires. A Chinese claim with no explicit entities returns
  `flagged` with `missing=[]`.
- `resolve()` is under `@lru_cache`, which **caches `None`**. A throttled lookup stays failed for the
  whole process, so a retry loop must call `resolve.cache_clear()` first.
- For claim-level grounding, require a verbatim quote from stored text and check numbers against it.
  The `pbl-report` skill has a working gate in `scripts/templates/`.

---

## 2. Identifiers and ontologies

### 2.1 miRBase renaming silently drops cargo miRNAs

Matching arm-less cargo names (`miR-203`, `miR-378`) against miRTarBase with
`^hsa-miR-{core}(-\d+)?(-3p|-5p)?$` returns **zero** rows — miRBase renamed them `miR-203a-3p` /
`miR-378a-3p`. The run still reported a healthy-looking coverage figure.

**Fix:** allow an optional letter suffix **only when the cargo name has no letter itself** —
`letter = "" if core[-1].isalpha() else "[a-z]?"`. Keep the exact anchors (`^…$`) or `miR-21`
swallows `miR-210`.

**How to apply:** always print the per-miRNA hit count and treat **any zero as a naming bug until
disproven**. miR-203 is *the* keratinocyte miRNA — losing it guts a skin analysis.

### 2.2 No ontology has a "myofibroblast" or "M1/M2 polarization" gene set

GO:0036446 is absent from GO_BP_2023 as Enrichr distributes it; ACTA2 lives in Hallmark-EMT /
YAP-TAZ / smooth-muscle-contraction terms; MRC1 (CD206) sits **only** in
endocytosis / phagosome / antigen-presentation terms — no polarization-specific set contains it.

**Fix:** operationalise each as a **documented proxy** — myofibroblast = TGF-β/SMAD + YAP/TAZ-Hippo
+ EMT + collagen-fibril; macrophage polarization = macrophage/monocyte terms + IFN-γ/TLR4 (M1) +
IL-4/IL-13/IL-10 (M2) + the arginine/NO switch (NOS2 vs ARG1). MRC1 stays **unrecoverable —
report the gap, do not widen until it appears.**

**Why:** widening a gene set until the anchor shows up is p-hacking the gene set.
**How to apply:** multi-anchor controls (3–4 textbook markers, ALL required); a partial hit is a
reported gap, never rounded to "ok".

### 2.3 Network proximity needs a genome-wide interactome

Building the STRING graph from `List A ∪ modules` (~800 nodes) gives **z_c = +1.0 … +3.4**
(targets "farther" than random) even with a compact module, because in a dense bounded subgraph
everything is one hop from a hub. Downloading STRING v12 human links at `combined_score ≥ 700`
(16,201 nodes / 236,930 edges; ~85 MB, caches to <1 MB adjacency JSON) flips the **same data** to
**z_c = −10.7 … −17.2**.

**Why it matters:** a positive z_c looks like a real negative result and would wrongly trigger the
CLAUDE.md §3 HALT gate. **How to apply:** never compute proximity on an API-assembled subgraph;
build the full interactome once (`scripts/build_interactome.py` pattern) and also pass
`exclude_from_null=module`.

### 2.4 Disease-gene APIs moved under the Step-2 skills (checked 2026-11-09)

Every item below returned **HTTP 200 with plausible but wrong output**, or a hard failure that older scripts
caught and turned into `0`. All eight Step-2 skills were patched and re-verified against known answers;
details and working code live in each skill.

- **Disease IDs migrated EFO → MONDO, and the old ID is not redirected.** Atopic dermatitis `EFO_0000274`
  is now `MONDO_0004980`, and T2D `EFO_0001360` is now `MONDO_0005148`. Open Targets returns
  `disease: null`, and GWAS v2 returns `totalElements: 0`. **Resolve by name, and record the ID used.**
- **GWAS Catalog:** the v1 REST and Summary-Statistics APIs return **410 Gone**, so use `/rest/api/v2`. Very
  strong hits have `p_value` underflow to `0.0`, so rank on `pvalue_mantissa`/`pvalue_exponent`. Mapped
  genes include lncRNAs (CCDST, LINC01527); filter to protein-coding before intersecting.
- **Open Targets 26.x schema:** `page` needs `{index, size}`. `componentId`→`id`,
  `knownDrugs`→`drugAndClinicalCandidates`, and `evidences(datatypes:)`→`datasourceIds:`.
- **Monarch:** the base URL needs `/v3/api`, and items are flat strings. **Complex diseases return 0 genes**
  on the main ID (AD: 0; FLG only on "dermatitis, atopic, susceptibility to"). That is a coverage gap, not a
  fetch failure.
- **NCBI ESearch ignores unknown field tags silently** and searches All Fields instead. ClinVar
  `pathogenic[CLNSIG]` = 2,322 hits for CFTR, against 1,295 for the real `clinsig_pathogenic[prop]`. Gene
  `[disease]`, `[phenotype]`, `[pathway]` and `[taxid]` are all ignored the same way. Test a new tag by
  comparing its count with a made-up tag.
- **ClinVar esummary:** `clinical_significance` is gone; use `germline_classification`.
- **Gene symbols collide with aliases.** `FLG[gene]` and Datasets `symbol/FLG` both return **FGFR1 first**.
  Resolve with `[pref]` first, and accept an alias only when unique.
- **GEO RNA-seq:** `pivot_samples` raises `KeyError: 'ID_REF'`, and the series matrix has 0 rows. Counts
  come from `geo/download/?type=rnaseq_counts`. That host can serve a **reCAPTCHA as HTTP 200**: detect it
  and stop (unknown ≠ absent); never try to get past it.

---

## 2.5 Self-checks that pass because they cannot fail

Four defects from the SGLT2-inhibitor / obesity run. Each produced a confident green tick over a
wrong number, and **none was caught by the check that was supposed to catch it** — they were caught
by a reviewer recomputing by hand. The pattern is the same every time: the check was written so
that it could not fail.

### 2.5.1 Assert equalities, not inequalities

A lineage check compared drawn graph edges against source edge records with `pairs[t] > el[t]` and
**passed while publishing 94 edges for a 92-edge graph**. An inequality admits an infinite set of
wrong answers; the equality admits one right one.

Two independent bugs produced the 94: a tier-blind `order.index("measured_binding") == 0` that
reclassified a sub-threshold pair, and a read of the *unfiltered* edge list where the eligible one
was meant. Neither would have shipped against `assert computed == expected`.

**Rule:** wherever a quantity can be recomputed exactly, assert equality. Keep a genuine inequality
(`pairs ≤ records`) as a *separate, correctly-typed* relation — do not let it stand in for the
equality.

### 2.5.2 Every check needs a negative control

A check that has never been seen to fail is not known to work. Before trusting one, break the thing
it guards and confirm it goes red: delete a row, perturb a value, re-inject the bug it was written
for. The same run's corrected edge check was negative-controlled three ways, which is why its
`PASS` means something.

### 2.5.3 Cross-source numbers must be tied together

The figure legend said 8/10/30/44; the checker said 9/10/31/44. Both ran from the same JSON, and
nothing required them to agree, so the contradiction sat in the deliverable until a third party
recomputed it. **When the same number is derived in two places, assert that the two derivations are
equal** — and derive it from the one canonical field (here `list_A.rows[*].per_compound[*]
.best_engagement`), not from whatever each site finds convenient.

### 2.5.4 Backups must be write-once

A figure-rebuild script crashed partway, having already overwritten three PNGs. The re-run's backup
step then copied those **relabelled** files over the archived originals. `results/` is untracked, so
there was no copy to restore from.

```python
if dest.exists():            # write-once: never overwrite an existing archive entry
    continue
shutil.copy2(src, dest)
```

Recovery was possible only because one archived file had escaped the overwrite and could serve as a
byte-for-byte control (sha256 match) for a reconstruction. Do not rely on being that lucky.

---

## 3. Figure output

**Every figure must be visually complete, every time** — a standing user requirement, not a
preference. Checklist before any figure is considered done:

- Colour encodes a **value** → you MUST add a colorbar. Capture the mappable
  (`scat = ax.scatter(…)`), then `cb = fig.colorbar(scat, ax=ax); cb.set_label(…)`.
- Marks colour-coded by **category** → add a legend (`matplotlib.lines.Line2D` proxy handles).
  Do not describe the colours only in the caption.
- Always `bbox_inches="tight"` with a sane `figsize` so titles/labels are never clipped.
- Label both axes; keep the title short enough to fit.
- **Read the PNG back and look at it.** Do not assume.
- Figures are derived **from `data/`**, and assert their values against the source before plotting.

---

## 4. PDF output — the font glyph gate

**A character absent from the PDF font renders as an empty `.notdef` box, but the text layer still
contains the original character** — extracting text with PyMuPDF and grepping it will *never*
reveal the problem. The only reliable check is against the font's cmap.

`msyh.ttc` (Microsoft YaHei) lacks **⁺ U+207A, ⁻ U+207B, ⁶ U+2076** — while `³ U+00B3` *is*
present, so the failure is inconsistent and easy to miss (`CD45⁺` rendered as `CD45□`). Greek
(αβγδε), `±`, `·`, `§`, `°`, `µ`, `…` are fine. Also missing: **✅ U+2705** and **⚠ U+26A0**
(+ `U+FE0F`) — a `✅ all recovered` column rendered as `□ all recovered`.

1. In the markdown→flowable `clean()`, map absent characters to ASCII: `⁺`→`+`, `⁻`→`-`, `⁶`→`^6`,
   `−`→`-`, `≠`→`!=` (alongside the existing `→ ↑ ↓ × ≈ ≤ ≥ – —` maps). Use plain words instead of
   emoji status markers in any markdown destined for PDF — **but keep the symbol in matplotlib
   figures**, which use DejaVu and render `⚠` correctly. Patch the two paths separately.
2. Add a font-coverage gate to the verifier:

```python
from fontTools.ttLib import TTCollection
cmap = TTCollection("C:/Windows/Fonts/msyh.ttc").fonts[0].getBestCmap()
nomap = sorted({c for c in clean(md) if ord(c) > 127 and ord(c) not in cmap})
# fail the build if nomap is non-empty
```

3. Strip `<!--HTML comments-->` in the converter — generator markers otherwise render as text.
4. The converter prints markdown backslash escapes literally: `\*` renders as a visible `\*`.
   A bare `*` is safe mid-sentence and in table cells — use `*`, never `\*`.
5. The builder must convert **both** `**bold**` and single-`*italic*`.
6. Cheap pre-scan: flag any `ord(ch) > 0x2000` outside a known-safe set in the generated `.md`
   before building — still read the rendered pages back afterwards.

Build details: `pdf_generation.md`.

---

## 5. Environment

- **Python:** `/c/Users/Joseph/.conda/envs/moa/python.exe` — conda is not on the bash PATH, use the
  full path. Key packages: pubchempy, requests, rdkit, matplotlib, networkx, matplotlib-venn.
- **Windows CJK:** `sys.stdout.reconfigure(encoding="utf-8")` and always
  `open(..., encoding="utf-8")` for any JSON/MD carrying Chinese.
- **Heavy stats:** run in a script file with an `if __name__ == "__main__":` guard (not `python -c`),
  and force single-thread (`n_cpus=1`) where a library uses joblib/loky — Windows process-spawn
  can crash otherwise. `pydeseq2` segfaults in this environment; the DE default is `engine='welch'`.
- **Sub-agents:** general sub-agents lack Write/Bash/WebFetch, so pipeline steps run in the main
  thread. **Read-only review agents do work** — the `report-qa` agent returns findings and the
  orchestrator persists them.
