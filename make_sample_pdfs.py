"""
make_sample_pdfs.py — Build PDF versions of the three working markdown
sample memorias.

Why: the three "real" PDFs (Sant Josep, Porreres, COAC Gran Canaria)
were great for metadata-extraction demos but always produce a 0,00 €
budget because narrative memorias don't carry a numbered scope list.
For the demo we want every sample in the dropdown to yield a real
presupuesto. These PDFs render the same numbered scope the markdown
samples use, so the parser pulls partidas + measurements out cleanly.

Run:
    python make_sample_pdfs.py
…produces:
    memorias/memoria_santa_eulalia.pdf
    memorias/memoria_rustico_ibiza.pdf
    memorias/memoria_finca_turistica.pdf
"""

from __future__ import annotations
import pathlib
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_JUSTIFY

ROOT = pathlib.Path(__file__).parent
MEMORIAS = ROOT / "memorias"

SAMPLES = [
    "memoria_santa_eulalia",
    "memoria_rustico_ibiza",
    "memoria_finca_turistica",
]

BRAND = HexColor("#1a3a5c")
MUTED = HexColor("#444444")


def _styles():
    s = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=s["Heading1"], fontName="Helvetica-Bold",
                              fontSize=14, leading=17, textColor=BRAND, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=s["Heading2"], fontName="Helvetica-Bold",
                              fontSize=11, leading=14, textColor=BRAND,
                              spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", parent=s["BodyText"], fontName="Helvetica",
                                fontSize=10, leading=13, alignment=TA_JUSTIFY,
                                spaceAfter=4),
        "item": ParagraphStyle("item", parent=s["BodyText"], fontName="Helvetica",
                                fontSize=10, leading=13.5, alignment=TA_JUSTIFY,
                                leftIndent=14, spaceAfter=4),
        "meta": ParagraphStyle("meta", parent=s["BodyText"], fontName="Helvetica",
                                fontSize=9.5, leading=12, textColor=MUTED,
                                spaceAfter=2),
    }


def _md_inline(text: str) -> str:
    """Convert minimal Markdown emphasis to ReportLab Paragraph markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<font face='Helvetica-Oblique'>\1</font>", text)
    return text


def md_to_pdf(md_path: pathlib.Path, pdf_path: pathlib.Path) -> None:
    st = _styles()
    text = md_path.read_text(encoding="utf-8")
    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=md_path.stem.replace("_", " ").title(),
        author="Rex Construcciones",
    )
    story: list = []
    # Walk the Markdown line by line; recognise headings (#, ##) and numbered
    # list items. Plain paragraphs become Paragraph flowables.
    buffer: list[str] = []

    def _flush_paragraph():
        if not buffer:
            return
        joined = " ".join(b.strip() for b in buffer if b.strip())
        if joined:
            # Choose the style: meta bullet for "**Key:** value" headers,
            # body for everything else.
            style_key = "meta" if re.match(r"^\s*\*\*[^*]+\*\*\s*:", joined) else "body"
            story.append(Paragraph(_md_inline(joined), st[style_key]))
        buffer.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            _flush_paragraph()
            continue
        h1 = re.match(r"^#\s+(.*)$", line)
        h2 = re.match(r"^##\s+(.*)$", line)
        item = re.match(r"^\d+\.\s+(.*)$", line)
        if h1:
            _flush_paragraph()
            story.append(Paragraph(_md_inline(h1.group(1)), st["h1"]))
        elif h2:
            _flush_paragraph()
            story.append(Paragraph(_md_inline(h2.group(1)), st["h2"]))
        elif item:
            _flush_paragraph()
            # Keep the leading number so the parser's ITEM_RE still matches
            # after pdfplumber / pypdf extract the text.
            n = re.match(r"^(\d+)\.\s+", line).group(1)
            story.append(Paragraph(
                f"{n}. " + _md_inline(item.group(1)), st["item"]))
        else:
            buffer.append(line)
    _flush_paragraph()

    doc.build(story)


if __name__ == "__main__":
    for stem in SAMPLES:
        md = MEMORIAS / f"{stem}.md"
        pdf = MEMORIAS / f"{stem}.pdf"
        md_to_pdf(md, pdf)
        print(f"wrote {pdf.relative_to(ROOT)}  ({pdf.stat().st_size} bytes)")
