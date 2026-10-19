# Week 5 Weekly Log — Draft

**Project:** FlowRemote\
**Milestone:** Authentication & First Feature\
**Activity date covered by the verified session:** 18 October 2026, Asia/Shanghai\
**Earlier work source:** Team Prompt Log dated 17 October 2026; individual activity dates require confirmation.\
**Reporting period:** [TO COMPLETE — STUDENT: enter the course's Week 5 reporting dates.]\
**Team / group number:** Group 2\
**Members and student IDs:** [TO COMPLETE — STUDENT]\
**Individual author:** [TO COMPLETE — STUDENT: complete an individual copy if required.]\
**Implementation version:** [ec3ad25](https://github.com/xianhuiqizi/Knight-hell/commit/ec3ad253549a76df46e3f53bf6161473e91e295d)

This is an evidence-based working draft, not a completed Form 1 or a record of
submission. Transfer the relevant sections into the official form and complete
all **[TO COMPLETE — STUDENT]** fields. The course material names the milestone
as 14 October. The earlier team record is dated 17 October; the later upload,
validation and full browser demonstration session took place on 18 October.
Preserve the actual activity dates rather than backdating work to the milestone.

## 1. Weekly objective and user value

The objective was to move from a prototype with seeded examples to a functioning
product with authentication and a meaningful first feature.

**Feature 1: Order validation, exception review and approval.**

> A user can upload an order workbook, identify invalid records, correct or
> exclude exceptions, and approve the reviewed batch so that errors are detected
> before downstream processing is authorized.

Authentication supports access control but is not counted as a separate core
feature. Accept, Edit and Skip are actions within this single review workflow.

## 2. Work completed and current implementation

The development session was directed by the requester and carried out with an
AI coding assistant. The following describes the resulting software, not an
allocation of individual student credit.

| Area | Verified outcome |
| --- | --- |
| Local backend | FastAPI runs on the local computer with a persistent SQLite database. Existing accounts and tasks were retained during updates. |
| Authentication | Registration, login, logout, protected pages and account isolation were exercised. Operators access their own tasks; administrators retain the project's broader visibility. |
| Task creation | A logged-in user supplies a task name and uploads an `.xlsx` workbook. Ownership is obtained from the signed session rather than trusted form input. The original file is stored under a generated filename and downloaded through an access-controlled route. |
| Workbook parsing | The first worksheet is read using its first non-empty row as headers. Supported English and Chinese headers can be reordered. Missing or ambiguous required columns are rejected. Leading blank rows are accepted within bounded limits. |
| Order validation | Required values, duplicate order IDs, valid positive integer quantities, non-negative monetary values, quantity × unit price consistency and valid dates are checked. Formulas are flagged rather than executed. |
| Traceability | Excel row numbers, original field values, current corrected values, rule version and validation results are stored. Several problems in one order produce one exception containing all reasons. |
| Human review | Accept applies an available arithmetic suggestion; Edit rechecks the corrected record; Skip excludes an order. Invalid corrections do not resolve the exception or create a successful decision record. |
| Approval | Unresolved exceptions block progression. After review, approval stores the approver, time and approved/skipped counts. The UI then enters `executing`; downstream execution is not implemented. |
| Version control | The implementation, migrations, tests and documentation were committed and pushed to the project repository as `ec3ad25`. |

The implementation uses FastAPI/Jinja for the web interface, SQLite for local
persistence, openpyxl for workbook parsing and decimal arithmetic for monetary
validation. The `task_uploads`, `order_inputs` and `task_validations` tables
extend the existing users, tasks, source records, exceptions, decisions and
approvals model. The design documents still need to be checked against this
expanded schema.

## 3. Verification and evidence

### Earlier team-reported checks

The [uploaded team record dated 17 October](../prompts/archive/prompt-log-team-2026-10-17.md)
reports that the team inspected the seed workbook, confirmed 38 domain tests,
logged in with both demo accounts, reran tests after the SQLite threading fix,
tried Accept/Edit/Skip, reran 34 standalone-demo checks and checked the persisted
approval. These are retained as recorded team contributions; they were not
independently repeated during this documentation merge.

That record reports 96 repository tests at its development stage. Its seeded
approval example had 99 ready records and 1 skipped record. Neither figure
describes the later seven-order upload demonstration. Do not add historical and
later test totals together.

**[TO COMPLETE — STUDENT: identify which members performed these recorded
checks, their actual dates and any retained evidence. Do not assign a team-level
claim to an individual without confirming it.]**

### Automated and live checks from 18 October

| Verification stage | Recorded result | Scope and qualification |
| --- | --- | --- |
| Earlier authentication tests | 28 passed | Authentication-related checks before the upload implementation. |
| Earlier live HTTP checks | 36 passed | Two-account access checks and invalid authentication inputs, using prepared seed tasks. |
| Earlier backend restart checks | 9 passed | Accounts, ownership and stored review decisions survived an actual backend restart. |
| Final implementation regression suite | 147 passed; 11 subtests also reported | Includes upload boundaries, real order validation, review behavior, approval guards and ownership tests. These totals overlap with earlier test stages and must not be summed. |
| Full browser demonstration | Completed; 16 screenshots saved | Actual UI actions followed by read-only database verification. No business result was inserted directly to make the demonstration pass. |

The checks in this table were executed by the assistant. They do not establish that a student
independently ran the tests or that a peer usability session occurred.

### Full browser demonstration: TASK-689195E45C

The assistant logged in as QA User A and uploaded `demo-orders-7.xlsx`, a clearly
labelled synthetic dataset. The initial result was **7 input orders, 2 passed
orders, 5 flagged orders and 8 issues**. The extra issues arise because one order
contains several errors.

| Excel row | Initial condition | Demonstrated action | Final exception state |
| --- | --- | --- | --- |
| 3 | Missing customer ID, invalid quantity, non-numeric amount and impossible date | First changed only quantity, which was rejected. Then entered `C-DEMO-01`, quantity `2`, amount `20` and date `2026-10-18`, and saved with revalidation. These were manual values for the synthetic scenario. | Manual |
| 4 | Amount `14` did not match `3 × 5` | Accepted the calculated suggestion `15.00`. | Accepted |
| 5 | Duplicate order ID `DUP` | Changed the ID to `DUP-FIX-001` and passed revalidation. | Manual |
| 6 | The other initially duplicated order | Skipped the record as a demonstration of explicit exclusion. | Skipped |
| 8 | Amount supplied as formula `=D8*E8` | Accepted `20.00`, calculated from quantity and unit price without evaluating the formula. | Accepted |

The unresolved count reached **0**. The batch contained **6 approvable orders and
1 skipped order**. Submitting approval persisted **5 decision records and exactly
1 approval record**, with QA User A as approver. Approval was saved at
`2026-10-18T08:37:26Z` / 16:37:26 China Standard Time.

The assistant then logged in as QA User B. B's task list did not contain A's new
task, and direct access returned `task not found`. After logging back in as A,
the decisions and approval remained visible. The original uploaded workbook was
also verified byte-for-byte against the retained input file.

### Evidence to attach

- [Full walkthrough and screenshot index](../../output/w5-evidence-20261018-163545/README.md).
- [Complete evidence ZIP](../../output/w5-evidence-20261018-163545.zip): 16 screenshots, the workbook, verification extract and checksums.
- Key screenshots: `04-validation-and-blocked-approval.jpg`, `05-invalid-edit-rejected.jpg`, `11-review-decisions.jpg`, `12-approval-review.jpg`, `13-approval-saved.jpg`, `14-account-b-task-list.jpg`, `15-account-b-denied.jpg` and `16-relogin-persistence.jpg`.
- [Consolidated Prompt Log](../prompts/prompt-log.md): historical entries 1–11 and session entries 12–19, with source copies and a cross-reference.
- **[TO COMPLETE — STUDENT: add course-platform attachment names or accessible links after upload.]**

The evidence links above are local workspace references outside the repository;
they are not public GitHub attachments. The localhost application link is only
usable on the computer running the backend.

## 4. Problems encountered and responses

| Problem | Response and learning point supported by the session |
| --- | --- |
| Earlier backend: a SQLite connection was created and used in different threads. | The earlier record attributes the fix to the assistant: permit cross-thread connection use while retaining one connection per request. It reports that the team reran the suite; individual attribution and evidence remain to be added. |
| Earlier standalone demo: every task route returned Task not found. | The assistant replaced a hard-coded hash-route offset with the prefix length. The earlier record reports 34/34 demo checks by the team. These checks concern the standalone demo, not backend authentication or persistence. |
| Seeded exceptions appeared before any upload-and-analysis pipeline existed. | The requester challenged the data source. The implementation now derives exceptions from uploaded rows and labels seeded tasks as demonstrations. A plausible screen is not evidence of actual data processing. |
| A workbook with an empty first row was rejected. | The assistant changed parsing to find the first non-empty row, retained bounds and added regression tests. Empty files and missing order headers remain explicit errors. |
| An uploaded file was readable as Excel but did not expose recognized order headers. | A downloadable order template and specific missing-column errors were added. Workbook readability is different from compatibility with the order schema. |
| An incomplete correction could still contain several errors. | Revalidation rejects the update until all applicable checks pass. This was demonstrated by correcting only quantity before fixing the remaining fields. |
| GitHub push attempts failed. | Attempts encountered permission errors and a separate connection timeout; a later requested retry succeeded. The evidence does not establish who changed permissions, so no personal infrastructure contribution is inferred. |

## 5. AI assistance and implementation limits

The AI assistant inspected the code and requirements, implemented changes, ran
automated and live checks, operated the browser demonstration, collected
screenshots and drafted this documentation. The requester specified the desired
features, questioned the origin of exceptions, reported the header error and
authorized the demonstration and repository operations.

The Prompt Log contains labelled technical English reconstructions of the
requests; those polished specifications are not verbatim original prompts.
Student-authored code, independent verification and individual understanding
must be documented separately below. The earlier team-reported checks are
preserved in section 3 and the consolidated log; the missing information is
individual attribution and supporting evidence, not an assumption that those
checks never occurred. Both original Prompt Log documents are archived so the
edited English wording can be traced back to its source.

This version uses deterministic rules, not a runtime AI model. The orders are
synthetic test data. Approval persistence is implemented, but OA/BI connectors,
actual execution, completed synchronization and result export are not. The
`executing` label is a state transition, not proof that downstream writes ran.

## 6. Individual contributions — complete one copy per member

**Name / student ID:** [TO COMPLETE — STUDENT]

| Contribution category | Your actual work and supporting evidence |
| --- | --- |
| Requirements and decisions | [TO COMPLETE — STUDENT: identify requests, decisions or defect reports that you personally contributed; do not claim other members' work.] |
| Code or configuration authored by you | [TO COMPLETE — STUDENT: name the file, change, reason and commit or screenshot. If none, state that clearly.] |
| Independent verification | [TO COMPLETE — STUDENT: describe steps you personally performed, expected and actual results, date and evidence. Assistant-run tests belong in section 3.] |
| Data model / App Map work | [TO COMPLETE — STUDENT: identify the table or page map you drew or reviewed and attach the actual photo.] |
| Team collaboration | [TO COMPLETE — STUDENT: describe an actual discussion, review or coordination action and its outcome.] |
| Time spent | [TO COMPLETE — STUDENT: enter actual time if the official form requires it; do not infer time from assistant execution.] |

## 7. Individual reflection — write in your own words

Use concrete examples from work you actually understood or repeated. The prompts
below are questions to answer, not completed first-person reflections.

1. **What did I learn?** Explain one implementation detail, such as why ownership
   must come from the session, why decimal arithmetic is used, or why an approval
   record differs from an executed workflow.\
   **[TO COMPLETE — STUDENT: your explanation and the code or behavior you inspected.]**
2. **What challenged me?** Describe a problem you personally encountered, what
   you tried and the outcome.\
   **[TO COMPLETE — STUDENT: your own experience; distinguish it from an assistant diagnosis.]**
3. **How did I evaluate the AI output?** Identify one claim or generated change
   you checked, and what evidence supported or contradicted it.\
   **[TO COMPLETE — STUDENT: an actual check, not an intended future action.]**
4. **What would I improve next?** Choose a specific usability, validation or
   maintainability improvement and explain its value.\
   **[TO COMPLETE — STUDENT: your proposal and rationale.]**

## 8. Peer feedback and remaining course work

| Item | Status to complete honestly |
| --- | --- |
| Independent peer usability test | [TO COMPLETE — STUDENT: tester, date, task attempted without guidance, observed difficulty and resulting change. Not established by the assistant demonstration.] |
| Cross-group data-model review | [TO COMPLETE — STUDENT: three actual feedback points and any revisions.] |
| Paper data-model and App Map photos | [TO COMPLETE — STUDENT: attach photos and reconcile the added upload/validation tables and pages.] |
| Comparison of design and implementation | [TO COMPLETE — STUDENT: record at least three actual additions, omissions or renamings you checked, as required by the local Week 5 checklist.] |
| Student-performed modification and explanation | [TO COMPLETE — STUDENT: record the actual field/type modification and dependent fixes, and the module explained to teammates, if not already documented in sections 6–7.] |
| Updated Kanban | [TO COMPLETE — STUDENT: board link, card identifiers and actual status changes. No Kanban update is claimed here.] |
| Form 1 / Weekly Log submission | [TO COMPLETE — STUDENT: submission date, platform and confirmation or receipt.] |

## 9. Next steps

The immediate priority is to complete the individual sections, obtain real peer
feedback, reconcile design materials, update Kanban and submit the evidence.
Optional development after the Week 5 hand-in includes exporting the corrected
and approved dataset with a review audit trail. Real OA/BI integration and AI
functionality require separate design, authorization and testing.

## 10. Submission checklist

- [ ] Replace every personal and administrative completion marker with accurate information.
- [ ] Verify names, reporting dates and each member's contribution.
- [ ] Check historical Prompt Log entries 1–11, confirm recorded team checks and complete individual attribution fields.
- [ ] Attach the evidence ZIP or required screenshots, and verify the submitted links work for the marker.
- [ ] Attach actual design photos and peer feedback; do not invent missing activities.
- [ ] Update Kanban and record the real board/card references.
- [ ] Make the synthetic-data, AI-assistance and execution-boundary disclosures clear.
- [ ] Submit the official Weekly Log / Form 1 and retain confirmation.
