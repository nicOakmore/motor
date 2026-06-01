"""
client_pdfs.py — Client-facing PDF artefacts (Spanish).

Two builders:

- build_presupuesto_pdf(...)  — REX-format budget: PRESUPUESTO header,
  DIRECCION OBRA / DATOS CLIENTE columns, multi-level numbering
  (chapter.partida), per-partida description paragraph, cuadro resumen.

- build_plan_obra_pdf(...)    — work plan with real calendar dates,
  skipping weekends and festivos; schedule table + Gantt-style bars.

Both share the firm letterhead footer on every page (CIF, address,
phone, email) so any single page is identifiable on its own.

Stdlib + reportlab.
"""

from __future__ import annotations
import datetime as _dt
import pathlib
from typing import Iterable, Sequence

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Flowable,
)
from reportlab.pdfgen.canvas import Canvas

# ---------- palette ----------
BRAND       = HexColor("#1a3a5c")
BRAND_SOFT  = HexColor("#2d5d8d")
INK         = HexColor("#1a1f2c")
MUTED       = HexColor("#5a6072")
RULE        = HexColor("#d6dae2")
HEAD_BG     = HexColor("#eef2f7")
ROW_ALT     = HexColor("#fafbfd")
GRAND_BG    = HexColor("#1a3a5c")


# ---------- helpers ----------

def fmt_eur(n: float) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_num(n: float, decimals: int = 2) -> str:
    return f"{n:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date(d: _dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def _styles():
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=s["Heading1"], fontName="Helvetica-Bold",
                                 fontSize=15, leading=18, textColor=BRAND,
                                 spaceBefore=0, spaceAfter=2),
        "h2":    ParagraphStyle("h2", parent=s["Heading2"], fontName="Helvetica-Bold",
                                 fontSize=11, leading=14, textColor=BRAND,
                                 spaceBefore=10, spaceAfter=4),
        "h3":    ParagraphStyle("h3", parent=s["Heading3"], fontName="Helvetica-Bold",
                                 fontSize=9.5, leading=12, textColor=BRAND_SOFT,
                                 spaceBefore=6, spaceAfter=2),
        "body":  ParagraphStyle("body", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.6, leading=11.5, alignment=TA_JUSTIFY,
                                 spaceAfter=4),
        "meta":  ParagraphStyle("meta", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.4, leading=10.5, textColor=MUTED,
                                 spaceAfter=0),
        "small": ParagraphStyle("small", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=7.4, leading=9, textColor=MUTED,
                                 spaceAfter=0),
        "cell":  ParagraphStyle("cell", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.4, leading=10.5, alignment=TA_LEFT,
                                 spaceAfter=0),
        "cell_r":ParagraphStyle("cell_r", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.4, leading=10.5, alignment=TA_RIGHT,
                                 spaceAfter=0),
        "cell_b":ParagraphStyle("cell_b", parent=s["BodyText"], fontName="Helvetica-Bold",
                                 fontSize=8.4, leading=10.5, textColor=BRAND,
                                 spaceAfter=0),
        "cell_c":ParagraphStyle("cell_c", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.4, leading=10.5, alignment=TA_CENTER,
                                 spaceAfter=0),
        "chap_label": ParagraphStyle("chap_label", parent=s["BodyText"],
                                      fontName="Helvetica-Bold", fontSize=9.6,
                                      leading=12, textColor=BRAND, spaceAfter=0),
        "partida_desc": ParagraphStyle("partida_desc", parent=s["BodyText"],
                                        fontName="Helvetica", fontSize=8,
                                        leading=10, textColor=INK,
                                        leftIndent=12, spaceAfter=2,
                                        alignment=TA_JUSTIFY),
    }


def _label_uso(v: str | None) -> str:
    return {"vivienda_habitual": "Vivienda habitual",
            "otros": "Otros / verificar"}.get(v or "", v or "—")


def _label_suelo(v: str | None) -> str:
    return {"urbano": "Urbano", "rustico": "Rústico"}.get(v or "", v or "—")


# ---------- Page header + footer ----------

