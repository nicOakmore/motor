"""
regulatory_pdfs.py — Mandatory regulatory annexes (Spanish).

Generated only when the project requires a proyecto técnico (LOE 38/1999
+ LUIB 12/2017 art.146):

- build_pliego_condiciones_pdf — Pliego de condiciones
- build_ess_pdf                — Estudio de Seguridad y Salud (RD 1627/1997)
- build_rcd_pdf                — Plan de gestión de RCD (RD 105/2008)
- build_control_calidad_pdf    — Plan de control de calidad (CTE)

These are template documents shaped like the real annexes a Spanish
construction firm submits with a licencia urbanística. Project-specific
data (promotor, emplazamiento, ref) is interpolated; the legal/technical
body text is short and defensible — meant as a starting point a
technician completes, not a substitute for one.
"""

from __future__ import annotations
import datetime as _dt
import pathlib

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle

# Reuse styling helpers from client_pdfs so all artefacts read as a set.
from client_pdfs import (
    _styles, _header_block, _title_row, _RexPageDecor,
    fmt_eur, fmt_num, fmt_date,
    BRAND, BRAND_SOFT, INK, MUTED, RULE, HEAD_BG, ROW_ALT,
)


# --------------------------------------------------------------------------
# Common section helpers
# --------------------------------------------------------------------------

def _section(title: str, st: dict, level: int = 2):
    return Paragraph(title, st["h2"] if level == 2 else st["h3"])


def _para(text: str, st: dict):
    return Paragraph(text, st["body"])


def _bullets(items: list[str], st: dict):
    return [Paragraph("• " + t, st["body"]) for t in items]


def _kv_table(rows: list[tuple[str, str]], st: dict, label_w_mm: float = 40):
    data = [[Paragraph(f"<b>{k}</b>", st["cell_b"]), Paragraph(v, st["cell"])]
            for k, v in rows]
    t = Table(data, colWidths=[label_w_mm * mm, (186 - label_w_mm) * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE),
    ]))
    return t


def _build_doc(out_path: pathlib.Path, title_header: str, firm: dict,
               ref: str, story: list) -> pathlib.Path:
    fecha = _dt.date.today()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=title_header, author=firm.get("nombre", ""),
    )
    decor = _RexPageDecor(title_header, firm, ref, fecha)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return out_path


# --------------------------------------------------------------------------
# 1. Pliego de condiciones
# --------------------------------------------------------------------------

