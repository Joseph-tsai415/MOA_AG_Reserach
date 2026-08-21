---
name: report-pdf
description: Build a fixed-house-style PDF from ANY project markdown report — a results/… MOA run (main report + step appendices), a reviews/… literature synthesis (single markdown), or any standalone .md / list of .md files. reportlab only (no external PDF engine). Handles CJK herb names, bold+italic, wide auto-scaled tables, callouts, numbered/bulleted lists, figures; glyph-gates tofu boxes; verifies the render. Report-voice compliant — no pipeline-version branding on cover or furniture.
license: Internal project tooling (MOA-AG). reportlab (BSD), PyMuPDF (AGPL) — both in the `moa` env.
metadata:
    skill-author: MOA-AG project (house skill)
---

# Report PDF Builder (project-general)

## Overview

One command turns a project markdown report into a polished, **consistently-styled** PDF: cover → body → (optional) appendices → figures, with a fixed palette, CJK-capable fonts, auto-scaled tables, callouts, and a plain footer. Built on **reportlab** — no system LaTeX/typst engine needed (`.claude/docs/pdf_generation.md`). It replaces the per-folder `make_pdf.py` copies (results/session9-10, reviews/q1-q3, synthesis) with **one builder** so every deliverable looks the same.

## Scope — NOT just MOA reports

Any research output in this project needs a PDF, and they do not share one folder shape:
- **`results/…` MOA runs** — step-structured (`step5_final_report.md` + `step0–4` artifacts). Governed by CLAUDE.md.
- **`reviews/…` literature syntheses** — a single narrative markdown per review. Governed by `research_questions.md`.
- **Any standalone report** — one `.md`, or an explicit list to assemble.

This skill serves all three via three input modes; it is a general tool, not tied to the MOA pipeline.

## When to Use This Skill

As the **final "print" step** of any run or review, after the markdown is finalised (for MOA runs, after `report-qa` returns SHIP). Do **not** hand-roll a new `make_pdf.py` — use this.

## Input modes

| Mode | Flag | What it assembles |
|---|---|---|
| **MOA run** | `--run DIR` | `step5_final_report.md` first, then auto-discovered step appendices (step0 provenance · List A · List B · hub targets · MOA summary/table · confidence · validation plan · integrity · HALT) — only those that exist |
| **Single report** | `--report FILE` | cover + that one markdown (reviews / any report) |
| **Explicit list** | `--md F1 F2 … [--base DIR]` | cover + each file, page-broken; `--base` resolves image paths |

## Fixed house style (do not re-theme per run)

- **Palette:** teal `#0f6e6a` (H1/table header), maroon `#8a1c3b` (H3/cover rule), ink body, muted grey; amber-bordered cream callouts; alternating-row tables.
- **Layout:** A4, 1.6 cm margins; cover (title + subtitle + plain verdict + optional cover figure + blurb + date); body; page-broken appendices; plain footer + page number.
- **Fonts:** Microsoft YaHei (`msyh`/`msyhbd`) so 七白散 renders; **Arial fallback** if absent.

## ⚠️ Report-voice rule (enforce it — the Session-10 lesson)

The PDF is a scientific document, so §5 applies to its cover/furniture too:
- **No pipeline-version or session branding** on cover, footer, or headers ("v11", "Session 9" — forbidden there). Session 9's footer carried version branding; Session 10 corrected it. Follow Session 10.
- The **cover verdict** is plain-language science (`--verdict "Promising-but-unproven · not globally AD-selective"`), never a version label.
- Version + session belong **only** in the report's own methods footer (already inside the markdown); the builder never adds them.
- Default MOA appendix set already excludes retired/branded docs (benchmark scorecard, "V11 audit").

## Usage

```
conda activate moa
# MOA run
python .claude/skills/report-pdf/scripts/build_report_pdf.py \
    --run results/<run> --subtitle "<Compound> in <Disease>" \
    --verdict "<plain go/no-go>" --footer "<plain one-liner>" \
    --cover-fig figures/step4_CT_network.png --out result.pdf --verify

# literature review (single markdown)
python .claude/skills/report-pdf/scripts/build_report_pdf.py \
    --report reviews/<review>/<review>.md \
    --title "<question as title>" --footer "<plain one-liner>" --out result.pdf --verify
```

Common flags: `--title` (auto-derives from the first `#` if omitted), `--subtitle`, `--verdict`, `--blurb`, `--date`, `--footer`, `--cover-fig` (relative to base), `--no-cover`, `--out`, `--verify`. **Always pass `--verify`**, then read a `_pdf_preview/page_*.png` back — it is the only way to catch tofu boxes (text extraction can't).

## Robustness (built in — merged from the results/ and reviews/ builders)

- **Glyph gate:** superscript-run collapsing (10⁻¹⁰ → 10^(-10)), subscripts, Greek→ASCII (κ→k, β→beta), set-ops (∩→"and"), checkmarks (✔→Y), smart quotes → ASCII, emoji stripped. Prevents `.notdef` boxes that text extraction cannot detect. Meaningful arrows (↑↓→←) and ×/≤/≥ are kept (msyh renders them).
- **Bold *and* italic** inline (`**b**`, `*i*`), `code`, `[links]` (underlined); the single-`*` italic pass is the `pdf_generation.md` fix.
- **Wide-table handling:** content-weighted column widths + font auto-scaling by column count (≤4→7.8pt … >8→5.4pt) so a 15-column review table still fits.
- **Numbered lists** (`1. 2.`), bulleted lists, HTML-comment stripping.
- **Malformed-markup safety:** `PARA()` degrades a line with illegal tag nesting to plain text instead of crashing the build.
- **Fresh story per build:** reportlab consumes the story list, so the output-lock retry rebuilds it (a reused list produced an empty 1 KB PDF).
- **Output-lock fallback:** if the PDF is open in a viewer, writes `*_v2.pdf` and says so.
- **`--verify`:** counts stray `*` across all pages (0 = clean) and renders sample pages to `_pdf_preview/`.

## Reference
Engine-availability + debug facts: `.claude/docs/pdf_generation.md` (CLAUDE.md §7). This builder supersedes the per-folder `make_pdf.py` copies it was distilled from (results/session9 = style origin; session10 = report-voice-corrected furniture; reviews/q3 = glyph gate + wide tables + numbered lists).
