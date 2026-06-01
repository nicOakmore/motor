"""
run_demo.py — End-to-end demo for the Motor de Presupuestos.

Wires the pieces the way CLAUDE.md describes:

  memorias/  ─┐
              ├─→ ingesta (scope-item facts)
              │
  precios/   ─┴─→ ingesta (price facts)
                          │
                          ▼
                  load_rules(rules.json)
                          │
                          ▼
                    engine.run()  ← mapping + regulatory rules fire
                          │
                          ▼
            bind_prices_to_partidas()  ← uses concepto_to_price knowledge
                          │
                          ▼
                    engine.run()       ← any rules that depend on `partida`
                          │
                          ▼
              compute_presupuesto + compute_plan_acopios
                          │
                          ▼
                       salidas/

NOTE: this script lives at the ingest/render edge. It is allowed to do
non-deterministic things (parse text, look at filesystem). The deterministic
core (engine.py) is NEVER asked to do these things.

The price-binding step uses the `concepto_to_price` map from rules.json —
knowledge, not Python literals.
"""

from __future__ import annotations
import csv
import json
import pathlib
import re
import sys

import engine
import bc3
import client_pdfs
import regulatory_pdfs
import cuadros_precios


ROOT = pathlib.Path(__file__).parent
MEMORIAS = ROOT / "memorias"
PRECIOS = ROOT / "precios"
SALIDAS = ROOT / "salidas"


# --------------------------------------------------------------------------
# Ingesta — read the picked memoria and turn it into scope-item facts.
# In production this is the LLM step. Here we simulate it with a tiny parser
# that recognises the line items in the sample memorias the firm dropped.
# --------------------------------------------------------------------------

# Scope verbs: the opening word(s) of a numbered item determine the tipo.
# Tested in order — first match wins, so put more specific verbs first.
# Each tipo must exist in rules.json:concepto_metadata or the runner flags it.
SCOPE_VERBS: list[tuple[str, str]] = [
    # Demoliciones / actuaciones previas
    # Match against the whole item body, not only the head — anchors come
    # later in the routing logic. Default tabique demolition to LHD (the
    # conservative/expensive choice); LH7 only if explicitly stated.
    (r"demolici[oó]n\s+de\s+tabique\s+(?:de\s+)?(?:ladrillo\s+)?hueco\s+simple|demolici[oó]n\s+de\s+tabique\s+LH7", "demolicion_tabique_lh7"),
    (r"demolici[oó]n\s+de\s+tabique", "demolicion_tabique_lhd"),
    (r"demolici[oó]n\s+de\s+muro", "demolicion_muro_fabrica"),
    (r"levantado\s+de\s+solado|levantado\s+de\s+pavimento", "levantado_solado"),
    (r"levantado\s+de\s+alicatado|retirada\s+de\s+alicatado", "levantado_alicatado"),
    (r"desmontaje\s+de\s+carpinter[ií]a", "desmontaje_carpinteria"),
    (r"picado\s+(?:de\s+)?(?:enlucido|yeso)", "picado_enlucido"),
    (r"apertura\s+de\s+hueco", "apertura_hueco_tabique"),

    # Movimiento de tierras
    (r"excavaci[oó]n\s+(?:a\s+cielo\s+abierto|en\s+terreno)", "excavacion_cielo_abierto"),
    (r"excavaci[oó]n\s+(?:de\s+)?zanjas?", "excavacion_zanjas"),
    (r"relleno\s+(?:de\s+)?tierras?", "relleno_tierras"),
    (r"transporte\s+(?:de\s+)?tierras?|retirada\s+de\s+tierras", "transporte_tierras"),

    # Cimentación
    (r"horm?ig[oó]n\s+de\s+limpieza", "hormigon_limpieza"),
    (r"horm?ig[oó]n\s+armado\s+en\s+zapatas?", "hormigon_zapatas"),
    (r"horm?ig[oó]n\s+armado\s+en\s+losa", "hormigon_losa"),
    (r"solera\s+de\s+horm?ig[oó]n", "solera_hormigon"),
    (r"encofrado", "encofrado_muros"),
    (r"acero\s+(?:corrugado|B500)", "acero_corrugado"),

    # Estructura
    (r"forjado", "forjado_unidireccional"),
    (r"losa\s+maciza", "losa_maciza"),
    (r"pilar(?:es)?\s+(?:de\s+)?horm?ig[oó]n|horm?ig[oó]n\s+armado\s+en\s+pilares", "hormigon_pilares"),
    (r"viga\s+(?:de\s+)?horm?ig[oó]n", "viga_hormigon"),
    (r"acero\s+estructural|perfil(?:es)?\s+laminados?", "acero_estructural"),
    (r"escalera\s+(?:de\s+)?horm?ig[oó]n", "escalera_hormigon"),
    (r"refuerzo\s+(?:de\s+)?viga", "refuerzo_viga"),

    # Cubiertas
    (r"cubierta\s+plana\s+transitable", "cubierta_plana_transitable"),
    (r"cubierta\s+plana", "cubierta_plana_no_transitable"),
    (r"cubierta\s+(?:de\s+)?teja|cubierta\s+inclinada", "cubierta_teja_arabe"),
    (r"impermeabilizaci[oó]n\s+(?:con\s+)?(?:l[aá]mina\s+)?EPDM", "impermeabilizacion_epdm"),
    (r"canal[oó]n", "canalon_aluminio"),
    (r"bajante", "bajante_pvc"),

    # Albañilería (tabiques nuevos)
    (r"(?:ejecuci[oó]n\s+de\s+)?(?:nuevo\s+)?(?:tabique|tabiquer[ií]a)\s+(?:de\s+)?(?:placa\s+de\s+)?yeso\s+laminado|(?:tabique|tabiquer[ií]a)\s+pyl", "tabique_pyl"),
    (r"trasdosado", "trasdosado_pyl"),
    (r"(?:ejecuci[oó]n\s+de\s+)?(?:nuevo\s+)?tabique\s+(?:de\s+)?(?:ladrillo\s+)?hueco\s+(?:del\s+)?9|tabique\s+LH9", "tabique_lh9"),
    (r"(?:ejecuci[oó]n\s+de\s+)?(?:nuevo\s+)?tabique(?:r[ií]a)?", "tabique_lh7"),
    (r"cerramiento\s+(?:de\s+)?bloque", "cerramiento_bloque"),
    (r"cerramiento\s+(?:de\s+)?f[aá]brica", "cerramiento_fabrica_doble"),
    (r"albardilla", "albardilla_hormigon"),

    # Aislamientos / impermeabilizaciones
    (r"aislamiento\s+(?:t[eé]rmico\s+)?(?:de\s+)?xps", "aislamiento_xps"),
    (r"aislamiento\s+(?:de\s+)?lana\s+mineral", "aislamiento_lana_mineral"),
    (r"aislamiento\s+(?:de\s+)?poliuretano", "aislamiento_pur_proyectado"),
    (r"aislamiento(?:\s+t[eé]rmico)?", "aislamiento_lana_mineral"),
    (r"impermeabilizaci[oó]n\s+(?:con\s+)?l[aá]minas?\s+asf[aá]lticas?", "impermeabilizacion_sbs"),
    (r"impermeabilizaci[oó]n", "impermeabilizacion_sbs"),

    # Revestimientos
    (r"enlucido(?:\s+(?:de\s+)?yeso)?", "enlucido_yeso"),
    (r"guarnecido", "guarnecido_enlucido"),
    (r"mortero\s+monocapa", "mortero_monocapa"),
    (r"estuco", "estuco_veneciano"),
    (r"alicatado\s+(?:de\s+)?(?:azulejo|cer[aá]mico)", "alicatado_azulejo"),
    (r"alicatado(?:\s+(?:de\s+)?(?:gres\s+)?porcel[aá]nico)?", "alicatado_porcelanico"),
    (r"rodapi[eé]\s+(?:de\s+)?(?:madera|dm)", "rodapie_madera"),
    (r"rodapi[eé]", "rodapie_porcelanico"),
    (r"falso\s+techo\s+(?:continuo|de\s+pyl)", "falso_techo_continuo"),
    (r"falso\s+techo", "falso_techo_registrable"),

    # Pavimentos
    (r"solado\s+(?:de\s+)?(?:gres\s+)?porcel[aá]nico\s+80", "solado_porcelanico_80"),
    (r"solado\s+(?:de\s+)?(?:gres\s+)?porcel[aá]nico", "solado_porcelanico_60"),
    (r"tarima\s+(?:maciza|de\s+roble)", "tarima_maciza_roble"),
    (r"tarima(?:\s+(?:flotante|laminada))?", "tarima_laminada"),
    (r"microcemento", "microcemento"),
    (r"recrecido", "recrecido_mortero"),
    (r"baldosa\s+hidr[aá]ulica", "baldosa_hidraulica"),
    (r"solado", "solado_porcelanico_60"),

    # Carpintería
    (r"puerta\s+(?:de\s+)?entrada|puerta\s+acorazada", "puerta_entrada_acorazada"),
    (r"puerta\s+corredera", "puerta_corredera_empotrada"),
    (r"puerta\s+(?:doble\s+)?vidriera", "puerta_doble_vidriera"),
    (r"puerta(?:\s+interior)?", "puerta_interior_lacada"),
    (r"armario\s+empotrado", "armario_empotrado"),
    (r"ventana\s+(?:de\s+)?pvc", "ventana_pvc"),
    (r"ventana\s+corredera", "ventana_corredera_aluminio"),
    (r"ventana(?:\s+(?:de\s+)?aluminio)?", "ventana_aluminio_rpt"),
    (r"persiana", "persiana_pvc"),
    (r"mosquitera", "mosquitera_aluminio"),
    (r"encimera", "encimera_cocina_madera"),

    # Pintura
    (r"esmalte", "esmalte_sintetico"),
    (r"barniz", "barniz_carpinteria"),
    (r"pintura\s+(?:al\s+)?silicato|pintura\s+(?:de\s+)?fachada", "pintura_silicato_fachada"),
    (r"pintura\s+(?:pl[aá]stica\s+)?satinada|pintura\s+lavable", "pintura_plastica_satinada"),
    (r"pintura(?:\s+pl[aá]stica)?", "pintura_plastica_lisa"),

    # Instalaciones
    (r"punto\s+(?:de\s+)?luz\s+conmutado", "punto_luz_conmutado"),
    (r"punto\s+(?:de\s+)?luz", "punto_luz_simple"),
    (r"punto\s+(?:de\s+)?enchufe\s+25", "punto_enchufe_25a"),
    (r"punto\s+(?:de\s+)?enchufe", "punto_enchufe_16a"),
    (r"cuadro\s+(?:el[eé]ctrico|general)", "cuadro_general"),
    (r"punto\s+(?:de\s+)?tv|punto\s+(?:de\s+)?datos|rj45", "punto_tv_datos"),
    (r"canalizaci[oó]n", "canalizacion_corrugado"),

    (r"punto\s+(?:de\s+)?fontaner[ií]a\s+(?:para\s+)?(?:cocina|lavavajillas)", "punto_cocina"),
    (r"punto\s+(?:de\s+)?fontaner[ií]a\s+(?:para\s+)?ducha", "punto_ducha"),
    (r"punto\s+(?:de\s+)?fontaner[ií]a\s+(?:para\s+)?inodoro", "punto_inodoro"),
    (r"punto\s+(?:de\s+)?fontaner[ií]a", "punto_lavabo"),
    (r"lavabo", "lavabo_porcelana"),
    (r"inodoro", "inodoro_porcelana"),
    (r"plato\s+(?:de\s+)?ducha|ducha\s+(?:con\s+)?grifer[ií]a", "plato_ducha"),

    (r"red\s+(?:de\s+)?saneamiento\s+horizontal|saneamiento\s+horizontal", "saneamiento_horizontal_110"),
    (r"red\s+(?:de\s+)?saneamiento\s+vertical|saneamiento\s+vertical", "saneamiento_vertical_110"),
    (r"arqueta", "arqueta_paso"),
    (r"sumidero", "sumidero_terraza"),

    (r"split\s+(?:inverter\s+)?4500|split.*4\.?500", "split_inverter_4500"),
    (r"split", "split_inverter_2500"),
    (r"aerotermia", "aerotermia_bibloque"),
    (r"suelo\s+radiante", "suelo_radiante"),
    (r"extracci[oó]n\s+(?:de\s+)?ba[nñ]o|extractor\s+ba[nñ]o", "extraccion_bano"),

    # Urbanización
    (r"pavimento\s+(?:de\s+)?horm?ig[oó]n", "pavimento_hormigon_fratasado"),
    (r"bordillo", "bordillo_hormigon"),
    (r"adoqu[ií]n", "pavimento_adoquin"),
    (r"c[eé]sped", "cesped_artificial"),
    (r"plantaci[oó]n", "plantacion_arbusto"),
]

