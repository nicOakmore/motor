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

# Captures the measurement at the end of an item line: "...: **80 m²**" or "...: 80 m²".
MEASURE_RE = re.compile(r":\s*\*{0,2}\s*(\d+(?:[\.,]\d+)?)\s*\*{0,2}\s*m[²2]", re.IGNORECASE)
# Numbered list item: starts with "N. " (after optional whitespace).
ITEM_RE = re.compile(r"^\s*\d+\.\s+(.*)", re.MULTILINE)


def parse_memoria(path: pathlib.Path) -> dict:
    """Return {meta:{...}, items:[{tipo,cantidad,unidad,capitulo}, ...]}.

    Line-based: each numbered item in 'Alcance de obra' is one scope-item.
    The verb at the start of the line decides the tipo; the trailing
    ': N m²' provides the medición. Words that appear inside descriptive
    text (e.g. 'paramentos enlucidos' inside a pintura line) do NOT count —
    only the leading verb does.
    """
    text = path.read_text(encoding="utf-8")
    suelo = "urbano"
    if re.search(r"suelo\s*[:*]+[\s*]*r[uú]stico", text, re.IGNORECASE):
        suelo = "rustico"
    requiere_proyecto = bool(
        re.search(r"(?<!no\s)(?<!no\s\s)REQUIERE\s+PROYECTO\s+T[ÉE]CNICO",
                  text, re.IGNORECASE)
    )
    uso = "vivienda_habitual" if "vivienda habitual" in text.lower() else "otros"

    def _grab(label: str) -> str:
        # Match "**Label:** value …" or "Label: value …", stops at end of line.
        m = re.search(rf"\*{{0,2}}{label}\*{{0,2}}\s*:\s*([^\n\r]+)",
                      text, re.IGNORECASE)
        if not m:
            return ""
        # strip surrounding markdown emphasis and trailing punctuation
        return re.sub(r"^[*_`\s]+|[*_`\s]+$", "", m.group(1)).strip(" .,:")

    promotor = _grab("Promotor")
    emplazamiento = _grab("Emplazamiento")

    items = []
    for body in ITEM_RE.findall(text):
        # strip markdown emphasis; whole-body search so qualifiers that follow
        # the measurement (e.g. "12 m² de tabique de ladrillo hueco doble")
        # still influence routing.
        body_clean = re.sub(r"[*_`]", " ", body).strip()
        head = body_clean.lower()
        measure_match = MEASURE_RE.search(body)
        if measure_match is None:
            continue
        cantidad = float(measure_match.group(1).replace(",", "."))
        tipo = None
        for pat, t in SCOPE_VERBS:
            # match anywhere from the start of the line; the head leads with
            # the verb so re.match is fine.
            if re.match(rf"^{pat}\b", head, re.IGNORECASE):
                tipo = t
                break
        if tipo is None:
            continue
        items.append({"tipo": tipo, "cantidad": cantidad, "unidad": "m2"})
    return {
        "meta": {
            "memoria": path.name,
            "suelo": suelo,
            "requiere_proyecto": requiere_proyecto,
            "uso": uso,
            "promotor": promotor,
            "emplazamiento": emplazamiento,
        },
        "items": items,
    }


def load_price_catalogue() -> list[dict]:
    """Read every CSV in ./precios/ as price rows. BC3/XLSX/PDF would plug in
    here too — for the demo only CSV is wired."""
    prices = []
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


# --------------------------------------------------------------------------
# Knowledge bridge — concept → price code, ámbito priority. Read from rules.json
# so it stays editable knowledge, not Python.
# --------------------------------------------------------------------------

