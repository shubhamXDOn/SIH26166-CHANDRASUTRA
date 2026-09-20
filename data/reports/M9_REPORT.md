# M9 Report — Evidence-Grounded Gemini AI Copilot & Explainable Analysis (CHANDRASUTRA · SIH26166)

**Milestone:** M9 — a *real* Gemini AI assistant integrated end-to-end with the
deterministic M2 → M8 evidence chain: honest capability states, canonical
sanitized evidence packets, strict response validation (forbidden-term,
secret/path-leak, schema, and evidence-citation checks), durable provenance and
audit trails, isolated conversation sessions, adaptive prompt budget fitting, a
live **AI Copilot** UI — and a never-fabricate policy enforced by validation,
not by hope.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-17
**Status:**
- **Engineering: DONE** — the complete M9 pipeline (config → evidence →
  prompt → REST call to Gemini → validation → audit/provenance) is
  implemented and tested with a scripted Gemini transport (57 dedicated tests
  in `tests/test_m9.py`, covering the 25-item B01–B25 bug-hunt acceptance
  corpus plus every capability state, validator, session, provenance and API
  contract). The full backend suite is green at **411 passed**, `smoke_test.py`
  is **74/74 PASS** (11 new `m9-*` probes), the frontend builds and
  `ssr-smoke.mjs` passes all renders including the upgraded AI Copilot page,
  and `docker compose config` is valid.
- **Live Gemini execution: NOT_RUN** — no `GEMINI_API_KEY` is set in this
  environment, so the service truthfully reports `NOT_CONFIGURED` for every
  AI endpoint and the copilot console stays honestly empty. The real
  `https://generativelanguage.googleapis.com/v1beta` transport is implemented
  (timeouts, rate limits, retries, state mapping, multi-turn) but is exercised
  only through a mocked HTTP layer in tests. No fabricated answer is ever
  produced, and the frontend never receives or holds the API key.

> **Honesty rule:** M9 only *explains* what the scientific pipeline already
> recorded. It never proposes scientific numbers, never authorizes a
> registration, its `evidence[]` references are cross-checked against the
> canonical metric registry of the actual evidence packet built from files, and
> any response containing a forbidden term, a suspected secret or absolute path,
> a non-empty answer claim without evidence, or an unknown metric/milestone
> reference is **rejected outright** (502, `INVALID_RESPONSE`) and recorded — it
> is never surfaced to the user.

---

## 1. What M9 delivers

### 1.1 Configuration (`configs/app.yaml` → `m9:`, `backend/app/ai/config.py`)

- `AI-M9-001` / v1 — the sole registered configuration, exposed via
  `GET /api/ai/status` and referenced in `/api/meta` as `m9_config`.
  Pydantic-backed `AIConfig` with string→number/boolean coercion; unknown
  configuration IDs fail loudly, never silently fall back.
- Provider `gemini`, `endpoint_base` pinned to
  `https://generativelanguage.googleapis.com/v1beta`, `model
  gemini-2.0-flash`, key via `GEMINI_API_KEY` (backend-only).
- `grounding_rules` normalize from YAML list form to a `{M1:, M2:, … M8:}`
  dict during load; `delimiters`, `constraints` (timeout, retries, rate limit,
  max tokens, max input chars, prompt fit), `forbidden_result_terms`,
  `tasks[]` (5), `evidence_schema_version`, `prompt_version`.
- `scientifically_tuned false` with engineering-defaults `source_reference`.

### 1.2 Honest capability states (`states.py`, `client.py`, `service.py`)

- `status_dict()` exposes `configured`, `available`, `status`, `model`,
  `configuration_id/version`, `prompt_version`, `evidence_schema_version`,
  timeouts/limits/rate limits, and a `policy` block
  (`explanatory_only`, `core_science_source`, `no_fabricated_responses`,
  `never_authorizes_registration`, `never_produces_scientific_numbers`).