def build_pliego_condiciones_pdf(out_path: pathlib.Path, firm: dict,
                                  meta: dict, partidas: list[dict],
                                  totales: dict, ref: str,
                                  project_title: str | None = None
                                  ) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")
    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 8),
        Paragraph("PLIEGO DE CONDICIONES", st["title"]),
        _para(
            "Documento contractual que regula las condiciones facultativas, "
            "económicas, legales y técnicas aplicables a la ejecución de la "
            "obra descrita en el presupuesto adjunto. Forma parte del proyecto "
            "técnico en el sentido del artículo 4 de la Ley 38/1999 de "
            "Ordenación de la Edificación (LOE) y del artículo 146 de la Ley "
            "12/2017 de Urbanismo de las Illes Balears (LUIB).",
            st,
        ),

        _section("1. Disposiciones generales", st),
        _para(
            "1.1. <b>Objeto.</b> El presente pliego tiene por objeto regular "
            "la ejecución de las obras descritas en el presupuesto, "
            "estableciendo las obligaciones técnicas, económicas y "
            "administrativas que asume el contratista.",
            st,
        ),
        _para(
            "1.2. <b>Documentos del proyecto.</b> El proyecto está compuesto "
            "por la memoria constructiva, el presupuesto detallado (capítulos, "
            "partidas y descompuestos), los planos, el presente pliego y los "
            "anexos regulatorios obligatorios (ESS RD 1627/1997, gestión de "
            "RCD RD 105/2008, plan de control de calidad CTE y plan de obra).",
            st,
        ),
        _para(
            "1.3. <b>Normativa aplicable.</b> CTE (RD 314/2006 y modificaciones), "
            "LOE 38/1999, RD 1098/2001 (cost build-up), LUIB 12/2017, Ley "
            "37/1992 del IVA, RD 1627/1997 (SyS), RD 105/2008 (RCD), Ley "
            "7/2024 (Baleares, regímenes de legalización en suelo rústico) y "
            "ordenanzas municipales aplicables.",
            st,
        ),

        _section("2. Condiciones facultativas", st),
        _para(
            "2.1. <b>Dirección facultativa.</b> Estará a cargo del técnico "
            "competente designado por la propiedad; con autoridad para resolver "
            "indeterminaciones técnicas, ordenar la ejecución por unidades de "
            "obra y autorizar modificaciones que no afecten al precio total.",
            st,
        ),
        _para(
            "2.2. <b>Contratista.</b> Asume la ejecución material de la obra "
            "conforme a las buenas prácticas constructivas, aporta los medios "
            "humanos y materiales, garantiza el cumplimiento de la normativa "
            "laboral y de SyS, y responde de la calidad y plazo pactados.",
            st,
        ),
        _para(
            "2.3. <b>Subcontratación.</b> Se ajustará a la Ley 32/2006; el "
            "contratista comunicará por escrito a la dirección facultativa la "
            "identidad de cada subcontrata, su afiliación al REA cuando "
            "proceda y la cobertura de SyS aplicada.",
            st,
        ),

        _section("3. Condiciones económicas", st),
        _para(
            "3.1. <b>Presupuesto base.</b> El importe pactado figura en el "
            "documento «presupuesto_cliente.pdf»: PEM "
            f"<b>{fmt_eur(totales['PEM'])}</b>, PEC "
            f"<b>{fmt_eur(totales['PEC'])}</b>, TOTAL "
            f"<b>{fmt_eur(totales['TOTAL'])}</b>. Los porcentajes aplicados "
            f"son: Gastos Generales {totales['gg_pct']*100:.0f}%, Beneficio "
            f"Industrial {totales['bi_pct']*100:.0f}%, IVA de referencia "
            f"{totales['iva_pct']*100:.0f}% (Ley 37/1992).",
            st,
        ),
        _para(
            "3.2. <b>Mediciones y certificaciones.</b> Las certificaciones "
            "mensuales se emitirán sobre obra realmente ejecutada, valorada a "
            "los precios unitarios de las partidas. Las mediciones se "
            "tomarán por la dirección facultativa con asistencia del "
            "contratista.",
            st,
        ),
        _para(
            "3.3. <b>Modificaciones.</b> Toda partida no recogida en el "
            "alcance original generará un precio contradictorio firmado por "
            "la dirección facultativa y el contratista antes de su ejecución.",
            st,
        ),
        _para(
            "3.4. <b>Plazos de pago.</b> Conforme a la Ley 3/2004; las "
            "certificaciones serán abonadas en un máximo de 30 días desde su "
            "aprobación.",
            st,
        ),

        _section("4. Condiciones legales", st),
        _para(
            "4.1. <b>Seguros.</b> El contratista mantendrá vigente una póliza "
            "de responsabilidad civil con cobertura mínima de 600.000 € por "
            "siniestro y un seguro de accidentes laborales conforme al "
            "régimen general de la Seguridad Social.",
            st,
        ),
        _para(
            "4.2. <b>Garantía.</b> Por aplicación del artículo 19 de la LOE: "
            "garantía decenal frente a vicios estructurales, trienal frente "
            "a vicios en habitabilidad y anual por defectos de acabado.",
            st,
        ),
        _para(
            "4.3. <b>Jurisdicción.</b> Las partes se someten a los tribunales "
            "de Eivissa/Ibiza para la resolución de cualquier controversia, "
            "renunciando al fuero propio si lo tuvieran.",
            st,
        ),

        _section("5. Condiciones técnicas particulares", st),
        _para(
            "5.1. <b>Recepción de materiales.</b> Cada material será objeto "
            "de control documental (marcado CE, declaración de prestaciones) "
            "y de aceptación visual y dimensional según el plan de control "
            "de calidad CTE adjunto.",
            st,
        ),
        _para(
            "5.2. <b>Ejecución por capítulo.</b> Las partidas se ejecutarán "
            "siguiendo las indicaciones de los CTE-DB aplicables, las normas "
            "UNE/EN vigentes y las buenas prácticas de la zona.",
            st,
        ),
        _para(
            "5.3. <b>Tolerancias y pruebas.</b> Las tolerancias dimensionales "
            "y los ensayos en obra se regirán por el CTE-DB-SE y las "
            "normas UNE específicas (hormigón EHE-08, aceros UNE-EN 10025, "
            "cerámicos UNE-EN 14411, etc.).",
            st,
        ),
        Spacer(1, 6),
        _para(
            "<b>Aceptación.</b> La firma del presupuesto por la propiedad "
            "supone la aceptación íntegra del presente pliego.",
            st,
        ),
    ]
    return _build_doc(out_path, "PLIEGO DE CONDICIONES", firm, ref, story)


