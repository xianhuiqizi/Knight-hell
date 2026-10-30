# P6 / Feature 3: grounded AI suggestions

Date: 2026-10-30

## 1. User value

An operator can request an AI correction for an unresolved order, inspect the
reason and evidence, and explicitly accept it. The AI is an adviser, not an
actor: it cannot change an exception, approve a batch or execute a target.

## 2. Scope

Implemented:

- field-level suggestions with confidence, reason and evidence;
- deterministic offline suggestions for a unique customer-registry match and
  quantity × unit price;
- an optional OpenAI Responses API provider with schema-constrained output;
- full business-rule verification before a suggestion can be accepted;
- append-only suggestion runs and field items with idempotent request ids;
- failed, invalid and low-confidence states that keep manual review available;
- role/ownership/state guards and engine-attributed activity events;
- human Accept applying the suggestion to the correct fields;
- a per-user AI connection window for selecting the offline or
  OpenAI-compatible provider, model, base URL and encrypted API key.

Not in this feature:

- background batch generation for all exceptions;
- automatic review decisions;
- customer-data training or fine-tuning;
- real OA/BI execution and retry after a partial write.

## 3. Request flow

1. The authenticated operator posts a request id for one unresolved exception.
2. The server rechecks task visibility, task state and exception state.
3. The server hashes the minimum context and loads at most eight exact customer
   candidates by name or ID.
4. A pending suggestion run is committed before any external call.
5. The offline or online provider returns structured field changes.
6. The server rejects unknown fields, invented customer values, incomplete
   multi-field corrections, malformed confidence and values that fail
   `orders-v1`.
7. A second transaction records the run and items, updates the legacy
   display fields only for an actionable result, and appends an activity event.
8. Accept revalidates and applies the active structured suggestion. It then
   records the human decision exactly like Edit or Skip.

The provider call is never made while a database transaction is open. A UNIQUE
constraint on `(exception_id, request_id)` makes repeated clicks idempotent.

## 4. Data model

| Table | Purpose |
| --- | --- |
| `ai_suggestion_runs` | request id, status, provider/model, prompt version, input hash, safe error, timing and raw structured response |
| `ai_suggestion_items` | one proposed field value with confidence, reason and evidence |
| `ai_settings` | per-user provider, model, base URL and encrypted API key |
| `activity_events` | append-only engine event for successful, invalid or failed generation |

`exceptions.suggestion`, `confidence` and `reason` remain the quick display and
legacy decision fields. The authoritative multi-field correction is the latest
completed run whose items cover every flagged field.

## 5. Safety rules

- Customer values are accepted only from retrieved registry candidates.
- Uploaded cell values are labelled as untrusted data in the model prompt.
- The model cannot introduce a field outside `flagged_fields`.
- No suggestion is better than an unsupported guess.
- Confidence below 0.70 is visible but not acceptable.
- A failed or invalid regeneration leaves the last verified suggestion intact.
- The model never receives credentials, another task or the whole workbook.
- API keys and full prompts are not stored in the database or activity log.
- API keys saved from the connection window are encrypted with a key derived
  from the application session secret; only the final four characters are
  returned to the browser as a hint.
- The connection window performs validation only and does not send a test API
  request when settings are saved.

## 6. Configuration

```text
FLOWREMOTE_AI_PROVIDER=offline | openai
FLOWREMOTE_AI_MODEL=gpt-6-astra
OPENAI_API_KEY=...
FLOWREMOTE_CUSTOMER_REGISTRY=path/to/customer_registry.csv
```

`offline` is the default, so tests and the seeded demo do not require network
access or paid calls. The `openai` mode uses the Responses API structured-output
parser and fails safely when no key is configured.

Each signed-in user can override these defaults from **AI settings**. That
configuration is read again when the user requests an exception suggestion, so
the connected model and endpoint are used by the existing Feature 3 pipeline.

The online adapter follows the official OpenAI documentation for
[structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and uses the official Python SDK.

## 7. Verification

| Scope | Result |
| --- | --- |
| Complete repository suite | 222 passed, 11 subtests passed |
| Feature 3 unit tests | offline grounding, no-guess behaviour, OpenAI adapter, missing key |
| Feature 3 integration tests | generation, correct-field Accept, idempotency, invalid values, partial correction, provider failure, low confidence, regeneration, guards |
| Regression | existing review, approval, execution and upload tests pass |

The Feature 3 group adds 28 focused tests, including encrypted key persistence,
per-user isolation, URL validation, the no-network save path and provider
selection. The live OpenAI path has an adapter test with a fake client and no
network call.
The persistence/deployment group adds seven focused tests for account survival
and storage selection.
No claim is made that a paid model request was executed because this workspace
does not contain an OpenAI API key.

## 8. Account persistence and enterprise storage boundary

Feature 3 depends on persistent accounts. Registration writes the `users` row
and password hash to the selected database; sign-in reads it again. A restart
test creates a user, closes the application, creates a second application
instance against the same SQLite file, and signs in successfully.

`StorageBackend` is the replaceable persistence interface. `create_app` accepts
a database factory, so routes are independent of the concrete database. The
included implementations are:

| Mode | Configuration | Driver |
| --- | --- | --- |
| Local | `FLOWREMOTE_STORAGE_MODE=local` | SQLite standard library |
| Enterprise | `FLOWREMOTE_STORAGE_MODE=enterprise` plus PostgreSQL URL | psycopg |

`FLOWREMOTE_DATABASE_URL` can override either mode and the legacy `DATABASE_URL`
remains supported. Enterprise mode refuses to start without a PostgreSQL URL.
Unsupported URL errors do not echo credentials. A company using a different
database family can implement `StorageBackend` and provide another factory
without rewriting authentication.

This change does not connect to an unknown enterprise database automatically.
Deployment still requires the company's approved host, Database Name, user,
password, TLS policy and migration permissions.