class _RexPageDecor:
    """REX page decorator. Header: title left + PRESUPUESTO/FECHA right.
    Footer: firm address/CIF/phone/email + page numbers."""

    def __init__(self, title: str, firm: dict, ref: str, fecha: _dt.date):
        self.title = title
        self.firm = firm
        self.ref = ref
        self.fecha = fecha

    def __call__(self, canvas: Canvas, doc) -> None:
        w, h = doc.pagesize
        canvas.saveState()

        # ---- Header (top) ----
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(1.2)
        canvas.line(15 * mm, h - 12 * mm, w - 15 * mm, h - 12 * mm)
        canvas.setFont("Helvetica-Bold", 9.5)
        canvas.setFillColor(BRAND)
        canvas.drawString(15 * mm, h - 9 * mm, self.title)
        canvas.setFont("Helvetica-Bold", 8.6)
        ref_line = f"{self.firm.get('ref_prefix', 'PRESUPUESTO')}: {self.ref}"
        canvas.drawRightString(w - 15 * mm, h - 7 * mm, ref_line)
        canvas.setFont("Helvetica", 8.4)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(w - 15 * mm, h - 10.5 * mm,
                               f"FECHA: {fmt_date(self.fecha)}")

        # ---- Footer ----
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(15 * mm, 17 * mm, w - 15 * mm, 17 * mm)

        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(INK)
        line1 = f"{self.firm.get('nombre','')} · {self.firm.get('direccion','')} {self.firm.get('cp_ciudad','')} · CIF: {self.firm.get('cif','')}"
        line2 = f"TLF: {self.firm.get('telefono','')} · E-MAIL: {self.firm.get('email','')}"
        canvas.drawCentredString(w / 2, 13 * mm, line1)
        canvas.drawCentredString(w / 2, 9.5 * mm, line2)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 5.5 * mm,
                          "Documento orientativo. Sujeto a validación técnica.")
        canvas.drawRightString(w - 15 * mm, 5.5 * mm, f"PÁG: {doc.page}")
        canvas.restoreState()


