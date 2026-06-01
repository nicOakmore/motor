# Rollback procedure — LLM batch

The LLM-assisted scope extraction is **opt-in**, **kill-switchable**, and
**isolated**. If anything goes wrong, here's how to disable it or
roll back, in order of increasing severity.

## 0. Kill-switch (no code change, no redeploy)

The feature self-disables when either env var is missing or off:

| Env var | Effect |
|---|---|
| `LLM_ENABLED=false` | CTA hidden on the result page; `POST /j/<id>/llm-suggest` returns HTTP 503. |
| `GROQ_API_KEY` unset | Same as above. |

On Render: dashboard → service → Environment → set `LLM_ENABLED=false` (or remove it) → save. Takes effect on the next request, no redeploy needed.

The deterministic pipeline (memoria upload, parser, mapping rules, regulatory rules, PDFs, editor) does not call the LLM at any point — disabling it never affects the rest of the app.

## 1. Revert just the LLM commits

If the LLM code itself is broken (import error, crash on load):

```
git revert --no-edit <commit-sha-of-llm-work>
git push origin main
```

The `~T` pliego round-trip (commit `d367aaa`) is a separate, independent commit and stays.

## 2. Hard reset to the pre-LLM tag

If you want to wipe everything from the LLM batch including any later fixes:

```
git reset --hard pre-llm-batch7
git push --force-with-lease origin main
```

The tag `pre-llm-batch7` was created at `d367aaa` immediately before the LLM work landed. After reset you're at the state where:
- BC3 round-trip with ~T pliego works
- All previous batches are intact
- No LLM code exists in the tree

Trigger a Render redeploy via the dashboard (or POST to `/v1/services/<svc>/deploys` with the Render API).

## 3. What's stored where

- `llm_extract.py` — the only LLM code. Self-contained. Stdlib only (no SDK).
- `app.py` — new route `POST /j/<id>/llm-suggest`. Guarded by `llm_extract.llm_enabled()`. Existing routes unchanged.
- `run_demo.py` — new function `rerun_with_extra_scope_items` that mixes LLM proposals with the parser's scope items. The function is only called from `/llm-suggest`; the default pipeline doesn't touch it.
- `templates/result.html` — conditional CTA card, shown only when `llm_enabled` is true and the job has 0 partidas.
- `requirements.txt` — no new dependency. The LLM call uses stdlib `urllib` to talk to Groq's OpenAI-compatible API.

## 4. Cost guarantee

The LLM uses **Groq's free tier** (`llama-3.3-70b-versatile` by default). At time of writing:
- No credit card required.
- Rate limits: roughly 30 req/min, 6000 req/day for `llama-3.3-70b-versatile`.
- If the quota is exceeded the call returns an HTTP 429 from Groq; our endpoint surfaces a clean Spanish error and the rest of the app keeps working.

To use a different free provider (e.g. Google Gemini Free tier or Cloudflare Workers AI), change `GROQ_ENDPOINT` and `_post` in `llm_extract.py` — the request shape is OpenAI-compatible chat completion JSON.
