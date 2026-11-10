"""Word output in the format of a Taiwanese medical-school PBL report: A4, 標楷體 14 pt, bordered tables, page footer.

    from pbl_docx import build
    build(md_text, out_path, resource_dir, ratios=[[1, 8], [3, 6, 4]], cover=[("Cover School", "..."), ("Cover Title", "..."), ("Cover Line", "...")])

Markdown tables with a plain `|---|---|` separator take their column ratios from `ratios`, in order.
Styles available on the cover: Cover School, Cover Title, Cover Line. Leave group and member fields blank for the group to fill.
"""
from __future__ import annotations

import io
import re
import subprocess
import zipfile
from pathlib import Path

FOOTER_TEXT = "僅供課程內部使用 · "

FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="標楷體" w:cs="Times New Roman"/>'


def style_rpr(xml: str, sid: str, sz: int, bold: bool) -> str:
    rpr = f"<w:rPr>{FONT}{'<w:b/><w:bCs/>' if bold else ''}<w:color w:val=\"000000\"/><w:sz w:val=\"{sz}\"/><w:szCs w:val=\"{sz}\"/></w:rPr>"
    pat = re.compile(r'(<w:style [^>]*w:styleId="%s".*?)(</w:style>)' % sid, re.S)

    def fix(m):
        block = re.sub(r"<w:rPr>.*?</w:rPr>", "", m.group(1), flags=re.S)
        return block + rpr + m.group(2)

    return pat.sub(fix, xml, count=1)


def para_style(name: str, sid: str, sz: int, bold: bool, before: int, after: int) -> str:
    return (f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
            f'<w:pPr><w:spacing w:before="{before}" w:after="{after}"/><w:jc w:val="center"/></w:pPr>'
            f'<w:rPr>{FONT}{"<w:b/><w:bCs/>" if bold else ""}<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr></w:style>')


