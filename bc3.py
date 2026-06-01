r"""
bc3.py — FIEBDC-3 (.bc3) reader/writer.

BC3 is the Spanish construction-data interchange standard.
Plain text, records delimited by `~` + a letter, fields by `|`,
subfields by `\`.

Record types this engine cares about:

  ~V  Property / version header
      ~V | PROPIEDAD | VERSION_FORMATO | PROGRAMA_EMISION | CABECERA | …

  ~K  Coefficients / decimals (we round-trip a default %indirectos)
      ~K | DEC_CD | DEC_RE | DEC_UD | DEC_FE | DEC_DI | DEC_RC | DEC_PR | … | %CI

  ~C  Concepto: a code in the catalogue
      ~C | CODIGO | UNIDAD | RESUMEN | PRECIO\PRECIO2… | FECHA | TIPO
      TIPO: 0 simple (mat / mo / maq), 1 partida / capítulo (decomposable), …

  ~D  Descomposicion: which children make up a parent code, with their
      rendimientos.
      ~D | CODIGO_PADRE | CODIGO_HIJO\FACTOR\RENDIMIENTO | … |

  ~M  Medicion: medición de una partida dentro de un capítulo.
      ~M | CODIGO_PADRE\CODIGO_HIJO | POSICION | MEDICIONES_TOTAL | COMENTARIO | TIPO

This module reads/writes the subset of FIEBDC-3 needed to round-trip
a presupuesto. Spec: www.fiebdc.org (vigente FIEBDC-3/2024).
"""

from __future__ import annotations
import re
from typing import Iterable, Iterator


# ---------------- Encoding helpers ----------------

def _split_records(text: str) -> Iterator[str]:
    """Yield each record's body (the chars after the '~' tag)."""
    raw = text.replace("\x1a", "")
    # Records are delimited by '~'. Drop the BOM/leading whitespace.
    for chunk in raw.split("~"):
        if not chunk.strip():
            continue
        yield chunk.lstrip("\r\n")


def _fields(body_after_tag: str) -> list[str]:
    """Split the rest of a record (post-tag) on '|'. First field is
    typically empty (the '|' immediately after the tag char)."""
    f = body_after_tag.split("|")
    if f and f[0] == "":
        f = f[1:]
    return f


def _comma_to_dot(s: str) -> str:
    return s.replace(",", ".").strip()


# ---------------- Reader ----------------

def parse_bc3(text: str) -> list[dict]:
    """Legacy entry point — returns the ~C records as price dicts only,
    same shape as before. Kept for backward compatibility with the price
    catalogue ingest path."""
    out: list[dict] = []
    for rec in _split_records(text):
        if rec[:1] != "C":
            continue
        f = _fields(rec[1:])
        if len(f) < 4:
            continue
        precio_raw = f[3].split("\\")[0] if f[3] else "0"
        try:
            precio = float(_comma_to_dot(precio_raw)) if precio_raw else 0.0
        except ValueError:
            precio = 0.0
        out.append({
            "code": f[0].strip(),
            "unidad": f[1].strip() if len(f) > 1 else "",
            "descripcion": f[2].strip() if len(f) > 2 else "",
            "precio_unitario": precio,
            "fuente": "BC3",
            "ambito": "import",
        })
    return out


