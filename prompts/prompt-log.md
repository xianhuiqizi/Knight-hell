# FlowRemote — Consolidated AI Prompt Log

Group 2 · ENT207TC Digital Startup Lab · Week 5

Consolidated on 18 October 2026

## Purpose and sources

This log records the requests, expectations, results and follow-up work behind
FlowRemote. It supports the Week 5 process record and AI-use disclosure. The
team should check the final submission against the applicable course form.

Two records have been merged without discarding their original wording:

- **T — Team history, dated 17 October:** [uploaded source](archive/prompt-log-team-2026-10-17.md). Contains nine prompts, a failure log and reported team checks.
- **L — Existing project record and 18 October supplement:** [pre-merge source](archive/prompt-log-before-merge-2026-10-18.md). Contains nine earlier prompts and eight later session entries.

The consolidated log contains **19 distinct entries**: eleven historical items
and eight items from 18 October. Seven overlapping historical entries were
merged. The data-model and App Map entries unique to L were retained; the SQLite
threading and standalone-demo routing entries unique to T were added.

## Wording, attribution and verification

All main-table prompts are **edited technical English restatements, not verbatim
transcripts**. They preserve the request's purpose and may incorporate details
established during implementation. Exact wording from the two source documents
remains in the archived copies; those documents are records, not a replacement
for the original conversations.

**Team (recorded)** means the uploaded history reports that the team performed
the action. It is retained as historical work, not reclassified as an
assistant-only action. Names, dates and supporting evidence should be added
where absent. **Assistant** identifies work attributed to the coding assistant.
The browser demonstration on 18 October was assistant-operated and is separate
from those earlier team-reported checks.

Complete **[TO COMPLETE — STUDENT]** fields with actual individual contributions.
Do not convert an assistant fix into a student-authored change. The source
column maps each consolidated entry to its earlier row number; it is not an
exact timestamp or a claim of finer chronological ordering.

## Historical work through 17 October 2026