def bind_prices_to_partidas(wm: engine.WorkingMemory, rules_spec: dict) -> None:
    """For every `partida-pendiente`, find the price by concept→code map and
    the ámbito priority, then assert a fully-priced `partida` fact."""
    # Prefer the rich concepto_metadata table (which has unidad + capítulo too);
    # fall back to legacy concepto_to_price for backward compatibility.
    metadata = rules_spec.get("concepto_metadata", {})
    concept_to_code = {k: v["price_code"] for k, v in metadata.items()
                       if isinstance(v, dict) and v.get("price_code")}
    for k, v in rules_spec.get("concepto_to_price", {}).items():
        if not k.startswith("_"):
            concept_to_code.setdefault(k, v)
    priority = (rules_spec.get("parameters", {})
                          .get("ambito_precios_prioridad", ["local"]))

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
        wm.assert_fact("partida", {
            "code": f"P{counter:03d}",
            "capitulo": pp["capitulo"],
            "descripcion": price["descripcion"],
            "unidad": pp["unidad"],
            "medicion": medicion,
            "precio_unitario": pu,
            "importe": round(medicion * pu, 2),
            "price_ref": code,
            "scope_ref": pp.get("scope_ref"),
        }, produced_by="bind_prices_to_partidas")


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

def run_for_memoria(memoria_path: pathlib.Path,
                    out_root: pathlib.Path | None = None,
                    verbose: bool = True) -> dict:
    """Run the full pipeline for one memoria.

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

    parsed = parse_memoria(memoria_path)

    # One project-meta fact per memoria — regulatory rules fire off this,
    # so we get one licencia/rústico/IVA flag per project, not per scope line.
    wm.assert_fact("project-meta", {
        "memoria": parsed["meta"]["memoria"],
        "suelo": parsed["meta"]["suelo"],
        "requiere_proyecto": parsed["meta"]["requiere_proyecto"],
        "uso": parsed["meta"]["uso"],
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

    (out_dir / "presupuesto.md").write_text(
        render_presupuesto(wm, totales, parsed["meta"], rules_spec.get("capitulo_orden", [])),
        encoding="utf-8",
    )
    (out_dir / "presupuesto.json").write_text(
        json.dumps({
            "meta": parsed["meta"],
            "totales": totales,
            "partidas": [f.data for f in wm.query("partida")],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "plan_acopios.csv").write_text(render_acopios_csv(plan), encoding="utf-8")
    (out_dir / "flags.md").write_text(render_flags(wm), encoding="utf-8")
    (out_dir / "traza.md").write_text(render_trace(wm), encoding="utf-8")

    bc3_text = bc3.write_bc3([f.data for f in wm.query("partida")],
                             programa="MotorPresupuestos")
    (out_dir / "presupuesto.bc3").write_text(bc3_text, encoding="latin-1")

    # Client-facing PDFs. Reference looks like REX's internal numbering:
    # <ref_series>.<short hash>, e.g. 2026.1CEA635D.
    import hashlib, datetime as _dt
    h = hashlib.sha1(f"{memoria_path.stem}-{totales['PEM']:.2f}".encode("utf-8")
                     ).hexdigest()[:6].upper()
    ref = f"{rules_spec.get('firm',{}).get('ref_series', _dt.date.today().year)}.{h}"
    firm = rules_spec.get("firm", {})
    duraciones = {k: v for k, v in
                  rules_spec.get("duracion_capitulo_dias", {}).items()
                  if not k.startswith("_")}
    capitulos = rules_spec.get("capitulo_orden", [])
    festivos_raw = rules_spec.get("festivos", {}).get("dias", [])
    festivos = [_dt.date.fromisoformat(s) for s in festivos_raw]
    client_pdfs.build_presupuesto_pdf(
        out_dir / "presupuesto_cliente.pdf",
        firm=firm, meta=parsed["meta"], totales=totales,
        partidas=partidas_out, capitulo_orden=capitulos, ref=ref,
    )
    client_pdfs.build_plan_obra_pdf(
        out_dir / "plan_de_obra.pdf",
        firm=firm, meta=parsed["meta"], partidas=partidas_out,
        duracion_dias=duraciones, capitulo_orden=capitulos, ref=ref,
        festivos=festivos,
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
        args = sorted(MEMORIAS.glob("*.md"))
    if not args:
        print("No memorias found. Drop one into ./memorias/ and re-run.")
        return 1
    for path in args:
        run_for_memoria(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
