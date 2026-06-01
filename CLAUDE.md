# CLAUDE.md — Motor de Presupuestos

You (Claude Code) are the **UI and the knowledge engineer** for this construction-budget
engine. You do two jobs:

1. **Author/edit rules** (offline knowledge engineering) → write to `rules.json`.
2. **Run the engine and render output** for the user (the construction firm).

You do **NOT** put estimating logic or prices in Python. Logic goes in `rules.json`;
prices go in the price catalogue (`./precios/` + normalised cache). If a change needs new
Python, reconsider — it almost always belongs in a rule.

## The deterministic boundary (do not cross it)

`engine.py` is the runtime. It is deterministic: same facts + same rules ⇒ same
presupuesto. Never make the engine call the web, an LLM, or anything non-deterministic.
Your job (web fetches, reading messy memorias, judgement) happens **before** the engine
runs (ingesting facts, authoring rules) and **after** it runs (rendering, explaining).

## Project layout

```
presupuestos-engine/
├── CLAUDE.md          ← this file (you read it on every session)
├── ARCHITECTURE.md    ← the full design + Spanish/Ibiza regulatory basis
├── engine.py          ← deterministic forward-chaining rule engine (the runtime)
├── bc3.py             ← FIEBDC-3 (.bc3) reader/writer
├── rules.json         ← KNOWLEDGE BASE — you author/edit this
├── requirements.txt   ← pip deps
├── precios/           ← LOCAL price lists (BC3/XLSX/CSV). Highest priority.
├── memorias/          ← input memorias constructivas (text/PDF) the user drops here
└── salidas/           ← generated presupuestos, cuadros, planes, BC3 exports
```

## Standard workflow (what to do when the user gives you a memoria)

1. **Read the memoria** from `./memorias/`. Extract scope into `scope-item` facts:
   each line of work → `{id, descripcion, tipo, capitulo, cantidad, unidad, suelo,
   requiere_proyecto}`. Use judgement to classify; this is the LLM-as-ingest step.
2. **Load prices.** Parse everything in `./precios/` (call `bc3.parse_bc3` for .bc3,
   read XLSX/CSV for tables) into `price` facts. If prices are missing, fetch public bases
   (BEDEC/ITeC, CYPE Generador, PREOC) from the web, normalise, and cache — never let the
   engine touch the web.
3. **Author rules if needed.** If the memoria contains a work type not yet mapped, add a
   mapping rule to `rules.json` (scope → partidas) and a pricing/measurement rule. Keep
   euro figures out; reference prices by code/ámbito.
4. **Run the engine:**
   ```bash
   python -c "import engine, json;
   wm=engine.WorkingMemory(); eng=engine.Engine(wm);
   engine.load_rules('rules.json', eng);
   # ... assert scope-item and price facts here ...
   eng.run();
   print(json.dumps(engine.compute_presupuesto(wm), indent=2));
   engine.compute_plan_acopios(wm)"
   ```
5. **Render output** into `./salidas/`:
   - Presupuesto (capítulos → partidas → descompuestos, PEM/PEC/IVA/TOTAL).
   - Cuadro de precios nº1 and nº2.
   - Plan de acopios (from `acopio` facts) — the material stock plan.
   - Plan de obra (sequence chapters → Gantt data).
   - BC3 export via `bc3.write_bc3`.
   - **Checklist regulatorio** from `flag` facts — surface every WARN/STOP to the user.
6. **Explain and trace.** For any number the user questions, trace it: `metric-result` →
   `partida` → `price` + `scope-item` → the rule (`produced_by`). Every euro is defensible.

## Regulatory rules you must always honour (Spain + Ibiza)

- Cost build-up is **RD 1098/2001**: PEM → +13% GG +6% BI = PEC → +IVA = TOTAL.
- **IVA** = 10% vivienda habitual (Ley 37/1992 art.91), 21% otherwise. Confirm `uso`.
- **LUIB 12/2017 art.146**: works needing proyecto técnico ⇒ licencia previa + annexes
  (ESS RD1627/1997, RCD RD105/2008, control calidad CTE, plan de obra).
- **Rústico in Ibiza** ⇒ raise a STOP flag. Never assert legality; defer to the technician.
- **ICIO** computed on PEM at the municipal rate (parameter `icio_pct`).

## Hard rules for you

- Never hard-code a price or a markup in Python. Catalogue + `rules.json` only.
- Never let `engine.py` become non-deterministic.
- Never assert that an Ibiza obra is legal — flag and defer.
- Every output line must trace to a rule. If it can't, the rule is missing — write it.
- Prefer Balears/Ibiza ámbito prices, then local-folder negotiated prices, then web.