| # | Phase / source | Technical restatement — edited, not verbatim | Expected | Recorded result | Corrections, team work and attribution |
| --- | --- | --- | --- | --- | --- |
| 1 | Setup; L1, T1 | Translate the prototype report and Week 5 requirements into a phased implementation plan. Identify an end-to-end user workflow that qualifies as Feature 1 and distinguish it from authentication infrastructure and static monitoring screens. | A step plan that ends with a working login and one feature. | A seven-phase plan. It also pointed out that our review chain, not the monitoring screen, is the feature the handout counts. The earlier record calls this seven phases labelled P0–P7; that label range contains eight phases. **[TO COMPLETE — STUDENT]** Reconcile the phase list with the actual plan before quoting a phase count. | Team (recorded decision): present the review and approval chain as Feature 1, and build a browser interface instead of a phone shell. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 2 | Setup; L2, T2 | Restructure the repository for a browser-based application, with clear boundaries for the UI, API, domain logic, persistence, AI integration and evaluation assets. Preserve the previous layout until the team has agreed the replacement. | Empty folders only, no code yet. | 28 folders. The mobile-app folder disappeared and agent, prompts and eval folders appeared. | Team (recorded decision): keep the old skeleton in a trash folder until the new layout was agreed. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 3 | P1 / Design; L3 | Revise the data-model diagram to include Approvals, explicit field definitions, representative values and the relationships supporting the review-to-approval workflow. Keep the links readable and reconcile the diagram with the implementation. | Five tables, six links, no crossing arrows, one example value per field. | A 2400x5594 sheet with five tables and six orthogonal arrows. | No completed individual check is recorded. **[TO COMPLETE — STUDENT]** Check that every field on the sheet matches what we will actually build, and add Execution events in P5. The historical five-table diagram also needs updating for the later upload and validation tables. |
| 4 | App Map; L4 | Update the application map for the browser implementation, including the approval page, role-based access, navigation and each button's database effect. Remove assumptions specific to the earlier Softr workflow. | Seven pages, every button mapped to a table change, build notes for our stack. | A sheet with seven pages and twelve buttons. | No completed individual check is recorded. **[TO COMPLETE — STUDENT]** Confirm the access column against the roles we implement in P2. |
| 5 | P1 / Data; L5, T3 | Implement the initial relational schema, deterministic seed dataset and verification queries without introducing third-party runtime dependencies. Reproduce the documented 100-order fixture and provide a valid Excel workbook for inspection. | A database holding 100 orders, 88 passing and 12 flagged, with no third-party packages. | Eleven files plus three generated artefacts. The seed reproduced the report numbers. The workbook had to be written by hand because the standard library has no xlsx writer. | Assistant: wrote a small xlsx writer, then verified the file with two independent readers. Team (recorded): opened the workbook and checked the flagged records. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 6 | P1 / Rules; L6, T4 | Define domain models and pure review rules that enforce valid record states, approval gating and one approval per attempt. Add isolated unit and integration tests that can run without installing additional dependencies. | Models that reject bad values, plus tests for the approval gate and one-approval-per-attempt. | 38 tests. At first the database tests failed because the working environment blocked the system temp folder. L records the 38-test split as 26 unit and 12 integration tests. | Assistant: moved the tests to an in-memory database. Team (recorded): ran the suite and confirmed 38 passed. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 7 | P2 / Authentication; L7, T5 | Implement registration, login, logout and signed sessions, with server-side task visibility based on authenticated ownership. Verify separate operator accounts and administrator access, and report any dependency-installation constraints. | Working login, a second account that cannot see the first account's tasks, and an admin view that can. | Password hashing, a signed cookie session, five templates and 28 new tests. Two packages (`itsdangerous`, `python-multipart`) could not be installed. This describes the earlier environment: python-multipart was subsequently installed for real uploads on 18 October. | Assistant: wrote the session signing and form parsing with the standard library. Team (recorded): logged in with both demo accounts and checked what each one sees. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 8 | P2 / Defect; T6 | Diagnose the SQLite cross-thread connection error in the FastAPI request lifecycle. Trace connection creation and use across synchronous dependencies and handlers, then apply a focused fix while retaining one database connection per request. | A diagnosis, not a rewrite. | The connection was created in one threadpool thread and used in another, because FastAPI runs sync dependencies and sync handlers separately. | Assistant: allowed the SQLite connection to move between threads, and kept one connection per request. Team (recorded): re-ran the suite. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 9 | P3 / Review; L8, T7 | Implement Accept, Edit and Skip as validated exception-state transitions. Persist each decision atomically, make repeated submissions idempotent and update the unresolved count used to gate approval. | Three actions that update one exception, write one decision, and drop the unresolved counter. | A pure `decide()` rule, one POST endpoint with replay-safe decision ids, an action column in the table and 18 new tests. | Assistant: implemented the guard "Accept needs a suggestion", the replay check and the transaction. Team (recorded): clicked Accept, Edit and Skip in the browser and watched the counter. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 10 | P3 / Demo defect; T8 | Investigate why every task route in the standalone demo reports Task not found. Verify how the hash-route prefix is removed, correct the task-ID extraction and rerun the demo checks to detect routing regressions. | A routing bug, not a data problem. | The route sliced the URL at the wrong offset (`slice(9)` for an 8-character prefix), so the task id lost its first letter. | Assistant: replaced the magic number with the prefix length. Team (recorded): re-ran the demo check (34/34). **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |
| 11 | P4 / Approval; L9, T9 | Implement guarded transitions from review to approval and persist one approval per task attempt. Calculate eligible records from both initially passed records and resolved exceptions, exclude skipped records and verify the displayed totals against the stored approval. | The gate opens at zero, the approval page shows 99 ready and 1 skipped, and approving records the batch once. | Three transitions with guards, an approval page, and a SQL count that was wrong: "ready" only counted the 11 corrected exceptions and ignored the 88 records that already passed. Approval advances the task to executing; it does not implement downstream execution. The 99-ready example is the older seeded batch. | Assistant: changed ready to `passed + accepted + manual`. Team (recorded): walked the full chain in the browser and checked the approval record. **[TO COMPLETE — STUDENT]** Add the responsible member(s), date and supporting evidence for the recorded team action. |