# Captures the measurement at the end of an item line. Units accepted:
# m², m³, m, ud / unidad(es), kg. The literal "m2"/"m3" forms are tolerated
# so the parser also reads memorias produced by software that ASCII-folds
# the superscripts.
MEASURE_RE = re.compile(
    r":\s*\*{0,2}\s*(\d+(?:[\.,]\d+)?)\s*\*{0,2}\s*"
    r"(m[²2³3]?|ud(?:es|s|)?|unidad(?:es)?|kg)\b",
    re.IGNORECASE,
)
# Numbered list item: starts with "N. " (after optional whitespace).
ITEM_RE = re.compile(r"^\s*\d+\.\s+(.*)", re.MULTILINE)
# Measurement-rule: huecos to deduct. Recognised forms (in parens after the
# measurement):  "(con 2 huecos de 1,8 m² cada uno)",  "(descontar 5,4 m² de
# huecos)",  "(huecos: 5,4 m²)".
HUECOS_MULTI_RE = re.compile(
    r"con\s+(\d+)\s+huecos?\s+(?:de\s+)?(\d+(?:[\.,]\d+)?)\s*m[²2]",
    re.IGNORECASE,
)
HUECOS_SUM_RE = re.compile(
    r"(?:descontar|huecos?)\s*:?\s*(\d+(?:[\.,]\d+)?)\s*m[²2]",
    re.IGNORECASE,
)