# --------------------------------------------------------------------------
# 2. Estudio de Seguridad y Salud (RD 1627/1997)
# --------------------------------------------------------------------------

def build_ess_pdf(out_path: pathlib.Path, firm: dict, meta: dict,
                  partidas: list[dict], totales: dict, ref: str,
                  project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")
    # SS budget: 1.5% of PEM is the conventional reference for this type
    # of work in Baleares.
    ss_pct = 0.015
    ss_importe = round(totales["PEM"] * ss_pct, 2)

    # Risk register reduced from the typical Anexo II of RD 1627/1997
    riesgos = [
        ("Caídas a distinto nivel", "Andamios certificados, líneas de vida, EPI anti-caída."),
        ("Caídas al mismo nivel", "Orden y limpieza, retirada continua de escombros."),
        ("Atrapamiento por maquinaria", "Resguardos, formación específica de operarios."),
        ("Cortes y golpes con herramientas", "EPI manos/ojos, mantenimiento de herramienta."),
        ("Sobreesfuerzos", "Ayudas mecánicas, rotación de tareas."),
        ("Exposición a polvo / sílice", "Mascarillas FFP3, humectación, aspiración localizada."),
        ("Ruido", "Protectores auditivos cuando se supere LAeq,d 80 dB(A)."),
        ("Riesgo eléctrico", "Cuadros con diferencial 30 mA, revisión periódica."),
        ("Riesgos viales (carga/descarga)", "Señalización, vigilante de maniobras."),
    ]
    riesgos_tbl = Table(
        [[Paragraph("<b>Riesgo identificado</b>", st["cell_b"]),
          Paragraph("<b>Medida preventiva</b>", st["cell_b"])]]
        + [[Paragraph(r, st["cell"]), Paragraph(m, st["cell"])]
           for r, m in riesgos],
        colWidths=[60 * mm, 126 * mm], repeatRows=1,
    )
    riesgos_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
    ]))

    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 8),
        Paragraph("ESTUDIO DE SEGURIDAD Y SALUD", st["title"]),
        _para(
            "Documento exigible por el <b>Real Decreto 1627/1997</b>, de 24 de "
            "octubre, por el que se establecen disposiciones mínimas de "
            "seguridad y de salud en las obras de construcción. Aplica al "
            "presente proyecto por requerir proyecto técnico.",
            st,
        ),

        _section("1. Memoria", st),
        _kv_table([
            ("Promotor",     meta.get("promotor") or "—"),
            ("Emplazamiento",meta.get("emplazamiento") or "—"),
            ("Tipo de obra", "Edificación / reforma"),
            ("Plazo estimado", f"Definido en el plan de obra (ver plan_de_obra.pdf)"),
            ("Mano de obra prevista", "según presupuesto adjunto"),
            ("Referencia",   ref),
        ], st),
        Spacer(1, 6),
        _para(
            "<b>Descripción.</b> El alcance, las partidas y las mediciones "
            "están detalladas en el presupuesto adjunto. Las operaciones "
            "previstas (demoliciones, movimiento de tierras, albañilería, "
            "instalaciones, acabados y, en su caso, urbanización exterior) "
            "comportan los riesgos identificados en el apartado 2.",
            st,
        ),

        _section("2. Riesgos identificados y medidas preventivas", st),
        riesgos_tbl,

        _section("3. Pliego de condiciones particulares (SS)", st),
        _para(
            "Es obligación del contratista la elaboración del <b>Plan de "
            "Seguridad y Salud</b> en aplicación del presente estudio, "
            "aprobado por el coordinador en materia de SyS antes del inicio "
            "de los trabajos (art. 7 RD 1627/1997).",
            st,
        ),
        *_bullets([
            "Equipos de Protección Individual con marcado CE para cada "
            "operario expuesto.",
            "Formación específica en SyS antes de la entrada en obra y "
            "actualización al cambiar de tajo.",
            "Reuniones semanales de coordinación entre dirección "
            "facultativa, recurso preventivo y contratistas.",
            "Libro de incidencias en obra a disposición de Inspección "
            "de Trabajo, dirección facultativa y representantes de los "
            "trabajadores.",
        ], st),

        _section("4. Presupuesto de Seguridad y Salud", st),
        _para(
            f"Se estima en el <b>{ss_pct*100:.1f}% del PEM</b>, equivalente a "
            f"<b>{fmt_eur(ss_importe)}</b>, importe que cubre EPIs, "
            f"protecciones colectivas (redes, barandillas, líneas de vida), "
            f"señalización, formación específica y recurso preventivo. Esta "
            f"partida es independiente del PEM ordinario y se imputa al "
            f"capítulo SyS al certificarse.",
            st,
        ),
    ]
    return _build_doc(out_path, "ESTUDIO DE SEGURIDAD Y SALUD", firm, ref, story)


