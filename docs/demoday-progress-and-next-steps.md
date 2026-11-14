# Demo Day progress and next steps

Snapshot date: 2026-11-14 · version **0.6.0** · branch `main` based on `1c79fe6`.

This document is the hand-off for the ENT207TC Demo Day build. It records what
is complete, what is deliberately read-only in the current phase, and the
detailed work remaining for the visible AI connection panel (C) and the
human confirmation queue (D).

---

## 1. Current status at a glance

| Item | Status |
| --- | --- |
| Phase 1 scope (A + B + E + F skeleton) | **Complete** |
| Existing `orders-v1` flow | **Unchanged and passing** |
| Multi-source upload (6 × `.xlsx`/`.csv`) | **Complete** |
| Upload-time recognition and mapping evidence | **Complete** |
| Unit/date normalization, duplicate merge, conflict issues | **Complete** |
| Progress / cancel / idempotent restart | **Complete** |
| Activity timeline | **Complete for normalization stages** |
| Three-sheet `.xlsx` download | **Complete** |
| Visible AI connection test (C) | **Not started** |
| Editable human confirmation cards (D) | **Not started** |
| Tests | **272 passed, 11 subtests** |
| Demo sample database | **Committed** at `data/demoday/demo_flowremote.db` |

The normalizer is deterministic, rule-first and makes no network request. C/D
are the next increment; they are not hidden failures in the current page.

---

## 2. What is already delivered

### 2.1 Demo Day pack

`data/demoday/` contains six deterministic, synthetic files:

1. `01_orders_header_offset.xlsx` — headers on row 4; missing customer ID.
2. `02_orders_thousand_cny.xlsx` — English aliases; `Price (CNY '000)` and one
   row deliberately entered in CNY rather than thousand CNY.
3. `03_orders_shuffled.csv` — CSV, shuffled columns, extra region/priority/note
   fields, `YYYY/MM/DD` dates.
4. `04_orders_second_sheet.xlsx` — cover sheet + second data sheet; mixed
   `DD/MM/YYYY` strings and Excel serial dates; other side of both conflicts.
5. `05_orders_warehouse_boxes.xlsx` — boxes with a box/piece inconsistency.
6. `06_orders_chinese_aliases.xlsx` — Chinese headers; missing quantity.

Expected result:

```text
6/6 recognized
174 source rows
36 merged records
143 records with rule-based fixes
230 field-level changes
6 unresolved items:
  missing_value       2
  unit_conflict       2
  cross_file_conflict 2
```

### 2.2 Sample database

`data/demoday/demo_flowremote.db` is a clean, fully normalized snapshot:

- one account: `demo@flowremote.dev / DemoDay2026!`;
- one normalize task `TASK-0724AA1895` in `needs_review`;
- 174 normalized source rows, 36 primary merged records;
- 230 `normalization_changes`, 6 `normalization_issues`;
- six activity events;
- no real user task or personal data from a developer machine.

It references six upload files by generated storage name. Those files are
committed under `data/demoday/sample_uploads/`. Run the snapshot without touching
`data/runtime/`:

```powershell
$env:FLOWREMOTE_DATABASE_URL="sqlite:///C:/.../Knight-hell/data/demoday/demo_flowremote.db"
$env:FLOWREMOTE_UPLOAD_DIR="C:/.../Knight-hell/data/demoday/sample_uploads"
.\.venv\Scripts\python.exe -m uvicorn flowremote.api.app:app --host 127.0.0.1 --port 8000
```

For a fresh live demo, prefer:

```powershell
.\.venv\Scripts\python.exe src\flowremote\devtools\seed_demoday.py --reset
```

### 2.3 Implementation surface

- Contract: `src/flowremote/contracts/normalization.py`.
- Rules: `src/flowremote/control_plane/normalization.py`.
- Job/progress/export: `src/flowremote/control_plane/normalization_jobs.py`.
- HTTP: `src/flowremote/api/routes/normalization.py`.
- Migration: `0009_normalization.sql` (additive only).
- UI: `normalize_task.html`, `app.js`, `app.css`, `new_task.html`.
- Seed/data: `devtools/demoday_data.py`, `devtools/seed_demoday.py`,
  `data/demoday/`.
- Tests: 24 unit + 14 integration in
  `tests/unit/test_normalization.py` and
  `tests/integration/test_normalization.py`.
- Evidence: `output/demoday-phase1/` (7 screenshots + downloaded workbook).

### 2.4 Verified numbers

```text
pytest tests -q
272 passed, 11 subtests passed in 49.81s

python -m compileall src/flowremote       passed
node --check src/flowremote/ui/static/app.js  passed
```

Existing 234 tests were not edited. The running normalization tick completed in
3.0 s in the live walkthrough (limit: 20 s). The downloaded workbook had three
sheets with 37 / 231 / 7 rows including headers.

---

## 3. Deliberate phase-1 boundaries

These are the exact reasons the current confirmation cards are read-only:

1. No editable inputs, no per-field save/recheck, no Confirm/Skip actions.
2. All six issues remain `unresolved`; the card shows **Pending confirmation**.
3. The summary shows **0 human / 6 to confirm / 0 skipped**.
4. Download is currently enabled while unresolved, because phase 1 is a
   download skeleton. Phase D must change this to a hard completion gate.
5. No AI connection test endpoint or panel; the normalizer makes no network
   call.
6. The timeline has no `ai_call` or `human_confirm` events yet.

Do not present the current read-only cards as a working human review step.

---

## 4. Next increment C — visible AI connection

### C1. Backend connection test

- Add `POST /settings/ai/test` (JSON and form-capable).
- Inputs: `provider` (`openai_compatible` / `offline`), `base_url`, `model`,
  `api_key`.
- Reuse `AISettingCipher`; never return the plain key. Keep the existing
  encrypted `ai_settings` table.
- OpenAI-compatible test:
  - Use a 2.5–3.0 s total timeout and no retries.
  - Prefer `GET {base_url}/models` with `Authorization: Bearer <key>`; if the
    endpoint does not implement model listing, fall back to a minimal
    model-backed request. Return the model id actually reported by the service.
  - Measure latency and return `{ok, provider, model, latency_ms, message}`.
  - Map errors to actionable messages:
    - 401/403 → invalid key;
    - 429/quota → rate/quota problem;
    - timeout/DNS/TLS/connect → network problem;
    - 404 model → model name unavailable;
    - other → short provider-neutral message.
- Offline Demo AI: return immediately with model `grounded-rules-v1`, latency 0,
  no network.
- Persist only after a successful connection (or explicit offline selection).
- Do not write key material to logs, activity descriptions, JSON exports or the
  database except as ciphertext + last-four hint.

### C2. UI panel

- Add a visible card/modal with:
  - Provider: OpenAI-compatible / Offline Demo AI.
  - Base URL, Model.
  - API key `type=password`, placeholder that says the saved key can be kept.
  - `Connect` button; spinner with a hard 3 s client-side cutoff.
  - Result line: `Connected · <model> · <latency> ms`.
  - Error line with a `Use Offline Demo AI` fallback button.
- `FLOWREMOTE_DEMO_MODE=1` may prefill Base URL/model from environment, but the
  UI must still show the paste → Connect interaction for the demo.
- After a failed online test:
  - Automatically offer/enter **Offline Demo AI** without blocking the cleanup.
  - Show a yellow banner: `Offline Demo AI · rules only`.
- Never write the key to `localStorage`, IndexedDB, query strings, page HTML or
  browser logs. Clear the password field after save/test.
- The modal must work on every authenticated page and in the full
  `/settings/ai` page.

### C3. Tests for C

- Successful fake provider returns model + latency within 3 s.
- Timeout/connection/401/429/404 mapping to readable messages.
- Offline provider works with no network.
- Key is encrypted at rest and never echoed.
- Failure falls back to Offline Demo AI and the flow can finish.
- Demo-mode environment prefill does not leak a key.
- Widget/form has password input, last-four hint only.

### C4. Acceptance for C

- A pasted valid key returns model name + latency in under 3 s.
- A wrong key shows a readable invalid-key message in under 3 s.
- A network failure can be recovered with a single offline fallback action.
- Nothing secret appears in HTML, localStorage, IndexedDB or logs.
- Cleanup still completes with offline AI and the page says offline mode.

---

## 5. Next increment D — editable human confirmation

### D1. Data and rules

Use additive migration `0010_normalization_human_review.sql`:

- `normalization_decisions` append-only table:
  - id, batch_id, task_id, issue_id, decision_id (UNIQUE), action
    (`confirm` / `skip`), changes_json, by_user, decided_at.
- Add to `normalization_issues` (or a companion table):
  - `resolved_by`, `resolved_at`, `revision`, `resolved_fields_json`.
- Reuse `normalization_changes.method='human'` for field edits.
- Every resolved/skipped item writes an activity event `normalize_human`.
- Every human action is idempotent by `decision_id` and revision-checked.

Revalidation after each save:

- Required fields present.
- `quantity` positive whole number.
- `unit` canonical (`piece`, `box`, `kg`); if box, apply conversion.
- `unit_price`, `amount` non-negative and amount = quantity × unit price within
  the existing 0.005 tolerance.
- `order_date` real ISO date.
- Duplicate/conflict checks across the merged batch.
- Cannot resolve an issue into an invalid record; show field-level error.
- Cross-file conflict: the human chooses a value/source; the primary normalized
  record is updated; the other source rows remain recorded in the audit.
- Missing customer ID: registry suggestion may be prefilled but the human must
  confirm; never auto-accept.
- Missing quantity: no invented value; human must enter it or skip.

Skip semantics (must be explicit in the UI and workbook):

- Skip marks the issue `skipped`, records a reason (required), leaves the
  affected normalized values as-is, and includes the row in `unresolved` with
  `status=skipped`.
- Skipped is not the same as resolved; it is allowed to complete so the demo can
  show a skip count.

### D2. UI cards

For each of the six issues, replace `Pending confirmation` with:

- Issue type badge, order id, source file + row, field(s).
- Original value.
- AI/rule suggested value + confidence + reason (“why uncertain”).
- One or more editable inputs:
  - missing customer ID → customer_id text input;
  - missing quantity → quantity number input;
  - unit conflict → normalized unit/quantity/price fields;
  - cross-file conflict → choose source/value or edit the primary fields.
- `Save & recheck` button; disabled until a change exists.
- `Skip` button with a required short reason.
- Inline validation error next to the field; no page reload losing context.
- On success: card becomes resolved/skipped, remaining count decrements.

Gate:

- Header/summary: `Needs your confirmation · N`.
- While N > 0, **Finish cleaning / Complete** is disabled and says
  `N item(s) still require a decision`.
- When N = 0, enable **Finish cleaning**; it writes the completion event,
  sets task status complete (or pending final export), and unlocks download.
- Provide a clear countdown `还剩 N 处` in English UI: `N left to confirm`.
- `Download cleaned .xlsx` must be disabled until N = 0 in the final increment.
  (Phase 1 currently permits the skeleton download; D closes this.)

### D3. Activity and summary

- Add event `normalize_human` per confirm/skip, actor = signed-in user.
- Final summary fields:
  - files, source rows, merged records, auto-fixed, human, skipped, duration,
    engine/model.
- Timeline expected:
  `upload → detect → map → ai_call (optional) → human_confirm → complete`.
- On offline AI, show `Offline Demo AI / grounded-rules-v1` in the summary and
  timeline.

### D4. Tests for D

- Opening the page shows exactly 6 editable cards.
- Saving a missing customer ID updates the normalized record and rechecks.
- Saving an invalid quantity/amount is rejected with a readable error.
- Confirming a unit conflict applies the chosen interpretation.
- Cross-file conflict resolution updates the primary record and audits both
  sources.
- Skip requires a reason and moves the issue to skipped.
- Counter decrements 6 → 0; Finish disabled until 0.
- Completion is idempotent; repeated Confirm/Skip with the same id is a no-op.
- Download is gated until zero unresolved; after completion the workbook
  contains human changes and skipped reasons.
- Owner/admin permission and revision conflict paths.
- 390 px layout remains usable; click path stays ≤12.

### D5. Acceptance for D

- Six cards appear, all fillable, with source/row/original/suggestion/reason.
- Filling and confirming each decrements the count; final item enables Finish.
- Invalid values are rejected, not saved.
- Skip is explicit and audited.
- Download contains correct `changes` (`human`) and `unresolved` (`skipped`)
  sheets only after completion.
- Whole flow ≤4 minutes and ≤12 clicks.

---

## 6. Final integration and demo polish

After C and D:

1. Add `ai_call` and `human_confirm` timeline events and update the summary.
2. Update `seed_demoday.py` to leave a fresh ready-to-start batch; add a
   `--completed` sample mode for a fully resolved reference database.
3. Update the sample DB with a completed 6/6 resolution and regenerate the
   downloaded workbook.
4. Rerun the 6-minute rehearsal three times; verify identical counts.
5. Record final screenshots (including AI panel, wrong-key error, six resolved
   cards, download gate, three-sheet workbook).
6. Update `docs/demoday-demo-runbook.md` with actual C/D interactions and
   fallback to Offline Demo AI.
7. Update README and this progress document with final counts and commit hash.
8. Re-run `pytest tests -q`; keep all original 234 tests and all new tests green.
9. Verify fresh clone → `uv sync` → `seed_demoday.py --reset` → uvicorn.
10. Verify 390 px viewport, network-off demo, and wrong-key recovery.

---

## 7. Suggested implementation order

1. C backend test endpoint + tests (smallest, unblocks UI).
2. C modal/panel + offline fallback + tests.
3. D migration + domain functions + revalidation unit tests.
4. D card forms + remaining counter + Finish gate + tests.
5. Activity/summary/download gate updates.
6. Final seed, sample DB, screenshots, runbook, README.

Risk / decision points to settle before D:

- How a skipped record should appear in the normalized sheet (proposal: keep the
  current normalized values and list the issue as skipped in `unresolved`).
- Which source wins for each cross-file conflict (proposal: human chooses).
- Whether a skipped-only batch is allowed to export (proposal: yes, with explicit
  skipped count, but no unresolved count).
- Exact C provider test route: `/models` is cheap but not universally supported;
  the fallback model request must stay under the 3 s budget.

---

## 8. Repository hygiene

The GitHub upload intentionally includes only the Demo Day deliverable:

- modified app/UI/docs;
- new normalization code, migration and tests;
- deterministic `data/demoday/` pack, sample DB and sample uploads;
- phase-1 screenshots and downloaded workbook.

Unrelated pre-existing untracked folders from other work (`data-public/`, `site/`,
`tools/`, `scripts/*tunnel*`, `prompts/demoday-improvement-prompt.md`, etc.) are
not part of this commit.

The sample DB contains no real names or personal data. The demo password is
public by design and must never be reused outside the local classroom demo.