## Session supplement: 18 October 2026

Entries 12–19 preserve the later implementation and verification record from L10–L17.
They are separate from the earlier team exercises. The technical work and the
recorded end-to-end browser walkthrough in this session were assistant-operated
under the requester's direction.

| # | Phase / source | Technical restatement — edited, not verbatim | Expected | Observed result and evidence | Corrections and student verification |
| --- | --- | --- | --- | --- | --- |
| 12 | Requirements audit; L10 | Audit the FlowRemote implementation against the Week 5 authentication and Feature 1 requirements. Distinguish static prototype content, seeded database records and behavior derived from uploaded input. Record the required deliverables and acceptance criteria in `w5.md`. | A traceable implementation gap assessment and a Week 5 checklist. | The initial exception counts came from seeded data, rather than an upload-and-analysis pipeline. The checklist separates functional behavior from evidence, design artifacts, Kanban and individual reflection. See the local `w5.md`. | The requester questioned where order exceptions came from before uploads existed. The assistant documented the distinction. **[TO COMPLETE — STUDENT]** Name the person who reviewed the requirements and describe their own conclusions. |
| 13 | Local backend / Authentication; L11 | Run the FastAPI backend locally with persistent SQLite storage. Exercise registration, login, logout and session handling, then verify that two operator accounts cannot read or mutate each other's tasks. Preserve existing data and check persistence after a backend restart. | A running local service, working authentication and evidence of ownership enforcement. | The earlier authentication exercise recorded 28 authentication tests, 36 live HTTP checks and 9 restart checks passing. Cross-account requests were denied and stored data remained unchanged. These tests used prepared seed tasks; they did not prove Excel import. See evidence A below. | The assistant configured the local environment and ran the checks. **[TO COMPLETE — STUDENT]** Record any login or registration steps you personally repeated, their date, actual result and evidence. |
| 14 | Excel upload; L12 | Add an authenticated task-creation workflow with a task name and `.xlsx` upload. Derive ownership exclusively from the signed session, persist the workbook and task metadata, protect downloads, and reject invalid or oversized input without leaving partial records. | Users can create their own tasks from Excel and retrieve their original files without exposing them to another operator. | Added the New task form, multipart upload route, upload metadata migration, generated storage filenames and protected downloads. The first version stored tasks as Awaiting validation; it did not invent exceptions. The initial full regression run passed 110 tests. | The assistant implemented and tested the feature. **[TO COMPLETE — STUDENT]** Explain one ownership check or storage choice you inspected yourself, and identify any change you personally made. |
| 15 | Upload defect; L13 | Diagnose the upload failure reporting that the first row must contain column headers. Support leading blank or whitespace-only rows while retaining bounded parsing, meaningful empty-sheet errors and the existing data-row limits. | Valid workbooks with blank rows before their headers are accepted; genuinely empty input is still rejected. | The parser now uses the first non-empty row as headers, searches within the first 1,000 rows and allows up to 10,000 rows below the header. Eighteen upload-related tests passed after the fix. Leading titles are not automatically recognized as distinct from headers. | The requester reported the actual error message; the assistant changed the parser and added regression tests. **[TO COMPLETE — STUDENT]** Identify the reporter and whether they personally retried the original file after the fix. |
| 16 | Order validation; L14 | Replace seeded exception generation for uploaded tasks with deterministic validation of actual workbook rows. Map supported English and Chinese headers; validate required fields, batch-level ID uniqueness, quantities, monetary values and dates; preserve source-row provenance and original values. Commit the records and validation results atomically, and revalidate corrections before resolving an exception. | Per-task counts and actionable exceptions are derived from the uploaded file, with auditable corrections and no fabricated customer matches. | Implemented `orders-v1`, `order_inputs` and `task_validations`. A seven-order fixture produced 2 passed orders, 5 flagged orders and 8 issues. Monetary comparisons use decimal arithmetic; only an amount-only problem receives a calculated suggestion. Invalid edits roll back. Existing saved uploads have a validation action. The final suite passed 147 tests, with 11 subtests reported separately. See evidence B. | The assistant added parsing, rules, persistence, UI explanations and tests, and extended internal record IDs beyond 999. **[TO COMPLETE — STUDENT]** Explain a rule you independently checked, an edge case you tried, and any modification you personally authored. |
| 17 | Version control; L15 | Create a focused Git commit containing the task-upload and order-validation implementation, migrations, documentation and tests, then push it to the configured GitHub branch using the authorized account. Report the actual result of each failed or successful push. | A reviewable, versioned implementation available in the project repository. | Commit `ec3ad25` was created and eventually pushed to `origin/main`. Earlier attempts encountered HTTP 403 permission failures and a separate connection timeout. A later authorized retry succeeded. The record does not establish who changed the permissions or how. | The requester authorized the commit, push and retries; the assistant executed the Git commands. **[TO COMPLETE — STUDENT]** Record any repository or account permission work you actually performed, if applicable. |
| 18 | Full demonstration; L16 | Demonstrate the complete browser workflow using a clearly labelled synthetic workbook: authenticate, upload, inspect validation results, show a rejected correction, resolve exceptions using Accept/Edit/Skip, and submit approval. Verify second-account isolation and persistence after re-login; save ordered screenshots and cross-check the stored decisions and approval without modifying them directly. | Reproducible Week 5 evidence linking user actions to persisted results, with implementation limits stated clearly. | Task `TASK-689195E45C` was created through the UI. Five exception decisions were stored: 2 accepted, 2 manually corrected and 1 skipped. Six orders were approved, with 0 unresolved exceptions and exactly 1 approval record. Account B could not see or open the task; re-login as A retained the results. Sixteen screenshots, the input workbook, a walkthrough, a database verification extract and checksums were packaged. See evidence C. | The assistant operated the browser and collected the evidence. This was not an independent student or peer usability test. **[TO COMPLETE — STUDENT]** Record a later walkthrough you personally performed and explain the difference between approval persistence and actual execution. |
| 19 | Documentation; L17 | Extend the Prompt Log using traceable technical English restatements, and draft a Week 5 report from verified implementation and demonstration evidence. Clearly distinguish assistant work from student contributions and leave unverified personal reflections, peer feedback and submission details for the team to complete. | Accurate, editable documentation with explicit authorship and completion markers. | This supplement and `docs/w5-weekly-log-draft.md` summarize the verified work. Personal-work and submission fields remain open. The rewritten prompts are labelled as editorial reconstructions, not original quotations. | **[TO COMPLETE — STUDENT]** Check the draft against your own experience, correct any claim you cannot substantiate, and complete your individual contribution and reflection before submission. |

