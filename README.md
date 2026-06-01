# Motor de Presupuestos

Construction-budget rule engine for Ibiza/Baleares.

- **Engine** — pure-Python forward-chaining (CLIPS-style). `engine.py`.
- **Knowledge** — declarative rules in `rules.json`.
- **Catalogue** — price lists in `precios/` (CSV / BC3 / XLSX).
- **CLI** — `python run_demo.py memorias/<file>.md` writes to `salidas/`.
- **Web** — Flask app (`app.py`) that accepts memorias and serves the salidas.
- **PDF** — one-page Spanish explainer, `python generate_pdf.py`.

The full design (Spanish/Ibiza regulatory basis, fact model, rule families) is in `ARCHITECTURE.md`. The contract Claude Code operates under is in `CLAUDE.md`.

## Run locally

```bash
pip install -r requirements.txt
python run_demo.py                          # process every memoria in ./memorias/
python app.py                               # web UI at http://localhost:5000
python generate_pdf.py                      # writes salidas/como_funciona.pdf
```

## Deploy to Render

The repo includes `render.yaml`. From the Render dashboard:

1. **New +** → **Blueprint**.
2. Connect this GitHub repo.
3. Render reads `render.yaml` and provisions a free Python web service.
4. First build takes ~2 minutes (pip install). Subsequent deploys are incremental on push.

Routes once live:

- `/` — upload / pick sample
- `/j/<job_id>` — results page
- `/como-funciona.pdf` — one-page Spanish explainer

Notes:

- Render's free plan has **ephemeral disk** — uploaded memorias and their salidas live only until the next deploy or sleep. That's fine for a sample.
- The free instance **sleeps after 15 minutes** of inactivity; first request after sleep takes ~30 s.
- To switch to a paid plan, change `plan: free` in `render.yaml`.

## Project layout

```
engine.py          deterministic forward-chaining engine
bc3.py             FIEBDC-3 reader/writer
rules.json         knowledge base
run_demo.py        CLI runner (ingesta → engine → render)
generate_pdf.py    one-page Spanish PDF
app.py             Flask web wrapper
templates/         Jinja templates
static/style.css   minimal styling
memorias/          sample memorias constructivas
precios/           sample price catalogue
salidas/           generated artefacts (CLI) / committed PDF
```