def _header_block(meta: dict, firm: dict, project_title: str | None, st: dict) -> Table:
    # DIRECCION OBRA | DATOS CLIENTE side-by-side
    direccion = meta.get("emplazamiento") or "—"
    promotor = meta.get("promotor") or "—"
    nif = meta.get("nif") or ""
    tlf = meta.get("telefono") or ""

    def bold(s): return Paragraph(f"<b>{s}</b>", st["cell_b"])
    def cell(s): return Paragraph(s, st["cell"])

    left = [
        [bold("DIRECCION OBRA")],
        [cell(direccion)],
    ]
    right = [
        [bold("DATOS CLIENTE")],
        [cell(promotor)],
        [cell(direccion)],
        [cell(f"NIF: {nif}")],
        [cell(f"TLF: {tlf}")],
    ]
    # Pad shorter column with empty cells
    n = max(len(left), len(right))
    while len(left) < n: left.append([cell("")])
    while len(right) < n: right.append([cell("")])

    rows = [[l[0], r[0]] for l, r in zip(left, right)]
    t = Table(rows, colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _title_row(project_title: str, st: dict) -> Paragraph:
    return Paragraph(f"<b>Título:</b> {project_title}", st["meta"])


# --------------------------------------------------------------------------
# Presupuesto cliente — REX format
# --------------------------------------------------------------------------

def build_presupuesto_pdf(out_path: pathlib.Path,
                          firm: dict,
                          meta: dict,
                          totales: dict,
                          partidas: list[dict],
                          capitulo_orden: list[str],
                          ref: str,
                          project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    fecha = _dt.date.today()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title="Presupuesto", author=firm.get("nombre", ""),
    )

    title = project_title or meta.get("memoria", "Presupuesto").replace(".md", "")
    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 6),
    ]

    # Group partidas per capítulo, preserve canonical order.
    by_cap: dict[str, list[dict]] = {}
    for p in partidas:
        by_cap.setdefault(p["capitulo"], []).append(p)
    ordered = [c for c in capitulo_orden if c in by_cap] + \
              [c for c in by_cap if c not in capitulo_orden]

    # Column layout matches REX: Nº | DESCRIPCION | Ud | Largo | Ancho | Alto | Parcial | MED. | PRECIO | TOTAL
    col_widths = [16 * mm, 60 * mm, 9 * mm, 13 * mm, 13 * mm, 13 * mm, 16 * mm, 14 * mm, 16 * mm, 17 * mm]
    head_labels = ("Nº", "DESCRIPCION", "Ud", "Largo", "Ancho", "Alto", "Parcial", "MED.", "PRECIO", "TOTAL")

    grand_total = 0.0
    for chap_idx, cap in enumerate(ordered, start=1):
        chap_num = f"{chap_idx:02d}"
        cap_partidas = by_cap[cap]
        cap_total = sum(float(p["importe"]) for p in cap_partidas)
        grand_total += cap_total

        # Capítulo header row: number, name, and the chapter total in MED./TOTAL
        chap_row: list = [
            Paragraph(f"<b>{chap_num}</b>", st["cell_b"]),
            Paragraph(f"<b>{cap.upper()}</b>", st["cell_b"]),
            "", "", "", "", "",
            Paragraph("<b>1</b>", st["cell_r"]),
            Paragraph(f"<b>{fmt_num(cap_total, 2)}</b>", st["cell_r"]),
            Paragraph(f"<b>{fmt_num(cap_total, 2)}</b>", st["cell_r"]),
        ]

        # Header of the table (repeated on each page if it wraps)
        header_row = [Paragraph(lbl, st["cell_b"]) for lbl in head_labels]

        body: list = [header_row, chap_row]
        for j, p in enumerate(cap_partidas, start=1):
            partida_num = f"{chap_num}.{j:03d}"
            medicion = float(p["medicion"])
            pu = float(p["precio_unitario"])
            importe = float(p["importe"])
            body.append([
                Paragraph(partida_num, st["cell"]),
                Paragraph(p["descripcion"][:80].upper(), st["cell_b"]),
                Paragraph(p["unidad"], st["cell_c"]),
                "", "", "", "",
                Paragraph(fmt_num(medicion, 2), st["cell_r"]),
                Paragraph(fmt_num(pu, 2), st["cell_r"]),
                Paragraph(fmt_num(importe, 2), st["cell_r"]),
            ])
            # description paragraph row — full width via SPAN
            body.append([
                "",
                Paragraph(f'<font size="7.5">{p["descripcion"]}</font>',
                          st["partida_desc"]),
                "", "", "", "", "", "", "", "",
            ])

        t = Table(body, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            # capítulo row
            ("BACKGROUND", (0, 1), (-1, 1), HexColor("#e8eef5")),
            ("LINEBELOW", (0, 1), (-1, 1), 0.3, BRAND_SOFT),
            # description rows: span columns 1..9
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8.4),
        ]
        # span description rows (every odd index >= 3, since we alternate
        # partida-row + desc-row starting at index 2)
        for r in range(3, len(body), 2):
            style.append(("SPAN", (1, r), (-1, r)))
            style.append(("TOPPADDING", (1, r), (-1, r), 0))
            style.append(("BOTTOMPADDING", (1, r), (-1, r), 3))
        t.setStyle(TableStyle(style))
        story.append(t)
        story.append(Spacer(1, 4))

    # ---- Cuadro resumen ----
    story.append(Spacer(1, 6))
    story.append(Paragraph("CUADRO RESUMEN (RD 1098/2001)", st["h2"]))
    gg_p = totales["gg_pct"] * 100
    bi_p = totales["bi_pct"] * 100
    iva_p = totales["iva_pct"] * 100
    rows = [
        ("PEM — Presupuesto de Ejecución Material", fmt_eur(totales["PEM"]), False),
        (f"Gastos Generales ({gg_p:.0f}%)",         fmt_eur(totales["GG"]),  False),
        (f"Beneficio Industrial ({bi_p:.0f}%)",     fmt_eur(totales["BI"]),  False),
        ("PEC — Presupuesto de Ejecución por Contrata", fmt_eur(totales["PEC"]), True),
    ]
    # Mixed IVA if totales carries it as a map
    if "iva_breakdown" in totales:
        for label, val in totales["iva_breakdown"]:
            rows.append((label, fmt_eur(val), False))
    else:
        rows.append((f"IVA ({iva_p:.0f}%)", fmt_eur(totales["IVA"]), False))
    if totales.get("RETENCION", 0):
        rows.append((f"Retención IRPF ({totales.get('retencion_pct',0)*100:.1f}%)",
                     f"-{fmt_eur(totales['RETENCION'])}", False))
    if totales.get("RECARGO_EQUIV", 0):
        rows.append((f"Recargo de equivalencia ({totales.get('recargo_pct',0)*100:.2f}%)",
                     fmt_eur(totales["RECARGO_EQUIV"]), False))
    rows.append(("TOTAL", fmt_eur(totales["TOTAL"]), "grand"))
    rows.append(("ICIO (orientativo, sobre PEM)", fmt_eur(totales["ICIO"]), "muted"))

    body = []
    for label, val, kind in rows:
        if kind == "grand":
            body.append([
                Paragraph(f'<font color="white"><b>{label}</b></font>',
                          ParagraphStyle("g", parent=st["cell"], textColor=white,
                                          fontName="Helvetica-Bold")),
                Paragraph(f'<font color="white"><b>{val}</b></font>',
                          ParagraphStyle("gr", parent=st["cell_r"], textColor=white,
                                          fontName="Helvetica-Bold")),
            ])
        elif kind is True:
            body.append([Paragraph(f"<b>{label}</b>", st["cell_b"]),
                         Paragraph(f"<b>{val}</b>", st["cell_r"])])
        elif kind == "muted":
            body.append([Paragraph(label, ParagraphStyle("m", parent=st["cell"], textColor=MUTED)),
                         Paragraph(val, ParagraphStyle("mr", parent=st["cell_r"], textColor=MUTED))])
        else:
            body.append([Paragraph(label, st["cell"]), Paragraph(val, st["cell_r"])])
    t = Table(body, colWidths=[130 * mm, 56 * mm])
    style_tbl = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
    ]
    for i, (_l, _v, kind) in enumerate(rows):
        if kind is True:
            style_tbl.append(("BACKGROUND", (0, i), (-1, i), HEAD_BG))
        elif kind == "grand":
            style_tbl.append(("BACKGROUND", (0, i), (-1, i), GRAND_BG))
    t.setStyle(TableStyle(style_tbl))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Forma de pago, plazo de ejecución y validez de oferta a convenir.</b> "
        "El presupuesto no incluye partidas no recogidas explícitamente en el "
        "alcance de la memoria; los importes son anteriores a IVA salvo donde "
        "se indica lo contrario y se han calculado aplicando los porcentajes "
        "regulatorios vigentes.",
        st["body"],
    ))

    decor = _RexPageDecor("PRESUPUESTO", firm, ref, fecha)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path