# --------------------------------------------------------------------------
# 3. Plan de gestión de RCD (RD 105/2008)
# --------------------------------------------------------------------------

def build_rcd_pdf(out_path: pathlib.Path, firm: dict, meta: dict,
                  partidas: list[dict], totales: dict, ref: str,
                  project_title: str | None = None) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")

    # Rough volumetric estimation: by chapter type, m³ residuos / m² de obra
    # útil — synthetic but defensible. Real plan computes per actual partida.
    # PEM is a proxy here.
    pem = totales["PEM"]
    estimado_total_m3 = round(pem / 220.0, 2)   # ~0.005 m³ per €PEM, mid-range

    # LER codes for typical residuos in reforma/edificación
    ler_rows = [
        ("17 01 07", "Mezclas de hormigón, ladrillos, tejas y materiales cerámicos sin contaminantes",
         f"~{round(estimado_total_m3 * 0.55, 2)} m³",
         "Vertedero autorizado / planta de reciclaje"),
        ("17 02 01", "Madera",
         f"~{round(estimado_total_m3 * 0.06, 2)} m³",
         "Reciclaje / valorización energética"),
        ("17 02 03", "Plástico",
         f"~{round(estimado_total_m3 * 0.04, 2)} m³",
         "Reciclaje selectivo"),
        ("17 04 05", "Hierro y acero",
         f"~{round(estimado_total_m3 * 0.05, 2)} m³",
         "Gestor autorizado de metales"),
        ("17 09 04", "Residuos mezclados de construcción y demolición",
         f"~{round(estimado_total_m3 * 0.25, 2)} m³",
         "Vertedero autorizado"),
        ("17 06 04", "Materiales de aislamiento (no peligrosos)",
         f"~{round(estimado_total_m3 * 0.05, 2)} m³",
         "Gestor autorizado"),
    ]
    ler_tbl = Table(
        [[Paragraph("<b>Cód. LER</b>", st["cell_b"]),
          Paragraph("<b>Descripción</b>", st["cell_b"]),
          Paragraph("<b>Estimación</b>", st["cell_b"]),
          Paragraph("<b>Gestión</b>", st["cell_b"])]]
        + [[Paragraph(c, st["cell"]), Paragraph(d, st["cell"]),
            Paragraph(e, st["cell_r"]), Paragraph(g, st["cell"])]
           for c, d, e, g in ler_rows],
        colWidths=[22 * mm, 84 * mm, 28 * mm, 52 * mm], repeatRows=1,
    )
    ler_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
    ]))

    rcd_pct = 0.012
    rcd_importe = round(pem * rcd_pct, 2)

    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 8),
        Paragraph("PLAN DE GESTIÓN DE RCD", st["title"]),
        _para(
            "Plan elaborado en cumplimiento del <b>Real Decreto 105/2008</b>, "
            "de 1 de febrero, por el que se regula la producción y gestión de "
            "los residuos de construcción y demolición.",
            st,
        ),

        _section("1. Identificación", st),
        _kv_table([
            ("Productor (promotor)", meta.get("promotor") or "—"),
            ("Emplazamiento",        meta.get("emplazamiento") or "—"),
            ("Poseedor (contratista)", firm.get("nombre", "—")),
            ("Referencia",            ref),
        ], st),

        _section("2. Estimación cuantitativa de RCD", st),
        _para(
            f"Volumen total estimado: <b>~{estimado_total_m3} m³</b>. Reparto "
            f"por código LER (lista europea de residuos):",
            st,
        ),
        ler_tbl,
        Spacer(1, 6),
        _para(
            "Las cantidades indicadas son una estimación a partir del PEM; "
            "se ajustarán al finalizar la obra mediante las certificaciones "
            "de los gestores autorizados.",
            st,
        ),

        _section("3. Operaciones de prevención y gestión", st),
        *_bullets([
            "Reutilización en obra de tierras y áridos limpios cuando sea "
            "técnicamente posible.",
            "Acopio selectivo en contenedores diferenciados para inertes, "
            "metálicos, madera y mezclados.",
            "Entrega de cada flujo a gestor autorizado con emisión de "
            "documento de identificación (DI) según RD 553/2020.",
            "Prohibición expresa de quema en obra y de vertido fuera de "
            "vertederos autorizados.",
        ], st),

        _section("4. Pliego de condiciones particulares", st),
        _para(
            "El contratista nombrará un responsable de RCD en obra, "
            "designará el área de acopio, controlará la trazabilidad "
            "documental hasta el gestor final y conservará los documentos "
            "durante al menos cinco años conforme al art. 5 del RD 105/2008.",
            st,
        ),

        _section("5. Presupuesto de gestión de RCD", st),
        _para(
            f"Se estima en el <b>{rcd_pct*100:.1f}% del PEM</b>, equivalente a "
            f"<b>{fmt_eur(rcd_importe)}</b>, e incluye alquiler y retirada "
            f"de contenedores, transporte y canon de vertedero / planta de "
            f"reciclaje.",
            st,
        ),
    ]
    return _build_doc(out_path, "PLAN DE GESTIÓN DE RCD", firm, ref, story)


