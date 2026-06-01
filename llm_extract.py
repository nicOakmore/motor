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
# Groq free-tier quotas (measured June 2026):
#   llama-3.3-70b-versatile  → 12 000 TPM,  100 000 TPD  (smartest, capped TPD)
#   llama-3.1-8b-instant     →  6 000 TPM,  500 000 TPD  (small TPM, big TPD)
#   gemma2-9b-it             → 14 000 TPM,  500 000 TPD  (best of both)
# Default to gemma2-9b-it: the highest TPM available AND the higher TPD
# budget — fits the longest prose memorias without hitting either limit.
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
FALLBACK_MODEL = "llama-3.1-8b-instant"
# Fallback is hard-constrained: 8B has only 6 000 TPM. Subtracting the
# fixed prompt overhead (catalogue ~3 500 t + system ~250 t + response
# reserve 512 t), we have ~1 750 tokens for the memoria ≈ 7 000 chars.
# Use 4 500 to keep some margin against catalogue growth.
FALLBACK_MEMORIA_CHARS = 4_500
FALLBACK_MAX_TOKENS = 512
# Total prompt budget ≈ memoria + catalogue (~3 500 t) + system (~250 t)
# + response (1 024 t) ≤ 12 000 t per call. 24 000 chars ≈ 6 000 tokens.
MAX_MEMORIA_CHARS = 24_000
REQUEST_TIMEOUT = 60        # seconds


# Lines that look like a table of contents: numbered chapter heading
# followed by no body text. We strip them before sending to the LLM so
# the model sees descriptive content instead of an endless index.
_TOC_PREFIX_RE = re.compile(
    r"^\s*(?:[IVX]+\.\d?|\d+(?:\.\d+){0,4})\s+[A-ZÁÉÍÓÚÑ ]{4,}\s*$"
)
# A run of lines that look like a TOC + the page references next to them.
_TOC_LINE_RE = re.compile(
    r"^\s*(?:[IVX]+\.\d?|\d+(?:\.\d+){0,4})\s+.+?(?:\.{2,}|\s)\d{1,4}\s*$"
)
# Lines that are a digital-signature noise line we want to drop.
_NOISE_RE = re.compile(r"^\s*[A-F0-9]{20,}\s*$|^\s*\d{2}\.\d{2}\.\d{4}\s+\d+/\d+/\d+\s*$")


def _strip_toc(text: str) -> str:
    """Remove table-of-contents lines and signature noise so the LLM sees
    descriptive prose, not an index."""
    out: list[str] = []
    for ln in text.splitlines():
        if _NOISE_RE.match(ln) or _TOC_PREFIX_RE.match(ln) or _TOC_LINE_RE.match(ln):
            continue
        # Lines with only a chapter number (e.g. "I.2") aren't useful either.
        if re.match(r"^\s*[IVX]+\.\d?\s*$", ln):
            continue
        out.append(ln)
    # Collapse runs of blank lines.
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return cleaned.strip()


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


def _slice_memoria(cleaned: str, max_chars: int) -> str:
    """Trim to max_chars. When the memoria is longer, we try to centre
    the window on the descriptive content (markers like "MEMORIA
    CONSTRUCTIVA", "PROPUESTA DE INTERVENCIÓN", "DESCRIPCIÓN DEL
    PROYECTO") — BUT only if there's still meaningful content after the
    marker. Otherwise we fall back to the head, which usually contains
    the project intro + early descriptive sections."""
    if len(cleaned) <= max_chars:
        return cleaned
    head_lc = cleaned.lower()
    best_start = 0
    for marker in ("propuesta de intervención", "propuesta de intervencion",
                    "descripción del proyecto", "descripcion del proyecto",
                    "memoria constructiva", "alcance de obra",
                    "alcance de la obra"):
        i = head_lc.find(marker)
        # Only use the marker if it leaves enough content after it to be
        # useful — otherwise the head is a better window.
        if i > 0 and (len(cleaned) - i) >= max_chars * 0.4:
            best_start = max(0, i - 400)
            break
    return cleaned[best_start:best_start + max_chars] + "\n[…final truncado…]"


def _build_user_message(memoria_text: str, tipos_catalogue: dict) -> str:
    """Compact user message: the memoria's descriptive content (TOC and
    signature noise removed) plus the catalogue of accepted tipos as JSON.
    The tipos block sits at the END so prompt-cache hits compound across
    calls (Groq supports OpenAI-style prompt caching transparently)."""
    cleaned = _strip_toc(memoria_text)
    text = _slice_memoria(cleaned, MAX_MEMORIA_CHARS)
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


def _call_model(model: str, memoria_text: str, max_chars: int,
                concepto_metadata: dict, api_key: str,
                max_tokens: int = 1024) -> str:
    """One Groq API call. Returns the model's content string, or raises."""
    cleaned = _strip_toc(memoria_text)
    text = _slice_memoria(cleaned, max_chars)
    tipos = {k: v.get("descripcion_corta", "") for k, v in concepto_metadata.items()
             if isinstance(v, dict) and not k.startswith("_")}
    user_msg = (
        "MEMORIA:\n```\n" + text + "\n```\n\n"
        "TIPOS PERMITIDOS (clave → descripción corta):\n"
        + json.dumps(tipos, ensure_ascii=False, indent=2)
    )
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    }
    raw = _post(payload, api_key)
    try:
        return raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def extract_scope(memoria_text: str,
                  concepto_metadata: dict,
                  model: str | None = None) -> list[dict]:
    """Propose scope-items from a memoria text. Returns a list of
    {tipo, cantidad, unidad} ready to drop into the editor as new rows.

    Two-stage fallback: try the primary model with the full budget; on
    rate-limit or model-deprecation, retry with the smaller fallback
    model and a tighter memoria window so the smaller TPM still fits.

    Raises LLMUnavailable when the feature is disabled or has no key.
    Returns [] when no model could propose anything usable.
    """
    if not llm_enabled():
        raise LLMUnavailable(
            "LLM feature disabled (set LLM_ENABLED=true and GROQ_API_KEY "
            "in env to enable)."
        )
    api_key = os.environ["GROQ_API_KEY"].strip()

    attempts = [
        (model or DEFAULT_MODEL, MAX_MEMORIA_CHARS,    1024),
        (FALLBACK_MODEL,         FALLBACK_MEMORIA_CHARS, FALLBACK_MAX_TOKENS),
    ]
    last_error: Exception | None = None
    for m, budget, max_tok in attempts:
        try:
            content = _call_model(m, memoria_text, budget,
                                  concepto_metadata, api_key, max_tok)
            if content:
                proposals = _parse_proposals(content, set(concepto_metadata.keys()))
                if proposals:
                    return proposals
                # Empty proposals: don't retry — model genuinely had nothing.
                return []
        except RuntimeError as exc:
            msg = str(exc)
            if any(k in msg for k in ("429", "413", "rate_limit", "decommissioned")):
                last_error = exc
                continue
            raise
    if last_error is not None:
        raise last_error
    return []
