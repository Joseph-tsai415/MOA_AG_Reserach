#!/usr/bin/env python3
"""
General fixed-house-style PDF builder for ANY project report — a `results/…` MOA run,
a `reviews/…` literature synthesis, or any standalone markdown report. reportlab only
(no external PDF engine); see .claude/docs/pdf_generation.md.

Merges the strongest features of the results/ and reviews/ builders:
  - comprehensive glyph gate (superscript/subscript/Greek/set-ops/checkmarks -> ASCII)
    so nothing renders as a .notdef box (text extraction cannot detect boxes)
  - content-weighted table columns + font auto-scaling for wide review tables
  - bold + italic + code + links, callouts, numbered & bulleted lists, images, rules
  - malformed-markup safety (PARA fallback), output-lock fallback, fresh-story-per-build
  - render-verify (--verify): stray-'*' check + sample-page PNGs

MODES (pick one):
  --run  DIR     MOA run:  step5_final_report.md + auto-discovered step appendices
  --report FILE  single markdown report (reviews):  cover + that file
  --md   F [F..] explicit assembly (needs --base for image resolution)

Report-voice: NO pipeline-version/session branding on cover or furniture (CLAUDE.md §5);
the version lives only in the report's own methods footer.

Usage examples:
  python build_report_pdf.py --run results/<run> --subtitle "X in Y" --verdict "…" \
         --cover-fig figures/step4_CT_network.png --verify
  python build_report_pdf.py --report reviews/q3_skin_to_gut/Q3_review.md \
         --title "Does skin inflammation act on the intestine?" --footer "Skin->gut review" --verify
"""
from __future__ import annotations
import argparse, html, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, Image, PageBreak, HRFlowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- fonts: CJK (msyh) so herb names render; Arial fallback ----------
FONTS = "C:/Windows/Fonts"
def _register_fonts():
    try:
        pdfmetrics.registerFont(TTFont("Body", f"{FONTS}/msyh.ttc", subfontIndex=0))
        pdfmetrics.registerFont(TTFont("Body-Bold", f"{FONTS}/msyhbd.ttc", subfontIndex=0))
    except Exception:
        pdfmetrics.registerFont(TTFont("Body", f"{FONTS}/arial.ttf"))
        pdfmetrics.registerFont(TTFont("Body-Bold", f"{FONTS}/arialbd.ttf"))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
_register_fonts()

# ---------- fixed house palette ----------
INK = colors.HexColor("#1a2733"); ACCENT = colors.HexColor("#0f6e6a")
ACCENT2 = colors.HexColor("#8a1c3b"); MUTE = colors.HexColor("#5a6b78")
HEADBG = colors.HexColor("#0f6e6a"); ROWALT = colors.HexColor("#f2f7f6")
CALLBG = colors.HexColor("#fbf3e6"); CALLBORDER = colors.HexColor("#d9a441"); LINEC = colors.HexColor("#c9d4d2")
MARGIN = 1.6 * cm; FRAME_W = A4[0] - 2 * MARGIN

def S(name, **kw):
    base = dict(fontName="Body", fontSize=9.2, leading=13.5, textColor=INK, spaceBefore=2, spaceAfter=4)
    base.update(kw); return ParagraphStyle(name, **base)

