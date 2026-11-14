# FlowRemote AI-RPA

FlowRemote is a browser-based control plane for AI-assisted data processing. It
combines Excel ingestion, deterministic order validation, grounded AI correction
suggestions, human review and approval, simulated RPA execution, audit logging,
local-first browser caching and portable local/enterprise database storage.

The current version is **0.6.0**. It is a complete promotional and course
demonstration application, but it is **not yet a production enterprise AI-RPA
product** because the RPA targets remain simulated and several production
security and operations features are still missing.

---

## Current maturity

| Area | Status |
| --- | --- |
| Account registration, login and persistent users | Implemented |
| Task creation and Excel upload | Implemented |
| Order validation and exception detection | Implemented |
| AI-assisted exception suggestions | Implemented |
| Per-user AI provider/model configuration | Implemented |
| Human Accept/Edit/Skip and approval gate | Implemented |
| Execution progress, results and audit log | Implemented with simulated targets |
| Local browser cache and offline review Outbox | Implemented |
| PWA install and offline summary page | Implemented |
| SQLite local / PostgreSQL enterprise switching | Implemented |
| Registration onboarding and AI-RPA management | Implemented |
| Light theme and section-by-section guided flow | Implemented |
| Portable Windows demo executable | Implemented and smoke-tested |
| Multi-source `.xlsx`/`.csv` normalization and 3-sheet export | Implemented (Demo Day Phase 1) |
| Real OA/BI/Excel connectors | Not implemented |
| Autonomous RPA Worker | Not implemented; execution currently advances through web requests |
| Retry / Resume / Cancel after partial execution | Not implemented |
| Production SaaS security and device revocation | Not implemented |

Typical intended flow:

```text
Register / Login
→ Upload source Excel
→ Validate order data
→ Review detected exceptions
→ Request or inspect AI suggestion
→ Accept / Edit / Skip
→ Approve batch
→ Execute approved records through simulated targets
→ View results and audit activity
```

With the local-first client:

```text
Server task snapshot
→ IndexedDB cache
→ Offline Accept / Edit / Skip
→ Local Outbox
→ Reconnect
→ Revision-checked idempotent synchronization
→ Updated authoritative server state
```

---

## Implemented features

### 1. Registration, authentication and isolation

- User registration with name, email and password.
- PBKDF2-HMAC-SHA256 password hashing with a per-user random salt.
- Signed, HTTP-only browser session cookie.
- Login, logout, signup and duplicate-email validation.
- Operator users only see tasks they own.
- Administrators can see all tasks.
- Unauthorized task access returns `404` rather than confirming that the task
  exists.
- Registered users are stored in the selected database and can log in again
  after an application restart.

### 2. Portable local/enterprise storage

The application uses a `StorageBackend` interface and a replaceable database
factory. Authentication and routes do not know whether storage is local SQLite
or enterprise PostgreSQL.

Local mode:

```text
FLOWREMOTE_STORAGE_MODE=local
FLOWREMOTE_DATABASE_URL=sqlite:///data/runtime/flowremote.db
```

Enterprise PostgreSQL mode:

```text
FLOWREMOTE_STORAGE_MODE=enterprise
FLOWREMOTE_ENTERPRISE_DATABASE_URL=postgresql://user:password@db.example.com:5432/flowremote
```

`FLOWREMOTE_DATABASE_URL` takes precedence, and the legacy `DATABASE_URL`
variable remains supported. Other database families can implement the same
`StorageBackend` protocol without changing authentication or route code.

### 3. Excel task creation

- Upload `.xlsx` workbooks up to 10 MB.
- Search up to the first 1,000 rows for a non-empty header row.
- Accept 1–10,000 data rows and up to 256 columns.
- Detect blank worksheets, malformed workbooks, wrong file types and missing
  required columns.