def reference_docx(path: Path) -> None:
    """A4, 標楷體 14 pt, bordered tables, page numbers: the course report's look, built from pandoc's blank template."""
    raw = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"], capture_output=True, check=True).stdout
    src = zipfile.ZipFile(io.BytesIO(raw))
    out = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    borders = "".join(f'<w:{e} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
                      for e in ("top", "left", "bottom", "right", "insideH", "insideV"))
    for item in src.infolist():
        data = src.read(item.filename)
        if item.filename == "word/styles.xml":
            x = data.decode("utf8")
            x = re.sub(r"(<w:rPrDefault>.*?)<w:rFonts [^>]*/>", lambda m: m.group(1) + FONT, x, count=1, flags=re.S)
            x = re.sub(r'(<w:rPrDefault>.*?)<w:sz w:val="\d+"/>', r'\1<w:sz w:val="28"/>', x, count=1, flags=re.S)
            x = re.sub(r'(<w:rPrDefault>.*?)<w:szCs w:val="\d+"/>', r'\1<w:szCs w:val="28"/>', x, count=1, flags=re.S)
            x = re.sub(r'(<w:rPrDefault>.*?<w:lang )[^>]*/>', r'\1w:val="en-US" w:eastAsia="zh-TW" w:bidi="ar-SA"/>', x, count=1, flags=re.S)
            for sid, sz, bold in (("Heading1", 36, True), ("Heading2", 32, True), ("Heading3", 30, True),
                                  ("Compact", 24, False), ("BlockText", 26, False)):
                x = style_rpr(x, sid, sz, bold)
            x = re.sub(r'(<w:style [^>]*w:styleId="Table".*?)<w:tblPr>.*?</w:tblPr>',
                       lambda m: m.group(1) + f"<w:tblPr><w:tblBorders>{borders}</w:tblBorders>"
                       '<w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>',
                       x, count=1, flags=re.S)
            extra = (para_style("Cover School", "CoverSchool", 40, True, 240, 240)
                     + para_style("Cover Title", "CoverTitle", 60, True, 900, 900)
                     + para_style("Cover Line", "CoverLine", 32, False, 120, 120))
            data = x.replace("</w:styles>", extra + "</w:styles>").encode("utf8")
        elif item.filename == "word/document.xml":
            x = data.decode("utf8")
            sect = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdPageFooter"/>'
                    '<w:pgSz w:w="11906" w:h="16838"/>'
                    '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
            x = re.sub(r"<w:sectPr\b.*?</w:sectPr>|<w:sectPr\b[^>]*/>", sect, x, count=1, flags=re.S)
            data = x.encode("utf8")
        elif item.filename == "word/_rels/document.xml.rels":
            rel = ('<Relationship Id="rIdPageFooter" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
            data = data.decode("utf8").replace("</Relationships>", rel + "</Relationships>").encode("utf8")
        elif item.filename == "[Content_Types].xml":
            over = ('<Override PartName="/word/footer1.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
            data = data.decode("utf8").replace("</Types>", over + "</Types>").encode("utf8")
        out.writestr(item, data)
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
              f'<w:r><w:t xml:space="preserve">{FOOTER_TEXT}</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')
    out.writestr("word/footer1.xml", footer)
    out.close()


def _keep_next(par: str) -> str:
    if "<w:keepNext/>" in par:
        return par
    if "<w:pPr>" not in par:
        return par.replace("<w:p>", "<w:p><w:pPr><w:keepNext/></w:pPr>", 1)
    return re.sub(r'(<w:pPr>(?:<w:pStyle [^>]*/>)?)', r"\1<w:keepNext/>", par, count=1)


def keep_header(m: re.Match) -> str:
    row = m.group(0)
    return re.sub(r"<w:p>.*?</w:p>", lambda p: _keep_next(p.group(0)), row, flags=re.S) if "w:tblHeader" in row else row


def keep_caption(m: re.Match) -> str:
    par = m.group(0)
    text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", par))
    return _keep_next(par) if re.match(r"表 \d+\.", text) else par


def keep_rows_whole(path: Path) -> None:
    """Stop table rows splitting across pages."""
    src = zipfile.ZipFile(path)
    items = {i: src.read(i) for i in src.infolist()}
    src.close()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in items.items():
            if info.filename == "word/document.xml":
                x = data.decode("utf8")
                x = re.sub(r"<w:trPr>(?!<w:cantSplit)", "<w:trPr><w:cantSplit/>", x)
                x = re.sub(r"<w:tr>(?!<w:trPr>)", "<w:tr><w:trPr><w:cantSplit/></w:trPr>", x)
                x = re.sub(r"<w:tr>.*?</w:tr>", keep_header, x, flags=re.S)
                x = re.sub(r"<w:p>(?:(?!</w:p>).)*?</w:p>", keep_caption, x, flags=re.S)
                data = x.encode("utf8")
            out.writestr(info, data)


def build(md: str, out: Path, resource_dir: Path, ratios: list[list[int]], cover: list[tuple[str, str]], work: Path | None = None) -> int:
    ratio_iter = iter(ratios)
    md = re.sub(r"^\|(?:---\|)+$", lambda _m: "|" + "|".join("-" * (r * 6) for r in next(ratio_iter)) + "|", md, flags=re.M)
    md = re.sub(r"(!\[[^\]]*\]\(figures/[^)]*\))", r"\1{width=16.76cm}", md)  # figures are built at 6.6 in
    head = "".join(f'::: {{custom-style="{style}"}}\n{text}\n:::\n\n' for style, text in cover)
    head += '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n\n'
    work = work or out.parent / "_docx_build"
    work.mkdir(parents=True, exist_ok=True)
    (work / "doc.md").write_text(head + md, encoding="utf-8")
    ref = work / "reference.docx"
    reference_docx(ref)
    rc = subprocess.run(["pandoc", str(work / "doc.md"), "-f", "markdown-implicit_figures", "-o", str(out),
                         "--reference-doc", str(ref), "--resource-path", str(resource_dir)]).returncode
    if rc == 0:
        keep_rows_whole(out)
    return rc