ST = {
    "h1": S("h1", fontName="Body-Bold", fontSize=16.5, leading=20.5, textColor=ACCENT, spaceBefore=13, spaceAfter=6),
    "h2": S("h2", fontName="Body-Bold", fontSize=13, leading=16.5, textColor=INK, spaceBefore=11, spaceAfter=5),
    "h3": S("h3", fontName="Body-Bold", fontSize=10.8, leading=14, textColor=ACCENT2, spaceBefore=8, spaceAfter=3),
    "h4": S("h4", fontName="Body-Bold", fontSize=9.6, leading=13, textColor=MUTE, spaceBefore=6, spaceAfter=2),
    "body": S("body"), "cap": S("cap", fontSize=8.2, leading=11, textColor=MUTE, spaceBefore=1, spaceAfter=8),
    "bullet": S("bullet", leftIndent=12, bulletIndent=2, spaceAfter=2),
    "call": S("call", fontSize=9, leading=13, textColor=colors.HexColor("#5a3d0a")),
    "coverT": S("coverT", fontName="Body-Bold", fontSize=23, leading=28, textColor=ACCENT, alignment=TA_CENTER),
    "coverS": S("coverS", fontSize=12.5, leading=17, textColor=INK, alignment=TA_CENTER),
    "coverM": S("coverM", fontSize=9.8, leading=14.5, textColor=MUTE, alignment=TA_CENTER),
}

# ---------- glyph gate: map everything msyh may lack to ASCII (boxes are undetectable) ----------
_SUP = {"⁰":"0","¹":"1","²":"2","³":"3","⁴":"4","⁵":"5","⁶":"6","⁷":"7","⁸":"8","⁹":"9","⁺":"+","⁻":"-"}
_SUB = {"₀":"0","₁":"1","₂":"2","₃":"3","₄":"4","₅":"5","₆":"6","₇":"7","₈":"8","₉":"9"}
_GREEK = {"κ":"k","β":"beta","α":"alpha","γ":"gamma","δ":"delta","μ":"u","λ":"lambda","ζ":"zeta","σ":"sigma","π":"pi"}

def _sup_run(m): return "^(" + "".join(_SUP[c] for c in m.group(0)) + ")"

def clean(t):
    t = t.replace("️", "")
    t = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+", _sup_run, t)            # 10⁻¹⁰ -> 10^(-10)
    for a, b in [("✔","Y"),("✓","Y"),("☑","Y"),("✗","n"),("✘","n"),("✕","x"),
                 ("⚠","!"),("🛡",""),("🧬",""),("🛑",""),("▶","»"),("★","*"),
                 ("∩"," and "),("∪"," or "),("⊆"," subset of "),("≈","~"),("≠","!="),
                 ("–","-"),("—","-"),("−","-"),("’","'"),("‘","'"),("“",'"'),("”",'"'),("…","...")]:
        t = t.replace(a, b)
    for a, b in {**_SUB, **_GREEK}.items():
        t = t.replace(a, b)
    # keep meaningful arrows (↑↓→←) and × ≤ ≥ · ± ° — msyh renders these; they carry meaning
    t = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000026FF]", "", t)   # strip emoji/misc-symbols
    return re.sub(r"[ ]{2,}", " ", t)