- Provider outcomes map to first-class states: `NOT_CONFIGURED`, `IN_PROGRESS`,
  `SUCCESS`, `INVALID_RESPONSE`, `PROVIDER_ERROR`, `TIMEOUT`, `RATE_LIMITED`,
  `BLOCKED`, `FAILED` — each with a stable error code
  (`AI-M9-001` … `AI-M9-007`) surfaced through the unified error envelope.
- No key → every task endpoint answers 501 with `error.code == "NOT_CONFIGURED"`
  **before** any body/pair validation, so the capability check always wins and
  the app keeps running.

### 1.3 Canonical sanitized evidence packet (`evidence.py`)

- Deterministic packet built by reading the same artifacts as M2–M8: milestone
  states (`status`), metrics per milestone, per `/api/...` insights, and an
  honest `message`. All secrets (`api_key`, `auth`) and POSIX absolute paths are
  redacted with a `Sanitizer` **before** hashing, so digest determinism holds
  and nothing secret ever reaches the model.
- `canonical_digest` (SHA-256 over `json.dumps(compact, sort_keys, …)`)
  travels in the prompt (`evidence_digest`) and is reused on any
  repetition/session append so the model always sees a caller-verifiable digest
  of exactly what it is being asked to explain.
- Volatile metric-record keys are compacted in `_m7_entry` so digest changes
  only when real artifact content changes.

### 1.4 Prompt builder with budget fitting (`prompts.py`)

- Task-aware system prompts: `explain`, `explain_failure`, `explain_routing`,
  `summarize_experiment`, `chat` — all scoped by `least_reference_tag`,
  `upper_reference_bound`, evidence schema, grounding rules, truthful-statements
  and forbidden-result vocabulary.
- `build()` with `max_input_chars` budget fitting: if the packet is too large
  the **largest subtree** is dropped (deterministically) and the fit is
  re-tried, so a huge pair still gets an honest, budgeted explanation rather
  than an error or a truncated half-prompt.
- `question` is capped to `max_question_chars`; chat prompt includes prior
  validated turns from the session.

### 1.5 Response validation (`validator.py`, B01–B25)

- Strict structure: JSON object (MD code-fenced JSON tolerated), required keys,
  types, `evidence[]` list length ≤ `max_evidence_refs`, `suggested_inspections`
  capped, `usage` coerce-or-drop, plus:
  - B01/B02 — batch JSON handled: non-JSON errors and batch full-array rejected;
  - B05 — no non-empty answer without ≥1 evidence ref (and vice versa);
  - B07 — evidence ref metric must exist in the packet's canonical registry;
  - B08 — evidence ref milestone must be known (M1..M8);
  - B10–B13 — forbidden terms rejected in answer, evidence claims (recursively
    into dicts), and suggested_inspections;
  - B14/B22 — secret/path leak scan recurses into nested dict values, not just
    top-level (`_strings`), with an `/api/…` endpoint-only exemption so
    legit suggestions like `/api/metrics/status` are allowed;
  - B15 — max relevance bound enforced (monotone/turbid/ambiguous discipline);
  - B19 — empty-dict pruning for optional-coerce keys;
  - B24/B25 — prompt/config never leak via cached validator error messages.
- Any failure raises `AIInvalidResponseError` → 502 `INVALID_RESPONSE`, recorded
  in audit + provenance, never surfaced as an answer.

### 1.6 Transport, sessions, audit, provenance

- `client.py`: httpx POST to `/v1beta/models/{model}:generateContent` with
  `x-goog-api-key` header (never exposed in responses), `generationConfig`
  (temperature 0, topP 1, response_mime_type JSON, max tokens), timeout bound,
  per-minute rate limiting, one retry for 429/503/5xx; all exceptions map
  through `map_transport_error` to states/errors and never include raw message
  noise.
- `sessions.py`: per-key TTL cache with LRU eviction; a `chat` turn reuses the
  same session + adds the prior validated turn to the prompt (server-side
  multi-turn), still validated per-turn.