- Support English and common Chinese headers.
- Allow column reordering and ignore unrelated extra columns.
- Store the original workbook with a generated filename.
- Protect source downloads by task ownership and administrator role.
- Remove the task, metadata and stored file if import fails partway through.

### 4. Deterministic order validation

The current `orders-v1` rule set checks:

- `order_id`
- `customer_name`
- `customer_id`
- `quantity`
- `unit_price`
- `amount`
- `order_date`

Validation includes:

- Required values.
- Duplicate order IDs within one uploaded batch.
- Positive whole-number quantity.
- Finite, non-negative monetary values with at most two decimal places.
- Exact decimal amount = quantity × unit price.
- Real dates in supported Excel or text formats.
- Formula cells that have not been evaluated.
- Batch uniqueness after manual corrections.

The system retains:

- Original Excel row number.
- Original values.
- Current values.
- Issue codes and messages.
- Validation rule version.
- Original uploaded workbook.

### 5. Exception review and approval gate

Each unresolved exception supports:

- **Accept** — use the verified AI suggestion.
- **Edit order** — replace values manually and re-run all checks.
- **Skip** — exclude the record from execution.

Each action creates an append-only decision row. A client decision ID prevents
double-clicks from creating duplicate decisions.

The approval gate remains closed while any exception is unresolved. Approval:

- Is allowed only when unresolved exceptions reach zero.
- Creates exactly one approval row.
- Creates exactly one execution run for the attempt.
- Cannot be repeated to produce a second write.

### 6. Grounded AI exception suggestions

The `agent/` layer provides provider-independent suggestions:

- Deterministic offline provider for network-free demos and tests.
- OpenAI Responses API provider using schema-constrained structured output.
- Per-user AI provider, model, base URL and API-key configuration.
- Encrypted API-key storage derived from the application session secret.
- Customer candidate retrieval before generation.
- Field-level value, confidence, reason and evidence.
- No suggestion when evidence is insufficient.
- No invented customer IDs.
- No partial multi-field correction accepted as complete.
- Revalidation against all normal order rules.
- 70% minimum confidence for direct Accept.
- Idempotent request IDs and append-only suggestion-run audit records.
- AI-generated content never bypasses human review, approval or execution.

AI behavior examples:

- Missing `customer_id` with one exact customer-registry match can be suggested.
- Ambiguous or missing customer identity returns no guess.
- Missing quantity without evidence returns no guess.
- Amount mismatch with valid quantity and price can be calculated.

API keys are never stored in browser `localStorage` or IndexedDB and are never
returned to the client in plaintext.

### 7. Execution progress, results and audit

After approval, FlowRemote creates an execution run and shows:

- Approved record count.
- Written record count.
- Synced record count.
- Progress percentage.
- Execution duration.
- Success rate.
- Per-run result banner.
- Activity timeline.

The current execution engine processes 20 records per step and demonstrates:

- Progress from 0 to the approved count.
- Completion and results.
- Partial failure through `FLOWREMOTE_EXECUTION_FAIL_AT`.
- Repeat-step and repeat-approval protection.
- Append-only activity events.
- JSON audit export at `/tasks/{task_id}/activity.json`.

**Important:** every OA/BI target is simulated. The database counters and audit
events are real, but no external enterprise system is written.

### 8. Local-first synchronization and offline review

The server remains authoritative. The browser keeps an IndexedDB cache containing:

- Latest visible task snapshot.
- Exceptions and revisions.
- Latest execution run.
- Verified AI suggestions and evidence.
- Sync cursor.
- Pending offline operations in an Outbox.

When offline, a user can queue:

- Accept.
- Skip.
- Single-field or multi-field Edit.

When the network returns:

- Operations are sent one at a time.
- Decision IDs provide idempotency.
- The task revision is checked.
- Stale changes return `409 revision_conflict`.
- A newer change on another device is never silently overwritten.

The header displays `Synced`, `Queued`, `Offline cache`, `Conflict` or an
availability warning.

