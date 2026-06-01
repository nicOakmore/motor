"""
generate_pdf.py — One-page Spanish PDF explaining how the engine works.

Output: salidas/como_funciona.pdf

Stdlib + reportlab only. A4. Minimal styling, deliberately information-dense.
"""

from __future__ import annotations
import pathlib

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "salidas" / "como_funciona.pdf"


def build() -> pathlib.Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Motor de Presupuestos — Cómo funciona",
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.6, leading=11.2, alignment=TA_JUSTIFY, spaceAfter=4,
    )
    h1 = ParagraphStyle(
        "h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=14, leading=16, spaceBefore=0, spaceAfter=4,
        textColor=HexColor("#1a3a5c"),
    )
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=9.4, leading=11, spaceBefore=5, spaceAfter=2,
        textColor=HexColor("#1a3a5c"),
    )
    small = ParagraphStyle(
        "small", parent=body, fontSize=7.5, leading=9.5,
        textColor=HexColor("#444444"),
    )

    story = []

    story.append(Paragraph("Motor de Presupuestos — Cómo funciona", h1))
    story.append(Paragraph(
        "Sistema de reglas que transforma una <b>memoria constructiva</b> en un "
        "presupuesto trazable conforme a la normativa española (RD 1098/2001, "
        "Ley 37/1992) y al régimen urbanístico de Ibiza/Baleares (LUIB 12/2017). "
        "Cada euro del presupuesto se justifica con una regla, un precio y una "
        "línea del alcance: si no se puede trazar, el sistema no lo emite.",
        body,
    ))
    story.append(Paragraph(
        "<b>Demo en vivo:</b> "
        "<font color='#1a3a5c'>https://motor-presupuestos.onrender.com</font> — "
        "sube una memoria o usa una de muestra y descarga el presupuesto, el "
        "plan de acopios, el checklist regulatorio y la exportación BC3.",
        body,
    ))

    story.append(Paragraph("Arquitectura en cinco capas", h2))
    # Paragraph styles for table cells (Table strings don't word-wrap).
    cell_b = ParagraphStyle("cell_b", parent=body, fontName="Helvetica-Bold",
                             fontSize=8.4, leading=10, alignment=TA_LEFT,
                             textColor=HexColor("#1a3a5c"), spaceAfter=0)
    cell_t = ParagraphStyle("cell_t", parent=body, fontName="Helvetica",
                             fontSize=8.4, leading=10, alignment=TA_LEFT,
                             spaceAfter=0)
    layers = [
        ("A. INGESTA",
         "Lectura de la memoria + catálogos de precios (BC3, XLSX, CSV). "
         "Convierte texto desordenado en hechos tipados."),
        ("B. NORMALIZACIÓN",
         "Catálogo canónico: cada precio se anota con {código, unidad, ámbito, "
         "fecha, fuente}. Prioridad: local &gt; Balears/Ibiza &gt; BEDEC/CYPE &gt; web."),
        ("C. MOTOR DE REGLAS",
         "Encadenamiento hacia adelante estilo CLIPS. Dispara reglas por "
         "saliencia hasta el punto fijo. Determinista: mismos hechos + mismas "
         "reglas ⇒ mismo presupuesto."),
        ("D. OPTIMIZACIÓN",
         "(Opcional) Consolida pedidos de material, aplica merma, agrupa por "
         "proveedor y plazo. Reservado para NSGA-II."),
        ("E. SALIDA",
         "Presupuesto (PEM→PEC→IVA→TOTAL), cuadros de precios nº1 y nº2, plan "
         "de acopios, plan de obra (Gantt), exportación BC3 (FIEBDC-3) y "
         "checklist regulatorio."),
    ]
    layers_data = [[Paragraph(label, cell_b), Paragraph(desc, cell_t)]
                   for label, desc in layers]
    tbl = Table(layers_data, colWidths=[33 * mm, 145 * mm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#dddddd")),
    ]))
    story.append(tbl)

    story.append(Paragraph("El cómputo regulado (RD 1098/2001)", h2))
    cost_rows = [
        ("PEM", "Presupuesto de Ejecución Material", "Σ partidas (medición × precio unitario)"),
        ("GG", "Gastos Generales", "13% · PEM"),
        ("BI", "Beneficio Industrial", "6% · PEM"),
        ("PEC", "Presupuesto de Ejecución por Contrata", "PEM + GG + BI"),
        ("IVA", "Impuesto sobre el Valor Añadido", "10% vivienda habitual (Ley 37/1992 art.91); 21% resto"),
        ("TOTAL", "Importe a facturar al promotor", "PEC × (1 + IVA)"),
        ("ICIO", "Impuesto Construcciones (municipal)", "tipo municipal · PEM"),
    ]
    cell_s = ParagraphStyle("cell_s", parent=cell_t, fontSize=8.2, leading=9.8)
    cell_sb = ParagraphStyle("cell_sb", parent=cell_b, fontSize=8.2, leading=9.8)
    cost_data = [[Paragraph(a, cell_sb), Paragraph(b, cell_s), Paragraph(c, cell_s)]
                 for a, b, c in cost_rows]
    cost_tbl = Table(cost_data, colWidths=[16 * mm, 70 * mm, 92 * mm])
    cost_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#dddddd")),
    ]))
    story.append(cost_tbl)

    story.append(Paragraph("Salvaguardas regulatorias en Ibiza", h2))
    story.append(Paragraph(
        "El motor levanta <b>banderas</b>, nunca decide legalidad. "
        "<b>WARN LICENCIA_PREVIA</b> si la obra requiere proyecto técnico "
        "(LOE 38/1999 → licencia previa por LUIB art. 146 con anexos ESS "
        "RD 1627/1997, RCD RD 105/2008, control de calidad CTE y plan de obra). "
        "<b>STOP RUSTICO_REVISAR</b> en suelo rústico (Ley 7/2024): el sistema "
        "no presupuesta sin validación técnica previa. "
        "<b>INFO IVA_REDUCIDO_10</b> al aplicar el 10% por vivienda habitual.",
        body,
    ))

    story.append(Paragraph("Flujo de trabajo", h2))
    wf_rows = [
        ("1", "Abrir <b>https://motor-presupuestos.onrender.com</b> en el navegador."),
        ("2", "Elegir una memoria de muestra o subir la propia (.md / .txt)."),
        ("3", "El motor genera el presupuesto y muestra el cuadro resumen, las partidas por capítulo, el plan de acopios y las banderas regulatorias."),
        ("4", "Descargar los artefactos: presupuesto.md / .json, plan_acopios.csv, flags.md, traza.md, presupuesto.bc3 (FIEBDC-3)."),
        ("5", "Trazar cualquier euro: traza.md → partida → price_ref + scope_ref + regla que lo produjo."),
    ]
    workflow_data = [[Paragraph(n, cell_sb), Paragraph(t, cell_s)] for n, t in wf_rows]
    wf_tbl = Table(workflow_data, colWidths=[6 * mm, 172 * mm])
    wf_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(wf_tbl)

    story.append(Paragraph("¿Por qué esta forma?", h2))
    story.append(Paragraph(
        "Un presupuesto de obra en España es un documento técnico-legal: cada "
        "partida debe ser medible, cada precio justificable, y el escalado "
        "GG/BI/IVA viene fijado por norma. Un LLM en caja negra que «redacte un "
        "presupuesto» no puede defender una sola línea ante un cliente, una "
        "inspección o una disputa. Al situar al LLM como <b>autor de reglas "
        "declarativas</b> y a un motor determinista como <b>ejecutor</b>, todo "
        "euro queda atado a una regla, un precio y un ítem del alcance — y los "
        "mismos datos producen siempre el mismo presupuesto.",
        body,
    ))

    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "Motor de Presupuestos · Documento generado automáticamente.",
        small,
    ))

    doc.build(story)
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"PDF generado: {out}")