def _read_memoria_text(path: pathlib.Path,
                       max_pages: int = 30) -> str:
    """Return the memoria's text content. Supports .md / .txt directly,
    .pdf via pypdf (light, fast) with pdfplumber as a fallback.

    Page cap of `max_pages` keeps proyectos técnicos (which can run past
    200 pages) within the free-tier worker's memory budget. The project
    header — promotor, emplazamiento, suelo, type — always sits in the
    first 5-10 pages, so capping costs us no useful metadata.

    Other formats fall back to raw bytes decoded as UTF-8 (lossy).
    """
    suf = path.suffix.lower()
    if suf == ".pdf":
        # pypdf is ~30× faster than pdfplumber on COAC-style PDFs full of
        # vector-graphic paths, and crucially doesn't blow the worker's
        # heap. We use it as the primary extractor.
        try:
            import pypdf                                  # noqa: PLC0415
        except ImportError:
            pypdf = None
        if pypdf is not None:
            parts: list[str] = []
            try:
                reader = pypdf.PdfReader(str(path))
                for idx, page in enumerate(reader.pages):
                    if idx >= max_pages:
                        break
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:                     # noqa: BLE001
                        # Skip the page if it has a malformed object; the
                        # rest of the doc usually still parses.
                        continue
                return "\n".join(parts)
            except Exception:                             # noqa: BLE001
                # Fall through to pdfplumber if pypdf chokes on the doc.
                pass
        try:
            import pdfplumber                             # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Neither pypdf nor pdfplumber is installed."
            ) from exc
        parts = []
        with pdfplumber.open(str(path)) as pdf:
            for idx, page in enumerate(pdf.pages):
                if idx >= max_pages:
                    break
                try:
                    parts.append(page.extract_text() or "")
                except Exception:                         # noqa: BLE001
                    continue
                page.flush_cache()
        return "\n".join(parts)
    if suf in (".md", ".txt", ""):
        return path.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def parse_memoria(path: pathlib.Path) -> dict:
    """Return {meta:{...}, items:[{tipo,cantidad,unidad,capitulo}, ...]}.

    Line-based: each numbered item in 'Alcance de obra' is one scope-item.
    The verb at the start of the line decides the tipo; the trailing
    ': N m²' provides the medición. Words that appear inside descriptive
    text (e.g. 'paramentos enlucidos' inside a pintura line) do NOT count —
    only the leading verb does.

    Accepts Markdown / plain-text memorias and PDF memorias (the latter
    via pdfplumber — see _read_memoria_text).
    """
    text = _read_memoria_text(path)
    suelo = "urbano"
    if re.search(r"suelo\s*[:*]+[\s*]*r[uú]stico", text, re.IGNORECASE):
        suelo = "rustico"
    requiere_proyecto = bool(
        re.search(r"(?<!no\s)(?<!no\s\s)REQUIERE\s+PROYECTO\s+T[ÉE]CNICO",
                  text, re.IGNORECASE)
    )
    uso = "vivienda_habitual" if "vivienda habitual" in text.lower() else "otros"

    # Look for an explicit declaration of touristic use of the building.
    # Just the word "turístico" appears in CTE normative references (fire
    # safety for "establecimientos turísticos", etc.) regardless of project
    # type — too noisy on real Ibiza PDFs. Require a head-of-doc declaration
    # that qualifies USO / DESTINO / VIVIENDA as touristic.
    HEAD_LEN = 6000
    text_l = text.lower()
    head = text_l[:HEAD_LEN]
    uso_turistico = bool(re.search(
        r"\b(?:uso|destino|fin)\s+tur[ií]stic[oa]\b"
        r"|\balquiler\s+(?:tur[ií]stico|vacacional|de\s+temporada)\b"
        r"|\bvivienda\s+tur[ií]stica\b"
        r"|\b(?:ETV|estancias?\s+tur[ií]sticas?\s+en\s+viviendas?)\b",
        head,
    ))

    # --- Auto-detect requiere_proyecto from prose. ---
    # The explicit markdown phrase "REQUIERE PROYECTO TÉCNICO" (without a
    # leading "no") sets it above. As a fallback, the title-page patterns
    # "PROYECTO BÁSICO", "PROYECTO DE EJECUCIÓN", "PROYECTO TÉCNICO" are
    # strong evidence too — documents only exist because the work requires
    # a proyecto técnico under LOE 38/1999.
    #
    # Critically: we first scan for an explicit OPT-OUT ("no requiere
    # proyecto técnico", "sin proyecto técnico"). When present, the auto-
    # detect is suppressed — markdown samples sometimes mention "proyecto
    # técnico" inside a "no requiere..." clause.
    head_text = text[:HEAD_LEN]
    head_no_accent = head_text.upper()
    has_opt_out = bool(re.search(
        r"\bNO\s+REQUIERE\s+PROYECTO\b"
        r"|\bSIN\s+PROYECTO\s+T[ÉE]CNICO\b"
        r"|\bNO\s+ES\s+NECESARIO\s+PROYECTO\b",
        head_no_accent,
    ))
    if not requiere_proyecto and not has_opt_out:
        if re.search(
            r"\bPROYECTO\s+(?:B[ÁA]SICO(?:\s+Y\s+DE\s+EJECUCI[ÓO]N)?"
            r"|DE\s+EJECUCI[ÓO]N|T[ÉE]CNICO)\b",
            head_no_accent,
        ):
            requiere_proyecto = True

    # --- Auto-detect suelo from prose. ---
    # Real PDFs rarely use the markdown "**Suelo:** **rústico**" syntax.
    # Recognise explicit declarations (suelo rústico / urbano / urbanizable)
    # plus strong Ibiza/Balearic signals: SRC = Suelo Rústico Común, ANEI,
    # ARIP (Áreas Naturales / Rural de Interés Paisajístico), and the
    # "polígono X parcela Y" pattern that's the cadastral identifier of
    # rural land in Spain.
    suelo_auto = None
    if any(p in head for p in (
        "suelo rústico", "suelo rustico", "suelo rústico común",
        "rústico común", "rustico comun", "anei", "arip",
    )) or re.search(r"\b(?:SRC|SRP)\b", head_no_accent):
        suelo_auto = "rustico"
    elif re.search(
        r"pol[ií]gono\s+\d+[,.\s]*parcelas?\s+\d",
        head, re.IGNORECASE,
    ):
        suelo_auto = "rustico"
    elif any(p in head for p in (
        "suelo urbano consolidado", "suelo urbano", "urbano consolidado",
    )) or re.search(r"\b(?:SU|SUC|SU-NC|SUNC)\b", head_no_accent):
        suelo_auto = "urbano"
    if suelo_auto is not None and suelo == "urbano":
        suelo = suelo_auto

    # Real proyectos run to hundreds of pages and reuse the same labels in
    # legal clauses ("…el promotor: a las normas…"). Bias the search to the
    # title-page region (first ~12 pages, ~10 000 chars). Values may live on
    # the line after the label (Porreres-style layout) so the regex tolerates
    # newlines between colon and value.
    HEADER_LEN = 10_000
    header = text[:HEADER_LEN]

    def _grab(labels: list[str]) -> str:
        # Two-pass: prefer the ALL-CAPS form (title-page convention),
        # then fall back to case-insensitive. The Spanish plural for words
        # ending in consonant adds -ES (Promotor → Promotores).
        def _clean(v: str) -> str:
            return re.sub(r"^[*_`\s]+|[*_`\s]+$", "", v).strip(" .,:")
        for label in labels:
            m = re.search(
                rf"\b{label.upper()}(?:ES|S)?\b\s*:\s*([^\n\r]+)",
                header,
            )
            if m:
                val = _clean(m.group(1))
                if val and len(val) < 140:
                    return val
        for label in labels:
            m = re.search(
                rf"\b{label}(?:es|s)?\b\s*:\s*([^\n\r]+)",
                header, re.IGNORECASE,
            )
            if m:
                val = _clean(m.group(1))
                if val and len(val) < 140 and not val.lower().startswith(
                    ("a las ", "el ", "la ", "los ", "las ", "que ", "una ", "un ")
                ):
                    return val
        return ""

    promotor = _grab(["Promotor", "Cliente", "Propiedad", "Titular"])
    emplazamiento = _grab(["Emplazamiento", "Ubicación", "Ubicacion",
                            "Situación", "Situacion",
                            "Dirección de obra", "Dirección"])

    # --- Address fallback for label-less PDF layouts ---
    # When no EMPLAZAMIENTO/UBICACIÓN label is present, try common Spanish
    # address signatures in the title region:
    #   1) Postal code + town  →  "07820 SAN ANTONIO"  /  "07800 IBIZA"
    #   2) Polígono / parcelas →  "POLÍGONO 1, PARCELAS 143-182-183"
    if not emplazamiento:
        m = re.search(
            r"\b(0[6-7]\d{3})\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚáéíóúñ \-.,]{2,60})",
            header,
        )
        if m:
            emplazamiento = (m.group(1) + " " + m.group(2)).strip(" .,")
    if not emplazamiento:
        m = re.search(
            r"pol[ií]gono\s+\d+[,.\s]*parcelas?\s+[\d\-,\s]{1,40}",
            header, re.IGNORECASE,
        )
        if m:
            emplazamiento = m.group(0).strip(" .,")

    # Walk every numbered list item, joining any soft-wrapped continuation
    # lines that belong to the same item. PDF text extraction frequently
    # wraps long items mid-sentence; we need the measurement that lands on
    # the second line ("…dormitorio secundario del / pasillo: 40 m²") to
    # be visible to the regex below.
    starts = [m.start() for m in re.finditer(r"^\s*\d+\.\s+", text, re.MULTILINE)]
    item_bodies: list[str] = []
    if starts:
        boundaries = starts + [len(text)]
        for s, e in zip(boundaries[:-1], boundaries[1:]):
            block = text[s:e].rstrip()
            block = re.sub(r"^\s*\d+\.\s+", "", block, count=1)
            # Collapse soft-wrap newlines to spaces, preserve hard breaks
            # between numbered items (already handled by slicing).
            block = re.sub(r"\s*\n\s*", " ", block)
            item_bodies.append(block)

    # Second-pass fallback: when no numbered list was found (typical of
    # narrative PDFs of real proyectos técnicos), scan paragraph by
    # paragraph for sentences that start with a known scope verb and end
    # in "<number> m²" / "ud" / etc. This catches the rare real memoria
    # that DOES note dimensions inline, without giving us hallucinations
    # from CTE references that mention "altura 2,40 m".
    if not item_bodies:
        for para in re.split(r"\n\s*\n", text):
            para_clean = " ".join(para.split())
            if len(para_clean) < 20 or len(para_clean) > 400:
                continue
            head_lc = para_clean.lower()
            for pat, _t in SCOPE_VERBS:
                if not re.match(rf"^{pat}\b", head_lc, re.IGNORECASE):
                    continue
                if MEASURE_RE.search(para_clean):
                    item_bodies.append(para_clean)
                break

    items = []
    for body in item_bodies:
        # strip markdown emphasis; whole-body search so qualifiers that follow
        # the measurement (e.g. "12 m² de tabique de ladrillo hueco doble")
        # still influence routing.
        body_clean = re.sub(r"[*_`]", " ", body).strip()
        head = body_clean.lower()
        measure_match = MEASURE_RE.search(body)
        if measure_match is None:
            continue
        cantidad = float(measure_match.group(1).replace(",", "."))

        # Measurement rule: subtract huecos. Two notations supported (see
        # HUECOS_*_RE). We search the body AFTER the measurement so the
        # original total stays in the parser even when the deduction is
        # noted parenthetically.
        deduccion = 0.0
        post = body_clean[measure_match.end():]
        m = HUECOS_MULTI_RE.search(post)
        if m:
            deduccion = int(m.group(1)) * float(m.group(2).replace(",", "."))
        else:
            m = HUECOS_SUM_RE.search(post)
            if m:
                deduccion = float(m.group(1).replace(",", "."))
        cantidad_final = max(0.0, cantidad - deduccion)

        tipo = None
        for pat, t in SCOPE_VERBS:
            if re.match(rf"^{pat}\b", head, re.IGNORECASE):
                tipo = t
                break
        if tipo is None:
            continue
        # Normalise the captured unit token to the catalogue's canonical form.
        raw_unit = (measure_match.group(2) or "").lower()
        if raw_unit in ("m²", "m2"):
            unidad = "m2"
        elif raw_unit in ("m³", "m3"):
            unidad = "m3"
        elif raw_unit.startswith("ud") or raw_unit.startswith("unidad"):
            unidad = "ud"
        elif raw_unit == "kg":
            unidad = "kg"
        elif raw_unit == "m":
            unidad = "m"
        else:
            unidad = "m2"
        items.append({
            "tipo": tipo, "cantidad": cantidad_final, "unidad": unidad,
            "cantidad_bruta": cantidad, "deduccion_huecos": round(deduccion, 2),
        })
    # Derived flags for regulatory rules (must be present on project-meta so
    # the engine can filter on them). Computed from the parsed scope-items.
    tipos = {it["tipo"] for it in items}
    incluye_demoliciones = any(
        t.startswith(("demolicion_", "excavacion_", "transporte_tierras",
                       "levantado_", "picado_"))
        for t in tipos
    )
    toca_envolvente = any(
        t.startswith(("cubierta_", "cerramiento_", "mortero_monocapa",
                       "aislamiento_", "impermeabilizacion_",
                       "ventana_", "puerta_entrada"))
        for t in tipos
    )

    return {
        "meta": {
            "memoria": path.name,
            "suelo": suelo,
            "requiere_proyecto": requiere_proyecto,
            "uso": uso,
            "uso_turistico": uso_turistico,
            "incluye_demoliciones": incluye_demoliciones,
            "toca_envolvente": toca_envolvente,
            "promotor": promotor,
            "emplazamiento": emplazamiento,
        },
        "items": items,
    }


