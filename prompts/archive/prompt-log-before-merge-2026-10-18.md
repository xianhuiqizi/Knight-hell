# Prompt log and documentation of what we did

Week 5 requirement for groups not using Softr. One row per prompt that mattered.
The **Fixed by hand** column is the one that shows learning, and this file is our
AI disclosure under the Module Handbook, section 17.

Keep this file up to date as we build. It is submitted with the weekly log.

| # | Prompt (what we asked) | Expected (what we thought we would get) | Got (what actually came back) | Fixed by hand (what we changed ourselves) |
| --- | --- | --- | --- | --- |
| 1 | "Read our prototype report and the Week 5 handout, then plan the Week 5 build." | A step-by-step plan that ends with a working login and one feature. | A seven-phase plan (P0 to P7), plus the note that our review chain is the feature the handout counts, not the monitoring screen. | We decided to present the review and approval chain as Feature 1, and to build a browser interface instead of a phone shell. |
| 2 | "Rebuild the project folder skeleton for a browser interface." | Empty folders only, no code yet. | 28 folders; the mobile app folder was replaced by a UI folder, and agent, prompts and eval folders were added. | We removed the old mobile-app layout and kept the previous skeleton in a trash folder until we are sure we do not need it. |
| 3 | "Regenerate the data model with the Approvals table added." | Five tables, six links, no crossing arrows, one example value per field. | A 2400x5594 sheet with five tables and six orthogonal arrows. | (to fill in) Check that every field on the sheet matches what we will actually build, and add Execution events in P5. |
| 4 | "Update the app map to include the approval page and drop the Softr wording." | Seven pages, every button mapped to a table change, build notes for our stack. | A sheet with seven pages and twelve buttons. | (to fill in) Confirm the access column against the roles we implement in P2. |
| 5 | "Build the first slice: tables, seed data and one verification query, nothing else." | A database holding 100 orders, 88 passing and 12 flagged, with no third-party packages. | Eleven files plus three generated artefacts. The seed reproduces the report numbers and the workbook was written with the standard library only. | (to fill in) Open the workbook in Excel and confirm it opens without a repair prompt; check that the flagged list matches our paper model. |
| 6 | "Finish P1 without installing anything: domain models, review rules and tests." | Models that reject bad values, plus tests for the approval gate and the one-approval-per-attempt rule, all runnable on a clean Python. | 38 tests (26 unit, 12 integration). The integration tests first failed because the sandbox blocked the system temp folder, so the database test now uses an in-memory database. | (to fill in) Run `python -m unittest discover -s tests` on your machine and note anything you had to change. |
| 7 | "Build P2: sign-up, sign-in, sessions and per-user visibility." | Working login, a second account that cannot see the first account's tasks, and an admin view that can. | Password hashing, a signed cookie session, five templates and 28 new tests. Two packages could not be installed, so sessions and form parsing were written with the standard library. | (to fill in) Log in with both demo accounts and confirm what each one sees. |
| 8 | "Build P3: Accept / Edit / Skip with a decisions record and the approval gate." | Three actions that update one exception, write one decision, and drop the unresolved counter; the gate opens at zero. | A pure `decide()` rule, one POST endpoint with replay-safe decision ids, an action column in the table and 18 new tests. | (to fill in) Click Accept, Edit and Skip in the browser and watch the counter and gate change. |
| 9 | "Build P4: proceed, approval page and the approvals write." | The gate opens at zero, the approval page shows 99 ready and 1 skipped, and approving records the batch once and moves the task to executing. | Three transitions with guards, an approval page, and a fix for the ready count, which had been ignoring the 88 records that passed validation. | (to fill in) Walk the full chain in the browser and check the approval record. |

## Session supplement: 18 October 2026

### How to read the prompts and authorship notes

Entries 10–17 below are **edited English reconstructions of the requests in this
session, not verbatim quotations**. They translate the original requests into
technical specifications and include implementation details established during
the subsequent work. They should not be presented as exact prompts originally
typed by a student. The conversation is the source for the original wording.

Implementation, automated checks and the recorded browser demonstration were
performed by the AI coding assistant under the requester's direction. Requesting
a feature or reporting a defect is distinct from personally writing the code or
independently running a test. Complete every **[TO COMPLETE — STUDENT]** field
with actual student work; if none occurred, say so. Do not relabel assistant
changes as "fixed by hand."

Entries 1–9 above are retained as historical notes. Their personal-work claims
and outstanding `to fill in` fields still need the team's review. Later automated
verification does not establish that the earlier student exercises took place.

