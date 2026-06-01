"""
engine.py — Deterministic forward-chaining rule engine (seed).

CLIPS-style production system, construction-estimating scoped. This is the
RUNTIME. It is deterministic: same facts + same rules => same presupuesto.

Knowledge (rules) lives in rules.json. Prices live in the price catalogue.
NOTHING domain-specific is hard-coded here. If you find yourself adding a
euro figure or a markup percentage to this file, stop — it belongs in a rule.

Authoring (writing/editing rules) is done OFFLINE by Claude Code.
This file only fires them.

Pattern mirrors Organica's production-rule layer and the Oakmore
"logic-in-config-not-code" convention.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Callable
import json
import itertools


# --------------------------------------------------------------------------
# WORKING MEMORY — append-only fact store with provenance (Organica rule)
# --------------------------------------------------------------------------

@dataclass
class Fact:
    """A typed fact. `kind` is the template name; `data` is its fields.
    `produced_by` records the rule that asserted it — provenance is mandatory."""
    kind: str
    data: dict[str, Any]
    produced_by: str = "ingesta"
    _id: int = field(default=0)

    def __getitem__(self, k): return self.data[k]
    def get(self, k, default=None): return self.data.get(k, default)


class WorkingMemory:
    """Append-only. Facts are never mutated, only superseded by new facts."""

    def __init__(self) -> None:
        self._facts: list[Fact] = []
        self._counter = itertools.count(1)

    def assert_fact(self, kind: str, data: dict, produced_by: str = "ingesta") -> Fact:
        f = Fact(kind=kind, data=data, produced_by=produced_by, _id=next(self._counter))
        self._facts.append(f)
        return f

    def query(self, kind: str, **filters) -> list[Fact]:
        out = []
        for f in self._facts:
            if f.kind != kind:
                continue
            if all(f.get(k) == v for k, v in filters.items()):
                out.append(f)
        return out

    def all(self) -> list[Fact]:
        return list(self._facts)


# --------------------------------------------------------------------------
# RULE — a named, declarative unit. condition(wm) -> matches; action(wm, m).
# --------------------------------------------------------------------------

@dataclass
class Rule:
    name: str
    salience: int            # higher fires first (CLIPS conflict resolution)
    family: str              # mapping | pricing | measurement | costing | stock | regulatory
    condition: Callable[[WorkingMemory], list[dict]]
    action: Callable[[WorkingMemory, dict], None]


class Engine:
    """Forward-chaining inference. Fires rules by salience until no rule
    produces new facts (fixpoint). Deterministic ordering throughout."""

    def __init__(self, wm: WorkingMemory) -> None:
        self.wm = wm
        self.rules: list[Rule] = []
        self.fired_log: list[str] = []

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def run(self, max_cycles: int = 1000) -> None:
        for _ in range(max_cycles):
            before = len(self.wm.all())
            # conflict set ordered by salience desc, then rule name for determinism
            for rule in sorted(self.rules, key=lambda r: (-r.salience, r.name)):
                for match in rule.condition(self.wm):
                    rule.action(self.wm, match)
                    self.fired_log.append(rule.name)
            if len(self.wm.all()) == before:
                break   # fixpoint: no new facts asserted


# --------------------------------------------------------------------------
# COSTING — the RD 1098/2001 build-up. Percentages come from project-param
# facts (seeded from rules.json), never literals here.
# --------------------------------------------------------------------------

def compute_presupuesto(wm: WorkingMemory) -> dict:
    """Aggregate partida facts into the regulated cost build-up.
    All percentages are read from project-param facts."""
    def param(clave, default):
        rows = wm.query("project-param", clave=clave)
        return float(rows[-1]["valor"]) if rows else default

    gg_pct = param("gg_pct", 0.13)
    bi_pct = param("bi_pct", 0.06)
    iva_pct = param("iva_pct", 0.10)
    icio_pct = param("icio_pct", 0.0)

    partidas = wm.query("partida")
    pem = round(sum(float(p["importe"]) for p in partidas if p.get("importe") is not None), 2)
    gg = round(pem * gg_pct, 2)
    bi = round(pem * bi_pct, 2)
    pec = round(pem + gg + bi, 2)
    iva = round(pec * iva_pct, 2)
    total = round(pec + iva, 2)
    icio = round(pem * icio_pct, 2)

    result = {
        "PEM": pem, "GG": gg, "BI": bi, "PEC": pec,
        "IVA": iva, "TOTAL": total, "ICIO": icio,
        "gg_pct": gg_pct, "bi_pct": bi_pct, "iva_pct": iva_pct,
    }
    for k, v in result.items():
        wm.assert_fact("metric-result", {"clave": k, "valor": v}, produced_by="compute_presupuesto")
    return result


def compute_plan_acopios(wm: WorkingMemory) -> list[dict]:
    """Aggregate material-line facts into a consolidated stock plan,
    applying merma. Rounding to supplier pack size is a stock RULE, not here."""
    agg: dict[str, dict] = {}
    for ml in wm.query("material-line"):
        code = ml["material_code"]
        merma = float(ml.get("merma_pct", 0.0))
        qty = float(ml["cantidad"]) * (1 + merma)
        if code not in agg:
            agg[code] = {"material_code": code, "descripcion": ml.get("descripcion", ""),
                         "unidad": ml.get("unidad", ""), "cantidad": 0.0}
        agg[code]["cantidad"] += qty
    plan = [dict(v, cantidad=round(v["cantidad"], 3)) for v in agg.values()]
    for row in plan:
        wm.assert_fact("acopio", row, produced_by="compute_plan_acopios")
    return plan


# --------------------------------------------------------------------------
# RULE LOADER — turns rules.json into Rule objects. This is where Claude Code's
# authored knowledge becomes executable. The JSON declares conditions/actions
# in a small DSL; the loader compiles them. (Seed: handles the common cases;
# Claude Code extends the DSL as needed.)
# --------------------------------------------------------------------------

def load_rules(path: str, engine: Engine) -> None:
    with open(path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)

    # seed project parameters as facts
    for clave, valor in spec.get("parameters", {}).items():
        engine.wm.assert_fact("project-param", {"clave": clave, "valor": valor})

    for r in spec.get("rules", []):
        engine.add_rule(_compile_rule(r))


def _compile_rule(r: dict) -> Rule:
    """Compile one JSON rule into a Rule. The DSL is intentionally small;
    Claude Code grows it. Supported action: 'assert' a fact built from a
    matched fact via field templating."""
    when = r["when"]          # {"kind": "...", "filters": {...}}
    then = r["then"]          # {"assert": {"kind": "...", "data": {...}}}

    def condition(wm: WorkingMemory) -> list[dict]:
        matches = []
        for f in wm.query(when["kind"], **when.get("filters", {})):
            # skip if this rule already produced output for this fact (idempotency)
            tag = f"{r['name']}::{f._id}"
            if not wm.query("_fired", tag=tag):
                matches.append({"src": f, "tag": tag})
        return matches

    def action(wm: WorkingMemory, m: dict) -> None:
        src = m["src"]
        out = then["assert"]
        data = {k: _resolve(v, src) for k, v in out["data"].items()}
        wm.assert_fact(out["kind"], data, produced_by=r["name"])
        wm.assert_fact("_fired", {"tag": m["tag"]}, produced_by=r["name"])

    return Rule(name=r["name"], salience=r.get("salience", 0),
                family=r.get("family", "mapping"),
                condition=condition, action=action)


def _resolve(template: Any, src: Fact) -> Any:
    """Resolve {field} references against the source fact. Literals pass through."""
    if isinstance(template, str) and template.startswith("{") and template.endswith("}"):
        return src.get(template[1:-1])
    return template


# --------------------------------------------------------------------------
# DEMO — wire it together. Replace ingesta with real memoria/price parsing.
# --------------------------------------------------------------------------

if __name__ == "__main__":
    wm = WorkingMemory()
    eng = Engine(wm)

    # 1. ingesta (stub) — normally parsed from memoria + price catalogue
    wm.assert_fact("project-param", {"clave": "gg_pct", "valor": 0.13})
    wm.assert_fact("project-param", {"clave": "bi_pct", "valor": 0.06})
    wm.assert_fact("project-param", {"clave": "iva_pct", "valor": 0.10})
    wm.assert_fact("partida", {"code": "E01", "capitulo": "Albañilería",
                               "descripcion": "Tabique LH7", "unidad": "m2",
                               "medicion": 40, "precio_unitario": 22.5, "importe": 900.0})
    wm.assert_fact("partida", {"code": "E02", "capitulo": "Acabados",
                               "descripcion": "Enlucido yeso", "unidad": "m2",
                               "medicion": 80, "precio_unitario": 9.0, "importe": 720.0})

    # 2. run rules (none loaded in this stub — engine still computes totals)
    eng.run()
    totals = compute_presupuesto(wm)

    print("PRESUPUESTO (demo):")
    for k in ("PEM", "GG", "BI", "PEC", "IVA", "TOTAL"):
        print(f"  {k:5} = {totals[k]:>12,.2f} €")