CATALOGUE_OVERRIDE_PATH = pathlib.Path("/tmp/precios_override.csv")


def load_price_catalogue() -> list[dict]:
    """Read every CSV in ./precios/ as price rows. If the admin has uploaded
    or fetched a custom catalogue, it lives at /tmp/precios_override.csv
    (Render's ephemeral disk) and takes precedence over the bundled
    catalogue for the current process lifetime.

    BC3/XLSX/PDF would plug in here too — for the demo only CSV is wired.
    """
    prices = []
    # Override (uploaded / fetched) wins when present.
    if CATALOGUE_OVERRIDE_PATH.exists():
        with CATALOGUE_OVERRIDE_PATH.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    row["precio_unitario"] = float(row.get("precio_unitario", 0) or 0)
                except (TypeError, ValueError):
                    row["precio_unitario"] = 0.0
                prices.append(row)
        if prices:
            return prices

    for csv_path in sorted(PRECIOS.glob("precios_*.csv")):
        with csv_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                row["precio_unitario"] = float(row["precio_unitario"])
                prices.append(row)
    return prices


def load_material_lines() -> list[dict]:
    rows = []
    path = PRECIOS / "materiales_unitarios.csv"
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row["cantidad_por_partida"] = float(row["cantidad_por_partida"])
            row["merma_pct"] = float(row["merma_pct"])
            rows.append(row)
    return rows


def load_descompuestos() -> dict[str, list[dict]]:
    """Load precios/descompuestos.csv, return {partida_code: [rows]}.
    Each row carries the labor/material/machinery breakdown for cuadro Nº 2.
    The descripción is joined from the master labor / materials / machinery
    catalogues so the renderer can show human-readable component names."""
    out: dict[str, list[dict]] = {}
    desc_path = PRECIOS / "descompuestos.csv"
    if not desc_path.exists():
        return out

    def _load_master(name: str, key: str) -> dict[str, dict]:
        p = PRECIOS / name
        d: dict[str, dict] = {}
        if not p.exists():
            return d
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                d[r[key]] = r
        return d

    labor    = _load_master("labor.csv",     "code")
    material = _load_master("materials.csv", "code")
    maquin   = _load_master("machinery.csv", "code")

    with desc_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            slot = row["slot"]
            code = row["comp_code"]
            master = (labor if slot == "mo"
                      else maquin if slot == "maq"
                      else material)
            descripcion = (master.get(code, {}).get("descripcion") or code)
            entry = {
                "slot": slot,
                "comp_code": code,
                "descripcion": descripcion,
                "unidad": row.get("unidad") or "",
                "rendimiento": float(row.get("rendimiento") or 0),
                "precio_unitario": float(row.get("precio_unitario") or 0),
                "importe": float(row.get("importe") or 0),
            }
            out.setdefault(row["partida_code"], []).append(entry)
    return out


# --------------------------------------------------------------------------
# Knowledge bridge — concept → price code, ámbito priority. Read from rules.json
# so it stays editable knowledge, not Python.
# --------------------------------------------------------------------------

