# ZERO X-RAY · Agentic Government Service Engine

ZERO X-RAY turns a supplied government-service journey into an evidence-based
Agentic Blueprint, lets an employee protect mandatory steps, and runs the
approved design as a traceable customer Sandbox journey. Beyond that initial
redesign, ZERO X-RAY also runs an 8-stage **Government Future Engine**
pipeline — Predict, Simulate, Challenge, Evolve, Prevent, and Monitoring/
Alerts — that turns the one-time redesign into an ongoing, evidence-grounded
early-warning system for the same service. See
[Government Future Engine (8-stage pipeline)](#government-future-engine-8-stage-pipeline)
below.

## Product workspaces

1. **Service Design Studio** — text, PDF, DOCX, XLSX and image intake; per-step
   compliance; human constraints; current/future journey; metrics; validation.
2. **Blueprint Governance** — draft, approve and publish lifecycle with a local
   audit trail.
3. **ZERO Agent Live Sandbox** — customer registration, natural-language
   outcome request, editable versioned plan, explicit approval, conditional
   Sandbox payment only when the service requires it, live execution events,
   completion and human-handoff controls.
4. **ZERO X-RAY Intelligence** — the Government Future Engine pipeline
   (Predict → Simulate → Challenge → Evolve → Prevent → Monitoring/Alerts),
   available as its own tab in the Dashboard right after the Journey view.

## Customer and Agent journeys

The live Sandbox now has two synchronized views:

- **Customer journey** — simulated UAE PASS sign-in, a minimal review showing
  only the service name and amount, structured choice editing, approval,
  conditional payment and completion.
- **Agent journey** — the detailed execution plan, integrations, controls,
  events and audit references used by service teams.

The service-entry screen includes ready bilingual examples for **Renew
Corporate P.O. Box** and the free **Customer Inquiry Service**. The inquiry
service supports structured topic and response-channel choices and never
creates a payment stage.

## Adaptive service paths

The engine classifies every supplied journey before redesigning it. It supports:

- paid renewals, purchases, bookings and applications;
- free applications and requests;
- complaints and grievances;
- disputes, refunds and objections;
- information, inquiry and tracking services;
- services that preserve a required human judgement or approval.

Payment is not inferred from a money-related word alone. A complaint about a
charge or refund is treated as a case outcome, not as a new customer payment.
Unknown fees are flagged for Blueprint-owner verification and never create a
fake Sandbox charge. Service owners can optionally pass `service_type` and
`payment_requirement` when policy is already known.

Unverified integrations are always labelled `PROPOSED` or `SIMULATED`. The
Sandbox never claims that a government system or payment gateway is connected.

## Government Future Engine (8-stage pipeline)

Once a service has been analyzed at least once (`/api/analyze`), the
Government Future Engine layer runs additional, explicitly-triggered stages
on top of that same service. Every stage is deterministic Python logic over
real stored data; an LLM (when configured) is used **only** to rephrase an
already-computed result into a sentence, and that phrasing is always
validated against the real numbers before being trusted — otherwise a
template is used instead. Nothing below is a statistically validated model;
every score/confidence/severity/threshold is either a real evidence-derived
ratio or a named engineering constant, and every API response carries a
`score_methodology` marker saying so explicitly.

```
Current Journey → Analysis → Future Journey   (existing engine, unchanged)
        ↓
1. Predict     — detects recurring patterns (gaps, friction points, citizen
                 intents) across a service's own stored analysis/journey
                 history and reports them with a code-computed confidence.
        ↓
2. Simulate    — runs one deterministic what-if scenario (volume surge,
                 integration failure, SLA breach, cascading step failure)
                 against the service's real step graph.
        ↓
3. Challenge   — stress-tests the service with a closed set of deterministic
                 attack cases and ranks the vulnerabilities it finds.
        ↓
4. Evolve      — proposes a structural, additive-only fix for each
                 vulnerability (current state → proposed state), and
                 estimates before/after exposure only when the data
                 supports it. Never removes or bypasses a protected
                 (human-owned) step.
        ↓
5. Prevent     — defines an early-warning trigger (a threshold on Predict
                 confidence or Challenge severity) for each Evolve proposal.
        ↓
6. Monitoring  — an on-demand, deterministic re-check of Prevent's triggers
   / Alerts     against the LATEST already-stored Predict/Challenge result.
                 A breach creates a stored `TRIGGERED` alert; the alert is
                 later marked `RESOLVED` if a re-check finds the condition
                 no longer holds. Alerts are stored records only — no
                 email/SMS/webhook integration exists or is claimed.
```

Each stage's output references the real, stored ID(s) it was built from
(`prediction_id`, `scenario_id`, `challenge_id`, `evolution_id`,
`prevention_id`), so the whole chain is auditable end to end. The frontend's
**ZERO X-RAY Intelligence** tab runs this chain interactively, stage by
stage, with a 5-step progress indicator (Predict → Simulate → Challenge →
Evolve → Prevent) and a separate Monitoring & Alerts section after it.

### API summary (Government Future Engine)

| Stage | Endpoint | Notes |
|---|---|---|
| Predict | `POST /api/services/{service_id}/predict` | No body |
| Simulate | `POST /api/services/{service_id}/scenarios`<br>`GET /api/services/{service_id}/scenarios` | `trigger_type: PREDICTION` (auto-derives scenario+variables from a `prediction_id`) or `MANUAL` (explicit `scenario_type`+`variables`) |
| Challenge | `POST /api/services/{service_id}/challenges`<br>`GET /api/services/{service_id}/challenges` | Optional `strategies[]` (default: all 4) and `prediction_id` to link |
| Evolve | `POST /api/services/{service_id}/evolutions`<br>`GET /api/services/{service_id}/evolutions` | Body: `{ "challenge_id": "..." }` |
| Prevent | `POST /api/services/{service_id}/preventions`<br>`GET /api/services/{service_id}/preventions` | Body: `{ "evolution_id": "..." }` |
| Monitoring | `POST /api/services/{service_id}/monitoring-checks` | Body: `{ "prevention_id": "..." }` |
| Alerts | `GET /api/services/{service_id}/alerts` | Lists all stored `TRIGGERED`/`RESOLVED` alerts for the service |

All of the above require the same `Authorization: Bearer <token>` header and
tenant scoping as the rest of the API (see `POST /api/auth/demo-login`).

### Limitations (Government Future Engine)

- **Not a statistical model.** Every confidence/likelihood/severity/risk
  score is a deterministic engineering heuristic (an evidence-derived ratio
  or a named constant) — never a calibrated probability. This is stated
  explicitly in every response's `score_methodology` field.
- **Predict needs history.** A service needs ≥2 stored analyses (or ≥2
  Sandbox journeys) before Predict can report anything beyond
  `data_sufficiency: INSUFFICIENT` — by design, it never fabricates a
  prediction from a single data point.
- **Monitoring is on-demand, not a background service.** A monitoring check
  only runs when explicitly requested (via the API or the UI's "Run
  monitoring check" button) and only reads the *already-stored* latest
  Predict/Challenge result — it does not run a new Predict/Challenge pass
  and does not run on a schedule.
- **Alerts are stored records only.** No email, SMS, or webhook integration
  exists; "Alerts" means rows in the `alerts` table, surfaced via the API/UI.
- **Backend-generated free text stays English-only.** Statements,
  explanations, severity/threshold rationale, and proposed-state text are
  generated by the backend agents in English; the ZERO X-RAY Intelligence
  UI's own labels/buttons/hints are fully bilingual (en/ar), but this
  specific backend-authored text is shown as returned, in either language
  mode, with an explicit on-screen note saying so.
- **Protected-step handling is a conservative approximation.** Evolve treats
  every `HUMAN`-typed future step as protected (never removes/retypes/
  reorders it) — this is a safe superset of the original
  `REQUIREMENT`/`HUMAN`/`AS_IS` designations from `protected_steps`, since
  that exact mapping isn't preserved in the stored future-journey data.

## Quick start

Use Python 3.12 and Node 18+. The Arabic product journey and production
architecture are documented in
[`PRODUCT_ARCHITECTURE_AR.md`](PRODUCT_ARCHITECTURE_AR.md); demo accounts and
flow are documented in
[`DEMO_ACCOUNTS_AR.md`](DEMO_ACCOUNTS_AR.md) and
[`DEMO_FLOW_AR.md`](DEMO_FLOW_AR.md).

On Windows, `run_project.bat` starts both the FastAPI backend
(`127.0.0.1:8000`) and the Vite frontend (`npm run dev`) in separate windows
and does not modify any project code.

### Backend

```powershell
cd server
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Copy `.env.example` (repo root) to `.env` and set `ZX_DEMO_DEV_PASSPHRASE` to
a local value — see [Environment variables](#environment-variables) below
for the full list. The default `.env.example` block (`ZX_LLM_MODE=ollama`,
`REQUIRE_OLLAMA=true`) requires a real local Ollama with the configured
model pulled — see [Optional Ollama startup](#optional-ollama-startup) — or
`/api/analyze` intentionally returns `AI_ENGINE_UNAVAILABLE` instead of a
silent fallback. For a quick start with no Ollama at all, either follow the
MOCK block in `.env.example`, or set `REQUIRE_OLLAMA=false` to use the
existing always-attempt/always-fall-back-safely development behavior.

```powershell
python -m uvicorn main:app --reload --port 8000
```

The Government Future Engine stages (Predict/Simulate/Challenge/Evolve/
Prevent/Monitoring) run their deterministic logic regardless of AI
configuration — an LLM is only ever used, optionally, to phrase an
already-computed explanation, and every agent falls back to a plain-Python
template when no LLM is configured or reachable.

### Frontend

Open a second PowerShell window:

```powershell
cd client
npm install
npm run dev
```

Open <http://localhost:5173>.

## Quality checks

```powershell
cd server
$env:PYTHONPATH="."
python -m unittest discover -s tests -v

cd ..\client
npm run lint
npm run build
```

`RUN_TESTS.ps1` runs the same three checks (backend tests, frontend lint,
frontend build) in one step, using the `server\.venv` created above.

## Runtime state

The Sandbox stores Blueprints, customers, plan versions, consent states,
payments, execution events, audit entries, and every Government Future
Engine stage's output (Predictions, Scenarios, Challenges, Evolutions,
Preventions, Alerts) in a single SQLite file — `server/data/runtime.db` on
first run, then persisted at `~/ZERO-XRAY-DATA/runtime.db` (or
`%USERPROFILE%\ZERO-XRAY-DATA\runtime.db` on Windows, or `D:\ZERO-XRAY-DATA`
when a `D:` drive exists) so data survives re-extracting the project. This
persistent copy is intentionally excluded from version control (see
`.gitignore`) and is created automatically on first run.

SQLite is intentionally used for the portable demo. Every store in
`server/core/*_store.py` is a small, isolated repository boundary that can be
replaced by managed PostgreSQL for deployment without touching the agents
that use it.

## Pricing safety

P.O. Box plan prices, mandatory one-time registration fees, optional add-ons
and confirmed tax are separate line items. The engine never treats every
currency value on a service page as a selectable package and does not invent a
VAT rate when the service-owner input does not confirm one.

## Production boundary

Before a live government deployment, replace Sandbox identity, payment and
execution adapters with approved integrations; add enterprise identity/RBAC,
managed secrets, encryption, data-residency controls, immutable audit storage,
security testing, monitoring and formal service-owner approval. The
Government Future Engine's Monitoring stage in particular would need a real
scheduler/notification integration (none exists today — see Limitations
above) before it could be relied on for unattended production alerting.


## Setup, dependencies, and test environment

### Backend installation

```powershell
cd server
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For running the complete backend test suite, install the test requirements (this includes the runtime requirements):

```powershell
pip install -r requirements-test.txt
```

`requirements.txt` declares the dependencies imported by the active backend, including FastAPI, LangGraph/LangChain Core, PyMuPDF, PyJWT, PostgreSQL support (`psycopg`), and NumPy. The heavier in-process embedding/model stack remains optional in `requirements-ai.txt` and is not required for the primary Ollama HTTP path.

### Frontend installation

```powershell
cd client
npm ci
npm run dev
```

Use `npm ci` when reproducing a tested setup from `package-lock.json`; `npm install` remains valid for normal development.

### Environment variables

Copy `.env.example` to `.env` and replace placeholders only with values appropriate for the local/deployment environment. Do not place real secrets in `.env.example` or in `VITE_*` variables. Important groups include `DATABASE_URL`, demo/OIDC authentication settings, employee-session TTL, Ollama settings, allowed origins, and monitoring scheduler settings.

### Database initialization

No destructive initialization command is required. Start the backend and the existing database layer creates/updates the required schema additively. With `DATABASE_URL` unset, the existing SQLite behavior remains the local/demo default. For production, set `DATABASE_URL` to the PostgreSQL connection URL supplied by the deployment environment.

### Optional Ollama startup

Ollama is optional for code paths that retain deterministic fallback behavior. To use the configured local model:

```powershell
ollama serve
ollama pull qwen3:4b
```

Then set `OLLAMA_HOST` and `OLLAMA_MODEL` as shown in `.env.example`. The existing architecture is preserved: AI output is validated and combined with deterministic logic where applicable; when an agent-level AI call is unavailable or invalid, its existing deterministic/template fallback remains in place and provenance can report `FALLBACK`. For analysis routes configured with `REQUIRE_OLLAMA=true`, the backend intentionally returns `AI_ENGINE_UNAVAILABLE` instead of silently presenting a fallback as successful AI. Set `REQUIRE_OLLAMA=false` only when intentionally using the project's existing fallback-capable development behavior.

### Complete test commands

Backend tests use `pytest` so both unittest-style tests and pytest fixture/function tests are executed:

```powershell
cd server
$env:PYTHONPATH="."
python -m pytest tests -q
```

Frontend quality checks:

```powershell
cd client
npm run lint
npm run build
```

On Windows, `RUN_TESTS.ps1` runs these same three checks. Tests must not be deleted, skipped, or weakened to make this command pass.

## OpenAPI / Swagger import (Phase 10)

Entity users with integration-management permission can import a Swagger/OpenAPI definition from **Systems & Integrations** instead of registering every endpoint manually. Paste either a direct OpenAPI JSON/YAML URL or a Swagger UI URL, select the Service and environment (`SANDBOX`, `CONNECTED`, or `NOT_CONNECTED`), and ZERO X-RAY discovers the safe operation metadata and links the imported Integration to that Service. For users who also have Analyze permission, the import action immediately starts the existing analysis/build flow for that Service, so the generated Agent is grounded in the newly discovered operations.

The import is **discovery only**: it does not execute any described API operation. Future Journey capability grounding prefers a unique conservative structured OpenAPI operation match and records safe `operation_id`, HTTP method, path, and environment in traceability; when evidence is insufficient or the Integration is unavailable, the step remains `INTEGRATION_REQUIRED`. Existing manually configured Integrations continue to use the legacy fallback.

OpenAPI fetching is SSRF-protected. HTTPS/public hosts are the default. Trusted internal staging environments that intentionally resolve to private addresses require an operator-controlled `ZX_OPENAPI_ALLOW_PRIVATE_HOSTS=true`; do not enable that for public deployments. Credentials, API keys, authorization headers, secret references, and schema example values are not stored in the OpenAPI operation registry.
