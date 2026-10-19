# FlowRemote - AI prompt log

Group 2 · ENT207TC Digital Startup Lab · Week 5 · last updated 2026-10-17

## Why this file exists

The Week 5 handout asks groups that build with a prompt-driven tool to keep a
prompt log. It does two jobs:

1. It shows how the team used AI while building FlowRemote, so anyone can see
   which parts were generated, which parts were checked, and which parts were
   changed by hand.
2. It is our AI-use disclosure under the Module Handbook, section 17.

One row per prompt that mattered. Prompts that only produced a formatting tweak
are not listed. The **Fixed by hand** column is the one that shows learning, so
each member adds their own line there before the weekly log is handed in.

## How to read the table

| Column | Meaning |
| --- | --- |
| Phase | Which part of the build plan the prompt belongs to (see `docs/project-summary.md`) |
| Prompt | What the team asked for, in plain words |
| Expected | What we thought we would get before sending it |
| Got | What actually came back, including the parts that were wrong |
| Fixed by hand | What changed afterwards, and who changed it |

## Summary

- 9 prompts covering setup, P1 (data), P2 (login), P3 (review) and P4 (approval).
- 2 prompts produced code that did not run on the first try and were corrected.
- 1 prompt produced a SQL count that was wrong; the end-to-end run caught it.
- 2 third-party packages could not be installed in the working environment, so
  their behaviour was written with the standard library instead.
- Everything below is reproducible from the repository: the seed script, the
  96 tests and the demo in `demo/`.

## The log

| # | Phase | Prompt | Expected | Got | Fixed by hand |
| --- | --- | --- | --- | --- | --- |
| 1 | Setup | "Plan the Week 5 build from our prototype report and the Week 5 handout." | A step plan that ends with a working login and one feature. | A seven-phase plan. It also pointed out that our review chain, not the monitoring screen, is the feature the handout counts. | Team decision: present the review and approval chain as Feature 1, and build a browser interface instead of a phone shell. |
| 2 | Setup | "Rebuild the project folder skeleton for a browser interface." | Empty folders only, no code yet. | 28 folders. The mobile-app folder disappeared and agent, prompts and eval folders appeared. | Team decision: keep the old skeleton in a trash folder until the new layout was agreed. |
| 3 | P1 | "Build the first slice: tables, seed data and one verification query." | A database holding 100 orders, 88 passing and 12 flagged, with no third-party packages. | Eleven files plus three generated artefacts. The seed reproduced the report numbers. The workbook had to be written by hand because the standard library has no xlsx writer. | Assistant: wrote a small xlsx writer, then verified the file with two independent readers. Team: opened the workbook and checked the flagged records. |
| 4 | P1 | "Add the domain models, the review rules and tests, without installing anything." | Models that reject bad values, plus tests for the approval gate and one-approval-per-attempt. | 38 tests. At first the database tests failed because the working environment blocked the system temp folder. | Assistant: moved the tests to an in-memory database. Team: ran the suite and confirmed 38 passed. |
| 5 | P2 | "Build P2: sign-up, sign-in, sessions and per-user visibility." | Working login, a second account that cannot see the first account's tasks, and an admin view that can. | Password hashing, a signed cookie session, five templates and 28 new tests. Two packages (`itsdangerous`, `python-multipart`) could not be installed. | Assistant: wrote the session signing and form parsing with the standard library. Team: logged in with both demo accounts and checked what each one sees. |
| 6 | P2 | "The tests fail with 'SQLite objects created in a thread can only be used in that same thread'." | A diagnosis, not a rewrite. | The connection was created in one threadpool thread and used in another, because FastAPI runs sync dependencies and sync handlers separately. | Assistant: allowed the SQLite connection to move between threads, and kept one connection per request. Team: re-ran the suite. |
| 7 | P3 | "Build P3: Accept / Edit / Skip with a decisions record and the approval gate." | Three actions that update one exception, write one decision, and drop the unresolved counter. | A pure `decide()` rule, one POST endpoint with replay-safe decision ids, an action column in the table and 18 new tests. | Assistant: implemented the guard "Accept needs a suggestion", the replay check and the transaction. Team: clicked Accept, Edit and Skip in the browser and watched the counter. |
| 8 | P3 | "The static demo shows 'Task not found' on every task." | A routing bug, not a data problem. | The route sliced the URL at the wrong offset (`slice(9)` for an 8-character prefix), so the task id lost its first letter. | Assistant: replaced the magic number with the prefix length. Team: re-ran the demo check (34/34). |
| 9 | P4 | "Build P4: proceed, approval page and the approvals write." | The gate opens at zero, the approval page shows 99 ready and 1 skipped, and approving records the batch once. | Three transitions with guards, an approval page, and a SQL count that was wrong: "ready" only counted the 11 corrected exceptions and ignored the 88 records that already passed. | Assistant: changed ready to `passed + accepted + manual`. Team: walked the full chain in the browser and checked the approval record. |

## Failure log

Every failure below is part of the learning, so it is recorded rather than
hidden. Each one now has a test that would catch it again.

| Failure | Why it happened | What fixed it | What proves it |
| --- | --- | --- | --- |
| Two packages could not be installed (`itsdangerous`, `python-multipart`) | The working environment only allowed git traffic out | Session signing and form parsing implemented with the standard library | 5 session tests and 17 auth tests |
| SQLite "created in a thread" error | FastAPI runs sync dependencies and handlers on different threads | `check_same_thread=False`, one connection per request | Full suite in the project |
| Demo route returned "Task not found" | Off-by-one in the URL slice | Use the prefix length instead of `9` | 34 demo checks |
| "Ready" count showed 11 instead of 99 | The count ignored the records that passed validation | `ready = passed + accepted + manual` | End-to-end run: approval page shows 99 ready, approvals row records 99 |
| GitHub push failed twice | Direct connection blocked; HTTP/2 through the proxy dropped the upload | Proxy for github.com, HTTP/1.1 and a larger post buffer | Commit `9c7c54d` is on the remote `main` |

## Rules we follow

- Keep API keys out of screenshots, public pages and shared chats.
- Save AI results into our own tables so we never pay for the same call twice.
- Log every AI call, including the ones that fail.
- If a tool builds something we cannot explain, it does not count as our work.
- One row per prompt that mattered; the last column is written by the person who
  ran the step, in their own words.

## Where this goes

- Weekly log: the same table, plus each member's reflection on what confused
  them and how they fixed it.
- Submission: together with the working login, the review and approval flow, the
  photos of the paper data model and app map, and the updated Kanban board.
- The interactive demo in `demo/` shows the same flow without any installation.