## Consolidated failure and correction log

| Stage / source | Failure or mismatch | Recorded response | Evidence and current interpretation |
| --- | --- | --- | --- |
| Earlier environment; T | `itsdangerous` and `python-multipart` could not be installed. T attributes this to an environment permitting only Git traffic. | Session signing and URL-encoded form parsing were written using the standard library. | T reports 5 session tests and 17 authentication tests. This is a historical dependency constraint; later multipart uploads use installed `python-multipart`. |
| P1; T4 / L6 | Database tests could not use the system temporary directory. | The early schema tests were moved to an in-memory database. | The historical record reports 38 passing tests. Later integration tests also use workspace-scoped temporary databases. |
| P2; T6 | A SQLite connection was created and used in different FastAPI threadpool threads. | Set `check_same_thread=False` and retain one connection per request. | The current source contains this connection setting and explanation; the historical team record reports a successful rerun. This is not evidence of a new concurrency stress test. |
| Standalone demo; T8 | Removing the wrong number of characters from `#/tasks/` corrupted the task ID. | Replace `slice(9)` with the actual prefix length. | T reports 34/34 demo checks; current `demo/app.js` uses `hash.slice("#/tasks/".length)`. Those are static-demo checks, not backend authentication checks. |
| P4; T9 / L9 | Approval showed 11 eligible records instead of 99 because the 88 initially passed records were omitted. | Use `ready = passed + accepted + manual`; exclude skipped records. | T records a 99-order approval in the seeded 100-order example. The separate seven-order demonstration on 18 October approved 6 orders and skipped 1. |
| Historical push; T failure log | Direct connectivity failed and HTTP/2 through a proxy interrupted upload. | T records a GitHub-specific proxy, HTTP/1.1 and a larger post buffer. | T cites `9c7c54d` on remote main. That revision was not found in the current local checkout during this merge, so the remote claim has not been independently confirmed here. No network settings were changed by this documentation merge. |
| Upload; L13 | An empty first worksheet row caused a header error. | Skip leading empty or whitespace-only rows while bounding the header search and data rows. | Eighteen upload-related tests passed at that stage. Empty sheets and incompatible column names remain explicit errors. |
| Data provenance; L10 / L14 | Seeded exception counts could be mistaken for analysis of an uploaded file. | Label demonstration data and implement persisted, deterministic validation of workbook rows. | The later seven-order fixture produced 2 passed orders, 5 flagged orders and 8 issues from its actual contents. |
| Review; L14 / L16 | Correcting one field left other invalid fields in the same order. | Revalidate all fields and batch uniqueness before committing a correction. | Screenshot 05 in evidence C shows the rejected partial edit; the successful demonstration ultimately stored only 5 decisions. |
| Later push; L15 | HTTP 403 permission errors and, on another attempt, a connection timeout. | The requester authorized retries; a later push succeeded. | `ec3ad25` was pushed to main. The session does not establish who changed permissions. This is distinct from T's earlier proxy/HTTP2 account. |