def bind_prices_to_partidas(wm: engine.WorkingMemory, rules_spec: dict) -> None:
    """For every `partida-pendiente`, find the price by concept→code map and
    the ámbito priority, then assert a fully-priced `partida` fact."""
    metadata = rules_spec.get("concepto_metadata", {})
    concept_to_code = {k: v["price_code"] for k, v in metadata.items()
                       if isinstance(v, dict) and v.get("price_code")}
    for k, v in rules_spec.get("concepto_to_price", {}).items():
        if not k.startswith("_"):
            concept_to_code.setdefault(k, v)
    priority = (rules_spec.get("parameters", {})
                          .get("ambito_precios_prioridad", ["local"]))
    descompuestos = load_descompuestos()

    prices_by_code: dict[str, list[engine.Fact]] = {}
    for p in wm.query("price"):
        prices_by_code.setdefault(p["code"], []).append(p)

    def best_price(code: str) -> engine.Fact | None:
        candidates = prices_by_code.get(code, [])
        if not candidates:
            return None
        def rank(pf: engine.Fact) -> tuple:
            amb = pf.get("ambito", "")
            idx = priority.index(amb) if amb in priority else len(priority)
            fecha = pf.get("fecha", "0000-00-00")
            return (idx, -ord(fecha[0]) if fecha else 0)
        return sorted(candidates, key=rank)[0]

    counter = 0
    for pp in wm.query("partida-pendiente"):
        concepto = pp["concepto"]
        code = concept_to_code.get(concepto)
        if code is None:
            wm.assert_fact("flag", {
                "nivel": "WARN", "codigo": "PRECIO_NO_MAPEADO",
                "mensaje": f"No hay código de precio para el concepto '{concepto}'. Añade una entrada en concepto_to_price."
            }, produced_by="bind_prices_to_partidas")
            continue
        price = best_price(code)
        if price is None:
            wm.assert_fact("flag", {
                "nivel": "WARN", "codigo": "PRECIO_NO_DISPONIBLE",
                "mensaje": f"Código '{code}' no encontrado en el catálogo (concepto '{concepto}')."
            }, produced_by="bind_prices_to_partidas")
            continue

        counter += 1
        medicion = float(pp["medicion"])
        pu = float(price["precio_unitario"])
        # Carry mo/mat/maq/indirectos forward so the cuadro de precios nº 2
        # (descompuesto) can render without re-reading the catalogue.
        mo  = float(price.get("mo")  or 0.0)
        mat = float(price.get("mat") or 0.0)
        maq = float(price.get("maq") or 0.0)
        indir = float(price.get("indirectos_pct") or 0.0)
        partida_data = {
            "code": f"P{counter:03d}",
            "capitulo": pp["capitulo"],
            "descripcion": price["descripcion"],
            "unidad": pp["unidad"],
            "medicion": medicion,
            "precio_unitario": pu,
            "importe": round(medicion * pu, 2),
            "mo_pu": mo, "mat_pu": mat, "maq_pu": maq,
            "indirectos_pct": indir,
            "price_ref": code,
            "scope_ref": pp.get("scope_ref"),
        }
        comp_rows = descompuestos.get(code)
        if comp_rows:
            partida_data["descompuesto"] = comp_rows
        wm.assert_fact("partida", partida_data,
                       produced_by="bind_prices_to_partidas")


def explode_material_lines(wm: engine.WorkingMemory, materials: list[dict]) -> None:
    """For each priced partida, generate material-line facts from the
    per-partida material ratios in materiales_unitarios.csv."""
    by_partida_code = {}
    for m in materials:
        by_partida_code.setdefault(m["partida_code"], []).append(m)

    for partida in wm.query("partida"):
        for m in by_partida_code.get(partida.get("price_ref"), []):
            wm.assert_fact("material-line", {
                "material_code": m["material_code"],
                "descripcion": m["descripcion"],
                "unidad": m["unidad"],
                "cantidad": float(partida["medicion"]) * m["cantidad_por_partida"],
                "merma_pct": m["merma_pct"],
                "partida_ref": partida["code"],
            }, produced_by="explode_material_lines")


# --------------------------------------------------------------------------
# Render — produce the artefacts the firm consumes.
# --------------------------------------------------------------------------

def fmt_eur(n: float) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def render_presupuesto(wm: engine.WorkingMemory, totales: dict, meta: dict,
                       capitulo_orden: list[str]) -> str:
    partidas = [p.data for p in wm.query("partida")]
    by_cap: dict[str, list[dict]] = {}
    for p in partidas:
        by_cap.setdefault(p["capitulo"], []).append(p)

    out = []
    out.append(f"# Presupuesto — {meta.get('memoria','(sin nombre)')}")
    out.append("")
    out.append(f"- Suelo: **{meta.get('suelo')}**")
    out.append(f"- Uso: **{meta.get('uso')}**")
    out.append(f"- Proyecto técnico: **{'sí' if meta.get('requiere_proyecto') else 'no'}**")
    out.append("")

    ordered_caps = [c for c in capitulo_orden if c in by_cap] + \
                   [c for c in by_cap if c not in capitulo_orden]

    for cap in ordered_caps:
        out.append(f"## Capítulo — {cap}")
        out.append("")
        out.append("| Code | Descripción | Ud | Medición | Precio ud | Importe |")
        out.append("|------|-------------|----|---------:|----------:|--------:|")
        subtotal = 0.0
        for p in by_cap[cap]:
            subtotal += p["importe"]
            out.append(
                f"| {p['code']} | {p['descripcion']} | {p['unidad']} | "
                f"{p['medicion']:.2f} | {fmt_eur(p['precio_unitario'])} | "
                f"{fmt_eur(p['importe'])} |"
            )
        out.append(f"| | | | | **Subtotal** | **{fmt_eur(subtotal)}** |")
        out.append("")

    out.append("## Cuadro resumen (RD 1098/2001)")
    out.append("")
    out.append("| Concepto | Importe |")
    out.append("|----------|--------:|")
    out.append(f"| PEM (Presupuesto de Ejecución Material) | {fmt_eur(totales['PEM'])} |")
    out.append(f"| Gastos Generales ({totales['gg_pct']*100:.0f}%) | {fmt_eur(totales['GG'])} |")
    out.append(f"| Beneficio Industrial ({totales['bi_pct']*100:.0f}%) | {fmt_eur(totales['BI'])} |")
    out.append(f"| **PEC (Presupuesto de Ejecución por Contrata)** | **{fmt_eur(totales['PEC'])}** |")
    out.append(f"| IVA ({totales['iva_pct']*100:.0f}%) | {fmt_eur(totales['IVA'])} |")
    out.append(f"| **TOTAL** | **{fmt_eur(totales['TOTAL'])}** |")
    out.append(f"| ICIO (orientativo, sobre PEM) | {fmt_eur(totales['ICIO'])} |")
    return "\n".join(out) + "\n"


def render_flags(wm: engine.WorkingMemory) -> str:
    flags = [f.data | {"rule": f.produced_by} for f in wm.query("flag")]
    order = {"STOP": 0, "WARN": 1, "INFO": 2}
    flags.sort(key=lambda f: order.get(f.get("nivel", "INFO"), 3))
    out = ["# Checklist regulatorio", ""]
    if not flags:
        out.append("_Sin banderas levantadas._")
        return "\n".join(out) + "\n"
    for f in flags:
        out.append(f"## [{f['nivel']}] {f['codigo']}")
        out.append(f"- Regla origen: `{f['rule']}`")
        out.append(f"- {f['mensaje']}")
        out.append("")
    return "\n".join(out) + "\n"


def render_acopios_csv(plan: list[dict]) -> str:
    out = ["material_code,descripcion,unidad,cantidad"]
    for row in plan:
        out.append(f"{row['material_code']},\"{row['descripcion']}\","
                   f"{row['unidad']},{row['cantidad']}")
    return "\n".join(out) + "\n"


