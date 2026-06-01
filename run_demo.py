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

# Scope verbs: the opening word of a numbered item determines its tipo.
# Tested in order — first match wins, so put more specific verbs first.
SCOPE_VERBS: list[tuple[str, str, str, str]] = [
    # (regex on item-leading word(s), tipo, capítulo, unidad)
    (r"demolici[oó]n", "demolicion_tabique", "Demoliciones", "m2"),
    (r"(?:ejecuci[oó]n\s+de\s+)?(?:nuevo\s+)?tabiquer[ií]a", "tabique", "Albañilería", "m2"),
    (r"(?:ejecuci[oó]n\s+de\s+)?(?:nuevo\s+)?tabique", "tabique", "Albañilería", "m2"),
    (r"enlucido", "enlucido", "Revestimientos", "m2"),
    (r"pintura", "pintura", "Pintura", "m2"),
    (r"solado", "solado_porcelanico", "Pavimentos", "m2"),
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
        # leading word(s) decide the tipo — strip markdown emphasis first
        head = re.sub(r"[*_`]", "", body).strip().lower()
        measure_match = MEASURE_RE.search(body)
        if measure_match is None:
            continue
        cantidad = float(measure_match.group(1).replace(",", "."))
        matched = None
        for pat, tipo, capitulo, unidad in SCOPE_VERBS:
            if re.match(rf"^{pat}\b", head, re.IGNORECASE):
                matched = (tipo, capitulo, unidad)
                break
        if matched is None:
            continue
        tipo, capitulo, unidad = matched
        items.append({
            "tipo": tipo, "capitulo": capitulo,
            "cantidad": cantidad, "unidad": unidad,
        })
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
    concept_to_code = rules_spec.get("concepto_to_price", {})
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

    for i, item in enumerate(parsed["items"], start=1):
        wm.assert_fact("scope-item", {
            "id": f"S{i:03d}",
            "descripcion": item["tipo"],
            "tipo": item["tipo"],
            "capitulo": item["capitulo"],
            "cantidad": item["cantidad"],
            "unidad": item["unidad"],
        }, produced_by="ingesta_memoria")

    for price in load_price_catalogue():
        wm.assert_fact("price", price, produced_by="ingesta_precios")

    eng.run()                       # mapping + regulatory rules fire
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

    # Client-facing PDFs. Reference is a short hash of memoria stem + first
    # partida importe — deterministic + readable, no PII.
    import hashlib
    ref = hashlib.sha1(
        f"{memoria_path.stem}-{totales['PEM']:.2f}".encode("utf-8")
    ).hexdigest()[:8].upper()
    duraciones = rules_spec.get("duracion_capitulo_dias", {})
    duraciones = {k: v for k, v in duraciones.items() if not k.startswith("_")}
    capitulos = rules_spec.get("capitulo_orden", [])
    client_pdfs.build_presupuesto_pdf(
        out_dir / "presupuesto_cliente.pdf",
        meta=parsed["meta"], totales=totales,
        partidas=partidas_out, capitulo_orden=capitulos, ref=ref,
    )
    client_pdfs.build_plan_obra_pdf(
        out_dir / "plan_de_obra.pdf",
        meta=parsed["meta"], partidas=partidas_out,
        duracion_dias=duraciones, capitulo_orden=capitulos, ref=ref,
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
