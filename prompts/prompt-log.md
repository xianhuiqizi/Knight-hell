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

## Rules we follow

- Keep API keys out of screenshots, public pages and shared chats.
- Save AI results into our own tables so we do not pay for the same call twice.
- Log every AI call, including the failed ones.
- If a tool builds something we cannot explain, it does not count as our work.

## Where this goes

- Weekly log: one copy per member, with that person's own reflection.
- Submission: together with the login, Feature 1, the paper photos and the Kanban board.
