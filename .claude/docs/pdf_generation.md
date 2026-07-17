# PDF / report generation — build reference

*On-demand reference (NOT auto-loaded). Read this only when building or debugging a PDF report. Pointer lives in CLAUDE.md §7.*

- **No system LaTeX/typst engine** (no xelatex/pdflatex/tectonic/typst-CLI/wkhtmltopdf/weasyprint). pandoc 3.8 is present (`/d/anaconda3/Library/bin/pandoc`) but cannot make a PDF without an engine.
- **DEFAULT = reportlab** (4.4.10): zero external deps, builds the PDF directly. Prefer building flowables from Python data structures over parsing markdown (sidesteps the inline-formatting bug below).
  - **CJK** (herb names 七白散): register `TTFont('Body','C:/Windows/Fonts/msyh.ttc',subfontIndex=0)` + `msyhbd.ttc` (bold).
  - **English-only**: register **Arial** (`arial.ttf`/`arialbd.ttf`) — it carries ↑↓→ arrows; still keep body text ASCII-safe as a backstop.
- **Markdown inline converter must handle BOTH `**bold**` AND single `*italic*`.** A bold-only converter leaves `*Method:*` / `*only*` as literal asterisks. After the bold sub, add `re.sub(r"(?<!\*)\*(?!\s)([^*]+?)\*(?!\*)", r"<i>\1</i>", t)`. Verify: extract text with `fitz` and assert no `*` survives on any page.
- **Font-glyph gate:** msyh.ttc lacks superscripts ⁺ ⁻ ⁶, so `CD45⁺` renders as a box — and text extraction can't detect it. Check the font cmap for any special glyph before trusting the render (use ASCII substitutes when unsure).
- **Output-lock fallback:** the PDF can be locked if open in a viewer (`PermissionError` on write). Test `open(path,'ab')` first; on failure write `*_v2.pdf` and tell the user to close the viewer to regenerate the primary.
- **Always verify layout** by rendering pages to PNG with PyMuPDF (`fitz.get_pixmap`) and reading them back — catches clipping, overlap, and glyph tofu. Every figure needs its completeness essentials (colorbar where colour encodes data, category legend, un-clipped title).
- **Optional typst** (pip `typst`>=0.15, no system LaTeX; the pip pkg has NO CLI so `pandoc --pdf-engine=typst` fails): two-step — `pandoc report.md -s -t typst -V mainfont="Microsoft YaHei" -o x.typ` (`-s` REQUIRED or "unknown variable: horizontalrule"), then `import typst; typst.compile('x.typ', output=..., root=<dir>)` (source file MUST be inside root; images resolve relative to root).

**Reference builders:** `results/atopic_dermatitis_session9/scripts/make_pdf.py` · `reviews/*/scripts/make_pdf.py` · `reviews/synthesis_skin_to_gut/scripts/build.py`.
