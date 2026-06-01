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
import json
import os
import pathlib
import re
import secrets
import shutil
import tempfile
from typing import Iterable

from flask import (
    Flask, abort, jsonify, redirect, render_template,
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
            return _err("Sample desconocido.", 400)
        src_path = inbox / sample_path.name
        shutil.copy2(sample_path, src_path)
    else:
        return _err("Sube una memoria o elige una de muestra.", 400)

    out_root = job_root / "salidas"
    try:
        result = run_demo.run_for_memoria(src_path, out_root=out_root, verbose=False)
    except Exception as exc:                          # noqa: BLE001
        return _err(f"Fallo procesando la memoria: {exc}", 500)

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