Historical failure descriptions and their reported test results are retained as
history. They are not all newly reproduced during this merge, nor is every
network/configuration failure covered by an automated regression test.

## Verification stages and counts

| Stage | Recorded figures | Scope |
| --- | --- | --- |
| Earlier team record, dated 17 October | 96 repository tests; 38 in the P1 stage; 28 new tests in P2; 18 new tests in P3; 34 standalone-demo checks | Historical figures from T and L; different suites/stages overlap. T describes two initial code/test failures and the incorrect SQL count. No fresh run of those historical versions was performed for this merge. |
| Local authentication exercise, 18 October | 28 authentication tests, 36 live HTTP checks, 9 actual restart checks | Prepared seed tasks used to exercise authentication and isolation. |
| First upload implementation | 110 full-suite tests passed | Task creation, file storage and access checks; analysis was added later. |
| Leading-blank-row fix | 18 upload-related tests passed | Targeted regression stage, not a new full-suite total. |
| Completed upload and analysis implementation | 147 tests passed; 11 subtests separately reported | Latest recorded full regression result for `ec3ad25`. |
| Full browser demonstration | 16 screenshots; 5 decisions; 1 approval; 6 approved and 1 skipped | Task `TASK-689195E45C`; assistant-operated UI actions, re-login and second-account isolation, followed by read-only database verification. |

Do not sum these figures or present the old 96-test result as the current total.
The standalone localStorage demo, seeded backend tasks and uploaded-order
workflow are distinct evidence sources.

### Source-to-entry cross-reference

| Uploaded team row | Consolidated entry |
| --- | --- |
| T1 / T2 | 1 / 2 |
| T3 / T4 / T5 | 5 / 6 / 7 |
| T6 / T7 / T8 / T9 | 8 / 9 / 10 / 11 |

L1–L7 remain entries 1–7; L8 becomes 9, L9 becomes 11, and L10–L17 become 12–19.
Original source copies are preserved in `prompts/archive/`.

