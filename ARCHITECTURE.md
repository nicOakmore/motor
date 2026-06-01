# Motor de Presupuestos — Architecture Foundation

**Purpose.** A Python rule-engine application, driven through Claude Code as its UI, that
generates automated construction *presupuestos* (budgets) for an Ibiza/Spain construction
firm. Input is a *memoria constructiva* (construction memory/scope) plus price lists
(from the web and from a local folder). Output is a structured, regulation-compliant
budget plus a material stock/procurement plan and a work plan.

This document is the **basis** Claude Code uses to build the app. It is not the finished
app. It defines: (1) the rule-engine architecture, (2) the seed Python code, (3) what to
put in Claude Code to use Claude Code as the UI.

---

## 1. Design lineage (reuse, don't reinvent)

This borrows two patterns the firm already validated:

- **Organica** — the LLM-as-knowledge-engineer / deterministic-runtime split. The LLM
  (here, Claude Code) authors and edits rules *offline*; a deterministic Python engine
  fires them *at runtime*. Every line of the presupuesto traces to a named rule. This is
  the auditability requirement that Spanish budgets demand (every partida must be
  justifiable).
- **Oakmore app conventions** — knowledge lives in `rules.json` and price data in JSON,
  never hard-coded in Python. One concern per file. If changing a markup or a measurement
  criterion requires editing Python, the architecture is wrong: it belongs in a rule file.

The engine is **CLIPS-style forward chaining** (Rete-like), authored as declarative rules,
exactly as Organica's production-rule layer — but scoped to construction estimating
instead of fraud detection.

---

## 2. The domain, encoded correctly (Spain + Ibiza)

The engine must produce a budget that maps to the Spanish standard. These are facts the
rules enforce, not opinions:

### 2.1 Budget hierarchy (FIEBDC-3 / BC3 standard)

```
OBRA (project)
└── CAPÍTULO (chapter — follows execution order)
    └── PARTIDA (line item, has a unit of measure)
        └── DESCOMPUESTO (breakdown: mano de obra + materiales + maquinaria + % medios aux.)
```

Chapters follow the logical construction sequence:
`derribos → movimiento de tierras → cimentación → estructura → cubiertas →
cerramientos → instalaciones → acabados → urbanización`.

Each partida = **medición × precio unitario = importe**. No medición, no partida.

### 2.2 The cost build-up (RD 1098/2001 — mandatory percentages)

```
PEM   (Presupuesto de Ejecución Material)  = Σ partidas
      Costes indirectos                     ≈ 6%  (folded into precios unitarios)
PEC   (Presupuesto de Ejecución por Contrata) = PEM × (1 + 0.13 + 0.06)
      ├── Gastos Generales (GG)              = 13% of PEM
      └── Beneficio Industrial (BI)          = 6%  of PEM
Base imponible                              = PEC
IVA   = 10%  (vivienda habitual, Ley 37/1992 art. 91.uno.2)
      = 21%  (resto: comercial, obra nueva de promoción, etc.)
TOTAL = Base imponible × (1 + IVA)
```

These percentages are the **public-works reference**; private budgets may adjust GG/BI but
the structure is identical. They live in `rules.json` as parameters, never as Python
literals.

### 2.3 Ibiza / Balearic regulatory layer

The engine flags (does not decide — flags for the technician) the permit regime, because
it changes what documentation the budget must carry:

- **LUIB — Ley 12/2017 de Urbanismo de las Illes Balears**, art. 146: works needing a
  *proyecto técnico* (Ley 38/1999 LOE) require **licencia urbanística municipal previa**.
  Minor works may go by **comunicación previa / declaración responsable**.
- **ICIO** (Impuesto sobre Construcciones, Instalaciones y Obras) applies in both cases —
  computed on PEM, municipal rate (Eivissa/Ibiza town rates differ; parameterised).
- Rústico/urbano distinction in Ibiza is high-risk (legalisation regimes,
  Ley 7/2024). The engine raises a `WARN` fact when scope hits rústico keywords; it never
  asserts legality.
- Mandatory annexes when a proyecto técnico applies: Estudio de Seguridad y Salud
  (RD 1627/1997), Gestión de residuos RCD (RD 105/2008), plan de control de calidad (CTE),
  plan de obra (Gantt).

### 2.4 Output artefacts the engine must be able to emit

1. **Presupuesto** — capítulos/partidas/descompuestos, PEM, PEC, IVA, total.
2. **Cuadro de precios nº1** (unit prices in figures + letters) and **nº2** (descompuestos).
3. **Plan de acopios / stock de material** — aggregated material quantities across all
   partidas, grouped by material, with supplier and lead-time fields.
4. **Plan de obra** — chapters sequenced with durations → Gantt-ready data.
5. **BC3 export** — FIEBDC-3 plain-text file for interop with Presto/Arquímedes/CYPE.
6. **Banderas regulatorias** — the permit/annex checklist for Ibiza.