### 9. PWA and offline cache

- Installable PWA manifest.
- Root-scoped service worker.
- App-shell caching.
- Network-first page navigation.
- Cache-first static assets.
- Offline summary page driven by IndexedDB.
- Account-bound local cache.
- Automatic local-cache clearing on logout and login pages.
- Manual **Clear local cache** action in AI settings.

This prevents a second account using the same browser from seeing the previous
account's cached tasks or AI content.

### 10. Demonstration and documentation

- Bundled seed data: 100 orders, 88 passed and 12 flagged.
- Demo accounts for operator and administrator roles.
- Self-contained Feature 3 demo:

```powershell
.\.venv\Scripts\python.exe demo\run_feature3_demo.py
```

- Automated Feature 3 demo check:

```powershell
.\.venv\Scripts\python.exe demo\run_feature3_demo.py --check
```

### 11. Registration onboarding and AI-RPA management

New registrations are routed into `/onboarding`, where the user configures:

- AI provider and model.
- Offline Demo AI or an OpenAI-compatible endpoint.
- Encrypted API key.
- Local Excel and HTTP targets.
- AI and RPA enable/disable controls.
- Daily request and execution limits.
- Maximum records per task.

The permanent control is that AI cannot remove human approval.

After setup, `/settings` provides an AI-RPA control center with current model,
connector status, daily usage, processed records, failures and automation
limits.

### 12. Light theme and guided flow

The promotional UI defaults to a light theme. Major sections carry stable guide
anchors, and `guide.js` presents a flow-aware explanation card in the matching
section:

- Close only the current card.
- Resume the current card from the toolbar.
- Move to the next same-page section or page.
- Exit and restart the guide.
- Persist guide progress per signed-in account.

The guide covers demo entry, registration, AI-RPA onboarding, upload,
validation, exception review, approval, execution, results, audit and settings.

### 13. Multi-source cleanup (ENT207TC Demo Day)

A normalizer runs alongside the existing `orders-v1` path. It accepts up to six
`.xlsx`/`.csv` files (10 MB each, 20 MB combined), detects the best worksheet and
header row, maps English/Chinese aliases with confidence and evidence, converts
thousand-CNY prices and boxes, normalizes ISO / DD-MM-YYYY / Excel-serial dates,
merges duplicate `order_id`s, and records conflicts instead of overwriting them.

- Rule version: `normalize-v1`; no external AI call is required.
- Result contract: `order_id`, `customer_name`, `customer_id`, `quantity`, `unit`,
  `unit_price`, `amount`, `order_date`, `source_file`, `source_row`.
- Recognition and mapping happen at upload; the visible cleaning run normalizes
  each file and merges the batch with a 300–500 ms progress refresh, cancel and
  idempotent restart.
- The result is `FlowRemote_normalized_YYYYMMDD_HHMM.xlsx` with **normalized**,
  **changes** (rule/AI/human provenance) and **unresolved** sheets.
- The Demo Day pack in `data/demoday/` has six deterministic files, 174 source
  rows, 36 merged records and exactly six confirmation items: two missing values,
  two unit conflicts and two cross-file conflicts. All names are synthetic.
- Build the pack, account and fallback batch with:

```powershell
.\.venv\Scripts\python.exe src\flowremote\devtools\seed_demoday.py --reset
```

The multi-source **editable** confirmation queue and the visible AI connection
test are the next increment; this phase records the six items, exports them and
keeps the existing review/AI layers intact.

### 14. Portable Windows executable

Download the current build:

- [FlowRemoteDemo.exe](dist/FlowRemoteDemo.exe)
- [Windows executable guide](WINDOWS_EXE.md)