def inline(t):
    t = clean(t); t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)                        # bold
    t = re.sub(r"(?<!\*)\*(?!\s)([^*]+?)\*(?!\*)", r"<i>\1</i>", t)      # italic
    t = re.sub(r"`([^`]+?)`", r'<font face="Courier" size="7.8" color="#7a2ea0">\1</font>', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<u>\1</u>", t)
    return t

def PARA(s, style, **kw):
    try: return Paragraph(s, style, **kw)
    except Exception: return Paragraph(re.sub(r"</?[^>]+>", "", s), style, **kw)

def img_flow(path, maxw=FRAME_W, maxh=20.5 * cm):
    if not os.path.exists(path): return None
    iw, ih = ImageReader(path).getSize()
    r = maxw / iw
    if ih * r > maxh: r = maxh / ih
    return Image(path, iw * r, ih * r)

def _plain(c):
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", re.sub(r"\*\*|\*|`", "", c))

def make_table(rows):
    """Content-weighted column widths + font auto-scaling by column count (wide review tables)."""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    fs, ld = (7.8, 9.8) if ncol <= 4 else (7.0, 8.9) if ncol <= 6 else (6.2, 7.9) if ncol <= 8 else (5.4, 6.9)
    cell = ParagraphStyle("c", parent=ST["body"], fontSize=fs, leading=ld, spaceBefore=0, spaceAfter=0)
    cellh = ParagraphStyle("ch", parent=cell, fontName="Body-Bold", fontSize=fs + 0.2, textColor=colors.white)
    weights = []
    for c in range(ncol):
        col = [_plain(r[c]) for r in rows]
        longest = max((max((len(w) for w in (x.split() or [""])), default=1) for x in col), default=1)
        mean_len = sum(len(x) for x in col) / max(len(col), 1)
        weights.append(max(longest * 0.9, mean_len * 0.55, 5))
    tot = sum(weights)
    colw = [max(FRAME_W * w / tot, 1.1 * cm) for w in weights]
    over = sum(colw) / FRAME_W
    if over > 1: colw = [w / over for w in colw]
    data = [[PARA(inline(c), cellh) for c in rows[0]]]
    for r in rows[1:]:
        data.append([PARA(inline(c), cell) for c in r])
    t = Table(data, colWidths=colw, repeatRows=1, hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), HEADBG), ("GRID", (0, 0), (-1, -1), 0.35, LINEC),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
             ("RIGHTPADDING", (0, 0), (-1, -1), 2.5), ("TOPPADDING", (0, 0), (-1, -1), 2),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), ROWALT))
    t.setStyle(TableStyle(style)); return t

def callout(lines):
    t = Table([[PARA("<br/>".join(inline(l) for l in lines), ST["call"])]], colWidths=[FRAME_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CALLBG),
                           ("LINEBEFORE", (0, 0), (0, -1), 3, CALLBORDER),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t

def md_to_flow(md, base_dir):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)          # strip HTML comments
    flow, lines, i, para, n = [], md.split("\n"), 0, [], 0
    n = len(lines)
    def flush():
        if para: flow.append(PARA(inline(" ".join(para)), ST["body"]))
    while i < n:
        st = lines[i].rstrip().strip()
        m = re.match(r"!\[[^\]]*\]\(([^)]+)\)", st)
        if m:
            flush(); para.clear()
            im = img_flow(os.path.join(base_dir, m.group(1).replace("/", os.sep)))
            if im: flow.append(im)
            i += 1; continue
        if st.startswith("#"):
            flush(); para.clear()
            lvl = len(st) - len(st.lstrip("#"))
            flow.append(PARA(inline(st.lstrip("#").strip()), ST.get(f"h{min(lvl,4)}", ST["h4"]))); i += 1; continue
        if st.startswith("|"):
            flush(); para.clear(); tbl = []
            while i < n and lines[i].strip().startswith("|"):
                row = lines[i].strip().strip("|")
                if re.match(r"^[\s:|\-]+$", row): i += 1; continue
                tbl.append([c.strip() for c in row.split("|")]); i += 1
            if tbl: flow.append(make_table(tbl)); flow.append(Spacer(1, 5))
            continue
        if st.startswith(">"):
            flush(); para.clear(); cl = []
            while i < n and lines[i].strip().startswith(">"):
                cl.append(lines[i].strip().lstrip(">").strip()); i += 1
            flow.append(callout([c for c in cl if c])); flow.append(Spacer(1, 5)); continue
        if st.startswith("**Figure") or st.startswith("**Table"):
            flush(); para.clear(); flow.append(PARA(inline(st), ST["cap"])); i += 1; continue
        if re.match(r"^\d+\.\s+", st):                       # numbered list
            flush(); para.clear()
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                mm = re.match(r"^(\d+)\.\s+(.*)$", lines[i].strip())
                flow.append(PARA(inline(mm.group(2)), ST["bullet"], bulletText=mm.group(1) + ".")); i += 1
            continue
        if st.startswith("- ") or st.startswith("* "):
            flush(); para.clear()
            while i < n and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                flow.append(PARA(inline(lines[i].strip()[2:]), ST["bullet"], bulletText="•")); i += 1
            continue
        if st in ("---", "***", "___"):
            flush(); para.clear()
            flow.append(Spacer(1, 3)); flow.append(HRFlowable(width="100%", thickness=0.6, color=LINEC))
            flow.append(Spacer(1, 3)); i += 1; continue
        if st == "": flush(); para.clear(); i += 1; continue
        para.append(st); i += 1
    flush(); return flow

# default appendix order for --run mode (only those that exist are included)
DEFAULT_APPENDIX = [
    ("Appendix 0 — Provenance & Plausibility Gate", "step0_provenance.md"),
    ("Appendix A — Potential Target List A", "step1_target_list_A.md"),
    ("Appendix B — Pathogenic Gene List B", "step2_disease_genes_B.md"),
    ("Appendix C — Hub Targets (specificity-gated)", "step3_hub_targets.md"),
    ("Appendix C2 — Hub Targets (validated, definitive)", "step3b_hub_targets_validated.md"),
    ("Appendix D — MOA Summary", "step4_moa_summary.md"),
    ("Appendix D2 — MOA Overview Table", "step4_moa_table.md"),
    ("Appendix E — Confidence Dashboard", "step5_confidence_dashboard.md"),
    ("Appendix F — Validation Plan", "validation_plan.md"),
    ("Appendix G — Data-Integrity Self-Audit", "data_integrity_check.md"),
    ("Appendix H — Provenance/Specificity Note (archived)", "HALT_no_intersection.md"),
]

def derive_title(md):
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return (m.group(1).strip() if m else "Research Report")

def resolve_docs(args):
    """Return (base_dir, [(appendix_title_or_None, abspath), ...])."""
    if args.run:
        base = os.path.abspath(args.run)
        docs = [(None, os.path.join(base, "step5_final_report.md"))]
        docs += [(t, os.path.join(base, f)) for t, f in DEFAULT_APPENDIX if os.path.exists(os.path.join(base, f))]
        return base, docs
    if args.report:
        p = os.path.abspath(args.report)
        return os.path.dirname(p), [(None, p)]
    # --md list
    base = os.path.abspath(args.base) if args.base else os.path.dirname(os.path.abspath(args.md[0]))
    return base, [(None, os.path.abspath(f)) for f in args.md]

def build_story(base, docs, opts, has_cover):
    """Fresh story each call — reportlab consumes it, so a lock-retry must rebuild."""
    primary = open(docs[0][1], encoding="utf-8").read()
    title = opts["title"] or derive_title(primary)
    story = []
    if has_cover:
        story = [Spacer(1, 3.0 * cm)]
        for line in _wrap_title(title):
            story.append(Paragraph(clean(line), ST["coverT"]))
        story += [Spacer(1, 0.7 * cm), HRFlowable(width="55%", thickness=1.2, color=ACCENT2, hAlign="CENTER"),
                  Spacer(1, 0.5 * cm)]
        if opts["subtitle"]:
            story.append(Paragraph(clean(opts["subtitle"]), ST["coverS"]))
        if opts["verdict"]:
            story += [Spacer(1, 0.4 * cm), Paragraph(f"<b>{clean(opts['verdict'])}</b>", ST["coverS"])]
        cover = img_flow(os.path.join(base, opts["cover_fig"]), maxw=13 * cm, maxh=8 * cm) if opts["cover_fig"] else None
        if cover:
            cover.hAlign = "CENTER"; story += [Spacer(1, 0.8 * cm), cover]
        if opts["blurb"]:
            story += [Spacer(1, 0.7 * cm), Paragraph(clean(opts["blurb"]), ST["coverM"])]
        if opts["date"]:
            story += [Spacer(1, 0.4 * cm), Paragraph(clean(opts["date"]), ST["coverM"])]
    for idx, (atitle, path) in enumerate(docs):
        if not os.path.exists(path): continue
        md = open(path, encoding="utf-8").read()
        if has_cover or idx > 0:
            story.append(PageBreak())
        if atitle:
            story.append(PARA(inline(atitle), ST["h1"]))
            story.append(HRFlowable(width="100%", thickness=1.0, color=ACCENT)); story.append(Spacer(1, 4))
        story += md_to_flow(md, base)
    return story

def _wrap_title(title, width=42):
    if len(title) <= width: return [title]
    words, lines, cur = title.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur: lines.append(cur); cur = w
        else: cur = (cur + " " + w).strip()
    if cur: lines.append(cur)
    return lines[:3]

def build(base, docs, out, opts, no_cover):
    has_cover = not no_cover
    footer = clean(opts["footer"] or opts["title"] or derive_title(open(docs[0][1], encoding="utf-8").read()))[:95]
    def on_page(canvas, doc):
        canvas.saveState(); canvas.setFont("Body", 7.2); canvas.setFillColor(MUTE)
        canvas.drawString(MARGIN, 1.0 * cm, footer)
        canvas.drawRightString(A4[0] - MARGIN, 1.0 * cm, f"p. {doc.page}")
        canvas.setStrokeColor(LINEC); canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 1.32 * cm, A4[0] - MARGIN, 1.32 * cm); canvas.restoreState()
    def _build(target):
        doc = BaseDocTemplate(target, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                              topMargin=1.5 * cm, bottomMargin=1.6 * cm,
                              title=opts["title"] or derive_title(open(docs[0][1], encoding="utf-8").read()))
        frame = Frame(doc.leftMargin, doc.bottomMargin, FRAME_W, A4[1] - 3.1 * cm, id="main")
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
        doc.build(build_story(base, docs, opts, has_cover))     # fresh story each build
    target = os.path.join(base, out)
    try:
        with open(target, "ab"): pass
        _build(target)
    except PermissionError:
        target = os.path.join(base, out.replace(".pdf", "_v2.pdf")); _build(target)
        print(f"NOTE: {out} was locked (open in a viewer); wrote {os.path.basename(target)}.")
    print(f"PDF written: {target} ({os.path.getsize(target)/1024:.0f} KB)")
    return target

def verify(pdf):
    try: import fitz
    except Exception:
        print("[verify] PyMuPDF unavailable — skipping render check"); return
    d = fitz.open(pdf); stray = sum(pg.get_text().count("*") for pg in d)
    print(f"[verify] {d.page_count} pages; stray '*' across doc: {stray}"
          + ("  [OK]" if stray == 0 else "  [WARN: unconverted markdown]"))
    outdir = os.path.join(os.path.dirname(pdf), "_pdf_preview"); os.makedirs(outdir, exist_ok=True)
    for idx in sorted({0, d.page_count // 2, d.page_count - 1}):
        d[idx].get_pixmap(dpi=110).save(os.path.join(outdir, f"page_{idx+1}.png"))
    print("[verify] sample pages -> _pdf_preview/page_*.png (read them back to check layout & tofu boxes)")

def main():
    ap = argparse.ArgumentParser(description="General house-style PDF builder")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="MOA run folder (step5_final_report.md + appendices)")
    g.add_argument("--report", help="single markdown report (reviews)")
    g.add_argument("--md", nargs="+", help="explicit markdown file list")
    ap.add_argument("--base", help="image base dir for --md mode")
    ap.add_argument("--out", default="result.pdf")
    ap.add_argument("--title"); ap.add_argument("--subtitle"); ap.add_argument("--verdict")
    ap.add_argument("--blurb"); ap.add_argument("--footer"); ap.add_argument("--date")
    ap.add_argument("--cover-fig"); ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    base, docs = resolve_docs(a)
    opts = dict(title=a.title, subtitle=a.subtitle, verdict=a.verdict, blurb=a.blurb,
                footer=a.footer, date=a.date, cover_fig=a.cover_fig)
    pdf = build(base, docs, a.out, opts, a.no_cover)
    if a.verify: verify(pdf)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