---

## 3. Five-layer architecture (Organica-derived, construction-scoped)

```
A — INGESTA         Memoria constructiva (text/PDF) + price lists (web + local folder)
                    → parsed into typed facts. BDI-style: each source is an agent.
B — NORMALIZACIÓN   Canonical price catalogue: every price → {code, unit, mo, mat, maq,
                    indirectos, source, date, ámbito}. De-dup, currency, VAT-exclusive.
C — MOTOR DE REGLAS Forward-chaining CLIPS-style engine. Rules map memoria scope → partidas,
                    select prices, apply measurement criteria, compute descompuestos,
                    apply GG/BI/IVA, raise regulatory flags. Deterministic + auditable.
D — OPTIMIZACIÓN    (optional, later) material stock optimisation: consolidate orders,
                    minimise waste/merma, batch by supplier/lead-time. NSGA-II hook reserved.
E — SALIDA          Presupuesto, cuadros de precios, plan de acopios, plan de obra, BC3,
                    checklist regulatorio. Rendered by Claude Code into PDF/XLSX/BC3.
```

The **LLM (Claude Code) sits at layer A and E**: it reads the messy memoria and authors
rules (offline), and it renders/explains output. The **deterministic engine is layer C**:
given the same facts and rules, it always produces the same budget. This separation is the
whole point — it is what makes the number defensible.

---

## 4. The fact model (what flows through the engine)

Typed facts, asserted into working memory. Mirrors CLIPS `deftemplate`.

| Fact type | Key fields |
|-----------|-----------|
| `scope-item` | id, descripción, capítulo, cantidad, unidad, fuente (memoria) |
| `price` | code, descripción, unidad, mo, mat, maq, indirectos_pct, fuente, fecha, ámbito |
| `partida` | code, capítulo, descripción, unidad, medición, precio_unitario, importe, price_ref |
| `material-line` | material_code, descripción, unidad, cantidad, partida_ref, merma_pct |
| `project-param` | clave, valor (gg_pct, bi_pct, iva_pct, icio_pct, municipio, uso) |
| `flag` | nivel (INFO/WARN/STOP), código, mensaje, regla_origen |
| `metric-result` | clave, valor (PEM, PEC, base, iva, total, plazo_dias) |

Working memory is **append-only** (Organica's provenance rule): every fact records the rule
that produced it. The presupuesto is then just a query over `partida` + `metric-result`
facts, and every number can be traced back to a rule + a price + a scope item.

---

## 5. Rule taxonomy (what lives in rules.json)

Six rule families, each authored by Claude Code, fired by the engine:

1. **Mapping rules** — `scope-item` → one or more `partida` (which work items a scope line
   implies). E.g. "tabique de ladrillo" → partida albañilería + partida enlucido + partida
   pintura.
2. **Pricing rules** — bind a `partida` to the best `price` (by ámbito = Balears/Ibiza
   first, then date, then source priority: local folder > BEDEC/ITeC > generic web).
3. **Measurement rules** — apply the correct *criterio de medición* (m², m³, ml, ud, kg) and
   merma/waste factors per material type.
4. **Costing rules** — fold indirectos into unit prices; compute PEM; apply GG 13%, BI 6%,
   IVA 10/21%; compute ICIO on PEM.
5. **Stock rules** — aggregate `material-line` facts across partidas into a consolidated
   `plan de acopios`, applying merma and rounding to supplier pack sizes.
6. **Regulatory rules** — raise `flag` facts for permit regime (licencia vs comunicación),
   required annexes, and rústico/urbano risk in Ibiza.

A rule never contains a hard-coded euro figure. Prices come from facts; percentages come
from `project-param` facts seeded from `rules.json` parameters.

---

## 6. Price-list ingestion (the two sources)

- **Local folder** (`./precios/`): drop BC3 files, XLSX price lists, or CSV. Highest
  priority. The firm's own negotiated prices live here. Parser reads BC3 `~C` records and
  tabular files into `price` facts.
- **Web**: public bases (BEDEC/ITeC, Generador CYPE, PREOC). Lower priority, used to fill
  gaps. Claude Code fetches and normalises these at authoring time; the engine only ever
  reads the normalised catalogue, never the live web.

Priority resolution is a pricing rule, not Python logic, so the firm can re-rank sources
without a code change.

---

## 7. Why this shape (the one-paragraph justification)

A construction budget in Spain is a legal-technical document: every partida must be
measurable, every price justifiable, the GG/BI/IVA build-up is fixed by RD 1098/2001, and
in Ibiza the permit regime changes the required annexes. A black-box LLM that "writes a
budget" cannot defend a single line. By making the LLM the *author* of declarative rules
and a deterministic engine the *executor*, every euro traces to a rule, a price, and a
scope item — and the same inputs always produce the same budget. That is the only shape
that survives a contradictory client, an inspection, or a dispute.
