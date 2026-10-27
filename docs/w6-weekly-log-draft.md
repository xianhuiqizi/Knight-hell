# Week 6 Weekly Log — Draft

**Project:** FlowRemote
**Milestone:** Integration & Second Feature
**Activity date covered by the verified session:** 25 October 2026, Asia/Shanghai
**Baseline commit tested:** `54df659` (identical to `origin/main` at the time of the test)
**Implementation version:** [TO COMPLETE — STUDENT: commit hash after you commit the Week 6 work.]
**Team / group number:** Group 2
**Members and student IDs:** [TO COMPLETE — STUDENT]
**Individual author:** [TO COMPLETE — STUDENT: complete an individual copy if required.]

This is an evidence-based working draft, not a completed Form 1 and not a record
of submission. Transfer the relevant sections into the official form and complete
every **[TO COMPLETE — STUDENT]** field. The development in this period was done
with an AI coding assistant under the requester's direction; the rows below
describe the resulting software, not an allocation of student credit.

## 1. Weekly objective and user value

Week 6 is about turning two features into one product. The task's endpoint after
Week 5 was a task stuck at `executing` with no way to see what happened next.

**Feature 2: Execution progress, results and the activity log.**

> A user can watch the approved batch execute and read the result with a complete
> activity log so that they know exactly what was written, what was skipped, and
> when it happened.

This is deliberately not the AI feature: the course asks teams to keep the AI part
for the AI feature, and this feature consumes data Feature 1 already produces
(the approval, the review decisions, the skipped record).

## 2. Work completed and current implementation

| Area | Verified outcome |
| --- | --- |
| Approval integration | Approving writes exactly one `execution_runs` row inside the same transaction as the approval, so a task can never be approved without a run or get two runs. |
| Execution step | The run advances 20 records per request: 20 → 40 → 60 → 80 → 99 on the demo batch. The browser advances it automatically; without JavaScript the **Run next 20 records** button does one step. |
| Completion | The run ends `complete`, the task moves to `complete`, and the duration and finish time are stored. |
| Results page | Success `99/100`, success rate `99.0%`, measured duration, and the storyboard sentence naming both targets. |
| Activity log | Append-only events for validation, each decision, review completion, review reopening, approval, completion and failure; `/tasks/{id}/activity.json` exports the same events. |
| Partial failure | `FLOWREMOTE_EXECUTION_FAIL_AT` stops a run at a chosen record: `execution_runs.status = partial`, an `execution_failed` event is written, and the results page says where it stopped. |
| Honest labelling | Every page that mentions OA/BI says the execution is simulated; `connectors/demo.py` opens no socket. |
| Guards | Owner/admin visibility, 404 for other users, 303 to login for anonymous requests, and a completed run ignores further steps. |

The interface is FastAPI/Jinja on SQLite with five new routes and two new
templates. Two tables were added: `execution_runs` and `activity_events`.

## 3. Verification and evidence

### Automated tests

| Scope | Count | Result |
| --- | --- | --- |
| Repository baseline (GitHub `54df659`) | 147 | passed, 18.2 s |
| Week 6 additions (19 unit + 20 integration) | 39 | passed |
| **Total after the change** | **186** | passed, 23.5 s |

The new integration tests cover: one run per approval, the execution page being
closed before approval, five steps to finish 99 records, a step after completion
doing nothing, the partial-failure path, results redirecting while a run is in
flight, the activity export matching the page, another operator getting 404,
anonymous requests, the admin view, and the no-JavaScript button.

### End-to-end checks against a running server

| Script | Scope | Result |
| --- | --- | --- |
| Feature 2 journey | seed → resolve 12 → proceed → approve → 5 steps → results → log → guards | 34/34 checks passed |
| Feature 1 regression | login, isolation, error inputs, upload and validation, gate, approval, idempotency, admin | 59/60 checks passed |

The one failing check is a **product gap, not a regression**: a workbook with zero
exceptions still lands in `review_required` instead of `pending_approval`
(PRD FR-4.5). The gate is open, so the operator can proceed, but the state is not
what the PRD says it should be. It is recorded in `docs/p5-report.md` rather than
silently fixed.

### What is not yet ready

- No screenshots or recording for this week yet; the browser demonstration still
  has to be captured. [TO COMPLETE — STUDENT]
- The Kanban board has not been updated. [TO COMPLETE — STUDENT]
- The paper App Map and data-model photo do not yet show the two new tables and
  the two new pages. [TO COMPLETE — STUDENT]

## 4. Feature 1 regression check

The whole Week 5 journey was re-run against the new build: sign-in, the second
account seeing a 404, wrong password, duplicate sign-up, the blocked approval
gate, Accept/Edit/Skip with real uploads, duplicate decision idempotency, the
single approval row, and the admin view. All of it still works; the only change
to Feature 1 behaviour is that the approval now also creates the execution run
and writes an activity event.

## 5. Design materials versus the implementation

| Paper artifact | Implementation now | Delta |
| --- | --- | --- |
| Paper data model (5 tables) | 9 business tables | `task_uploads`, `order_inputs`, `task_validations` (Week 5), `execution_runs`, `activity_events` (Week 6) |
| Paper App Map (7 pages, 12 buttons) | 9 pages | New: Execution progress, Results |
| State machine T14–T18 | T14, T15, T16, T18 implemented | T17 (retry) not implemented; T16 is recorded on the run because the task table has no `partial` state |

The design documents were updated (`docs/flowremote-state-machine-spec.md` 4.4,
`docs/project-summary.md` 12); the **photos/figures still need redrawing** so the
submission is consistent. [TO COMPLETE — STUDENT]

## 6. Known limits

- Execution is simulated: counts are real database state, outward writes are not.
- A partial run cannot be retried yet (T17).
- `tasks.status` has no `partial` value; the run carries the failure, and the task
  deliberately stays `executing`.
- Durations use second-precision timestamps, so a run that finishes inside one
  second shows `< 1 s`.
- Zero-exception tasks still require the review screen (FR-4.5).
- No CSRF token; the app relies on `SameSite=Lax`, as in Week 5.
- Administrators can advance any run, which matches the approval rule.

## 7. Individual contributions

[TO COMPLETE — STUDENT: who worked on the step rules, the routes, the pages, the
tests, the report, and who ran the browser demonstration. Do not assign team-level
claims to an individual without confirming them.]

## 8. Evidence checklist for the submission

| Item | Status |
| --- | --- |
| Working app with two features | Ready to demonstrate |
| Test output (186 passed) | Reproducible with `pytest tests -q` |
| Journey script output (34/34) | `tmp/w6-probe/feature2-results.json` |
| Screenshots of the two new pages | [TO COMPLETE — STUDENT] |
| 60–90 s walkthrough recording (Add / Find it again / Open it) | [TO COMPLETE — STUDENT] |
| Updated Kanban | [TO COMPLETE — STUDENT] |
| Prompt Log entry for this period | [TO COMPLETE — STUDENT] |

## 9. Reflection prompts

[TO COMPLETE — STUDENT: answer in your own words, one short paragraph each.]

1. What did you expect Feature 2 to need, and what did it actually need?
2. Which bug or surprise did you find by testing rather than by writing code?
3. Where does the product still feel like two demos instead of one product?
4. What will you test with the first external user next week?
