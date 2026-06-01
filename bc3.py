"""
bc3.py — FIEBDC-3 (.bc3) reader/writer (seed).

BC3 is the Spanish construction-data interchange standard. Plain text, records
delimited by '~' + a letter, fields by '|', subfields by '\\'.

Key record types this engine uses:
  ~V  property/version header (PROPIEDAD | VERSION | PROGRAMA_EMISION ...)
  ~K  coefficients / decimals (incl. costes indirectos)
  ~C  concepto (a price: CODIGO | UNIDAD | RESUMEN | PRECIO | FECHA | TIPO)
  ~D  descomposicion (CODIGO_PADRE | hijos: CODIGO\\FACTOR\\RENDIMIENTO ...)
  ~M  medicion (lines: CODIGO_PADRE\\CODIGO_HIJO | mediciones ...)
  ~T  texto / pliego

This seed reads ~C records into `price` facts and writes a minimal valid BC3
from `partida` facts. Claude Code extends to full ~D/~M support.
Spec: www.fiebdc.org (vigente FIEBDC-3/2024).
"""

from __future__ import annotations
from typing import Iterable


def parse_bc3(text: str) -> list[dict]:
    """Read ~C concept records into normalised price dicts.
    Returns VAT-exclusive unit prices ready to assert as `price` facts."""
    prices = []
    # records start at '~'; line endings per spec are CRLF, EOF is ASCII-26
    raw = text.replace("\x1a", "")
    records = [r for r in raw.split("~") if r.strip()]
    for rec in records:
        rec = rec.lstrip("\r\n")
        tag = rec[0]
        if tag != "C":
            continue
        # strip the tag char, then split fields by '|'
        # ~C|CODIGO|UNIDAD|RESUMEN|PRECIO\PRECIO2...|FECHA|TIPO|
        fields = rec[1:].split("|")
        # fields[0] is empty (the '|' right after 'C'); real fields start at 1
        if fields and fields[0] == "":
            fields = fields[1:]
        if len(fields) < 4:
            continue
        code = fields[0].strip()
        unidad = fields[1].strip()
        resumen = fields[2].strip()
        precio = fields[3].split("\\")[0].strip()  # first price column
        try:
            precio_val = float(precio.replace(",", ".")) if precio else 0.0
        except ValueError:
            precio_val = 0.0
        prices.append({
            "code": code, "unidad": unidad, "descripcion": resumen,
            "precio_unitario": precio_val, "fuente": "BC3", "ambito": "import",
        })
    return prices


def write_bc3(partidas: Iterable[dict], programa: str = "MotorPresupuestos") -> str:
    """Write a minimal valid BC3 from partida dicts.
    Emits ~V header and one ~C per partida. CRLF line endings, EOF marker."""
    lines = []
    # ~V  PROPIEDAD | VERSION_FORMATO | PROGRAMA_EMISION | CABECERA | ...
    lines.append(f"~V||FIEBDC-3/2024|{programa}|Presupuesto generado|")
    for p in partidas:
        code = p.get("code", "")
        unidad = p.get("unidad", "")
        resumen = p.get("descripcion", "").replace("|", " ")
        precio = f"{float(p.get('precio_unitario', 0)):.2f}".replace(".", ",")
        # ~C  CODIGO | UNIDAD | RESUMEN | PRECIO | FECHA | TIPO |
        lines.append(f"~C|{code}|{unidad}|{resumen}|{precio}||0|")
    out = "\r\n".join(lines) + "\r\n\x1a"
    return out


if __name__ == "__main__":
    demo = "~V||FIEBDC-3/2024|Demo|\r\n~C|E01|m2|Tabique LH7|22,50||0|\r\n\x1a"
    print("Parsed:", parse_bc3(demo))
    print("Written:")
    print(repr(write_bc3([{"code": "E01", "unidad": "m2",
                           "descripcion": "Tabique LH7", "precio_unitario": 22.5}])))
