"""
llm_extract.py — Offline LLM scope extraction from prose memorias.

Calls Groq's free-tier API (OpenAI-compatible) with a tightly-scoped
prompt: "given this memoria and this list of valid tipos, propose the
works mentioned and their mediciones".

Architectural rules:
  - The LLM lives at the INGEST edge. It NEVER asserts facts into the
    deterministic engine directly. It proposes scope-items; the
    technician (via the editor) approves them; only approved items
    enter the engine.
  - Kill-switch: set LLM_ENABLED=false in env to disable the feature
    instantly without a redeploy. With no GROQ_API_KEY the feature
    self-disables and the rest of the app keeps working.
  - The pipeline that doesn't use the LLM is the default path; this
    module only loads on demand.

Stdlib only — no SDK dependency. Single HTTPS POST against
https://api.groq.com/openai/v1/chat/completions.
"""

from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request


GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
# Cap the memoria payload so we stay inside Groq's free-tier per-minute
# token budget. Real PDFs that survive our 60-page parser cap will still
# fit; long technical annexes get truncated.
MAX_MEMORIA_CHARS = 12_000
REQUEST_TIMEOUT = 45        # seconds


class LLMUnavailable(RuntimeError):
    """Raised when the LLM feature is disabled or its credentials are
    missing — callers should treat this as "feature not configured"
    rather than a hard error."""


def llm_enabled() -> bool:
    return (
        os.environ.get("LLM_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        and bool((os.environ.get("GROQ_API_KEY") or "").strip())
    )


SYSTEM_PROMPT = (
    "Eres un aparejador especializado en presupuestos de obra para "
    "Ibiza/Baleares. Lees memorias constructivas en español y propones, "
    "para cada partida claramente mencionada en el texto, el «tipo» de "
    "una lista cerrada y la medición numérica.\n\n"
    "Reglas estrictas:\n"
    "1. Devuelve EXCLUSIVAMENTE un JSON con la forma "
    "{\"propuestas\": [{\"tipo\": \"<string>\", \"cantidad\": <float>, "
    "\"unidad\": \"<m2|m3|m|ud|kg>\"}, ...]}.\n"
    "2. El campo \"tipo\" tiene que ser literalmente uno de los tipos "
    "permitidos que se te indican.\n"
    "3. Si la memoria no menciona el trabajo con suficiente claridad, "
    "OMITE la propuesta. No inventes mediciones.\n"
    "4. Si la memoria es narrativa y no se puede deducir ninguna medición, "
    "devuelve {\"propuestas\": []}.\n"
    "5. No incluyas comentarios, explicaciones ni texto antes o después del "
    "JSON.\n"
)


def _build_user_message(memoria_text: str, tipos_catalogue: dict) -> str:
    """Compact user message: a truncated memoria plus the catalogue of
    accepted tipos as JSON. The tipos block sits at the END so the prompt
    cache can hit on the SAME catalogue across calls (Groq supports OpenAI-
    style prompt caching transparently)."""
    text = memoria_text[:MAX_MEMORIA_CHARS]
    if len(memoria_text) > MAX_MEMORIA_CHARS:
        text = text + "\n[…texto truncado por longitud…]"
    tipos = {k: v.get("descripcion_corta", "") for k, v in tipos_catalogue.items()
             if isinstance(v, dict) and not k.startswith("_")}
    return (
        "MEMORIA:\n```\n" + text + "\n```\n\n"
        "TIPOS PERMITIDOS (clave → descripción corta):\n"
        + json.dumps(tipos, ensure_ascii=False, indent=2)
    )


def _post(payload: dict, api_key: str) -> dict:
    # Groq's edge is fronted by Cloudflare, which 403s urllib's default
    # User-Agent ("Python-urllib/3.x") with Error 1010
    # "browser_signature_banned". Use a real-looking UA.
    req = urllib.request.Request(
        GROQ_ENDPOINT,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36 "
                            "MotorPresupuestos/1.0"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM network error: {exc.reason}") from exc


def _parse_proposals(content: str, allowed_tipos: set[str]) -> list[dict]:
    """Pull the JSON object out of the model's reply, validate each entry."""
    # Try direct JSON first; if the model wrapped it in prose, fall back to
    # the first {…} block.
    obj = None
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return []
    proposals = obj.get("propuestas") or obj.get("scope") or []
    if not isinstance(proposals, list):
        return []

    out: list[dict] = []
    allowed_units = {"m2", "m3", "m", "ud", "kg"}
    for entry in proposals:
        if not isinstance(entry, dict):
            continue
        tipo = (entry.get("tipo") or "").strip()
        if tipo not in allowed_tipos:
            continue
        try:
            cantidad = float(entry.get("cantidad") or 0)
        except (TypeError, ValueError):
            continue
        if cantidad <= 0:
            continue
        unidad = (entry.get("unidad") or "").strip().lower()
        if unidad not in allowed_units:
            unidad = "ud"
        out.append({"tipo": tipo, "cantidad": cantidad, "unidad": unidad})
    return out


def extract_scope(memoria_text: str,
                  concepto_metadata: dict,
                  model: str | None = None) -> list[dict]:
    """Propose scope-items from a memoria text. Returns a list of
    {tipo, cantidad, unidad} ready to drop into the editor as new rows.

    Raises LLMUnavailable when the feature is disabled or has no key.
    Returns [] when the model didn't propose anything usable.
    """
    if not llm_enabled():
        raise LLMUnavailable(
            "LLM feature disabled (set LLM_ENABLED=true and GROQ_API_KEY "
            "in env to enable)."
        )
    api_key = os.environ["GROQ_API_KEY"].strip()
    payload = {
        "model": model or DEFAULT_MODEL,
        "temperature": 0.1,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content":
                _build_user_message(memoria_text, concepto_metadata)},
        ],
    }
    raw = _post(payload, api_key)
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return []
    return _parse_proposals(content, set(concepto_metadata.keys()))
