"""
app.py — Flask wrapper around the Motor de Presupuestos.

Routes:
  GET  /                     upload form + sample picker
  POST /run                  ingest the chosen/uploaded memoria, run the engine
  GET  /j/<job_id>           results page with summary + downloads
  GET  /j/<job_id>/<file>    download an artefact
  GET  /como-funciona.pdf    the one-page Spanish PDF (regenerated on first hit)

Each upload gets its own job directory under JOBS_ROOT to keep state isolated.
On Render the filesystem is ephemeral — that's fine, this is a sample app.
"""

from __future__ import annotations
import csv
import hmac
import io
import json
import os
import pathlib
import re
import secrets
import shutil
import tempfile
import urllib.error
import urllib.request
from typing import Iterable

from flask import (
    Flask, Response, abort, jsonify, redirect, render_template,
    request, send_file, url_for,
)
from werkzeug.utils import secure_filename

import bc3
import run_demo
import llm_extract


ROOT = pathlib.Path(__file__).parent
SAMPLE_MEMORIAS_DIR = ROOT / "memorias"
PDF_OUT = ROOT / "salidas" / "como_funciona.pdf"

# Job storage: /tmp on Render (ephemeral); cwd-local elsewhere. Override via env.
JOBS_ROOT = pathlib.Path(
    os.environ.get("JOBS_ROOT") or (tempfile.gettempdir() + "/rex-jobs")
)
JOBS_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".md", ".txt", ".pdf", ".bc3"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024     # 8 MB — fits PDF memorias with images


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# --------------------------------------------------------------------------
# HTTP Basic Auth (credentials from env, never hard-coded).
# Set BASIC_AUTH_USER and BASIC_AUTH_PASS to enable. Empty/unset = open.
# /healthz and /robots.txt are excluded so platform pings and crawlers
# (which we want to bounce, not authenticate) keep working.
# --------------------------------------------------------------------------

AUTH_USER = os.environ.get("BASIC_AUTH_USER", "").strip()
AUTH_PASS = os.environ.get("BASIC_AUTH_PASS", "").strip()
OPEN_PATHS = {"/healthz", "/robots.txt"}


def _auth_ok(req) -> bool:
    if not (AUTH_USER and AUTH_PASS):
        return True
    a = req.authorization
    if not a or a.type != "basic":
        return False
    # constant-time compare to avoid timing oracles
    return (hmac.compare_digest(a.username or "", AUTH_USER)
            and hmac.compare_digest(a.password or "", AUTH_PASS))