Build a one-file Windows demo with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_demo_exe.ps1
```

Output:

```text
dist\FlowRemoteDemo.exe
```

Double-clicking the EXE:

1. Creates isolated runtime data under `%LOCALAPPDATA%\FlowRemoteDemo`.
2. Applies all database migrations.
3. Seeds the demonstration task and demo accounts.
4. Starts FastAPI on a local loopback port.
5. Waits for `/health`.
6. Opens the default browser at `/demo`.
7. Shows a small control window for opening the browser, opening the data
   folder, or stopping the local services.

The EXE also supports:

```text
FlowRemoteDemo.exe --smoke-test
FlowRemoteDemo.exe --headless --no-browser
```

The final `dist/FlowRemoteDemo.exe` and its SHA-256 checksum are deliberately
tracked in Git for direct download. Other generated files under `dist/` and all
files under `build/` remain ignored.

---

## Architecture

```text
Browser / Installable PWA
├── Jinja-rendered HTML
├── IndexedDB snapshot cache
├── Offline Outbox
├── Service Worker
└── AI settings and review UI
          │
          ▼ HTTPS
FastAPI application
├── Authentication and role guards
├── Task and upload routes
├── Review and approval rules
├── AI suggestion and settings routes
├── Sync snapshot / pull / operation APIs
├── Execution controls and audit export
└── StorageBackend
          │
          ├── SQLite (local)
          └── PostgreSQL (enterprise target)

AI providers
├── Offline grounded rules
└── OpenAI Responses API

RPA targets
└── SimulatedTarget / SimulatedFailure
```

### Source layout

```text
src/flowremote/
  contracts/      enums, domain models, time format
  control_plane/  storage, auth, validation, review, decisions, sync, activity
  agent/          AI provider contracts, orchestration, validation, settings
  rpa/            execution step rules
  connectors/     simulated OA/BI targets
  api/            FastAPI app, dependencies and routes
  ui/             Jinja templates, CSS, JavaScript, PWA assets
  devtools/       seed data and local helpers
```

### Technical stack

- Python 3.13
- FastAPI
- Uvicorn
- Jinja2
- Pydantic
- SQLite
- PostgreSQL via `psycopg`
- OpenAI Python SDK and Responses API structured output
- `cryptography` for encrypted AI credentials
- openpyxl for Excel parsing
- Native JavaScript
- IndexedDB
- Service Worker / Web App Manifest
- pytest

---

## Data model

Core business tables:

- `users`
- `tasks`
- `source_records`
- `exceptions`
- `decisions`
- `approvals`
- `task_uploads`
- `order_inputs`
- `task_validations`
- `execution_runs`
- `activity_events`
- `ai_suggestion_runs`
- `ai_suggestion_items`
- `ai_settings`
- `devices`
- `sync_clock`
- `sync_changes`
- `schema_version`

Important invariants:

- Users are globally unique by email.
- One task approval is unique per attempt.
- One approved attempt creates one execution run.
- Decisions are append-only.
- Activity events are append-only.
- Written count cannot exceed approved count.
- Synced count cannot exceed written count.
- Exception and task revisions support optimistic concurrency.
- Sync cursors are monotonic.

---

## HTTP interfaces

### Authentication

| Method | Path |
| --- | --- |
| GET | `/login` |
| POST | `/login` |
| GET | `/signup` |
| POST | `/signup` |
| POST | `/logout` |

### Tasks and uploads

| Method | Path |
| --- | --- |
| GET | `/` |
| GET | `/tasks/new` |
| POST | `/tasks` |
| GET | `/tasks/{id}` |
| GET | `/tasks/{id}/source` |
| POST | `/tasks/{id}/validate` |
| GET | `/orders-template.xlsx` |

### Review and approval

| Method | Path |
| --- | --- |
| POST | `/tasks/{id}/exceptions/{recordId}/decisions` |
| POST | `/tasks/{id}/exceptions/{recordId}/suggestions` |
| POST | `/tasks/{id}/proceed` |
| GET | `/tasks/{id}/approval` |
| POST | `/tasks/{id}/approval` |
| POST | `/tasks/{id}/back-to-review` |

### AI settings

| Method | Path |
| --- | --- |
| GET | `/settings/ai` |
| POST | `/settings/ai` |

### Simulation and audit

| Method | Path |
| --- | --- |
| GET | `/tasks/{id}/execution` |
| POST | `/tasks/{id}/execution/step` |
| GET | `/tasks/{id}/execution.json` |
| GET | `/tasks/{id}/results` |
| GET | `/tasks/{id}/activity.json` |
| POST | `/tasks/normalize` | Create a multi-source cleanup batch |
| POST | `/tasks/{id}/normalize/start` | Start or resume the cleaning run |
| POST | `/tasks/{id}/normalize/tick` | Advance one deterministic progress step |
| GET | `/tasks/{id}/normalize/status` | Progress snapshot |
| POST | `/tasks/{id}/normalize/cancel` | Cancel and remove derived rows |
| GET | `/tasks/{id}/normalize/download` | Three-sheet cleaned workbook |

### Local-first synchronization

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sync/bootstrap` | Register device and return authoritative snapshot |
| GET | `/api/sync/pull?cursor=N` | Return changes after a cursor |
| POST | `/api/sync/operations` | Apply a revision-checked idempotent decision |
| GET | `/sw.js` | Root-scoped service worker |
| GET | `/static/manifest.webmanifest` | PWA metadata |

