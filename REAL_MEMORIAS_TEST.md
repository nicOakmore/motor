# Real-memoria parser smoke test — 2026-06-01

Three publicly-published Spanish proyectos básicos / de ejecución pulled
from municipal and college sources, run through the parser to expose what
the demo handles and what it doesn't.

## Sources

| File | Origin | Type | Pages | Size |
|---|---|---|---:|---:|
| `santjosep_ibiza.pdf` | [Ayto. Sant Josep de sa Talaia](https://www.santjosep.org/wp-content/uploads/2014/03/MEMORIA-PROYECTO-B%C3%81SICO-Y-DE-EJECUCI%C3%93N1.pdf) | Proyecto básico + ejecución, ampliación centro tercera edad | 240 | 4.3 MB |
| `porreres_mallorca.pdf` | [Ayto. Porreres](https://porreres.cat/sites/cilma_porreres/files/documents/memoria_descriptiva.pdf) | Cambio de uso, vivienda → agroturismo | 90+ | 4.5 MB |
| `coac_grancanaria.pdf` | [COAC Gran Canaria template](https://arquitectosgrancanaria.es/medios/documents/memorias/08.01.VU.1b.pdf) | Plantilla CTE vivienda unifamiliar aislada | 30+ | 1.1 MB |

## Metadata extraction

|  | Promotor | Emplazamiento | Uso turístico |
|---|---|---|---|
| Sant Josep | ✅ `AYUNTAMIENTO DE SANT JOSEP DE SA TALAIA` | ✅ `AVENIDA SAN AGUSTÍN Nº80, CALA DE BOU` | ✅ False (no false positive on "establecimientos turísticos" CTE refs) |
| Porreres | ✅ `COZY PROPERTIES S.L` (multi-line layout — value on the line below `PROMOTOR:`) | ❌ no `EMPLAZAMIENTO:` label; address is typeset under the project title without a header field | ✅ False |
| COAC | ✅ template default value | ✅ `C/ Tedera s/n La Garita - Telde, Gran Canaria` | ✅ False |

**Fixes applied during this test:**
1. Tightened `USO_TURISTICO_IBIZA` regex to require an explicit `uso/destino turístico`, `alquiler turístico/vacacional`, `vivienda turística` or `ETV` — plain `turístico` was firing on CTE fire-safety references.
2. Search only the first 10 000 chars of the document (title page region); real proyectos repeat the same labels in legal clauses deep in the body.
3. Two-pass label lookup: prefer ALL-CAPS layout, then case-insensitive fallback that rejects values starting with a clause body (`a las …`, `el …`, etc.).
4. Spanish plural `PROMOTORES` / `EMPLAZAMIENTOS` now matched via `(?:ES|S)?`.

## Partida extraction

All three returned **0 partidas**. Expected: real memorias narrate the
scope in prose + tables + reference dimensions; the partida-with-medición
lines we parse from the demo memorias only appear in a separate
*Mediciones y Presupuesto* document (or as a `.bc3` export), not in the
descriptive memoria itself.

**What this means for the demo:**

- The pipeline reads the memoria for **project metadata**. ✅
- For partidas the real workflow needs the firm's
  *Mediciones y Presupuesto* document. Three viable paths to wire it up:
  - **BC3 import** — `bc3.parse_bc3()` already reads `~C` records into
    `price` facts; extending it to ingest `~D` (descomposición) and `~M`
    (medición) records would let the engine pick up partidas directly
    from Presto/Arquímedes/CYPE exports.
  - **In-app editor** — what the current demo offers: upload memoria for
    metadata, then add partidas from the 111-entry catalogue via the
    editor. Already works.
  - **LLM-assisted scope extraction** — feed the memoria prose to an LLM
    offline, propose `scope-item` facts, technician approves. Punch-listed.

## What still needs work (real-world tweaks)

- Address detection in label-less layouts (Porreres-style): a CP+ciudad
  regex (`\b\d{5}\s+\w+`) would catch the project address typeset under
  the title without a header field.
- Auto-detect `requiere_proyecto = true` from broader signals (the
  document title contains "PROYECTO BÁSICO Y DE EJECUCIÓN", surface is
  vivienda, etc.) — currently relies on the literal string "REQUIERE
  PROYECTO TÉCNICO" which our markdown sample uses but real PDFs don't.
- Detect `suelo = rústico` from real PDF prose ("polígono / parcela"
  references, mention of "suelo rústico común", "régimen ANEI/ARIP").