@app.before_request
def _require_auth():
    if request.path in OPEN_PATHS:
        return None
    if _auth_ok(request):
        return None
    return Response(
        "Autenticación requerida.", 401,
        {"WWW-Authenticate": 'Basic realm="Motor de Presupuestos", charset="UTF-8"'},
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _new_job_id() -> str:
    return secrets.token_urlsafe(9)


def _job_dir(job_id: str) -> pathlib.Path:
    if not JOB_ID_RE.match(job_id):
        abort(404)
    d = JOBS_ROOT / job_id
    if not d.is_dir():
        abort(404)
    return d


def _list_samples() -> list[pathlib.Path]:
    paths = []
    for ext in ("*.md", "*.pdf", "*.bc3"):
        paths.extend(SAMPLE_MEMORIAS_DIR.glob(ext))
    return sorted(paths)


def _ensure_pdf() -> pathlib.Path:
    if not PDF_OUT.exists():
        import generate_pdf
        generate_pdf.build()
    return PDF_OUT


def _fmt_eur(n: float) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


app.jinja_env.filters["eur"] = _fmt_eur


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template(
        "index.html",
        samples=[p.name for p in _list_samples()],
    )


@app.post("/run")
def run():
    """Accept either an uploaded file (form field 'memoria') or a sample name
    (form field 'sample'). Runs the engine and redirects to the result page."""
    job_id = _new_job_id()
    job_root = JOBS_ROOT / job_id
    inbox = job_root / "input"
    inbox.mkdir(parents=True, exist_ok=True)

    src_path: pathlib.Path | None = None

    upload = request.files.get("memoria")
    sample = request.form.get("sample", "").strip()

    if upload and upload.filename:
        name = secure_filename(upload.filename) or "memoria.md"
        if pathlib.Path(name).suffix.lower() not in ALLOWED_EXT:
            return _err("Formato no permitido. Sube .md o .txt.", 400)
        src_path = inbox / name
        upload.save(src_path)
    elif sample:
        # whitelist: only files that actually exist in the sample dir
        sample_path = SAMPLE_MEMORIAS_DIR / secure_filename(sample)
        if not sample_path.is_file() or sample_path.parent.resolve() != \
                SAMPLE_MEMORIAS_DIR.resolve():
            return _err("Muestra desconocida.", 400)
        src_path = inbox / sample_path.name
        shutil.copy2(sample_path, src_path)
    else:
        return _err("Sube una memoria o elige una de muestra.", 400)

    out_root = job_root / "salidas"
    try:
        result = run_demo.run_for_memoria(src_path, out_root=out_root, verbose=False)
    except Exception as exc:                          # noqa: BLE001
        return _err(f"Fallo al procesar la memoria: {exc}", 500)

    # Persist a tiny manifest for the result page (don't re-run the engine).
    manifest = {
        "memoria_name": src_path.name,
        "out_subdir": result["out_dir"].relative_to(out_root).as_posix(),
        "meta": result["meta"],
        "totales": result["totales"],
        "flags": result["flags"],
        "partidas": result["partidas"],
        "acopios": result["acopios"],
    }
    (job_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return redirect(url_for("result", job_id=job_id))


@app.get("/j/<job_id>")
def result(job_id: str):
    d = _job_dir(job_id)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    out_dir = d / "salidas" / manifest["out_subdir"]
    artefacts = sorted(p.name for p in out_dir.glob("*") if p.is_file())

    # Group partidas by capítulo, preserving the rules.json order if present.
    cap_order = []
    try:
        rules_spec = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
        cap_order = rules_spec.get("capitulo_orden", []) or []
    except Exception:                                 # noqa: BLE001
        pass
    by_cap: dict[str, list[dict]] = {}
    for p in manifest["partidas"]:
        by_cap.setdefault(p["capitulo"], []).append(p)
    ordered_caps = [c for c in cap_order if c in by_cap] + \
                   [c for c in by_cap if c not in cap_order]
    grouped = [(cap, by_cap[cap]) for cap in ordered_caps]

    return render_template(
        "result.html",
        job_id=job_id,
        manifest=manifest,
        artefacts=artefacts,
        grouped=grouped,
        llm_enabled=llm_extract.llm_enabled(),
    )


@app.get("/j/<job_id>/edit")
def edit(job_id: str):
    """Render the partida editor for the given job."""
    d = _job_dir(job_id)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    catalogue = run_demo.load_price_catalogue()
    rules_spec = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    params = rules_spec.get("parameters", {})
    return render_template(
        "edit.html",
        job_id=job_id,
        manifest=manifest,
        catalogue=sorted(catalogue, key=lambda r: r["code"]),
        params=params,
    )


@app.post("/j/<job_id>/save")
def save_edits(job_id: str):
    """Accept edited partidas + project-param overrides, recompute totales,
    regenerate every output artefact. The original regulatory flags from
    the first run are preserved (edits don't re-fire mapping rules)."""
    d = _job_dir(job_id)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))

    rules_spec = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    catalogue = {row["code"]: row for row in run_demo.load_price_catalogue()}
    metadata = rules_spec.get("concepto_metadata", {})
    # secondary lookup: capitulo / unidad by price_code so newly-added rows
    # from the catalogue get their meta filled in.
    code_to_meta = {v["price_code"]: v for v in metadata.values()
                    if isinstance(v, dict) and v.get("price_code")}

    # Project-param overrides. The form uses whole-percent inputs (e.g. "10"
    # for 10%); convert to fractions consistent with rules.json.
    params = dict(rules_spec.get("parameters", {}))
    for key in ("gg_pct", "bi_pct", "iva_pct", "retencion_irpf_pct",
                "recargo_equivalencia_pct"):
        raw = (request.form.get(f"pp_{key}") or "").strip()
        if not raw:
            continue
        try:
            v = float(raw.replace(",", "."))
        except ValueError:
            continue
        if v > 1.0:                 # whole-percent → fraction
            v = v / 100.0
        params[key] = v
    rules_spec["parameters"] = params

    # Parse partidas — fields are p_<idx>_<field>.
    indices = set()
    for k in request.form:
        m = re.match(r"^p_(\d+)_", k)
        if m:
            indices.add(int(m.group(1)))
    edited: list[dict] = []
    counter = 0
    for i in sorted(indices):
        if request.form.get(f"p_{i}_remove") == "1":
            continue
        code = (request.form.get(f"p_{i}_code") or "").strip()
        # New rows may not have a code yet — get one from a fresh
        # catalogue selection field.
        if not code:
            code = (request.form.get(f"p_{i}_new_from_catalogue") or "").strip()
        try:
            medicion = float((request.form.get(f"p_{i}_medicion") or "0").replace(",", "."))
        except ValueError:
            medicion = 0.0
        if medicion <= 0:
            continue
        try:
            precio = float((request.form.get(f"p_{i}_precio_unitario") or "0").replace(",", "."))
        except ValueError:
            precio = 0.0
        cat = catalogue.get(code, {})
        meta_entry = code_to_meta.get(code, {})
        descripcion = (request.form.get(f"p_{i}_descripcion") or
                       cat.get("descripcion") or
                       meta_entry.get("descripcion_corta") or
                       code or "")
        unidad = (request.form.get(f"p_{i}_unidad") or
                  cat.get("unidad") or meta_entry.get("unidad") or "ud")
        capitulo = (request.form.get(f"p_{i}_capitulo") or
                    meta_entry.get("capitulo") or "Sin capítulo")
        iva_raw = (request.form.get(f"p_{i}_iva_pct") or "").strip()
        iva_pct = None
        if iva_raw:
            try:
                iva_pct = float(iva_raw.replace(",", "."))
                if iva_pct > 1.0:        # user typed "10" meaning 10%
                    iva_pct = iva_pct / 100.0
            except ValueError:
                iva_pct = None
        # If no precio supplied, use catalogue default.
        if precio == 0.0:
            precio = float(cat.get("precio_unitario") or 0.0)
        counter += 1
        partida = {
            "code": f"P{counter:03d}",
            "capitulo": capitulo,
            "descripcion": descripcion,
            "unidad": unidad,
            "medicion": medicion,
            "precio_unitario": precio,
            "importe": round(medicion * precio, 2),
            "price_ref": code,
        }
        if iva_pct is not None:
            partida["iva_pct"] = iva_pct
        edited.append(partida)

    if not edited:
        return _err("El presupuesto no puede quedarse sin partidas.", 400)

    totales = run_demo.recompute_totales(edited, rules_spec)

    out_dir = (d / "salidas" / manifest["out_subdir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Regulatory flags from the initial run are preserved; the editor doesn't
    # re-run mapping rules.
    new = run_demo.write_artefacts(
        out_dir=out_dir,
        meta=manifest["meta"],
        partidas=edited,
        totales=totales,
        flags=manifest.get("flags", []),
        acopios=manifest.get("acopios", []),
        trace_rows=[],
        rules_spec=rules_spec,
        project_title=manifest.get("memoria_name", "").replace(".md", ""),
    )

    # Refresh manifest.json with the new totales + partidas; preserve fields
    # the editor doesn't touch.
    new_manifest = {
        **manifest,
        "totales": new["totales"],
        "partidas": new["partidas"],
        "edited": True,
    }
    (d / "manifest.json").write_text(
        json.dumps(new_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return redirect(url_for("result", job_id=job_id))


@app.get("/j/<job_id>/<path:filename>")
def download(job_id: str, filename: str):
    d = _job_dir(job_id)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    out_dir = (d / "salidas" / manifest["out_subdir"]).resolve()
    safe = secure_filename(filename)
    target = (out_dir / safe).resolve()
    # path traversal guard
    if not str(target).startswith(str(out_dir) + os.sep) or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=safe)


@app.get("/como-funciona.pdf")
def how_pdf():
    pdf = _ensure_pdf()
    return send_file(pdf, mimetype="application/pdf",
                     as_attachment=False, download_name="como_funciona.pdf")


@app.post("/j/<job_id>/llm-suggest")
def llm_suggest(job_id: str):
    """Offline LLM step: feed the memoria text to the model with the
    concepto_metadata catalogue, get back proposed scope-items, rerun
    the engine and regenerate every artefact. Strictly OPT-IN — controlled
    by LLM_ENABLED + GROQ_API_KEY env vars. The engine path is unchanged."""
    d = _job_dir(job_id)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if not llm_extract.llm_enabled():
        return _err("La extracción por IA está deshabilitada en este servidor.", 503)

    # Pick up the original memoria text from the job's input dir.
    inbox = d / "input"
    memoria_files = sorted(inbox.glob("*"))
    if not memoria_files:
        return _err("No se encontró la memoria original del job.", 404)
    memoria_path = memoria_files[0]
    try:
        memoria_text = run_demo._read_memoria_text(memoria_path)
    except Exception as exc:                          # noqa: BLE001
        return _err(f"No se pudo leer la memoria: {exc}", 500)

    rules_spec = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    concepto_metadata = rules_spec.get("concepto_metadata", {})

    try:
        propuestas = llm_extract.extract_scope(memoria_text, concepto_metadata)
    except llm_extract.LLMUnavailable as exc:
        return _err(str(exc), 503)
    except Exception as exc:                          # noqa: BLE001
        return _err(f"La IA no pudo proponer partidas: {exc}", 502)

    if not propuestas:
        # Bounce back with a flash-style message: keep the original outputs,
        # add a flag so the result page can show "AI couldn't extract anything".
        manifest.setdefault("llm_history", []).append({
            "model": llm_extract.DEFAULT_MODEL, "propuestas": 0,
        })
        (d / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return redirect(url_for("result", job_id=job_id) + "?llm=empty")

    # Re-run the engine with the LLM-proposed scope items mixed in.
    out_root = (d / "salidas").resolve()
    new = run_demo.rerun_with_extra_scope_items(
        memoria_path=memoria_path,
        extra_items=propuestas,
        out_root=out_root,
        rules_spec=rules_spec,
    )
    manifest.update({
        "totales": new["totales"],
        "partidas": new["partidas"],
        "flags": new["flags"],
        "acopios": new["acopios"],
        "llm_history": manifest.get("llm_history", []) + [{
            "model": llm_extract.DEFAULT_MODEL,
            "propuestas": len(propuestas),
        }],
    })
    (d / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("result", job_id=job_id) + "?llm=ok")


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


# --------------------------------------------------------------------------
# /admin — catálogo (CSV upload + fetch from a public URL)
# --------------------------------------------------------------------------

CATALOGUE_COLUMNS_REQUIRED = ("code", "unidad", "descripcion", "precio_unitario")
CATALOGUE_COLUMNS_OPTIONAL = ("mo", "mat", "maq", "indirectos_pct",
                              "ambito", "fuente", "fecha")
MAX_FETCH_BYTES = 4 * 1024 * 1024     # 4 MB cap on any fetched catalogue


PUBLIC_SOURCES = [
    {
        "name": "Comunidad de Madrid · Base de Precios",
        "url": "https://www.comunidad.madrid/servicios/vivienda/base-datos-construccion",
        "notes": "Base oficial. Publicación periódica (BC3 + XLSX). Necesita "
                 "buscar el enlace al BC3 más reciente en la página.",
    },
    {
        "name": "Junta de Extremadura · Base de Precios",
        "url": "https://basepreciosconstruccion.gobex.es/",
        "notes": "Base regional pública con descarga libre. Buscar el "
                 "enlace al BC3 de la edición vigente.",
    },
    {
        "name": "CYPE · Generador de Precios",
        "url": "https://generadordeprecios.info/",
        "notes": "Consulta gratuita por partida. No descarga el catálogo "
                 "entero; útil para verificar partidas concretas.",
    },
    {
        "name": "ITeC · BEDEC (demo gratuita)",
        "url": "https://en.itec.cat/services/bedec/",
        "notes": "Comunidad ITeC: 15 consultas/mes gratis. Suscripción para "
                 "descarga masiva.",
    },
    {
        "name": "PREOC · Precios de la Construcción",
        "url": "https://www.preoc.es/",
        "notes": "Catálogo comercial. Suscripción para descarga.",
    },
    {
        "name": "INE · Índice de precios de materiales",
        "url": "https://www.ine.es/uc/hAB1z7WY",
        "notes": "Estadística oficial — no es un catálogo de partidas pero "
                 "sirve para indexar precios.",
    },
]


def _csv_rows_to_catalogue(text: str) -> list[dict]:
    """Parse CSV text, validate required columns, return canonical rows."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("El CSV está vacío o sin cabecera.")
    missing = [c for c in CATALOGUE_COLUMNS_REQUIRED if c not in reader.fieldnames]
    if missing:
        raise ValueError(
            f"Faltan columnas obligatorias: {', '.join(missing)}. "
            f"Requeridas: {', '.join(CATALOGUE_COLUMNS_REQUIRED)}."
        )
    rows: list[dict] = []
    for raw in reader:
        code = (raw.get("code") or "").strip()
        if not code:
            continue
        try:
            precio = float((raw.get("precio_unitario") or "0").replace(",", "."))
        except (TypeError, ValueError):
            precio = 0.0
        # Build a sanitised row using only known columns.
        row = {
            "code": code,
            "unidad": (raw.get("unidad") or "").strip(),
            "descripcion": (raw.get("descripcion") or "").strip(),
            "precio_unitario": f"{precio:.4f}",
        }
        for c in CATALOGUE_COLUMNS_OPTIONAL:
            v = raw.get(c)
            if v is not None:
                row[c] = v.strip() if isinstance(v, str) else v
        rows.append(row)
    if not rows:
        raise ValueError("El CSV no contiene filas válidas con columna `code`.")
    return rows


def _write_override_catalogue(rows: list[dict]) -> None:
    cols = list(CATALOGUE_COLUMNS_REQUIRED) + list(CATALOGUE_COLUMNS_OPTIONAL)
    run_demo.CATALOGUE_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with run_demo.CATALOGUE_OVERRIDE_PATH.open(
        "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _override_status() -> dict:
    path = run_demo.CATALOGUE_OVERRIDE_PATH
    if not path.exists():
        return {"active": False, "rows": 0, "bytes": 0}
    import datetime
    return {
        "active": True,
        "rows": sum(1 for _ in path.open(encoding="utf-8")) - 1,
        "bytes": path.stat().st_size,
        "mtime": datetime.datetime.fromtimestamp(
            path.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
    }


@app.get("/admin")
def admin():
    return render_template(
        "admin.html",
        sources=PUBLIC_SOURCES,
        status=_override_status(),
        required_cols=CATALOGUE_COLUMNS_REQUIRED,
        optional_cols=CATALOGUE_COLUMNS_OPTIONAL,
    )


@app.post("/admin/upload-csv")
def admin_upload_csv():
    f = request.files.get("catalogue")
    if not f or not f.filename:
        return _err("Sube un CSV con la cabecera correcta.", 400)
    name = secure_filename(f.filename)
    if not name.lower().endswith(".csv"):
        return _err("Sólo se admite CSV en este momento.", 400)
    raw = f.read(MAX_FETCH_BYTES + 1)
    if len(raw) > MAX_FETCH_BYTES:
        return _err(f"Demasiado grande (máx {MAX_FETCH_BYTES // 1024} KB).", 413)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            return _err("No se pudo decodificar el CSV (probar UTF-8 o CP1252).", 400)
    try:
        rows = _csv_rows_to_catalogue(text)
    except ValueError as exc:
        return _err(str(exc), 400)
    _write_override_catalogue(rows)
    return redirect(url_for("admin") + f"?ok=uploaded&rows={len(rows)}")


@app.post("/admin/fetch-url")
def admin_fetch_url():
    url = (request.form.get("url") or "").strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        return _err("Pega una URL completa (http:// o https://).", 400)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MotorPresupuestos/1.0",
            "Accept": "text/csv, application/octet-stream, text/plain, */*",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get_content_type() or ""
            raw = resp.read(MAX_FETCH_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return _err(f"La URL devolvió HTTP {exc.code}.", 502)
    except Exception as exc:                              # noqa: BLE001
        return _err(f"No se pudo descargar la URL: {exc}", 502)
    if len(raw) > MAX_FETCH_BYTES:
        return _err(f"Recurso demasiado grande (máx {MAX_FETCH_BYTES // 1024} KB).", 413)

    is_bc3 = url.lower().endswith(".bc3") or "bc3" in ctype.lower()
    try:
        if is_bc3:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            bc3_prices = bc3.parse_bc3(text)
            if not bc3_prices:
                return _err("BC3 sin registros ~C utilizables.", 400)
            # Adapt BC3 price rows to our catalogue shape.
            rows: list[dict] = []
            for p in bc3_prices:
                rows.append({
                    "code": p["code"],
                    "unidad": p.get("unidad", ""),
                    "descripcion": p.get("descripcion", "")[:240],
                    "precio_unitario": f"{p.get('precio_unitario', 0):.4f}",
                    "fuente": p.get("fuente", "BC3"),
                    "ambito": p.get("ambito", "import"),
                })
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
            rows = _csv_rows_to_catalogue(text)
    except ValueError as exc:
        return _err(str(exc), 400)
    _write_override_catalogue(rows)
    return redirect(url_for("admin") + f"?ok=fetched&rows={len(rows)}&from={request.form.get('url')}")


@app.post("/admin/reset-catalogue")
def admin_reset_catalogue():
    p = run_demo.CATALOGUE_OVERRIDE_PATH
    if p.exists():
        p.unlink()
    return redirect(url_for("admin") + "?ok=reset")


@app.get("/robots.txt")
def robots():
    # Block all crawlers, both well-behaved (robots.txt) and via X-Robots-Tag header.
    body = "User-agent: *\nDisallow: /\n"
    resp = app.response_class(body, mimetype="text/plain")
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return resp


@app.after_request
def _block_crawlers(resp):
    # Belt-and-suspenders: send X-Robots-Tag on every response, in case some
    # crawler ignores robots.txt but honours the header.
    resp.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive, nosnippet")
    return resp


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

def _err(msg: str, code: int = 400):
    return render_template("error.html", msg=msg, code=code), code


@app.errorhandler(413)
def too_large(_):
    return _err(f"Archivo demasiado grande (máx {MAX_UPLOAD_BYTES // 1024} KB).", 413)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
