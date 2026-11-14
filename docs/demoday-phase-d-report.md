# Demo Day Phase D — editable human review with AI advice

Status: **implemented and verified** on 2026-11-14.

Phase D closes the last product gap in the six-minute multi-source cleanup
story: the six confirmation items are no longer read-only. Each card can be
edited and confirmed, skipped with an optional reason, or filled from an **AI
suggestion**.
The cleaned workbook is downloadable only after the human gate reaches zero and
the presenter presses **Complete cleaning**.

## 1. What the presenter sees

At the end of normalization the result page shows:

- a red/yellow summary banner: `Normalization finished with 6 item(s) to confirm`;
- a **Human gate** panel with `6 item(s) remaining`, confirmed/skipped counts and
  a disabled **Complete cleaning (6 left)** button;
- **Human review** cards for:
  - two missing values (`customer_id`, `quantity`);
  - two unit conflicts (`thousand CNY`, `box vs piece`);
  - two cross-file conflicts (`unit_price`, `amount`);
- each card contains the issue type, order ID, source file/row, original value,
  reason, current normalized values, editable fields, and:
  - **AI suggestion**
  - **Confirm**
  - **Skip** (optional reason; leaving it blank records a default audit reason);
- the download link is hidden/replaced with **Download unlocks after Complete
  cleaning**.

After all six cards are confirmed or skipped, the counter reads `0 item(s)
remaining`, **Complete cleaning** becomes enabled, and the page moves to
**Review complete** with the download button.

## 2. Editable fields and revalidation

The server never trusts the browser. A decision is accepted only if all of the
following pass in `normalization_review.py`:

| Check | Rule |
| --- | --- |
| Required fields | customer name/ID, quantity, unit, unit price, amount, date |
| Quantity | positive whole number, at most 1,000,000,000 |
| Unit | canonical `piece`, `box` or `kg` |
| Money | non-negative, at most two decimal places, at most 1 trillion |
| Date | real calendar date, normalized to ISO |
| Arithmetic | `abs(amount - quantity × unit_price) <= 0.005` |

A rejected edit returns HTTP 400 with a readable message and leaves the issue
`unresolved`. The issue is only marked `resolved` after the record update and
audit insert succeed in one transaction.

`missing_value` requires the missing field to be filled. `file_error` can only
be skipped. Both unit-conflict cases are resolvable:

- **thousand-CNY conflict**: the current values are arithmetically consistent as
  CNY; confirming the current values records the human decision.
- **box/piece conflict**: the offline suggestion converts the boxes to pieces
  (`quantity × 12`, unit `piece`) while keeping the amount unchanged.

## 3. AI suggestion

`POST /tasks/{id}/normalize/issues/{issue_id}/ai-suggest` is advisory and never
auto-confirms.

1. **Online**: if the user has a saved OpenAI-compatible connection, the server
   calls its Chat Completions endpoint with a bounded 8-second timeout. The
   default target is DeepSeek Flash (`deepseek-flash` at
   `https://api.deepseek.com`).
2. **Offline**: if the provider is offline, no key exists, the request times out
   or the API fails, grounded **Offline Demo AI** advice is returned instead.
   The UI displays a warning and still fills the form.
3. **Validation**: the returned JSON is filtered to the issue's editable fields,
   then passed through the same validation as a manual confirmation. An AI
   customer ID that is not already present in the batch is rejected and replaced
   by offline advice.
4. **Human control**: the fields are populated but the person must still press
   **Confirm** or **Skip**.
5. **Storage**: the last suggestion is stored on the issue
   (`ai_suggestion_json`, `ai_source`, `ai_suggested_at`). No key is returned,
   logged or placed in browser storage.

The AI prompt treats all workbook values and reasons as untrusted data, not
instructions. The model is asked for strict JSON only; the parser also accepts
fenced JSON and discards unknown fields.

## 4. Decision and gate semantics

`normalization_decisions` is append-only and has a unique client `decision_id`
for idempotency. A replay returns the existing outcome and does not create a
second change or activity row.

- **Confirm** writes changed fields to the primary `normalized_records` row,
  appends `human` rows to `normalization_changes`, marks the issue `resolved`,
  and logs `normalize_human_confirm`.
- **Skip** records the optional reason (or `No reason provided.`), removes the order's rows from the normalized
  output (`is_primary = 0`), marks the issue `skipped`, and logs
  `normalize_human_skip`. The skipped item remains in the `unresolved` sheet with
  the human reason appended.
- **Finish** is allowed only while the batch is `needs_review` and zero issues
  remain unresolved. It sets the batch and task to `complete`, stores
  `review_completed_at`, updates the record count, and logs
  `normalize_review_complete`.
- **Download** rejects anything except a `complete` batch. The workbook then has
  three sheets: `normalized`, `changes` (rule + human rows) and `unresolved`
  (header only when nothing was skipped).

## 5. API contract