# --------------------------------------------------------------------------
# Plan de obra with real calendar dates
# --------------------------------------------------------------------------

def _next_working_day(d: _dt.date, festivos: set[_dt.date]) -> _dt.date:
    while d.weekday() >= 5 or d in festivos:  # 5=Sat, 6=Sun
        d += _dt.timedelta(days=1)
    return d


def _add_working_days(start: _dt.date, n: int, festivos: set[_dt.date]) -> _dt.date:
    """Return the last working day of an n-working-day window starting at start
    (start is day 1). Skips weekends and festivos."""
    if n <= 0:
        return start
    d = _next_working_day(start, festivos)
    days_used = 1
    while days_used < n:
        d += _dt.timedelta(days=1)
        d = _next_working_day(d, festivos)
        days_used += 1
    return d


class _Gantt(Flowable):
    """Horizontal-bar Gantt with discrete-day x-axis (relative day numbers
    for visual scale; absolute dates appear in the table)."""

    ROW_H = 7.5 * mm
    HEADER_H = 8 * mm
    LABEL_W = 50 * mm

    def __init__(self, rows: Sequence[tuple[str, int, int]], total_days: int):
        super().__init__()
        self.rows = list(rows)
        self.total_days = max(total_days, 1)
        self.width = 180 * mm
        self.height = self.HEADER_H + len(self.rows) * self.ROW_H + 4 * mm

    def wrap(self, availWidth: float, availHeight: float):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        bars_x = self.LABEL_W
        bars_w = self.width - self.LABEL_W - 2 * mm
        px_per_day = bars_w / self.total_days
        c.setStrokeColor(RULE)
        c.setLineWidth(0.3)
        axis_y = self.height - self.HEADER_H + 3 * mm
        c.line(bars_x, axis_y, bars_x + bars_w, axis_y)
        tick_step = max(1, self.total_days // 6)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        for d in range(0, self.total_days + 1, tick_step):
            x = bars_x + d * px_per_day
            c.line(x, axis_y - 1.2 * mm, x, axis_y)
            c.drawCentredString(x, axis_y + 1.4 * mm, f"Día {d}")
        for i, (label, start, dur) in enumerate(self.rows):
            y = self.height - self.HEADER_H - (i + 1) * self.ROW_H + 1.5 * mm
            c.setFont("Helvetica", 8.4)
            c.setFillColor(INK)
            c.drawString(0, y + 0.5 * mm, label[:38])
            c.setStrokeColor(RULE)
            c.line(bars_x, y - 0.5 * mm, bars_x + bars_w, y - 0.5 * mm)
            bx = bars_x + (start - 1) * px_per_day
            bw = dur * px_per_day
            c.setFillColor(BRAND if i % 2 == 0 else BRAND_SOFT)
            c.setStrokeColor(BRAND)
            c.setLineWidth(0.2)
            c.roundRect(bx, y - 0.5 * mm, bw, self.ROW_H - 3 * mm,
                        radius=1.2, stroke=1, fill=1)
            if bw > 12 * mm:
                c.setFillColor(white)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawCentredString(bx + bw / 2, y + 0.5 * mm, f"{dur} d")


def build_plan_obra_pdf(out_path: pathlib.Path,
                        firm: dict,
                        meta: dict,
                        partidas: list[dict],
                        duracion_dias: dict[str, int],
                        capitulo_orden: list[str],
                        ref: str,
                        festivos: Sequence[_dt.date] | None = None,
                        start_date: _dt.date | None = None,
                        project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    fecha_doc = _dt.date.today()
    start_date = start_date or (fecha_doc + _dt.timedelta(days=14))
    festivos_set = set(festivos or [])
    # canonical: start on a working day
    start_date = _next_working_day(start_date, festivos_set)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title="Plan de obra", author=firm.get("nombre", ""),
    )

    present = {p["capitulo"] for p in partidas}
    chapters = [c for c in capitulo_orden if c in present] + \
               [c for c in present if c not in capitulo_orden]

    # Build the per-chapter schedule using working days
    schedule: list[tuple[str, _dt.date, int, _dt.date, int, int]] = []
    # tuple: (chapter, inicio, dur, fin, rel_start_day, rel_end_day)
    cursor = start_date
    rel_day = 1
    for cap in chapters:
        dur = int(duracion_dias.get(cap, 3))
        inicio = _next_working_day(cursor, festivos_set)
        fin = _add_working_days(inicio, dur, festivos_set)
        # advance cursor to the next calendar day after fin
        cursor = fin + _dt.timedelta(days=1)
        schedule.append((cap, inicio, dur, fin, rel_day, rel_day + dur - 1))
        rel_day += dur
    total_dias_laborables = sum(s[2] for s in schedule)
    inicio_global = schedule[0][1] if schedule else start_date
    fin_global = schedule[-1][3] if schedule else start_date

    title = project_title or meta.get("memoria", "Plan de obra").replace(".md", "")
    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 8),
        Paragraph(
            f"Secuencia de capítulos con duración estimada en días laborables. "
            f"Inicio previsto <b>{fmt_date(inicio_global)}</b>, "
            f"finalización <b>{fmt_date(fin_global)}</b>. Calendario laboral "
            f"Ibiza-Baleares: descansa sábados, domingos y festivos oficiales.",
            st["meta"],
        ),
        Spacer(1, 8),
        Paragraph("Secuencia de capítulos", st["h2"]),
    ]

    head = [Paragraph(t, st["cell_b"]) for t in
            ("#", "Capítulo", "Inicio", "Duración", "Fin")]
    body = [head]
    for i, (cap, inicio, dur, fin, _rs, _re) in enumerate(schedule, start=1):
        body.append([
            Paragraph(str(i), st["cell_r"]),
            Paragraph(cap, st["cell"]),
            Paragraph(fmt_date(inicio), st["cell_c"]),
            Paragraph(f"{dur} días", st["cell_r"]),
            Paragraph(fmt_date(fin), st["cell_c"]),
        ])
    body.append([
        "",
        Paragraph("<b>Duración total estimada</b>", st["cell_b"]),
        Paragraph(f"<b>{fmt_date(inicio_global)}</b>", st["cell_c"]),
        Paragraph(f"<b>{total_dias_laborables} días</b>", st["cell_r"]),
        Paragraph(f"<b>{fmt_date(fin_global)}</b>", st["cell_c"]),
    ])
    t = Table(body, colWidths=[10 * mm, 84 * mm, 30 * mm, 22 * mm, 30 * mm],
              repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, -1), (-1, -1), 0.4, BRAND_SOFT),
        ("BACKGROUND", (0, -1), (-1, -1), HEAD_BG),
    ]
    for r in range(1, len(body) - 1):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), ROW_ALT))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 12))

    # Gantt
    story.append(Paragraph("Diagrama de barras", st["h2"]))
    story.append(_Gantt(
        [(cap, rs, dur) for (cap, _i, dur, _f, rs, _re) in schedule],
        total_dias_laborables,
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Hitos y observaciones", st["h2"]))
    for n in [
        f"Acopio de material previo al inicio de cada capítulo (ver plan de acopios). "
        f"Fecha de inicio prevista <b>{fmt_date(inicio_global)}</b>.",
        "Calendario excluye sábados, domingos y festivos oficiales (Baleares).",
        "Las partidas de instalaciones (cuando proceda) se solapan con albañilería "
        "para no extender el plazo total.",
        "Cualquier cambio de alcance ajusta automáticamente el plan tras volver a "
        "ejecutar el motor con la memoria actualizada.",
    ]:
        story.append(Paragraph("• " + n, st["body"]))

    decor = _RexPageDecor("PLAN DE OBRA", firm, ref, fecha_doc)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path