| # | Technical restatement of the request — edited English, not verbatim | Expected outcome | Observed result and evidence | Assistant corrections and student verification |
| --- | --- | --- | --- | --- |
| 10 | Audit the FlowRemote implementation against the Week 5 authentication and Feature 1 requirements. Distinguish static prototype content, seeded database records and behavior derived from uploaded input. Record the required deliverables and acceptance criteria in `w5.md`. | A traceable implementation gap assessment and a Week 5 checklist. | The initial exception counts came from seeded data, rather than an upload-and-analysis pipeline. The checklist separates functional behavior from evidence, design artifacts, Kanban and individual reflection. See the local `w5.md`. | The requester questioned where order exceptions came from before uploads existed. The assistant documented the distinction. **[TO COMPLETE — STUDENT]** Name the person who reviewed the requirements and describe their own conclusions. |
| 11 | Run the FastAPI backend locally with persistent SQLite storage. Exercise registration, login, logout and session handling, then verify that two operator accounts cannot read or mutate each other's tasks. Preserve existing data and check persistence after a backend restart. | A running local service, working authentication and evidence of ownership enforcement. | The earlier authentication exercise recorded 28 authentication tests, 36 live HTTP checks and 9 restart checks passing. Cross-account requests were denied and stored data remained unchanged. These tests used prepared seed tasks; they did not prove Excel import. See evidence A below. | The assistant configured the local environment and ran the checks. **[TO COMPLETE — STUDENT]** Record any login or registration steps you personally repeated, their date, actual result and evidence. |
| 12 | Add an authenticated task-creation workflow with a task name and `.xlsx` upload. Derive ownership exclusively from the signed session, persist the workbook and task metadata, protect downloads, and reject invalid or oversized input without leaving partial records. | Users can create their own tasks from Excel and retrieve their original files without exposing them to another operator. | Added the New task form, multipart upload route, upload metadata migration, generated storage filenames and protected downloads. The first version stored tasks as Awaiting validation; it did not invent exceptions. The initial full regression run passed 110 tests. | The assistant implemented and tested the feature. **[TO COMPLETE — STUDENT]** Explain one ownership check or storage choice you inspected yourself, and identify any change you personally made. |
| 13 | Diagnose the upload failure reporting that the first row must contain column headers. Support leading blank or whitespace-only rows while retaining bounded parsing, meaningful empty-sheet errors and the existing data-row limits. | Valid workbooks with blank rows before their headers are accepted; genuinely empty input is still rejected. | The parser now uses the first non-empty row as headers, searches within the first 1,000 rows and allows up to 10,000 rows below the header. Eighteen upload-related tests passed after the fix. Leading titles are not automatically recognized as distinct from headers. | The requester reported the actual error message; the assistant changed the parser and added regression tests. **[TO COMPLETE — STUDENT]** Identify the reporter and whether they personally retried the original file after the fix. |
| 14 | Replace seeded exception generation for uploaded tasks with deterministic validation of actual workbook rows. Map supported English and Chinese headers; validate required fields, batch-level ID uniqueness, quantities, monetary values and dates; preserve source-row provenance and original values. Commit the records and validation results atomically, and revalidate corrections before resolving an exception. | Per-task counts and actionable exceptions are derived from the uploaded file, with auditable corrections and no fabricated customer matches. | Implemented `orders-v1`, `order_inputs` and `task_validations`. A seven-order fixture produced 2 passed orders, 5 flagged orders and 8 issues. Monetary comparisons use decimal arithmetic; only an amount-only problem receives a calculated suggestion. Invalid edits roll back. Existing saved uploads have a validation action. The final suite passed 147 tests, with 11 subtests reported separately. See evidence B. | The assistant added parsing, rules, persistence, UI explanations and tests, and extended internal record IDs beyond 999. **[TO COMPLETE — STUDENT]** Explain a rule you independently checked, an edge case you tried, and any modification you personally authored. |
| 15 | Create a focused Git commit containing the task-upload and order-validation implementation, migrations, documentation and tests, then push it to the configured GitHub branch using the authorized account. Report the actual result of each failed or successful push. | A reviewable, versioned implementation available in the project repository. | Commit `ec3ad25` was created and eventually pushed to `origin/main`. Earlier attempts encountered HTTP 403 permission failures and a separate connection timeout. A later authorized retry succeeded. The record does not establish who changed the permissions or how. | The requester authorized the commit, push and retries; the assistant executed the Git commands. **[TO COMPLETE — STUDENT]** Record any repository or account permission work you actually performed, if applicable. |
| 16 | Demonstrate the complete browser workflow using a clearly labelled synthetic workbook: authenticate, upload, inspect validation results, show a rejected correction, resolve exceptions using Accept/Edit/Skip, and submit approval. Verify second-account isolation and persistence after re-login; save ordered screenshots and cross-check the stored decisions and approval without modifying them directly. | Reproducible Week 5 evidence linking user actions to persisted results, with implementation limits stated clearly. | Task `TASK-689195E45C` was created through the UI. Five exception decisions were stored: 2 accepted, 2 manually corrected and 1 skipped. Six orders were approved, with 0 unresolved exceptions and exactly 1 approval record. Account B could not see or open the task; re-login as A retained the results. Sixteen screenshots, the input workbook, a walkthrough, a database verification extract and checksums were packaged. See evidence C. | The assistant operated the browser and collected the evidence. This was not an independent student or peer usability test. **[TO COMPLETE — STUDENT]** Record a later walkthrough you personally performed and explain the difference between approval persistence and actual execution. |
| 17 | Extend the Prompt Log using traceable technical English restatements, and draft a Week 5 report from verified implementation and demonstration evidence. Clearly distinguish assistant work from student contributions and leave unverified personal reflections, peer feedback and submission details for the team to complete. | Accurate, editable documentation with explicit authorship and completion markers. | This supplement and `docs/w5-weekly-log-draft.md` summarize the verified work. Personal-work and submission fields remain open. The rewritten prompts are labelled as editorial reconstructions, not original quotations. | **[TO COMPLETE — STUDENT]** Check the draft against your own experience, correct any claim you cannot substantiate, and complete your individual contribution and reflection before submission. |

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

## Rules we follow

- Keep API keys out of screenshots, public pages and shared chats.
- Save AI results into our own tables so we do not pay for the same call twice.
- Log every AI call, including the failed ones.
- If a tool builds something we cannot explain, it does not count as our work.

## Where this goes

- Weekly log: one copy per member, with that person's own reflection.
- Submission: together with the login, Feature 1, the paper photos and the Kanban board.