---

## Run FlowRemote locally

```powershell
cd E:\knight_hell

# Install or update dependencies
uv sync

# Rebuild the Demo Day six-file pack, account and fallback batch
.\.venv\Scripts\python.exe src\flowremote\devtools\seed_demoday.py --reset

# Optional: rebuild the original single-workbook orders-v1 demo
.\.venv\Scripts\python.exe src\flowremote\devtools\seed.py --reset --verify

# Start the web application
.\.venv\Scripts\python.exe -m uvicorn flowremote.api.app:app `
  --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

### Demo accounts

| Email | Password | Role |
| --- | --- | --- |
| `demo@flowremote.dev` | `DemoDay2026!` | operator (Demo Day) |
| `alex.morgan@example.com` | `123456` | operator |
| `admin@example.com` | `123456` | admin |

The demo password is for local demonstration only. Do not deploy these accounts
to a public production environment.

### AI configuration

Copy `.env.example` to `.env` when environment configuration is needed.

Default demonstration behavior:

```text
FLOWREMOTE_AI_PROVIDER=offline
```

Online provider:

```text
FLOWREMOTE_AI_PROVIDER=openai
FLOWREMOTE_AI_MODEL=gpt-6-astra
OPENAI_API_KEY=...
```

Users can also configure provider, model, base URL and encrypted key from the
in-app **AI settings** window.

---

## Tests and verification

Current repository status:

- **272 tests passed**
- **11 subtests passed**
- Python compilation passed
- Browser JavaScript syntax passed
- All migrations `0001` through `0009` applied successfully
- Seed data reproduces 100 input / 88 passed / 12 flagged
- Demo Day pack reproduces 6 files / 174 rows / 36 merged records / 6 issues
- Feature 3 automated demo passes all nine checks

Coverage includes:

- Password hashing and session signing.
- Registration persistence across app restart.
- Operator/admin task isolation.
- Workbook parsing and upload limits.
- Order validation and correction.
- AI settings, encryption and per-user isolation.
- Offline/online AI provider behavior.
- Review decisions and approval gate.
- Execution progression, completion and partial failure.
- Activity log export.
- Sync bootstrap, device registration, pull cursor and PWA assets.
- Offline decision idempotency and revision conflicts.
- Multi-field offline corrections.
- Local and enterprise storage selection.
- Registration onboarding and AI-RPA usage controls.
- Demo landing page, guide assets, Light theme assets and EXE smoke checks.
- Multi-source detection, alias mapping with evidence, unit/date normalization,
  duplicate merge, cross-file conflicts, progress/cancel/restart and 3-sheet export.