def parse_bc3_full(text: str) -> dict:
    """Full ~C + ~D + ~M parse.

    Returns:
      {
        "header": {…},                    # ~V + ~K
        "conceptos": {code: {…}},         # all ~C records, indexed by code
        "descomposicion": {parent: [      # ~D
            {"child": code, "factor": float, "rendimiento": float}, …
        ]},
        "mediciones": [                   # ~M
            {"capitulo": code, "partida": code, "medicion": float,
             "comentario": str, "lineas": [{"comentario": str,
                 "ud": float, "largo": float, "ancho": float, "alto": float,
                 "parcial": float}, …]},
        ],
        "partidas": [                     # derived: ~M ∩ ~D ∩ ~C
            {"code", "capitulo", "descripcion", "unidad", "medicion",
             "precio_unitario", "importe", "descompuesto": [
                 {"slot", "comp_code", "descripcion", "unidad",
                  "rendimiento", "precio_unitario", "importe"}, …]}, …
        ],
      }
    """
    header: dict = {"propiedad": "", "version": "", "programa": "",
                    "cabecera": ""}
    conceptos: dict[str, dict] = {}
    descomposicion: dict[str, list[dict]] = {}
    mediciones: list[dict] = []
    indirectos_pct = 0.0     # default; overridden by ~K

    for rec in _split_records(text):
        tag = rec[:1]
        body = rec[1:]
        f = _fields(body)

        if tag == "V":
            header["propiedad"] = f[0].strip() if len(f) > 0 else ""
            header["version"]   = f[1].strip() if len(f) > 1 else ""
            header["programa"]  = f[2].strip() if len(f) > 2 else ""
            header["cabecera"]  = f[3].strip() if len(f) > 3 else ""

        elif tag == "K":
            # ~K has a long, position-dependent payload. The relevant value
            # for us is the project %indirectos which sits at a vendor-
            # specific position; we look for the first token that parses as
            # a small float in 0..0.30 range and treat it as the default.
            for tok in f:
                tok = _comma_to_dot(tok)
                if not tok:
                    continue
                try:
                    v = float(tok)
                    if 0.001 < v < 0.30:
                        indirectos_pct = v
                        break
                except ValueError:
                    pass

        elif tag == "C":
            if len(f) < 4:
                continue
            precio_raw = f[3].split("\\")[0] if f[3] else "0"
            try:
                precio = float(_comma_to_dot(precio_raw)) if precio_raw else 0.0
            except ValueError:
                precio = 0.0
            tipo_field = f[5].strip() if len(f) > 5 else "0"
            try:
                tipo = int(tipo_field) if tipo_field else 0
            except ValueError:
                tipo = 0
            code = f[0].strip()
            conceptos[code] = {
                "code": code,
                "unidad": f[1].strip() if len(f) > 1 else "",
                "descripcion": f[2].strip() if len(f) > 2 else "",
                "precio_unitario": precio,
                "fecha": f[4].strip() if len(f) > 4 else "",
                "tipo": tipo,
            }

        elif tag == "D":
            if not f:
                continue
            parent = f[0].strip()
            children: list[dict] = []
            for hijo in f[1:]:
                if not hijo:
                    continue
                parts = hijo.split("\\")
                child_code = parts[0].strip()
                if not child_code:
                    continue
                factor = 1.0
                rendim = 1.0
                if len(parts) > 1 and parts[1]:
                    try:
                        factor = float(_comma_to_dot(parts[1]))
                    except ValueError:
                        pass
                if len(parts) > 2 and parts[2]:
                    try:
                        rendim = float(_comma_to_dot(parts[2]))
                    except ValueError:
                        pass
                children.append({"child": child_code, "factor": factor,
                                  "rendimiento": rendim})
            if children:
                descomposicion[parent] = children

        elif tag == "M":
            if not f:
                continue
            parent_child = f[0].split("\\")
            capitulo = parent_child[0].strip() if parent_child else ""
            partida  = parent_child[1].strip() if len(parent_child) > 1 else ""
            try:
                medicion_total = float(_comma_to_dot(f[2])) if len(f) > 2 and f[2] else 0.0
            except ValueError:
                medicion_total = 0.0
            comentario = f[3].strip() if len(f) > 3 else ""
            # Optional medición line breakdown (positions 5..)
            lineas: list[dict] = []
            for extra in f[5:]:
                if not extra:
                    continue
                pieces = extra.split("\\")
                # Spec layout (in groups of 5 subfields): COMENTARIO\Ud\Largo\Ancho\Alto
                while len(pieces) >= 5:
                    line, pieces = pieces[:5], pieces[5:]
                    try:
                        ud  = float(_comma_to_dot(line[1] or "0"))
                        lg  = float(_comma_to_dot(line[2] or "0"))
                        an  = float(_comma_to_dot(line[3] or "0"))
                        al  = float(_comma_to_dot(line[4] or "0"))
                    except ValueError:
                        continue
                    if ud == lg == an == al == 0:
                        continue
                    parcial = ud * (lg if lg else 1) * (an if an else 1) * (al if al else 1)
                    lineas.append({
                        "comentario": line[0].strip(),
                        "ud": ud, "largo": lg, "ancho": an, "alto": al,
                        "parcial": round(parcial, 4),
                    })
            mediciones.append({
                "capitulo": capitulo, "partida": partida,
                "medicion": medicion_total, "comentario": comentario,
                "lineas": lineas,
            })

    # ---- Assemble partidas: each ~M with a partida code becomes one
    # partida; its descompuesto is built from ~D + the children's ~C prices.
    LABOR_RE = re.compile(r"^(O|MO|H)", re.IGNORECASE)
    MAT_RE   = re.compile(r"^(M|MT|MAT)", re.IGNORECASE)
    MAQ_RE   = re.compile(r"^(Q|MQ|MA)", re.IGNORECASE)

    def _slot_for(code: str) -> str:
        # Best-effort categorisation. Real BC3s vary by vendor; partidas
        # already grouped via ~T/~N records would be more reliable.
        if LABOR_RE.match(code) and not MAQ_RE.match(code):
            return "mo"
        if MAT_RE.match(code):
            return "mat"
        if MAQ_RE.match(code):
            return "maq"
        # Fallback: treat unrecognised composite children as materials.
        return "mat"

    partidas: list[dict] = []
    for med in mediciones:
        code = med["partida"]
        if not code:
            continue
        cap = conceptos.get(med["capitulo"], {})
        c   = conceptos.get(code)
        if c is None:
            continue
        unidad = c.get("unidad", "")
        descripcion = c.get("descripcion", "")
        precio_u = c.get("precio_unitario", 0.0)
        importe = round(med["medicion"] * precio_u, 2)

        descompuesto: list[dict] = []
        mo_pu = mat_pu = maq_pu = 0.0
        for child in descomposicion.get(code, []):
            child_c = conceptos.get(child["child"], {})
            comp_pu = float(child_c.get("precio_unitario") or 0.0)
            rendim  = float(child["rendimiento"] or 1.0)
            comp_importe = round(rendim * comp_pu, 4)
            slot = _slot_for(child["child"])
            if slot == "mo":
                mo_pu += comp_importe
            elif slot == "maq":
                maq_pu += comp_importe
            else:
                mat_pu += comp_importe
            descompuesto.append({
                "slot": slot,
                "comp_code": child["child"],
                "descripcion": child_c.get("descripcion", child["child"]),
                "unidad": child_c.get("unidad", ""),
                "rendimiento": rendim,
                "precio_unitario": comp_pu,
                "importe": round(comp_importe, 2),
            })
        partidas.append({
            "code": code,
            "capitulo": cap.get("descripcion") or med["capitulo"],
            "descripcion": descripcion,
            "unidad": unidad,
            "medicion": med["medicion"],
            "precio_unitario": precio_u,
            "importe": importe,
            "mo_pu": round(mo_pu, 2),
            "mat_pu": round(mat_pu, 2),
            "maq_pu": round(maq_pu, 2),
            "indirectos_pct": indirectos_pct,
            "price_ref": code,
            "descompuesto": descompuesto,
        })

    return {
        "header": header,
        "conceptos": conceptos,
        "descomposicion": descomposicion,
        "mediciones": mediciones,
        "partidas": partidas,
    }


