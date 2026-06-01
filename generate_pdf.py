"""
generate_pdf.py — Two-page Spanish guide for Rex Construcciones.

Audience: the firm owner / a non-technical constructor. Tone: direct,
action-oriented. Each section tells the reader what to click. Sample
memorias are listed with clickable raw-GitHub download links.

Output: salidas/como_funciona.pdf
"""

from __future__ import annotations
import pathlib

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "salidas" / "como_funciona.pdf"

# Live URL + access (the audience is the firm owner)
LIVE_URL = "https://motor-presupuestos.onrender.com"
AUTH_USER = "adminmotor.com"
AUTH_PASS = "1234.67A"

# Raw-GitHub URLs to the sample memorias (public repo, no auth)
REPO_RAW = "https://raw.githubusercontent.com/nicOakmore/motor/main/memorias"

SAMPLES = [
    ("memoria_santa_eulalia.md",
     "Vivienda urbana Santa Eulària · Markdown",
     "Reforma sencilla en Markdown: tabique, enlucido, pintura, solado. "
     "Vivienda habitual, NO requiere proyecto técnico. <b>PEM 3.126,40 €</b>, "
     "TOTAL 4.092,45 €."),
    ("memoria_rustico_ibiza.md",
     "Finca rústica Ibiza · Markdown",
     "Suelo rústico → STOP. Requiere proyecto técnico, se generan los 4 "
     "anexos regulatorios. <b>PEM 3.837,50 €</b>, TOTAL 5.023,29 €."),
    ("memoria_finca_turistica.md",
     "Finca alquiler turístico San Antonio · Markdown",
     "Cubierta + fachada + uso turístico → 6 banderas. "
     "<b>PEM 22.904,90 €</b>, TOTAL 29.982,51 €."),
    ("memoria_santa_eulalia.pdf",
     "Igual que la primera, en formato PDF",
     "El mismo contenido en PDF — el parser extrae 5 partidas también de un "
     "PDF estructurado. <b>PEM 3.126,40 €</b>."),
    ("memoria_rustico_ibiza.pdf",
     "Igual que la rústica, en PDF",
     "El mismo contenido en PDF — dispara STOP rústico y genera anexos."),
    ("memoria_finca_turistica.pdf",
     "Igual que la turística, en PDF",
     "El mismo contenido en PDF — dispara las 6 banderas regulatorias."),
    ("santjosep_ibiza.pdf",
     "Proyecto Sant Josep de sa Talaia · PDF real (240 pp)",
     "Memoria oficial de un Ayuntamiento. Narrativa pura, sin scope "
     "numerado. El parser saca metadata y la <b>IA propone partidas</b> "
     "contra el catálogo. En la última corrida: PEM 90.667,90 € · TOTAL "
     "118.684,28 €."),
    ("porreres_mallorca.pdf",
     "Cambio a agroturismo Porreres · PDF real",
     "Memoria de cambio de uso (agroturismo). Suelo rústico detectado "
     "automáticamente del patrón polígono/parcela. Aplica también la "
     "IA si la prosa no rinde partidas directamente."),
    ("coac_grancanaria.pdf",
     "Plantilla COAC vivienda · PDF real",
     "Plantilla CTE genérica. Demuestra que el motor extrae también de "
     "formularios estandarizados."),
]