---

## Not implemented or not production-ready

### RPA execution

- External OA, BI, Excel Online or enterprise APIs are not connected.
- Execution targets are simulated.
- The browser polling endpoint currently advances simulated execution.
- There is no independent background Worker or device agent.
- There is no lease, heartbeat, distributed lock or worker recovery.

### Failure recovery

- Partial execution cannot be retried or resumed.
- There is no Cancel/Pause state machine.
- There is no per-record receipt or remote reconciliation.
- The task state has no dedicated `partial`, `cancelled` or `paused` value.

### Workflow platform

- No workflow-template builder.
- No scheduled triggers.
- No queue management.
- No multiple workflow definitions.
- Zero-exception uploads currently still enter the review screen.
- No separate queued-to-running workflow launcher.

### Enterprise security

- No CSRF token on state-changing forms.
- No login rate limiting or account lockout.
- No password reset or email verification.
- No MFA.
- No server-side session revocation.
- Device rows are registered but remote device revocation is not implemented.
- No organization/tenant model.
- Only operator/admin roles exist.
- No approver, auditor or integration-admin roles.

### File and data storage

- Uploaded files use local disk rather than enterprise object storage.
- No virus scanning.
- No retention/deletion automation.
- No signed object-storage URLs.
- PostgreSQL configuration exists, but no real enterprise database was connected
  during verification.

### Local-first limitations

- Offline support currently covers Accept/Edit/Skip on a loaded review page.
- Task creation and AI generation require a server connection.
- Full workflow browsing while offline uses only the cached snapshot.
- Conflict resolution requires the user to reload/review the newer server state.
- Service Worker behavior has syntax and static-asset tests, but no full
  Playwright offline browser suite yet.

### Operations

- No Docker/Kubernetes deployment package.
- No CI/CD pipeline checked into the repository.
- No metrics endpoint or tracing.
- No automated backup/restore.
- No antivirus, SIEM or enterprise secret manager integration.
- No high-volume load test.

### AI

- The online provider adapter is tested with a fake client, not a paid live API
  call.
- No completed evaluation set or acceptance-rate dashboard.
- No batch generation for all exceptions.
- No automatic decisions or training.
- External-model data-governance policy remains deployment-specific.

---

## Recommended next work

The most valuable next milestone is a **real promotional execution loop**, not
more UI features:

1. Add a database-backed Worker with leases and heartbeats.
2. Implement a real Local Excel Connector.
3. Implement a bundled Local HTTP Target Connector.
4. Record one receipt per external record.
5. Add Retry failed only, Resume, Pause, Cancel and reconciliation.
6. Add server-side sessions, CSRF, rate limits and device revocation.
7. Add one approved enterprise OA/BI connector using real API documentation.
8. Add Playwright end-to-end and offline browser tests.

After those are complete, FlowRemote can credibly move from a promotional
prototype to a pilot-ready AI-RPA control plane.

---

## Documentation

- `docs/project-summary.md` — overall project history and interfaces.
- `docs/flowremote-prd.md` — product requirements.
- `docs/flowremote-state-machine-spec.md` — lifecycle and transition rules.
- `docs/p5-report.md` — execution, results and audit implementation.
- `docs/p6-report.md` — AI suggestions, AI settings and storage boundary.
- `docs/p7-local-sync.md` — local-first cache, Outbox and PWA design.
- `docs/flowremote-layered-architecture.html` — visual layered architecture.
- `demo/README.md` — demo commands and walkthrough.
- `docs/demoday-gap-analysis.md` — current state → gap audit.
- `docs/demoday-progress-and-next-steps.md` — phase-1 status, sample DB and detailed C/D backlog.
- `docs/demoday-demo-runbook.md` — 60-second prep, 6-minute script and fallbacks.
- `prompts/prompt-log.md` — AI-use and implementation prompt log.