# ---------------- Writer ----------------

def _fmt_num(v: float, decimals: int = 4) -> str:
    s = f"{float(v):.{decimals}f}"
    # FIEBDC convention: comma decimal separator.
    return s.replace(".", ",")


def write_bc3(partidas: Iterable[dict],
              programa: str = "MotorPresupuestos",
              capitulos: dict[str, str] | None = None,
              materials_catalogue: dict[str, dict] | None = None,
              indirectos_pct: float | None = None) -> str:
    """Emit a FIEBDC-3/2024 file with `~V`, `~K`, `~C`, `~D`, `~M` records.

    Round-trippable with parse_bc3_full when the input partidas carry a
    `descompuesto` field. Without it the writer falls back to the
    aggregated mo/mat/maq behaviour of the previous version (a single ~C
    per partida, no ~D/~M).

    capitulos: optional {capitulo_name: cap_code} to emit chapter ~C
      records. If omitted, capítulos are auto-numbered "CAP01", "CAP02"…
    materials_catalogue: optional {comp_code: {"descripcion","unidad",
      "precio_unitario"}} so component prices are emitted too. If a
      component appears in a descompuesto but not in the catalogue, we
      emit a minimal ~C with the rendimiento*precio recoverable from the
      partida row.
    indirectos_pct: project % indirectos to round-trip via ~K (default 6 %).
    """
    partidas = list(partidas)
    indir = indirectos_pct if indirectos_pct is not None else (
        partidas[0].get("indirectos_pct", 0.06) if partidas else 0.06
    )
    lines: list[str] = [
        f"~V||FIEBDC-3/2024|{programa}|Presupuesto generado|",
        # ~K: a permissive value — most readers only use this for decimals.
        # 2 decimal places everywhere; %indirectos as the last field.
        f"~K|2|2|2|2|2|2|2|2|2|2|{_fmt_num(indir, 4)}|",
    ]

    # ---- Capítulos
    capitulo_to_code: dict[str, str] = {}
    if capitulos:
        capitulo_to_code = {k: v for k, v in capitulos.items()}
    else:
        seen: list[str] = []
        for p in partidas:
            cap = p.get("capitulo", "Sin capítulo")
            if cap not in capitulo_to_code:
                capitulo_to_code[cap] = f"CAP{len(seen)+1:02d}"
                seen.append(cap)

    for cap_name, cap_code in capitulo_to_code.items():
        safe = cap_name.replace("|", " ")
        lines.append(f"~C|{cap_code}|cap|{safe}|0||1|")

    # ---- Component master ~C records (avoid duplicates)
    emitted: set[str] = set()
    if materials_catalogue:
        for ccode, cinfo in materials_catalogue.items():
            if ccode in emitted:
                continue
            emitted.add(ccode)
            desc = (cinfo.get("descripcion") or ccode).replace("|", " ")
            unidad = cinfo.get("unidad") or ""
            precio = cinfo.get("precio_unitario") or 0
            lines.append(
                f"~C|{ccode}|{unidad}|{desc}|{_fmt_num(precio, 4)}||0|"
            )

    # ---- For each partida: emit ~C (partida), ~D (descomposición), ~M
    for p in partidas:
        code = str(p.get("code") or "")
        unidad = (p.get("unidad") or "").replace("|", " ")
        desc = (p.get("descripcion") or "").replace("|", " ")
        precio = float(p.get("precio_unitario") or 0)
        lines.append(
            f"~C|{code}|{unidad}|{desc}|{_fmt_num(precio, 4)}||1|"
        )

        comps = p.get("descompuesto") or []
        if comps:
            # Make sure each component's ~C exists somewhere in the file.
            for c in comps:
                ccode = c.get("comp_code") or ""
                if not ccode or ccode in emitted:
                    continue
                emitted.add(ccode)
                cdesc = (c.get("descripcion") or ccode).replace("|", " ")
                cunid = c.get("unidad") or ""
                cprec = c.get("precio_unitario") or 0
                lines.append(
                    f"~C|{ccode}|{cunid}|{cdesc}|{_fmt_num(cprec, 4)}||0|"
                )
            # ~D record: PADRE | HIJO\FACTOR\RENDIMIENTO | …
            parts = [f"{c['comp_code']}\\1\\{_fmt_num(c.get('rendimiento') or 0)}"
                     for c in comps]
            lines.append(f"~D|{code}|" + "|".join(parts) + "|")

        # ~M record
        cap_code = capitulo_to_code.get(p.get("capitulo", "Sin capítulo"),
                                        "CAP01")
        med = _fmt_num(float(p.get("medicion") or 0), 2)
        lines.append(f"~M|{cap_code}\\{code}||{med}|||")

    out = "\r\n".join(lines) + "\r\n\x1a"
    return out