```text
POST /tasks/{id}/normalize/issues/{issue_id}/ai-suggest
Content-Type: application/json (optional)
-> 200 {
     ok, issue_id, fields, confidence, reason, evidence,
     source: "openai" | "offline",
     source_label, model, warning, current, allowed_fields
   }

POST /tasks/{id}/normalize/issues/{issue_id}/confirm
Content-Type: application/json
{ "decision_id": "one-time-id", "changes": { "customer_id": "C-2104" } }
-> 200 { ok, action: "confirm", status: "resolved",
         remaining, confirmed, skipped, batch_status }

POST /tasks/{id}/normalize/issues/{issue_id}/skip
Content-Type: application/json
{ "decision_id": "one-time-id", "reason": "Vendor must confirm the source value." }
-> 200 { ok, action: "skip", status: "skipped", ... }

POST /tasks/{id}/normalize/finish
-> 303 back to the task page, or a 400 page with the remaining count
```

All routes require sign-in and task visibility. A different operator gets 404;
an admin can review any task.

## 6. Activity timeline

The existing normalize timeline now includes:

- `normalize_ai_suggestion` — actor is the AI source label;
- `normalize_human_confirm` / `normalize_human_skip` — actor is the signed-in
  user;
- `normalize_review_complete` — actor is the signed-in user.

Payloads contain issue/order IDs, changed field names, AI source/model/confidence
and skip reasons, never API keys.

## 7. Tests and verification

Phase D closed at **313 passed, 11 subtests passed**; the later bilingual
increment brings the current suite to **321 passed** (see `docs/i18n-report.md`).

Phase D adds 15 tests:

- 7 unit tests for AI JSON parsing, fenced responses, unknown-field filtering,
  success, 401, 429, timeout and empty-key paths;
- 8 HTTP/DB tests for the review page, offline advice, mocked online advice,
  invented customer ID rejection, arithmetic mismatch, skip export, required skip
  reason and the finish/audit gate.

Coverage also verifies that replayed decisions create one decision row, the
skipped order is absent from `normalized`, the skip reason is present in
`unresolved`, and the download endpoint is blocked before the gate.

## 8. Full live end-to-end verification

A separate temporary server and SQLite database were used (the live demo
database was not modified). The flow was executed over HTTP exactly as the
browser would:

```text
demo login → upload six files → start → tick to needs_review
→ six AI suggestions (offline) → six confirms → 6 → 0
→ Complete cleaning → download → open workbook
```

Observed result:

| Check | Result |
| --- | --- |
| Source rows | 174 |
| Merged records | 36 |
| Confirmation items | 6 → 0 |
| AI suggestions | 6 (offline, confidence/reason present) |
| Download before gate | 409 |
| Finish before gate | 400 |
| Final status | `complete` |
| Workbook sheets | normalized / changes / unresolved |
| Workbook rows incl. header | 37 / 238 / 1 |
| Required fields / arithmetic | all 36 records valid |
| Activity events | AI suggestion, human confirm, review complete |

The downloaded workbook is `output/phase-d/e2e-normalized.xlsx`; the machine
summary is `output/phase-d/e2e-verification.json`.

A second run exercised **Skip** on one cross-file conflict: 5 confirmed, 1
skipped, 35 clean records, and the `unresolved` sheet contained the skipped order
with the reason. The batch still completed and downloaded.

The same flow was then driven through a real headless Edge browser over CDP, not
just the API:

- the page rendered six **AI suggestion** / **Confirm** / **Skip** cards;
- the gate button was checked as `disabled`, `opacity: 0.42`,
  `cursor: not-allowed` while six items remained;
- clicking **AI suggestion** showed the **Offline Demo AI** confidence/reason and
  filled the card;
- confirming six cards moved the counter 6 → 0;
- **Complete cleaning** became enabled, the page showed **Review complete**, and
  the download link appeared.

Browser artifacts:

- `output/phase-d/browser-review-initial.png` — six cards, 6 left, locked gate;
- `output/phase-d/browser-ai-suggestion.png` — AI advice applied to a card;
- `output/phase-d/browser-review-complete.png` — Review complete + download link;
- `output/phase-d/browser-e2e-verification.json` — 6 confirmed, download true.

The external online AI call was not made during this live check (no real key was
copied into the temporary database). The online path is covered by the mocked
DeepSeek chat-completions test; the live demo's saved connection remains the
presenter's choice.

## 9. Rollback

The migration is additive. To roll back the feature without losing prior data:

1. Deploy the pre-D application code.
2. Leave the new `normalization_decisions` table and additive columns in place;
   they are ignored by the old code.
3. Do not delete `normalization_changes` rows with `method = 'human'` if the
   audit history matters.

The previous combined C+D attempt remains on `backup/phase-cd-attempt` for
reference only. Do not deploy it over this branch.

## 10. Limits

- AI advice is not a decision; it cannot bypass Confirm/Skip.
- The online AI call is bounded to 8 seconds; after that the offline suggestion
  is used. This is deliberate for a six-minute live demo.
- The review queue is single-batch and single-user; there is no multi-reviewer
  claim/lease workflow yet.
- The skipped record is retained in the `unresolved` sheet but not in the clean
  normalized sheet.

## 11. Screenshot checklist for the runbook

The presenter should capture/verify:

1. six cards with **AI suggestion**, **Confirm** and **Skip**;
2. the disabled **Complete cleaning (6 left)** button and locked download;
3. an AI advice box after clicking **AI suggestion**;
4. one confirmed card and the counter changing to 5;
5. the final **Review complete** state and enabled download.