# --------------------------------------------------------------------------
# 4. Plan de control de calidad (CTE)
# --------------------------------------------------------------------------

def build_control_calidad_pdf(out_path: pathlib.Path, firm: dict, meta: dict,
                               partidas: list[dict], totales: dict, ref: str,
                               project_title: str | None = None
                               ) -> pathlib.Path:
    st = _styles()
    title = project_title or meta.get("memoria", "Obra").replace(".md", "")

    materiales_rows = [
        ("Hormigón estructural",
         "EHE-08, UNE-EN 206-1",
         "Marcado CE, hoja de suministro, ensayos a 28 días según fck",
         "1 serie de 3 probetas por cada 100 m³ y/o 7 días"),
        ("Acero corrugado B500S",
         "EHE-08, UNE-EN 10080",
         "Marcado CE, certificado de garantía, ensayo de tracción",
         "1 ensayo por cada 40 t o lote suministrado"),
        ("Cemento",
         "RC-16, UNE-EN 197-1",
         "Marcado CE, hoja de suministro, control documental",
         "Recepción por lote"),
        ("Áridos",
         "EHE-08 art.28, UNE-EN 12620",
         "Marcado CE, granulometría, equivalente de arena",
         "Cada cambio de procedencia"),
        ("Ladrillo cerámico LH",
         "UNE-EN 771-1",
         "Marcado CE, dimensiones, absorción de agua",
         "1 ensayo por cada 50.000 ud o cambio de fabricante"),
        ("Yeso para enlucidos",
         "UNE-EN 13279-1",
         "Marcado CE, hoja de suministro",
         "Recepción por lote"),
        ("Aislantes térmicos",
         "CTE-DB-HE, UNE-EN 13162 / 13164",
         "Marcado CE, lambda declarada, espesor",
         "Recepción por lote / cambio de producto"),
        ("Impermeabilizantes",
         "UNE-EN 13707 / 13956",
         "Marcado CE, espesor, prueba de estanqueidad",
         "Recepción por lote / prueba de estanqueidad al finalizar"),
        ("Carpintería exterior",
         "CTE-DB-HE, UNE-EN 14351-1",
         "Marcado CE con prestaciones (U, permeabilidad, estanqueidad)",
         "Recepción por unidad"),
        ("Pavimentos cerámicos",
         "UNE-EN 14411",
         "Marcado CE, clase de uso (PEI/clase), antideslizante",
         "Recepción por lote"),
    ]
    mat_tbl = Table(
        [[Paragraph("<b>Material / sistema</b>", st["cell_b"]),
          Paragraph("<b>Normativa</b>", st["cell_b"]),
          Paragraph("<b>Control documental + recepción</b>", st["cell_b"]),
          Paragraph("<b>Frecuencia de ensayo</b>", st["cell_b"])]]
        + [[Paragraph(a, st["cell"]), Paragraph(b, st["cell"]),
            Paragraph(c, st["cell"]), Paragraph(d, st["cell"])]
           for a, b, c, d in materiales_rows],
        colWidths=[40 * mm, 36 * mm, 64 * mm, 46 * mm], repeatRows=1,
    )
    mat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BRAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
    ]))

    cc_pct = 0.010
    cc_importe = round(totales["PEM"] * cc_pct, 2)

    story: list = [
        _header_block(meta, firm, project_title, st),
        Spacer(1, 4),
        _title_row(title, st),
        Spacer(1, 8),
        Paragraph("PLAN DE CONTROL DE CALIDAD", st["title"]),
        _para(
            "Documento exigible por el <b>Código Técnico de la Edificación "
            "(CTE)</b>, RD 314/2006, art. 7 y por la EHE-08 para los "
            "elementos estructurales. Establece los controles documentales, "
            "de recepción y de ejecución que aseguran que los materiales y "
            "los sistemas instalados cumplen las prestaciones declaradas.",
            st,
        ),

        _section("1. Alcance y responsabilidades", st),
        _para(
            "Aplica a todos los materiales y unidades de obra recogidos en "
            "el presupuesto. La dirección facultativa designa el laboratorio "
            "de control acreditado por ENAC y supervisa la conformidad. "
            "El contratista facilita la documentación de cada material y "
            "asiste a la toma de muestras.",
            st,
        ),

        _section("2. Control por material / sistema", st),
        mat_tbl,

        _section("3. Control de ejecución", st),
        *_bullets([
            "Replanteo y geometría con tolerancias del CTE-DB-SE.",
            "Hormigón: control nivel normal salvo indicación expresa, "
            "consistencia, recubrimientos, juntas.",
            "Aceros: longitudes de anclaje y solapes según EHE-08.",
            "Albañilería: planeidad ≤ 5 mm en 2 m, aplomo ≤ 10 mm en 3 m.",
            "Solados: pendientes mínimas en zonas húmedas, planeidad ≤ 4 mm "
            "en 2 m.",
            "Carpintería: estanqueidad al agua y al aire según prestaciones "
            "declaradas en marcado CE.",
        ], st),

        _section("4. Documentación final", st),
        _para(
            "Al finalizar la obra se entregará a la dirección facultativa: "
            "(a) las hojas de suministro y declaraciones de prestaciones de "
            "cada material; (b) los resultados de los ensayos de laboratorio; "
            "(c) las actas de pruebas de servicio (estanqueidad, "
            "instalaciones); y (d) el certificado final firmado.",
            st,
        ),

        _section("5. Presupuesto del control de calidad", st),
        _para(
            f"Se estima en el <b>{cc_pct*100:.1f}% del PEM</b>, equivalente a "
            f"<b>{fmt_eur(cc_importe)}</b>. Incluye los ensayos de "
            f"laboratorio acreditado y la asistencia técnica en obra.",
            st,
        ),
    ]
    return _build_doc(out_path, "PLAN DE CONTROL DE CALIDAD", firm, ref, story)
