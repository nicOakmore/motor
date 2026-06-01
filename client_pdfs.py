"""
client_pdfs.py — Client-facing PDF artefacts (Spanish).

Two builders:

- build_presupuesto_pdf(path, meta, totales, partidas, capitulo_orden, ref)
    Full client budget: cover-style header + capítulos with partidas +
    cuadro resumen (PEM → PEC → IVA → TOTAL).

- build_plan_obra_pdf(path, meta, partidas, duracion_dias, capitulo_orden, ref)
    One-page work plan: project metadata + capítulo schedule table +
    Gantt-style bars + total duration.

Both produce defensible, presentation-grade documents. Style is consistent
across them (same palette, header, footer, fonts) so they read as a set.

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
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_JUSTIFY
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
WARN        = HexColor("#a86b00")
STOP        = HexColor("#b1342f")
INFO        = HexColor("#14638a")


# ---------- helpers ----------

def fmt_eur(n: float) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _styles():
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=s["Heading1"], fontName="Helvetica-Bold",
                                 fontSize=18, leading=22, textColor=BRAND,
                                 spaceBefore=0, spaceAfter=4),
        "h2":    ParagraphStyle("h2", parent=s["Heading2"], fontName="Helvetica-Bold",
                                 fontSize=11, leading=14, textColor=BRAND,
                                 spaceBefore=10, spaceAfter=4),
        "h3":    ParagraphStyle("h3", parent=s["Heading3"], fontName="Helvetica-Bold",
                                 fontSize=9.5, leading=12, textColor=BRAND_SOFT,
                                 spaceBefore=6, spaceAfter=2),
        "body":  ParagraphStyle("body", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=9, leading=12, alignment=TA_JUSTIFY,
                                 spaceAfter=4),
        "meta":  ParagraphStyle("meta", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.6, leading=11, textColor=MUTED,
                                 spaceAfter=0),
        "small": ParagraphStyle("small", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=7.5, leading=9.5, textColor=MUTED,
                                 spaceAfter=0),
        "cell":  ParagraphStyle("cell", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.6, leading=10.5, alignment=TA_LEFT,
                                 spaceAfter=0),
        "cell_r":ParagraphStyle("cell_r", parent=s["BodyText"], fontName="Helvetica",
                                 fontSize=8.6, leading=10.5, alignment=TA_RIGHT,
                                 spaceAfter=0),
        "cell_b":ParagraphStyle("cell_b", parent=s["BodyText"], fontName="Helvetica-Bold",
                                 fontSize=8.6, leading=10.5, textColor=BRAND,
                                 spaceAfter=0),
    }


def _meta_block(meta: dict, ref: str, st: dict) -> Table:
    today = _dt.date.today().strftime("%d/%m/%Y")
    rows = [
        ("Promotor",      meta.get("promotor") or "—"),
        ("Emplazamiento", meta.get("emplazamiento") or "—"),
        ("Uso",           _label_uso(meta.get("uso"))),
        ("Suelo",         _label_suelo(meta.get("suelo"))),
        ("Proyecto técnico", "Sí" if meta.get("requiere_proyecto") else "No"),
        ("Referencia",    ref),
        ("Fecha",         today),
    ]
    data = [[Paragraph(f"<b>{k}</b>", st["cell_b"]),
             Paragraph(v, st["cell"])] for k, v in rows]
    t = Table(data, colWidths=[35 * mm, 145 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE),
    ]))
    return t


def _label_uso(v: str | None) -> str:
    return {"vivienda_habitual": "Vivienda habitual",
            "otros": "Otros / verificar"}.get(v or "", v or "—")


def _label_suelo(v: str | None) -> str:
    return {"urbano": "Urbano", "rustico": "Rústico"}.get(v or "", v or "—")


# Page header + footer (printed on every page via SimpleDocTemplate's onPage)

class _PageDecor:
    """Stateful page decorator: thin coloured rule at the top + footer with
    page number and a discreet legal disclaimer."""

    def __init__(self, title: str):
        self.title = title

    def __call__(self, canvas: Canvas, doc) -> None:
        w, h = doc.pagesize
        canvas.saveState()
        # top accent
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(1.2)
        canvas.line(15 * mm, h - 12 * mm, w - 15 * mm, h - 12 * mm)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(BRAND)
        canvas.drawString(15 * mm, h - 9 * mm, self.title)
        # footer
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(15 * mm, 12 * mm, w - 15 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 8 * mm,
                          "Documento orientativo. Sujeto a validación técnica y al régimen "
                          "urbanístico aplicable (LUIB 12/2017).")
        canvas.drawRightString(w - 15 * mm, 8 * mm, f"Página {doc.page}")
        canvas.restoreState()


# --------------------------------------------------------------------------
# Presupuesto cliente
# --------------------------------------------------------------------------

def build_presupuesto_pdf(out_path: pathlib.Path,
                          meta: dict,
                          totales: dict,
                          partidas: list[dict],
                          capitulo_orden: list[str],
                          ref: str) -> pathlib.Path:
    st = _styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Presupuesto", author="Motor de Presupuestos",
    )

    story: list = []
    story.append(Paragraph("Presupuesto", st["title"]))
    story.append(Paragraph(
        "Documento de presupuesto detallado conforme al RD 1098/2001 (capítulos · "
        "partidas · descompuestos) con escalado PEM → PEC → IVA.",
        st["meta"],
    ))
    story.append(Spacer(1, 6))
    story.append(_meta_block(meta, ref, st))
    story.append(Spacer(1, 8))

    # group partidas per capítulo, preserve canonical order
    by_cap: dict[str, list[dict]] = {}
    for p in partidas:
        by_cap.setdefault(p["capitulo"], []).append(p)
    ordered = [c for c in capitulo_orden if c in by_cap] + \
              [c for c in by_cap if c not in capitulo_orden]

    for idx, cap in enumerate(ordered, start=1):
        story.append(Paragraph(f"Capítulo {idx} · {cap}", st["h2"]))
        head = [Paragraph(t, st["cell_b"]) for t in
                ("Code", "Descripción", "Ud", "Medición", "Precio ud", "Importe")]
        body = [head]
        sub = 0.0
        for p in by_cap[cap]:
            sub += float(p["importe"])
            body.append([
                Paragraph(p["code"], st["cell"]),
                Paragraph(p["descripcion"], st["cell"]),
                Paragraph(p["unidad"], st["cell"]),
                Paragraph(f"{float(p['medicion']):.2f}", st["cell_r"]),
                Paragraph(fmt_eur(float(p["precio_unitario"])), st["cell_r"]),
                Paragraph(fmt_eur(float(p["importe"])), st["cell_r"]),
            ])
        body.append([
            "", "", "", "",
            Paragraph("<b>Subtotal capítulo</b>", st["cell_r"]),
            Paragraph(f"<b>{fmt_eur(sub)}</b>", st["cell_r"]),
        ])
        col_widths = [16 * mm, 78 * mm, 12 * mm, 20 * mm, 26 * mm, 28 * mm]
        t = Table(body, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
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
        story.append(Spacer(1, 6))

    # Cuadro resumen
    story.append(Spacer(1, 6))
    story.append(Paragraph("Cuadro resumen (RD 1098/2001)", st["h2"]))
    gg_p = int(totales["gg_pct"] * 100)
    bi_p = int(totales["bi_pct"] * 100)
    iva_p = int(totales["iva_pct"] * 100)
    rows = [
        ("PEM — Presupuesto de Ejecución Material", fmt_eur(totales["PEM"]), False),
        (f"Gastos Generales ({gg_p}%)",            fmt_eur(totales["GG"]),  False),
        (f"Beneficio Industrial ({bi_p}%)",        fmt_eur(totales["BI"]),  False),
        ("PEC — Presupuesto de Ejecución por Contrata", fmt_eur(totales["PEC"]), True),
        (f"IVA ({iva_p}%)",                         fmt_eur(totales["IVA"]), False),
        ("TOTAL",                                   fmt_eur(totales["TOTAL"]), "grand"),
        ("ICIO (orientativo, sobre PEM)",           fmt_eur(totales["ICIO"]), "muted"),
    ]
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
            body.append([
                Paragraph(f"<b>{label}</b>", st["cell_b"]),
                Paragraph(f"<b>{val}</b>", st["cell_r"]),
            ])
        elif kind == "muted":
            body.append([
                Paragraph(label, ParagraphStyle("m", parent=st["cell"], textColor=MUTED)),
                Paragraph(val, ParagraphStyle("mr", parent=st["cell_r"], textColor=MUTED)),
            ])
        else:
            body.append([Paragraph(label, st["cell"]), Paragraph(val, st["cell_r"])])
    t = Table(body, colWidths=[120 * mm, 60 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
        ("BACKGROUND", (0, 3), (-1, 3), HEAD_BG),     # PEC
        ("BACKGROUND", (0, 5), (-1, 5), GRAND_BG),    # TOTAL
    ]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<b>Forma de pago, plazo de ejecución y validez de oferta a convenir.</b> "
        "El presupuesto no incluye partidas no recogidas explícitamente en el "
        "alcance de la memoria; los importes son anteriores a IVA salvo donde se "
        "indica lo contrario y se han calculado aplicando los porcentajes "
        "regulatorios vigentes.",
        st["body"],
    ))

    decor = _PageDecor("Presupuesto")
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path


# --------------------------------------------------------------------------
# Plan de obra
# --------------------------------------------------------------------------

class _Gantt(Flowable):
    """Horizontal-bar Gantt with discrete-day x-axis. Renders inside a
    Platypus story. Width = available frame width; height grows with rows."""

    ROW_H = 7.5 * mm
    HEADER_H = 8 * mm
    LABEL_W = 50 * mm
    PADDING = 2 * mm

    def __init__(self, rows: Sequence[tuple[str, int, int]], total_days: int):
        super().__init__()
        # rows: list of (label, start_day (1-based), duration_days)
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

        # Top axis: tick every ~5 days, labelled
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

        # Rows
        for i, (label, start, dur) in enumerate(self.rows):
            y = self.height - self.HEADER_H - (i + 1) * self.ROW_H + 1.5 * mm
            # label
            c.setFont("Helvetica", 8.4)
            c.setFillColor(INK)
            c.drawString(0, y + 0.5 * mm, label[:38])
            # row baseline
            c.setStrokeColor(RULE)
            c.line(bars_x, y - 0.5 * mm, bars_x + bars_w, y - 0.5 * mm)
            # bar
            bx = bars_x + (start - 1) * px_per_day
            bw = dur * px_per_day
            c.setFillColor(BRAND if i % 2 == 0 else BRAND_SOFT)
            c.setStrokeColor(BRAND)
            c.setLineWidth(0.2)
            c.roundRect(bx, y - 0.5 * mm, bw, self.ROW_H - 3 * mm,
                        radius=1.2, stroke=1, fill=1)
            # duration label inside the bar if wide enough
            if bw > 12 * mm:
                c.setFillColor(white)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawCentredString(bx + bw / 2, y + 0.5 * mm, f"{dur} días")


def build_plan_obra_pdf(out_path: pathlib.Path,
                        meta: dict,
                        partidas: list[dict],
                        duracion_dias: dict[str, int],
                        capitulo_orden: list[str],
                        ref: str) -> pathlib.Path:
    st = _styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Plan de obra", author="Motor de Presupuestos",
    )

    # Which capítulos appear in this project, in canonical order?
    present = {p["capitulo"] for p in partidas}
    chapters = [c for c in capitulo_orden if c in present] + \
               [c for c in present if c not in capitulo_orden]

    # Sequence start days
    schedule = []        # (chapter, start_day, duration, end_day)
    day = 1
    for cap in chapters:
        dur = int(duracion_dias.get(cap, 3))
        schedule.append((cap, day, dur, day + dur - 1))
        day += dur
    total_days = max(day - 1, 1)

    story: list = []
    story.append(Paragraph("Plan de obra", st["title"]))
    story.append(Paragraph(
        "Secuencia de capítulos con duración estimada en días laborables. "
        "Los plazos son orientativos y se ajustarán al inicio de obra en "
        "función de suministros, condiciones meteorológicas y solapamientos.",
        st["meta"],
    ))
    story.append(Spacer(1, 6))
    story.append(_meta_block(meta, ref, st))
    story.append(Spacer(1, 10))

    # Schedule table
    story.append(Paragraph("Secuencia de capítulos", st["h2"]))
    head = [Paragraph(t, st["cell_b"]) for t in
            ("#", "Capítulo", "Inicio (día)", "Duración (días)", "Fin (día)")]
    body = [head]
    for i, (cap, start, dur, end) in enumerate(schedule, start=1):
        body.append([
            Paragraph(str(i), st["cell_r"]),
            Paragraph(cap, st["cell"]),
            Paragraph(str(start), st["cell_r"]),
            Paragraph(str(dur), st["cell_r"]),
            Paragraph(str(end), st["cell_r"]),
        ])
    body.append([
        "", Paragraph("<b>Duración total estimada</b>", st["cell_b"]),
        "", Paragraph(f"<b>{total_days} días</b>", st["cell_r"]), "",
    ])
    t = Table(body, colWidths=[10 * mm, 90 * mm, 24 * mm, 28 * mm, 22 * mm],
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
    story.append(_Gantt([(cap, s, d) for cap, s, d, _ in schedule], total_days))
    story.append(Spacer(1, 14))

    # Notes
    story.append(Paragraph("Hitos y observaciones", st["h2"]))
    notes = [
        "Acopio de material previo al inicio de cada capítulo según el plan de acopios.",
        "Las partidas de instalaciones (cuando proceda) se solapan con albañilería para no extender el plazo total.",
        "Cualquier cambio de alcance ajusta automáticamente el plan tras volver a ejecutar el motor con la memoria actualizada.",
    ]
    for n in notes:
        story.append(Paragraph("• " + n, st["body"]))

    decor = _PageDecor("Plan de obra")
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path
