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
import hmac
import json
import os
import pathlib
import re
import secrets
import shutil
import tempfile
from typing import Iterable

from flask import (
    Flask, Response, abort, jsonify, redirect, render_template,
    request, send_file, url_for,
)
from werkzeug.utils import secure_filename

import run_demo


ROOT = pathlib.Path(__file__).parent
SAMPLE_MEMORIAS_DIR = ROOT / "memorias"
PDF_OUT = ROOT / "salidas" / "como_funciona.pdf"

# Job storage: /tmp on Render (ephemeral); cwd-local elsewhere. Override via env.
JOBS_ROOT = pathlib.Path(
    os.environ.get("JOBS_ROOT") or (tempfile.gettempdir() + "/rex-jobs")
)
JOBS_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".md", ".txt"}
MAX_UPLOAD_BYTES = 256 * 1024     # 256 KB — memorias are text, generous cap


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
    return sorted(SAMPLE_MEMORIAS_DIR.glob("*.md"))


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

    # Project-param overrides
    params = dict(rules_spec.get("parameters", {}))
    for key in ("gg_pct", "bi_pct", "iva_pct", "retencion_irpf_pct",
                "recargo_equivalencia_pct"):
        raw = (request.form.get(f"pp_{key}") or "").strip()
        if raw:
            try:
                params[key] = float(raw)
            except ValueError:
                pass
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


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


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