def render_trace(wm: engine.WorkingMemory) -> str:
    """Provenance dump: every fact + the rule that produced it."""
    out = ["# Fact trace (provenance)", "",
           "| # | Kind | produced_by | Data |",
           "|---|------|-------------|------|"]
    for f in wm.all():
        if f.kind == "_fired":
            continue
        data = json.dumps(f.data, ensure_ascii=False)
        if len(data) > 120:
            data = data[:117] + "..."
        out.append(f"| {f._id} | `{f.kind}` | `{f.produced_by}` | `{data}` |")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def write_artefacts(out_dir: pathlib.Path,
                    meta: dict,
                    partidas: list[dict],
                    totales: dict,
                    flags: list[dict],
                    acopios: list[dict],
                    trace_rows: list[dict],
                    rules_spec: dict,
                    project_title: str | None = None) -> dict:
    """Write every output artefact from a final partida set.

    Pure rendering — no engine inference. Used both by the initial
    pipeline (after the engine fires) and by the editor's save handler
    (after the user overrides partidas). Returns a manifest dict.
    """
    import hashlib, datetime as _dt
    out_dir.mkdir(parents=True, exist_ok=True)

    capitulos = rules_spec.get("capitulo_orden", [])
    firm = rules_spec.get("firm", {})
    festivos_raw = rules_spec.get("festivos", {}).get("dias", [])
    festivos = [_dt.date.fromisoformat(s) for s in festivos_raw]
    duraciones = {k: v for k, v in
                  rules_spec.get("duracion_capitulo_dias", {}).items()
                  if not k.startswith("_")}

    h = hashlib.sha1(
        f"{meta.get('memoria','')}-{totales['PEM']:.2f}".encode("utf-8")
    ).hexdigest()[:6].upper()
    ref = f"{firm.get('ref_series', _dt.date.today().year)}.{h}"

    # Markdown + JSON for programmatic / dev use
    md = _render_presupuesto_md(meta, totales, partidas, capitulos)
    (out_dir / "presupuesto.md").write_text(md, encoding="utf-8")
    (out_dir / "presupuesto.json").write_text(
        json.dumps({"meta": meta, "totales": totales, "partidas": partidas},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "plan_acopios.csv").write_text(
        render_acopios_csv(acopios), encoding="utf-8")
    (out_dir / "flags.md").write_text(
        _render_flags_md(flags), encoding="utf-8")
    if trace_rows:
        (out_dir / "traza.md").write_text(
            _render_trace_md(trace_rows), encoding="utf-8")

    bc3_text = bc3.write_bc3(partidas, programa="MotorPresupuestos")
    # FIEBDC-3 uses Windows-1252 (CP1252) — covers em-dash, smart quotes,
    # bullets, etc. that real Spanish memorias contain. Strict latin-1
    # rejects all of those.
    (out_dir / "presupuesto.bc3").write_text(
        bc3_text, encoding="cp1252", errors="replace")

    client_pdfs.build_presupuesto_pdf(
        out_dir / "presupuesto_cliente.pdf",
        firm=firm, meta=meta, totales=totales,
        partidas=partidas, capitulo_orden=capitulos, ref=ref,
        project_title=project_title,
    )
    client_pdfs.build_plan_obra_pdf(
        out_dir / "plan_de_obra.pdf",
        firm=firm, meta=meta, partidas=partidas,
        duracion_dias=duraciones, capitulo_orden=capitulos, ref=ref,
        festivos=festivos, project_title=project_title,
    )

    # Cuadros de precios — always emitted; complement the budget.
    cuadros_precios.build_cuadro_nro1_pdf(
        out_dir / "cuadro_precios_nro1.pdf",
        firm=firm, meta=meta, partidas=partidas, ref=ref,
        project_title=project_title,
    )
    cuadros_precios.build_cuadro_nro2_pdf(
        out_dir / "cuadro_precios_nro2.pdf",
        firm=firm, meta=meta, partidas=partidas, ref=ref,
        project_title=project_title,
    )

    # Mandatory regulatory annexes, only when a proyecto técnico applies
    # (LOE 38/1999 + LUIB 12/2017 art.146).
    if meta.get("requiere_proyecto"):
        regulatory_pdfs.build_pliego_condiciones_pdf(
            out_dir / "pliego_condiciones.pdf",
            firm=firm, meta=meta, partidas=partidas, totales=totales,
            ref=ref, project_title=project_title,
        )
        regulatory_pdfs.build_ess_pdf(
            out_dir / "estudio_seguridad_salud.pdf",
            firm=firm, meta=meta, partidas=partidas, totales=totales,
            ref=ref, project_title=project_title,
        )
        regulatory_pdfs.build_rcd_pdf(
            out_dir / "plan_gestion_rcd.pdf",
            firm=firm, meta=meta, partidas=partidas, totales=totales,
            ref=ref, project_title=project_title,
        )
        regulatory_pdfs.build_control_calidad_pdf(
            out_dir / "plan_control_calidad.pdf",
            firm=firm, meta=meta, partidas=partidas, totales=totales,
            ref=ref, project_title=project_title,
        )

    return {
        "ref": ref,
        "meta": meta,
        "totales": totales,
        "partidas": partidas,
        "flags": flags,
        "acopios": acopios,
    }


def _render_presupuesto_md(meta: dict, totales: dict,
                            partidas: list[dict], capitulo_orden: list[str]) -> str:
    by_cap: dict[str, list[dict]] = {}
    for p in partidas:
        by_cap.setdefault(p["capitulo"], []).append(p)
    out = []
    out.append(f"# Presupuesto — {meta.get('memoria','(sin nombre)')}")
    out.append("")
    out.append(f"- Suelo: **{meta.get('suelo')}**")
    out.append(f"- Uso: **{meta.get('uso')}**")
    out.append(f"- Proyecto técnico: **{'sí' if meta.get('requiere_proyecto') else 'no'}**")
    out.append("")
    ordered = [c for c in capitulo_orden if c in by_cap] + \
              [c for c in by_cap if c not in capitulo_orden]
    for cap in ordered:
        out.append(f"## Capítulo — {cap}")
        out.append("")
        out.append("| Code | Descripción | Ud | Medición | Precio ud | Importe |")
        out.append("|------|-------------|----|---------:|----------:|--------:|")
        subtotal = 0.0
        for p in by_cap[cap]:
            subtotal += float(p["importe"])
            out.append(
                f"| {p['code']} | {p['descripcion']} | {p['unidad']} | "
                f"{float(p['medicion']):.2f} | {fmt_eur(float(p['precio_unitario']))} | "
                f"{fmt_eur(float(p['importe']))} |"
            )
        out.append(f"| | | | | **Subtotal** | **{fmt_eur(subtotal)}** |")
        out.append("")
    out.append("## Cuadro resumen (RD 1098/2001)")
    out.append("")
    out.append("| Concepto | Importe |")
    out.append("|----------|--------:|")
    out.append(f"| PEM | {fmt_eur(totales['PEM'])} |")
    out.append(f"| GG ({totales['gg_pct']*100:.0f}%) | {fmt_eur(totales['GG'])} |")
    out.append(f"| BI ({totales['bi_pct']*100:.0f}%) | {fmt_eur(totales['BI'])} |")
    out.append(f"| **PEC** | **{fmt_eur(totales['PEC'])}** |")
    for label, val in totales.get("iva_breakdown", []) or [(f"IVA ({totales['iva_pct']*100:.0f}%)", totales['IVA'])]:
        out.append(f"| {label} | {fmt_eur(val)} |")
    if totales.get("RETENCION"):
        out.append(f"| Retención IRPF ({totales['retencion_pct']*100:.1f}%) | -{fmt_eur(totales['RETENCION'])} |")
    if totales.get("RECARGO_EQUIV"):
        out.append(f"| Recargo de equivalencia ({totales['recargo_pct']*100:.2f}%) | {fmt_eur(totales['RECARGO_EQUIV'])} |")
    out.append(f"| **TOTAL** | **{fmt_eur(totales['TOTAL'])}** |")
    out.append(f"| ICIO (orientativo, sobre PEM) | {fmt_eur(totales['ICIO'])} |")
    return "\n".join(out) + "\n"


def _render_flags_md(flags: list[dict]) -> str:
    order = {"STOP": 0, "WARN": 1, "INFO": 2}
    flags = sorted(flags, key=lambda f: order.get(f.get("nivel", "INFO"), 3))
    out = ["# Checklist regulatorio", ""]
    if not flags:
        out.append("_Sin banderas levantadas._")
        return "\n".join(out) + "\n"
    for f in flags:
        out.append(f"## [{f['nivel']}] {f['codigo']}")
        if f.get("rule"):
            out.append(f"- Regla origen: `{f['rule']}`")
        out.append(f"- {f['mensaje']}")
        out.append("")
    return "\n".join(out) + "\n"


def _render_trace_md(trace_rows: list[dict]) -> str:
    out = ["# Traza de hechos (provenance)", "",
           "| # | Kind | produced_by | Data |",
           "|---|------|-------------|------|"]
    for f in trace_rows:
        if f.get("kind") == "_fired":
            continue
        data = json.dumps(f.get("data", {}), ensure_ascii=False)
        if len(data) > 120:
            data = data[:117] + "..."
        out.append(f"| {f.get('id','?')} | `{f.get('kind','')}` | `{f.get('produced_by','')}` | `{data}` |")
    return "\n".join(out) + "\n"


def rerun_with_extra_scope_items(memoria_path: pathlib.Path,
                                 extra_items: list[dict],
                                 out_root: pathlib.Path,
                                 rules_spec: dict) -> dict:
    """Re-run the full pipeline for a memoria, adding the LLM-proposed
    scope items on top of whatever the deterministic parser found.

    The LLM proposals enter the SAME path real scope-items do — they get
    routed through concepto_metadata, priced from the catalogue and
    booked into the engine alongside the parser's items. Deterministic
    from there on: the LLM never asserts a partida directly."""
    wm = engine.WorkingMemory()
    eng = engine.Engine(wm)
    engine.load_rules(str(ROOT / "rules.json"), eng)

    parsed = parse_memoria(memoria_path)

    wm.assert_fact("project-meta", {
        "memoria": parsed["meta"]["memoria"],
        "suelo": parsed["meta"]["suelo"],
        "requiere_proyecto": parsed["meta"]["requiere_proyecto"],
        "uso": parsed["meta"]["uso"],
        "uso_turistico": parsed["meta"].get("uso_turistico", False),
        "incluye_demoliciones": parsed["meta"].get("incluye_demoliciones", False),
        "toca_envolvente": parsed["meta"].get("toca_envolvente", False),
    }, produced_by="ingesta_memoria")

    metadata = rules_spec.get("concepto_metadata", {})
    all_items = list(parsed["items"])
    # LLM proposals are tagged with their provenance so the trace remains
    # auditable; the engine doesn't distinguish, but humans reading
    # traza.md can.
    for it in extra_items:
        tipo = it.get("tipo")
        if not tipo or tipo not in metadata:
            continue
        all_items.append({
            "tipo": tipo,
            "cantidad": float(it.get("cantidad") or 0),
            "unidad": (it.get("unidad") or
                       metadata[tipo].get("unidad") or "ud"),
            "_provenance": "llm",
        })

    for i, item in enumerate(all_items, start=1):
        meta_entry = metadata.get(item["tipo"], {})
        produced_by = ("ingesta_llm" if item.get("_provenance") == "llm"
                        else "ingesta_memoria")
        wm.assert_fact("scope-item", {
            "id": f"S{i:03d}",
            "descripcion": meta_entry.get("descripcion_corta", item["tipo"]),
            "tipo": item["tipo"],
            "capitulo": meta_entry.get("capitulo", "Sin capítulo"),
            "cantidad": item["cantidad"],
            "unidad": meta_entry.get("unidad", item["unidad"]),
        }, produced_by=produced_by)
        wm.assert_fact("partida-pendiente", {
            "capitulo": meta_entry.get("capitulo", "Sin capítulo"),
            "concepto": item["tipo"],
            "medicion": item["cantidad"],
            "unidad": meta_entry.get("unidad", item["unidad"]),
            "scope_ref": f"S{i:03d}",
        }, produced_by=produced_by)

    for price in load_price_catalogue():
        for k in ("mo", "mat", "maq", "indirectos_pct"):
            try:
                price[k] = float(price.get(k) or 0.0)
            except (TypeError, ValueError):
                price[k] = 0.0
        wm.assert_fact("price", price, produced_by="ingesta_precios")

    eng.run()
    bind_prices_to_partidas(wm, rules_spec)
    explode_material_lines(wm, load_material_lines())
    eng.run()

    totales = engine.compute_presupuesto(wm)
    plan = engine.compute_plan_acopios(wm)
    flags = [f.data for f in wm.query("flag")]
    flags_with_rule = [f.data | {"rule": f.produced_by}
                        for f in wm.query("flag")]
    partidas_out = [f.data for f in wm.query("partida")]
    trace_rows = [{"id": f._id, "kind": f.kind, "produced_by": f.produced_by,
                   "data": f.data} for f in wm.all()]

    out_dir = out_root / memoria_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    write_artefacts(
        out_dir=out_dir, meta=parsed["meta"], partidas=partidas_out,
        totales=totales, flags=flags_with_rule, acopios=plan,
        trace_rows=trace_rows, rules_spec=rules_spec,
    )

    return {
        "out_dir": out_dir, "meta": parsed["meta"], "totales": totales,
        "flags": flags, "partidas": partidas_out, "acopios": plan,
    }


def recompute_totales(partidas: list[dict], rules_spec: dict) -> dict:
    """Recompute totales for an edited partida list — same engine math,
    no re-running of mapping/regulatory rules."""
    wm = engine.WorkingMemory()
    for clave, valor in rules_spec.get("parameters", {}).items():
        if isinstance(valor, (int, float, str, bool)):
            wm.assert_fact("project-param", {"clave": clave, "valor": valor})
    for p in partidas:
        wm.assert_fact("partida", p, produced_by="editor_override")
    return engine.compute_presupuesto(wm)


def _ingest_bc3(memoria_path: pathlib.Path,
                rules_spec: dict, wm: engine.WorkingMemory) -> dict:
    """When the input is a .bc3 export from Presto/Arquímedes/CYPE, we
    bypass the memoria parser and load partidas directly. Returns a
    parsed-shaped dict so the rest of the pipeline is identical."""
    # FIEBDC files emitted by Presto/Arquímedes/CYPE use Windows-1252;
    # latin-1 also works as a strict subset for most files.
    try:
        text = memoria_path.read_text(encoding="cp1252", errors="replace")
    except (OSError, UnicodeError):
        text = memoria_path.read_text(encoding="latin-1", errors="replace")
    parsed_bc3 = bc3.parse_bc3_full(text)
    bc3_partidas = parsed_bc3["partidas"]

    # Reasonable defaults — the BC3 has no memoria meta. The editor can
    # override; regulatory flags will fire from these where applicable.
    meta = {
        "memoria": memoria_path.name,
        "suelo": "urbano",
        "requiere_proyecto": len(bc3_partidas) >= 25,
        "uso": rules_spec.get("parameters", {}).get("uso", "vivienda_habitual"),
        "uso_turistico": False,
        "incluye_demoliciones": any(
            "demolic" in (p.get("descripcion", "").lower())
            for p in bc3_partidas),
        "toca_envolvente": any(
            any(k in (p.get("descripcion", "").lower())
                for k in ("cubierta", "fachada", "carpinter", "aislamiento"))
            for p in bc3_partidas),
        "promotor": parsed_bc3["header"].get("propiedad", "") or "",
        "emplazamiento": parsed_bc3["header"].get("cabecera", "") or "",
    }

    # project-meta drives regulatory rules.
    wm.assert_fact("project-meta", {
        "memoria": meta["memoria"],
        "suelo": meta["suelo"],
        "requiere_proyecto": meta["requiere_proyecto"],
        "uso": meta["uso"],
        "uso_turistico": meta["uso_turistico"],
        "incluye_demoliciones": meta["incluye_demoliciones"],
        "toca_envolvente": meta["toca_envolvente"],
    }, produced_by="ingesta_bc3")

    # Inject the BC3 partidas straight into working memory.
    for i, p in enumerate(bc3_partidas, start=1):
        wm.assert_fact("partida", {
            "code": p.get("code") or f"P{i:03d}",
            "capitulo": p.get("capitulo", "Sin capítulo"),
            "descripcion": p.get("descripcion", ""),
            "unidad": p.get("unidad", "ud"),
            "medicion": p.get("medicion", 0),
            "precio_unitario": p.get("precio_unitario", 0),
            "importe": p.get("importe", 0),
            "mo_pu": p.get("mo_pu", 0),
            "mat_pu": p.get("mat_pu", 0),
            "maq_pu": p.get("maq_pu", 0),
            "indirectos_pct": p.get("indirectos_pct", 0.06),
            "price_ref": p.get("price_ref", ""),
            "descompuesto": p.get("descompuesto", []),
            "pliego": p.get("pliego", ""),
        }, produced_by="ingesta_bc3")

    return {"meta": meta, "items": [], "bc3_partidas": bc3_partidas}


def run_for_memoria(memoria_path: pathlib.Path,
                    out_root: pathlib.Path | None = None,
                    verbose: bool = True) -> dict:
    """Run the full pipeline for one memoria (or a BC3 export).

    Returns {out_dir, totales, flags, partidas, meta} so callers (CLI or web)
    can render however they like. out_root defaults to ./salidas/.
    """
    out_root = out_root or SALIDAS
    if verbose:
        print(f"\n=== {memoria_path.name} ===")
    wm = engine.WorkingMemory()
    eng = engine.Engine(wm)

    with (ROOT / "rules.json").open(encoding="utf-8") as fh:
        rules_spec = json.load(fh)

    engine.load_rules(str(ROOT / "rules.json"), eng)

    # ---- Branch: BC3 file → partidas direct; everything else → memoria parser
    if memoria_path.suffix.lower() == ".bc3":
        parsed = _ingest_bc3(memoria_path, rules_spec, wm)
        # Run regulatory rules now that project-meta + partidas are present.
        eng.run()
        # Skip the binding step (BC3 already carries priced partidas).
        for price in load_price_catalogue():
            for k in ("mo", "mat", "maq", "indirectos_pct"):
                try:
                    price[k] = float(price.get(k) or 0.0)
                except (TypeError, ValueError):
                    price[k] = 0.0
            wm.assert_fact("price", price, produced_by="ingesta_precios")
        explode_material_lines(wm, load_material_lines())
        eng.run()
        totales = engine.compute_presupuesto(wm)
        plan = engine.compute_plan_acopios(wm)
        flags = [f.data for f in wm.query("flag")]
        partidas_out = [f.data for f in wm.query("partida")]
        out_dir = out_root / memoria_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        trace_rows = [{"id": f._id, "kind": f.kind, "produced_by": f.produced_by,
                       "data": f.data} for f in wm.all()]
        flags_with_rule = [f.data | {"rule": f.produced_by}
                            for f in wm.query("flag")]
        write_artefacts(
            out_dir=out_dir, meta=parsed["meta"], partidas=partidas_out,
            totales=totales, flags=flags_with_rule, acopios=plan,
            trace_rows=trace_rows, rules_spec=rules_spec,
        )
        if verbose:
            print(f"  Partidas: {len(partidas_out)}")
            print(f"  PEM:   {totales['PEM']:>12,.2f} EUR")
            print(f"  PEC:   {totales['PEC']:>12,.2f} EUR")
            print(f"  TOTAL: {totales['TOTAL']:>12,.2f} EUR")
            print(f"  Flags: {len(flags)}")
            for f in flags:
                print(f"    [{f['nivel']}] {f['codigo']}")
            try:
                rel = out_dir.relative_to(ROOT)
            except ValueError:
                rel = out_dir
            print(f"  -> output written to {rel}/")
        return {
            "out_dir": out_dir, "meta": parsed["meta"], "totales": totales,
            "flags": flags, "partidas": partidas_out, "acopios": plan,
        }

    parsed = parse_memoria(memoria_path)

    # One project-meta fact per memoria — regulatory rules fire off this,
    # so we get one licencia/rústico/IVA/etc flag per project, not per scope line.
    wm.assert_fact("project-meta", {
        "memoria": parsed["meta"]["memoria"],
        "suelo": parsed["meta"]["suelo"],
        "requiere_proyecto": parsed["meta"]["requiere_proyecto"],
        "uso": parsed["meta"]["uso"],
        "uso_turistico": parsed["meta"].get("uso_turistico", False),
        "incluye_demoliciones": parsed["meta"].get("incluye_demoliciones", False),
        "toca_envolvente": parsed["meta"].get("toca_envolvente", False),
    }, produced_by="ingesta_memoria")

    # Look up capítulo + canonical unidad from concepto_metadata so the runner
    # is the single bridge between scope items and partidas (no per-tipo MAP
    # rules to maintain — adding a new partida = 1 catalogue row + 1 metadata
    # entry, both generated by catalogue_seed.py).
    metadata = rules_spec.get("concepto_metadata", {})
    for i, item in enumerate(parsed["items"], start=1):
        meta_entry = metadata.get(item["tipo"], {})
        wm.assert_fact("scope-item", {
            "id": f"S{i:03d}",
            "descripcion": meta_entry.get("descripcion_corta", item["tipo"]),
            "tipo": item["tipo"],
            "capitulo": meta_entry.get("capitulo", "Sin capítulo"),
            "cantidad": item["cantidad"],
            "unidad": meta_entry.get("unidad", item["unidad"]),
        }, produced_by="ingesta_memoria")
        # Emit the partida-pendiente directly — no MAP_ rule needed.
        wm.assert_fact("partida-pendiente", {
            "capitulo": meta_entry.get("capitulo", "Sin capítulo"),
            "concepto": item["tipo"],
            "medicion": item["cantidad"],
            "unidad": meta_entry.get("unidad", item["unidad"]),
            "scope_ref": f"S{i:03d}",
        }, produced_by="ingesta_memoria")

    for price in load_price_catalogue():
        # Normalise numeric columns so partida facts inherit float values,
        # not raw CSV strings.
        for k in ("mo", "mat", "maq", "indirectos_pct"):
            try:
                price[k] = float(price.get(k) or 0.0)
            except (TypeError, ValueError):
                price[k] = 0.0
        wm.assert_fact("price", price, produced_by="ingesta_precios")

    eng.run()                       # regulatory rules fire
    bind_prices_to_partidas(wm, rules_spec)
    explode_material_lines(wm, load_material_lines())
    eng.run()                       # any rule that depends on `partida`

    totales = engine.compute_presupuesto(wm)
    plan = engine.compute_plan_acopios(wm)

    # Snapshot facts we'll need for both rendering and PDF generation.
    flags = [f.data for f in wm.query("flag")]
    partidas_out = [f.data for f in wm.query("partida")]

    out_dir = out_root / memoria_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot a serialisable trace for traza.md before writing artefacts.
    trace_rows = [{"id": f._id, "kind": f.kind, "produced_by": f.produced_by,
                   "data": f.data} for f in wm.all()]
    flags_with_rule = [f.data | {"rule": f.produced_by} for f in wm.query("flag")]

    write_artefacts(
        out_dir=out_dir,
        meta=parsed["meta"],
        partidas=partidas_out,
        totales=totales,
        flags=flags_with_rule,
        acopios=plan,
        trace_rows=trace_rows,
        rules_spec=rules_spec,
    )

    if verbose:
        print(f"  Partidas: {len(partidas_out)}")
        print(f"  PEM:   {totales['PEM']:>12,.2f} EUR")
        print(f"  PEC:   {totales['PEC']:>12,.2f} EUR")
        print(f"  IVA:   {totales['IVA']:>12,.2f} EUR")
        print(f"  TOTAL: {totales['TOTAL']:>12,.2f} EUR")
        if flags:
            print(f"  Flags: {len(flags)}")
            for f in flags:
                print(f"    [{f['nivel']}] {f['codigo']}")
        try:
            rel = out_dir.relative_to(ROOT)
        except ValueError:
            rel = out_dir
        print(f"  -> output written to {rel}/")

    return {
        "out_dir": out_dir,
        "meta": parsed["meta"],
        "totales": totales,
        "flags": flags,
        "partidas": partidas_out,
        "acopios": plan,
    }


def main() -> int:
    SALIDAS.mkdir(exist_ok=True)
    args = [pathlib.Path(p) for p in sys.argv[1:]]
    if not args:
        args = sorted(list(MEMORIAS.glob("*.md")) +
                      list(MEMORIAS.glob("*.pdf")) +
                      list(MEMORIAS.glob("*.bc3")))
    if not args:
        print("No memorias found. Drop one into ./memorias/ and re-run.")
        return 1
    for path in args:
        run_for_memoria(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
