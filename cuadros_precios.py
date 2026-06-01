"""
cuadros_precios.py — Spanish industry-standard supplementary documents.

- build_cuadro_nro1_pdf  · Cuadro de Precios Nº 1: precios unitarios en
  cifra y en letra, una fila por partida.
- build_cuadro_nro2_pdf  · Cuadro de Precios Nº 2: descompuesto de cada
  partida en mano de obra, materiales, maquinaria, indirectos.

Mandatory in any presupuesto técnico (alongside the budget itself).
Real BC3 emitters (Presto, Arquímedes, CYPE) include both — these
mirror their layout.
"""

from __future__ import annotations
import datetime as _dt
import pathlib
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle

from client_pdfs import (
    _styles, _header_block, _title_row, _RexPageDecor,
    fmt_eur, fmt_num,
    BRAND, BRAND_SOFT, INK, MUTED, RULE, HEAD_BG, ROW_ALT,
)


# --------------------------------------------------------------------------
# Spanish number-to-words for cuadro nº 1 (precio en letra).
# Covers 0..999_999, plus céntimos. "Tres mil cuatrocientos veinte euros con
# cincuenta céntimos" — matches the convention used by Presto/Arquímedes.
# --------------------------------------------------------------------------

_UNIDADES = [
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis",
    "diecisiete", "dieciocho", "diecinueve", "veinte",
]
_DECENAS = {
    20: "veinte", 30: "treinta", 40: "cuarenta", 50: "cincuenta",
    60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa",
}
_CENTENAS = {
    100: "ciento", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos",
    500: "quinientos", 600: "seiscientos", 700: "setecientos",
    800: "ochocientos", 900: "novecientos",
}


def _hasta_99(n: int) -> str:
    if n <= 20:
        return _UNIDADES[n]
    if n < 30:
        return f"veinti{_UNIDADES[n - 20]}"
    dec = (n // 10) * 10
    uni = n % 10
    if uni == 0:
        return _DECENAS[dec]
    return f"{_DECENAS[dec]} y {_UNIDADES[uni]}"


def _hasta_999(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    if n < 100:
        return _hasta_99(n)
    cen = (n // 100) * 100
    resto = n % 100
    if resto == 0:
        return _CENTENAS[cen]
    return f"{_CENTENAS[cen]} {_hasta_99(resto)}"


def _miles(n: int) -> str:
    """0..999_999 → palabras."""
    if n == 0:
        return "cero"
    if n < 1000:
        return _hasta_999(n)
    miles = n // 1000
    resto = n % 1000
    if miles == 1:
        cab = "mil"
    else:
        cab = f"{_hasta_999(miles)} mil"
    if resto == 0:
        return cab
    return f"{cab} {_hasta_999(resto)}"


def euros_en_letra(amount: float) -> str:
    """Render a euro amount in words (Spanish). Caps at 999_999.99."""
    enteros = int(amount)
    cents = int(round((amount - enteros) * 100))
    parts = []
    if enteros == 0:
        parts.append("cero euros")
    elif enteros == 1:
        parts.append("un euro")
    else:
        parts.append(f"{_miles(enteros)} euros")
    if cents:
        parts.append(f"con {_miles(cents)} céntimos")
    out = " ".join(parts)
    # Cosmetic fix: "uno mil" → "un mil" doesn't happen here because we
    # always start with "mil", but "ciento un" / "veintiún" are dialectal
    # choices we leave alone.
    return out[0].upper() + out[1:]


# --------------------------------------------------------------------------
# Common doc helper
# --------------------------------------------------------------------------

def _build(out_path: pathlib.Path, title_header: str, firm: dict,
           ref: str, story: list) -> pathlib.Path:
    fecha = _dt.date.today()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=title_header, author=firm.get("nombre", ""),
    )
    decor = _RexPageDecor(title_header, firm, ref, fecha)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path


# --------------------------------------------------------------------------
# Cuadro Nº 1 — precios unitarios en cifra y en letra
# --------------------------------------------------------------------------

def build_cuadro_nro1_pdf(out_path: pathlib.Path, firm: dict, meta: dict,
                           partidas: list[dict], ref: str,
                           project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")
    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 6),
        Paragraph("CUADRO DE PRECIOS Nº 1", st["title"]),
        Paragraph(
            "Precios unitarios de las partidas, expresados en cifra y en "
            "letra, conforme al artículo 100 del RGLCAP (RD 1098/2001) y a "
            "las normas habituales de la edificación.",
            st["meta"],
        ),
        Spacer(1, 6),
    ]

    head = [Paragraph(t, st["cell_b"]) for t in
            ("Code", "Descripción", "Ud", "Precio (€)", "Precio en letra")]
    body = [head]
    for p in partidas:
        pu = float(p.get("precio_unitario") or 0)
        body.append([
            Paragraph(p["code"], st["cell"]),
            Paragraph(p["descripcion"], st["cell"]),
            Paragraph(p["unidad"], st["cell_c"]),
            Paragraph(fmt_num(pu, 2), st["cell_r"]),
            Paragraph(f'<font size="7.6">{euros_en_letra(pu)}</font>', st["cell"]),
        ])
    t = Table(body,
              colWidths=[16 * mm, 56 * mm, 9 * mm, 18 * mm, 87 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
    ]))
    story.append(t)
    return _build(out_path, "CUADRO DE PRECIOS Nº 1", firm, ref, story)