### Evidence references

- **Implementation:** [commit ec3ad25](https://github.com/xianhuiqizi/Knight-hell/commit/ec3ad253549a76df46e3f53bf6161473e91e295d).
- **A — Authentication and persistence:** local folder `ENT207/output/auth-check-20261018/`; `live-http-results.json` and `restart-results.json`. These results predate the upload feature and use prepared seed tasks. The local text report also contains demo credentials; do not publish it without removing them.
- **B — Real upload validation:** [local verification summary](../../output/order-validation-20261018/verification.json), from task `TASK-79634955B9`. This is the initial analysis test, not the later completed approval demonstration.
- **C — Complete browser demonstration:** [local evidence walkthrough](../../output/w5-evidence-20261018-163545/README.md) and [local evidence ZIP](../../output/w5-evidence-20261018-163545.zip), for task `TASK-689195E45C`.
- **Weekly report draft:** [W5 Weekly Log draft](../docs/w5-weekly-log-draft.md).

Evidence A–C is stored locally outside this Git repository. The relative links
work in the current workspace but will not resolve on GitHub unless the evidence
is separately attached or published. **[TO COMPLETE — STUDENT]** Add the actual
course-submission attachment names or access links after uploading them.

The test totals describe different verification stages and overlap; do not add
them together into a larger total. The 147-test result is the final recorded
regression run for the implementation, not a fresh run during documentation.

### Implementation boundary

The data is synthetic, but parsing, validation, review decisions and approval
persistence are real. No runtime AI model or customer-registry inference was
used. `Approve & Execute` currently records approval and changes the task to
`executing`; no OA/BI write, completed synchronization or result export was
demonstrated.

## Rules for completing and submitting this record

- Keep credentials, API keys and session secrets out of published logs and screenshots.
- Attribute fixes and checks to the person or assistant that performed them; add individual reflections in the member's own words.
- If runtime AI is added later, retain outputs and log failed as well as successful calls; that is a future practice, not a claim of model calls in the current rule-based workflow.
- Be able to explain generated code and its limitations before claiming it as understood work.
- Submit this log with the Weekly Log, functional evidence, actual paper design photos and the updated Kanban.
- Treat `demo/` as a standalone illustration, not proof of backend persistence, authentication or live order analysis.

## Feature 3 supplement: grounded AI suggestions (30 October 2026)

| # | Scope | Technical restatement - edited, not verbatim | Expected | Recorded result and verification |
| --- | --- | --- | --- | --- |
| 20 | AI feature | Add an advisory AI correction workflow without allowing the model to change review, approval or execution state. Keep provider calls behind a contract, use structured output, retrieve customer candidates before generation, validate every proposed field with the existing order rules, and preserve failed attempts for audit. Add a per-user connection window for selecting the provider, model, compatible endpoint and encrypted API key without performing a test request. | An operator can generate, inspect and explicitly accept a grounded correction; invalid or unavailable AI never blocks manual Edit/Skip, and saved connection settings feed the next suggestion request. | Added append-only suggestion tables, an encrypted per-user settings table, offline and OpenAI-compatible providers, a validation service, the AI connection window, structured UI output and 28 Feature 3 tests. The current full suite reports 222 passed. The OpenAI adapter and configured-provider path were tested without network calls; no paid API call is claimed because no API key was available. |
| 21 | Persistence / deployment | Confirm that registered accounts persist across application restarts. Expose a replaceable storage-backend interface that keeps local SQLite development working while allowing an approved enterprise PostgreSQL URL to be selected through configuration, with a database-factory injection point for another database family. | A registered local user can sign in after a restart, and switching to enterprise storage does not require changes to authentication or route code. | Added `StorageBackend`, `StorageConfig`, environment-based local/enterprise resolution, PostgreSQL `psycopg` support and a factory parameter on `create_app`. Seven persistence/configuration tests pass. No connection to an actual enterprise database was attempted because no approved host or credentials were provided. |