# ---------------- Demo ----------------

if __name__ == "__main__":
    # Round-trip self-test: synthesise a small set of partidas with a
    # descompuesto, write BC3, parse it back, print the partidas.
    partidas = [{
        "code": "01.001",
        "capitulo": "Albañilería",
        "descripcion": "Tabique LH7",
        "unidad": "m2",
        "medicion": 40,
        "precio_unitario": 22.50,
        "importe": 900.0,
        "indirectos_pct": 0.06,
        "descompuesto": [
            {"comp_code": "O0004", "descripcion": "Oficial 1ª albañil",
             "unidad": "h", "rendimiento": 0.3334, "precio_unitario": 24.50,
             "importe": 8.17, "slot": "mo"},
            {"comp_code": "M0001", "descripcion": "Ladrillo hueco 7",
             "unidad": "ud", "rendimiento": 40.09, "precio_unitario": 0.18,
             "importe": 7.22, "slot": "mat"},
        ],
    }]
    text = write_bc3(partidas)
    print("=== BC3 emitted ===")
    print(text)
    print()
    print("=== parse_bc3_full(round-tripped) ===")
    parsed = parse_bc3_full(text)
    for p in parsed["partidas"]:
        print(f"  {p['code']}  {p['descripcion']}  ud={p['unidad']}  "
              f"medición={p['medicion']}  pu={p['precio_unitario']}  "
              f"importe={p['importe']}")
        for c in p["descompuesto"]:
            print(f"     {c['slot']:3s} {c['comp_code']}  rendim={c['rendimiento']}  "
                  f"pu={c['precio_unitario']}  importe={c['importe']}")