- `audit.py`: JSONL append per request to `derived/ai/audit.log` with
  status/error-code/milestone refs and **digests only**.
- `provenance.py`: `build_m9_provenance()` + `write_m9_provenance()` emit
  `derived/ai/<pair_id>/<request_id>/provenance.json` — configuration/versions,
  model, task, evidence + response SHA-256 digests, policy. It never stores the
  prompt, the response contents, the question, or the API key.

### 1.7 API (`backend/app/api/ai.py`)

| Route | Purpose |
|---|---|
| `GET /api/ai/status` | capability + policy + limits (200 always, `NOT_CONFIGURED` when no key) |
| `POST /api/ai/explain` | explain the recorded analysis for a pair |
| `POST /api/ai/explain-failure` | explain recorded failures/blockers |
| `POST /api/ai/explain-routing` | explain M3/M8 routing decisions |
| `POST /api/ai/summarize-experiment` | summarize recorded experiment measurements |
| `POST /api/ai/chat` | multi-turn question–answer, session-grounded |

Success envelope: `{status, request_id, task, pair_id, answer, evidence[],
limitations[], suggested_inspections[], usage, ai, created_at}`. Only
`pair_id` is required for the four explanation tasks; `question` is required for
`chat` and validated **inside** `service.execute` *after* the configured guard
(so an unconfigured chat returns 501 `NOT_CONFIGURED`, never a 422).

### 1.8 Frontend — AI Copilot (`AIInsights.jsx`, `Sidebar.jsx`, `App.jsx`)

- Rebranded **AI Copilot** page with a live **Copilot console**: pair id + task
  selector (+ optional question) → `POST /api/ai/<task>` → structured render of
  answer, cited `evidence[]` (claim + source milestone/metric), `limitations[]`
  and `suggested_inspections[]`; friendly inline error for provider/validation
  failures that never fabricates.
- NOT_CONFIGURED state renders an honest empty console (no fake content) plus
  policy/security cards; header banner updated to
  `M9 · Evidence-Grounded AI Copilot`; key never in the bundle (build verified,
  SSR renders OK).

---

## 2. Acceptance & bug-hunt validation (B01–B25, tests/test_m9.py)

The full M9 suite is **57 tests, all green**. Bug-hunt behaviours exercised in
`test_m9_bug_hunt_behaviours`:

| # | Behaviour | How verified |
|---|-----------|--------------|
| B01 | Batch JSON (non-JSON error) rejected, no partial leak | validator raises; response dropped |
| B02 | Batch JSON (whole payload array) rejected | validator raises |
| B05 | non-empty answer without evidence rejected | validator raises `INVALID_RESPONSE` |
| B07 | evidence metric not in packet registry rejected | `FUNNEL_UNKNOWN` → raises |
| B08 | evidence milestone unknown rejected | `source_milestone "M9"` → raises |
| B10 | forbidden term in answer rejected | `accuracy` flagged |
| B11/B22 | forbidden term in nested dict claim rejected | recursive scan |
| B12/B14 | secret (API key literal) in claim rejected | leak scan → raises |
| B13 | forbidden term in suggested_inspections rejected | raises |
| B15 | max relevance bound enforced | 4 refs rejected, 3 accepted |
| B19 | empty-dict pruning (usage coerce-or-drop) | malformed usage dropped, valid kept |
| B20 | cache cleared on validation failure | still raises on re-validate |
| B21 | no logs leak prompt/config | capfd clean |
| B24 | error message omits prompt/config contents | message is code-only |
| B25 | mocks can't inject prompt/config into error | network mock → state-mapped error |

Also verified across the suite: prompt fit drops the largest subtree when
over-budget; digest tracks semantic change not volatile keys; sessions isolate
users, prune by TTL, and evict LRU-order; audit + provenance nodes carry digests
only; API never returns the API key; all five task endpoints exist and return
501 `NOT_CONFIGURED` unconfigured, and the honest-empty end-to-end (empty repo →
honest answer with **zero** evidence refs) passes.