def build() -> pathlib.Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Motor de Presupuestos — Guía rápida",
        author="Rex Construcciones",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=16, leading=19, spaceBefore=0, spaceAfter=2,
        textColor=HexColor("#1a3a5c"),
    )
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, leading=13, spaceBefore=8, spaceAfter=3,
        textColor=HexColor("#1a3a5c"),
    )
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.8, leading=11.5, alignment=TA_JUSTIFY, spaceAfter=3,
    )
    intro = ParagraphStyle(
        "intro", parent=body, fontSize=9.4, leading=12.5,
    )
    cell = ParagraphStyle(
        "cell", parent=body, fontName="Helvetica",
        fontSize=8.4, leading=10.5, alignment=TA_LEFT, spaceAfter=0,
    )
    cell_b = ParagraphStyle(
        "cell_b", parent=cell, fontName="Helvetica-Bold",
        textColor=HexColor("#1a3a5c"),
    )
    small = ParagraphStyle(
        "small", parent=body, fontSize=7.5, leading=9.5,
        textColor=HexColor("#444444"), spaceAfter=0,
    )
    link_color = "#1a3a5c"

    def link(href: str, text: str) -> str:
        return (f'<link href="{href}" color="{link_color}">'
                f'<u>{text}</u></link>')

    story: list = []

    # ===== PAGE 1 =====
    story.append(Paragraph("Motor de Presupuestos · Guía rápida para Rex Construcciones", h1))
    story.append(Paragraph(
        "Conviertes una <b>memoria constructiva</b> en un presupuesto completo "
        "con plan de obra, cuadros de precios, plan de acopios, BC3 y los "
        "anexos legales obligatorios cuando aplican — en menos de un minuto.",
        intro,
    ))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"<b>Acceso:</b> {link(LIVE_URL, LIVE_URL)} · "
        f"usuario <b>{AUTH_USER}</b> · contraseña <b>{AUTH_PASS}</b>",
        body,
    ))

    story.append(Paragraph("Tres maneras de empezar", h2))
    paths_data = [
        ("1.", "<b>Prueba una memoria de muestra</b>. En la pantalla principal "
               "elige una del desplegable y pulsa «Procesar muestra». Tienes "
               "seis ejemplos listos (lista abajo)."),
        ("2.", "<b>Sube tu memoria</b>. Acepta <font face='Helvetica-Bold'>"
               "Markdown, texto, PDF</font> (incluidos los de proyecto técnico "
               "de 200+ páginas) y <font face='Helvetica-Bold'>BC3</font>. "
               "Pulsa «Procesar memoria»."),
        ("3.", "<b>Sube un BC3 de Presto / Arquímedes / CYPE</b>. El motor "
               "lee capítulos, partidas, descompuestos, mediciones y pliego "
               "directamente — no hace falta retipear nada."),
    ]
    paths_tbl = Table(
        [[Paragraph(n, cell_b), Paragraph(t, cell)] for n, t in paths_data],
        colWidths=[6 * mm, 176 * mm],
    )
    paths_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(paths_tbl)

    story.append(Paragraph("Las seis memorias de muestra (clic para descargar)", h2))
    samples_data = []
    for fname, title, desc in SAMPLES:
        label = link(f"{REPO_RAW}/{fname}", fname)
        samples_data.append([
            Paragraph(label, cell_b),
            Paragraph(f"<b>{title}.</b> {desc}", cell),
        ])
    samples_tbl = Table(samples_data, colWidths=[55 * mm, 127 * mm])
    samples_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#d6dae2")),
    ]))
    story.append(samples_tbl)

    story.append(Paragraph("Lo que obtienes (descargables en la pantalla de resultado)", h2))
    deliverables_data = [
        ("Presupuesto cliente",
         "PDF con cabecera Rex Construcciones, capítulos, partidas, cuadro PEM → PEC → IVA → TOTAL."),
        ("Plan de obra",
         "PDF con calendario real (excluye fines de semana y festivos de Baleares) y diagrama de barras."),
        ("Cuadro de Precios Nº 1",
         "Precios unitarios en cifra y en letra (art. 100 RGLCAP)."),
        ("Cuadro de Precios Nº 2",
         "Descompuesto mo / mat / maq con rendimientos reales por partida."),
        ("Plan de acopios",
         "CSV con materiales consolidados y merma aplicada."),
        ("Checklist regulatorio",
         "Markdown con todas las banderas y la regla que las disparó."),
        ("Presupuesto BC3",
         "FIEBDC-3/2024 — exportable a Presto / Arquímedes / CYPE."),
        ("Cuando hay proyecto técnico, también:",
         "Pliego de condiciones · Estudio de Seguridad y Salud (RD 1627/1997) · "
         "Plan de gestión de RCD (RD 105/2008) · Plan de control de calidad CTE."),
    ]
    delivs_tbl = Table(
        [[Paragraph(f"<b>{a}</b>", cell_b), Paragraph(b, cell)]
         for a, b in deliverables_data],
        colWidths=[55 * mm, 127 * mm],
    )
    delivs_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#d6dae2")),
    ]))
    story.append(delivs_tbl)

    # ===== PAGE 2 =====
    story.append(PageBreak())

    story.append(Paragraph("Lo que el sistema detecta automáticamente", h2))
    auto_items = [
        "<b>Promotor</b> y <b>emplazamiento</b> — incluso en PDFs reales de "
        "200+ páginas, con o sin etiqueta «PROMOTOR:» / «EMPLAZAMIENTO:».",
        "<b>Suelo</b>: rústico, urbano, ANEI/ARIP, código SRC, o el patrón "
        "cadastral «polígono N, parcelas X-Y-Z».",
        "<b>Si requiere proyecto técnico</b>: lo deduce de los títulos "
        "«PROYECTO BÁSICO», «PROYECTO DE EJECUCIÓN» o «PROYECTO TÉCNICO».",
        "<b>Si hay demoliciones o movimiento de tierras</b> — para activar "
        "la ordenanza municipal de ruido.",
        "<b>Si toca cubierta, fachada o carpintería exterior</b> — para "
        "activar el CTE-DB-HE (eficiencia energética).",
        "<b>Uso turístico / vacacional / ETV</b> — sólo si la memoria lo "
        "declara explícitamente (evita falsos positivos en referencias CTE).",
        "<b>Huecos en tabiques</b>: «(con 4 huecos de 1,8 m²)» descuenta "
        "automáticamente de la medición.",
    ]
    for it in auto_items:
        story.append(Paragraph("• " + it, body))

    story.append(Paragraph("Banderas regulatorias automáticas (Spain / Ibiza)", h2))
    flags_data = [
        ("STOP",  "USO_TURISTICO_IBIZA",  "Ley 8/2012 + Decreto 20/2015 ETV — moratorias municipales."),
        ("STOP",  "RUSTICO_REVISAR",      "Ley 7/2024 — régimen de legalización en suelo rústico."),
        ("WARN",  "LICENCIA_PREVIA",      "LUIB 12/2017 art. 146 — licencia municipal previa + anexos obligatorios."),
        ("WARN",  "ACCESIBILIDAD_SUA",    "CTE-DB-SUA — itinerarios accesibles, aseos."),
        ("WARN",  "EFICIENCIA_HE",        "CTE-DB-HE — limitación de demanda, transmitancias U, certif. energética."),
        ("INFO",  "RUIDO_MUNICIPAL",      "Ordenanza municipal de ruido cuando hay demoliciones / movimiento de tierras."),
        ("INFO",  "IVA_REDUCIDO_10",      "Ley 37/1992 art. 91 — IVA 10% por vivienda habitual."),
    ]
    flags_tbl = Table(
        [[Paragraph(f"<b>{lvl}</b>", cell_b), Paragraph(f"<b>{code}</b>", cell),
          Paragraph(why, cell)] for lvl, code, why in flags_data],
        colWidths=[14 * mm, 47 * mm, 121 * mm],
    )
    flags_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#d6dae2")),
    ]))
    story.append(flags_tbl)

    story.append(Paragraph("Editar en el navegador (sin instalar nada)", h2))
    edit_items = [
        "<b>Cambiar</b> medición, precio unitario o IVA por partida.",
        "<b>Añadir</b> partida nueva desde el catálogo de 111 entradas (autocomplete).",
        "<b>Eliminar</b> partidas que no apliquen.",
        "<b>Sobrescribir</b> Gastos Generales, Beneficio Industrial, IVA por defecto, retención IRPF, recargo de equivalencia.",
        "Al guardar, <b>todos los PDFs y el BC3 se regeneran al instante</b> con los nuevos números.",
    ]
    for it in edit_items:
        story.append(Paragraph("• " + it, body))

    story.append(Paragraph("Catálogo y depth", h2))
    story.append(Paragraph(
        "El catálogo trae <b>111 partidas en 17 capítulos</b> (Demoliciones, "
        "Movimiento de tierras, Cimentación, Estructura, Cubiertas, "
        "Albañilería, Aislamientos, Revestimientos, Pavimentos, Carpintería "
        "interior / exterior, Pintura, Fontanería, Saneamiento, Electricidad, "
        "Climatización, Urbanización) con precios mid-range Ibiza 2026. "
        "52 partidas llevan <b>descompuesto detallado</b> "
        "(15 oficios con €/h, 58 materiales, 7 máquinas) — el Cuadro Nº 2 "
        "muestra h × tarifa / cantidad × precio igual que Presto.",
        body,
    ))
    story.append(Paragraph(
        "Cambiar el catálogo por uno propio o por una exportación BEDEC/ITeC: "
        "sustituye los CSV de la carpeta <font face='Helvetica-Oblique'>precios/</font> "
        "y vuelve a procesar. El motor no toca el código.",
        body,
    ))

    story.append(Paragraph("IA · activa en este servidor", h2))
    story.append(Paragraph(
        "Cuando subes una memoria narrativa (PDF de proyecto técnico sin "
        "lista numerada de partidas), el panel de resultados ofrece el "
        "botón <b>«Extraer partidas con IA»</b>. El modelo (<b>Llama 3.3 "
        "70B</b> vía Groq, gratis) propone partidas contra el catálogo; el "
        "motor determinista las precia y la auditoría sigue funcionando "
        "(la IA nunca asienta hechos sola). El Sant Josep PDF de 240 "
        "páginas pasa de 0 € a ~118.000 € con este flujo. La IA se puede "
        "apagar al instante desde Render → Environment → <code>LLM_ENABLED"
        "</code>.",
        body,
    ))

    story.append(Paragraph("Catálogo · /admin", h2))
    story.append(Paragraph(
        "El menú superior incluye «<b>Catálogo</b>» (<font color='#1a3a5c'>"
        f"{LIVE_URL}/admin</font>). Dos paneles: <b>(1)</b> subir tu CSV "
        "propio con cabecera "
        "<font face='Helvetica-Oblique'>code, unidad, descripcion, "
        "precio_unitario</font> — al subir, todos los siguientes "
        "presupuestos usan tus precios. <b>(2)</b> Pegar una URL pública "
        "(CSV o BC3) — el motor descarga y aplica. Botón de «Restaurar al "
        "original». Fuentes públicas a la vista: Comunidad de Madrid, "
        "Junta de Extremadura, CYPE Generador, ITeC BEDEC, PREOC, INE.",
        body,
    ))

    story.append(Paragraph("Cómo usarlo en tu día a día", h2))
    flow = [
        "<b>1.</b> Te llega la memoria del cliente o del técnico → la subes en la pantalla principal.",
        "<b>2.</b> Revisas en pantalla las partidas que ha encontrado, los totales y las banderas. "
        "Si algo no cuadra, abres el <b>editor</b> y lo ajustas.",
        "<b>3.</b> Descargas el <b>Presupuesto cliente</b> + el <b>Plan de obra</b> y los envías al cliente.",
        "<b>4.</b> Si la obra requiere proyecto técnico, descargas también el "
        "<b>Pliego</b>, el <b>ESS</b>, el <b>Plan de RCD</b> y el <b>Control "
        "de calidad CTE</b> — quedan para el técnico competente.",
        "<b>5.</b> El <b>BC3</b> lo abres en Presto / Arquímedes para guardar "
        "en tu sistema interno.",
    ]
    for s in flow:
        story.append(Paragraph(s, body))

    story.append(Spacer(1, 2))
    story.append(Paragraph(
        "Cada euro del presupuesto es trazable hasta la regla y la línea "
        "de la memoria que lo originó (archivo <font face='Helvetica-Oblique'>"
        "traza.md</font>) — defendible ante el cliente, el técnico o una "
        "inspección. Próximos pasos en el roadmap: ingestión de archivos "
        "CAD (DWG / DXF) para extraer mediciones geométricas y mapearlas "
        "automáticamente al catálogo.",
        small,
    ))

    doc.build(story)
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"PDF generado: {out}")