# --------------------------------------------------------------------------
# Cuadro Nº 2 — descompuesto mo/mat/maq/indirectos por partida
# --------------------------------------------------------------------------

def build_cuadro_nro2_pdf(out_path: pathlib.Path, firm: dict, meta: dict,
                           partidas: list[dict], ref: str,
                           project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")
    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 6),
        Paragraph("CUADRO DE PRECIOS Nº 2", st["title"]),
        Paragraph(
            "Descompuesto de cada precio unitario en mano de obra, "
            "materiales, maquinaria e indirectos. Los porcentajes y los "
            "componentes son los aplicados por el motor (RD 1098/2001).",
            st["meta"],
        ),
        Spacer(1, 6),
    ]

    head = [Paragraph(t, st["cell_b"]) for t in
            ("Code", "Descripción", "Ud", "M.O.", "Mat.", "Maq.",
             "% Indir.", "Precio (€)")]
    body = [head]
    for p in partidas:
        mo  = float(p.get("mo_pu")  or 0)
        mat = float(p.get("mat_pu") or 0)
        maq = float(p.get("maq_pu") or 0)
        indir_pct = float(p.get("indirectos_pct") or 0)
        pu = float(p.get("precio_unitario") or 0)
        body.append([
            Paragraph(p["code"], st["cell"]),
            Paragraph(p["descripcion"], st["cell"]),
            Paragraph(p["unidad"], st["cell_c"]),
            Paragraph(fmt_num(mo, 2),  st["cell_r"]),
            Paragraph(fmt_num(mat, 2), st["cell_r"]),
            Paragraph(fmt_num(maq, 2), st["cell_r"]),
            Paragraph(f"{indir_pct*100:.1f}%", st["cell_r"]),
            Paragraph(fmt_num(pu, 2), st["cell_r"]),
        ])
    t = Table(body,
              colWidths=[16 * mm, 70 * mm, 9 * mm, 16 * mm, 16 * mm,
                         16 * mm, 18 * mm, 22 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Fórmula aplicada por partida: <b>precio unitario = "
        "(M.O. + Materiales + Maquinaria) × (1 + % indirectos)</b>. "
        "Las pequeñas diferencias por redondeo se asignan a la columna de "
        "materiales para mantener el precio total inalterado.",
        st["small"],
    ))
    return _build(out_path, "CUADRO DE PRECIOS Nº 2", firm, ref, story)