---

## 3. Regression

| Suite | Result |
|-------|--------|
| `pytest tests/test_m9.py -q` | **57 passed** (dedicated suite) |
| `pytest tests/ -q` (full) | **411 passed**, 2 warnings (~9 min) |
| `smoke_test.py` (live HTTP: M1–M9 + frontend) | **74/74 PASS** (11 new `m9-*` probes: meta config, milestone, ai-status, 501-unconfigured × 5 tasks, no-secret-in-responses) |
| `npm run build` (frontend) | **built OK (vite, 43 modules)** |
| `node frontend/ssr-smoke.mjs` | **OVERALL PASS (all renders incl. AIInsights/AI Copilot)** |
| `docker compose config` | **valid** (backend `8000` + frontend `80`; live daemon pending Docker availability) |

No M1–M8 regressions observed; all prior milestone suites and the M3/M6/M7/M8
bug-hunt corpora remain green after the M9 additions.

---

## 4. Known limitations

1. **Live Gemini not exercised here** — `GEMINI_API_KEY` is not set in this
   environment, so every AI endpoint truthfully reports `NOT_CONFIGURED`
   (501) and the copilot console stays empty. The REST transport, retry, rate
   limit and timeout paths are covered through mocked HTTP in tests and will
   run live once a key is provisioned.
2. **Real-data execution** — BLOCKED on PRADAN approval, as for M1–M8. M9
   explains whatever the pipeline recorded; with no real pipeline runs it
   explains the honest empty/NOT_RUN state.
3. **Multi-turn scope** — chat sessions are server-side state held in-memory
   (TTL 15 min, LRU cap 20) and are not persisted across restarts; provenance
   covers each turn independently.
4. **Model choice** — pinned to a single `gemini-2.0-flash` model id in M9
   configuration; multi-provider/model selection is out of scope.
5. **Containerisation** — `docker compose config` validates; a live compose up
   needs the Docker daemon (not running in this environment).

---

## 5. Traceability vs spec (SIH26166)

- **M9.1 AI assistant configuration + honest capability** — `ai/config.py`,
  `ai/states.py`, `/api/ai/status`, `/api/meta.m9_config`; NO key → clean
  `NOT_CONFIGURED`, app keeps running, nothing fabricated.
- **M9.2 Evidence grounding** — `ai/evidence.py`: deterministic sanitized
  packet from the same artifacts M2–M8 read; canonical SHA-256 digest;
  honest empty/NOT_RUN state.
- **M9.3 Prompt engineering + budget fit** — `ai/prompts.py`: task-aware
  prompts, evidence schema + grounding rules, deterministic largest-subtree fit,
  capped question.
- **M9.4 Response validation & safety (B01–B25)** — `ai/validator.py`:
  strict schema, forbidden terms (recursive), secret/path leak scan with
  `/api/…` exemption, evidence-citation registry/milestone checks, relevance
  bound, no prompt/config leaks in errors.
- **M9.5 Transport & resilience** — `ai/client.py`: REST `generateContent`,
  backend-only key header, timeout, retry, rate limit, state mapping.
- **M9.6 Provenance & audit** — `ai/provenance.py`, `ai/audit.py`: digests
  only; never stores prompt/response/question/key; `derived/ai/…` artifacts.
- **M9.7 Sessions** — `ai/sessions.py`: isolated TTL/LRU server-side multi-turn.
- **M9.8 API + UI** — `api/ai.py` (5 task endpoints + status), upgraded
  **AI Copilot** page with live console and honest NOT_CONFIGURED empty state,
  SSR smoke, `smoke_test.py` probes.
- **M9.9 Honesty & safety** — no fabricated answers (validation-enforced), no
  key exposure, no secret/path leaks, evidence-cited answers only, full suite
  411 green, no regressions.