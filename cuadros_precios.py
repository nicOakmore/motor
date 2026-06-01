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

_SLOT_LABEL = {"mo": "M.O.", "mat": "Mat.", "maq": "Maq."}


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
            "Descompuesto detallado de cada precio unitario: por cada partida "
            "se listan los componentes de mano de obra (h × tarifa), "
            "materiales (cantidad × precio) y maquinaria (h × tarifa). "
            "El precio unitario final = (Σ componentes) × (1 + % indirectos), "
            "conforme al artículo 130 del RGLCAP (RD 1098/2001).",
            st["meta"],
        ),
        Spacer(1, 8),
    ]

    for partida in partidas:
        # Partida header line
        story.append(Paragraph(
            f"<b>{partida['code']} · {partida['descripcion']}</b> "
            f"<font color='#5a6072'>· {partida['unidad']}</font>",
            st["h3"],
        ))

        comps = partida.get("descompuesto") or []
        if comps:
            head = [Paragraph(t, st["cell_b"]) for t in
                    ("Tipo", "Código", "Descripción", "Ud", "Rendim.",
                     "Precio ud", "Importe")]
            body = [head]
            slot_subtotal = {"mo": 0.0, "mat": 0.0, "maq": 0.0}
            for c in comps:
                slot_subtotal[c["slot"]] += float(c["importe"])
                body.append([
                    Paragraph(_SLOT_LABEL.get(c["slot"], c["slot"]), st["cell"]),
                    Paragraph(c["comp_code"], st["cell"]),
                    Paragraph(c["descripcion"], st["cell"]),
                    Paragraph(c.get("unidad") or "", st["cell_c"]),
                    Paragraph(fmt_num(c["rendimiento"], 4), st["cell_r"]),
                    Paragraph(fmt_num(c["precio_unitario"], 2), st["cell_r"]),
                    Paragraph(fmt_num(c["importe"], 2), st["cell_r"]),
                ])
            # subtotals + indirectos + total rows. Span columns 0..5 for the
            # label and keep the importe in column 6.
            sub_total = sum(slot_subtotal.values())
            indir_pct = float(partida.get("indirectos_pct") or 0)
            indir_imp = round(sub_total * indir_pct, 2)
            total_pu  = float(partida.get("precio_unitario") or 0)
            body.append([
                Paragraph("<b>Subtotal sin indirectos</b>", st["cell_r"]),
                "", "", "", "", "",
                Paragraph(f"<b>{fmt_num(sub_total, 2)}</b>", st["cell_r"]),
            ])
            body.append([
                Paragraph(f"Costes indirectos ({indir_pct*100:.1f}%)", st["cell_r"]),
                "", "", "", "", "",
                Paragraph(fmt_num(indir_imp, 2), st["cell_r"]),
            ])
            body.append([
                Paragraph("<b>PRECIO UNITARIO</b>", st["cell_r"]),
                "", "", "", "", "",
                Paragraph(f"<b>{fmt_num(total_pu, 2)} €</b>", st["cell_r"]),
            ])
            t = Table(body,
                      colWidths=[14 * mm, 14 * mm, 78 * mm, 9 * mm,
                                 22 * mm, 22 * mm, 23 * mm],
                      repeatRows=1)
            n = len(body)
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, BRAND),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("SPAN", (0, n - 3), (5, n - 3)),
                ("SPAN", (0, n - 2), (5, n - 2)),
                ("SPAN", (0, n - 1), (5, n - 1)),
                ("LINEABOVE", (0, n - 3), (-1, n - 3), 0.4, BRAND_SOFT),
                ("BACKGROUND", (0, n - 1), (-1, n - 1), HEAD_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, n - 4), [white, ROW_ALT]),
            ]
            t.setStyle(TableStyle(style))
            story.append(KeepTogether([t, Spacer(1, 6)]))
        else:
            # Fallback aggregated view when no detailed descompuesto exists.
            mo  = float(partida.get("mo_pu")  or 0)
            mat = float(partida.get("mat_pu") or 0)
            maq = float(partida.get("maq_pu") or 0)
            indir_pct = float(partida.get("indirectos_pct") or 0)
            pu = float(partida.get("precio_unitario") or 0)
            agg = Table([
                [Paragraph("<b>M.O.</b>",  st["cell_b"]), Paragraph(fmt_num(mo,  2), st["cell_r"]),
                 Paragraph("<b>Mat.</b>", st["cell_b"]),  Paragraph(fmt_num(mat, 2), st["cell_r"]),
                 Paragraph("<b>Maq.</b>", st["cell_b"]),  Paragraph(fmt_num(maq, 2), st["cell_r"]),
                 Paragraph(f"<b>% Indir.</b>", st["cell_b"]),
                 Paragraph(f"{indir_pct*100:.1f}%", st["cell_r"]),
                 Paragraph("<b>PU</b>", st["cell_b"]),
                 Paragraph(f"<b>{fmt_num(pu, 2)} €</b>", st["cell_r"])],
            ], colWidths=[14 * mm, 18 * mm, 14 * mm, 18 * mm, 14 * mm, 18 * mm,
                          18 * mm, 14 * mm, 14 * mm, 24 * mm])
            agg.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), ROW_ALT),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]))
            story.append(KeepTogether([
                agg,
                Paragraph(
                    "<i>Sin descompuesto detallado disponible para esta "
                    "partida — se muestra el agregado por capítulos.</i>",
                    st["small"],
                ),
                Spacer(1, 6),
            ]))

    return _build(out_path, "CUADRO DE PRECIOS Nº 2", firm, ref, story)
