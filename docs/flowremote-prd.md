# FlowRemote AI-RPA - Product Requirements Document

| Field | Value |
| --- | --- |
| Product | FlowRemote AI-RPA - mobile control plane for device-side RPA |
| Document | Product Requirements Document (PRD) |
| Version | 0.1 - draft for review |
| Date | 2026-10-11 |
| Source of truth | Storyboard `Untitled.pdf`: one board, 11 mobile screens, one predefined workflow, task TASK-1001 "Order Data Validation & Sync", plus 4 designer annotations |
| Companion document | `flowremote-state-machine-spec.md` (states, transitions, guards, invariants) |
| Status | Draft - contains 12 open questions in section 15 that need product decisions |

---

## 1. Overview

FlowRemote is a phone app that controls business automation running on a bound office PC. The automation itself does not live on the phone. The phone is the control plane: it configures a run, watches progress, resolves the exceptions an AI could not resolve on its own, approves the write, and reads the audit trail afterwards.

The storyboard follows one complete run.

| Item | Value |
| --- | --- |
| Task | TASK-1001 - Order Data Validation & Sync |
| Workflow type | Predefined workflow (company workspace template) |
| Operator | Alex Morgan, Operations Specialist, alex.morgan@example.com |
| Bound device | Office-PC-01, Online |
| Source | `Orders_September.xlsx` in the Company Workspace, 100 input records |
| Targets | OA - Order Administration (primary write), BI - Business Intelligence (secondary sync) |
| Outcome in the storyboard | 100 checked, 88 passed, 12 exceptions resolved (8 AI, 3 manual, 1 skipped), 99 written to OA and synced to BI, 1 skipped, 42.8 s, 99.0% success |

The product promise, in the storyboard's own words: "Review and control business workflows from your phone."

## 2. Problem

Order data arrives with gaps: a missing customer id, a blank quantity, a missing customer name. Someone has to check every record, decide what the correct value is, and then update the order system and the reporting warehouse. Today that work is manual, split across two systems, and hard to audit.

The valuable part of the work is judgement, not data entry. FlowRemote pushes the mechanical part to the device-side RPA engine and keeps only the judgement on the phone: accept the AI suggestion, type a better value, or drop the record.

## 3. Goals and non-goals

### 3.1 Goals

| ID | Goal |
| --- | --- |
| G1 | Let an operator configure and start a predefined validation task from a phone in under a minute. |
| G2 | Resolve every flagged exception on the phone, one field at a time, with the AI suggestion, its confidence, and its reason visible next to the original value. |
| G3 | Block any write to OA or BI until a human has explicitly approved it. |
| G4 | Write each approved record to the primary target and sync the same record set to the secondary target, without duplication. |
| G5 | Leave a complete, attributable audit trail: who decided what, when, and which engine executed it. |

### 3.2 Non-goals (v1)

| ID | Non-goal |
| --- | --- |
| N1 | Authoring new workflows on the phone. The storyboard exposes one predefined workflow card; authoring stays on the desktop side. |
| N2 | Multi-task dashboards, scheduling, or queue management. The storyboard shows exactly one active workflow. |
| N3 | Editing source records in the workspace. Validation is read-only against the source (BR-1). |
| N4 | Admin functions such as user management, device enrollment, or target endpoint configuration. |
| N5 | Automatic approval without a human, even at 100% AI confidence. |

## 4. Personas and actors

| Actor | Type | Responsibility in this task |
| --- | --- | --- |
| Operations Specialist (Alex Morgan) | Human, phone | Signs in, reviews the batch metadata, resolves exceptions, approves execution, reads results. |
| FlowRemote Engine | Automation, device | Runs validation, flags exceptions, reports progress and events. |
| AI suggestion service | Automation, backend | Proposes a value per flagged field with a confidence score and a reason. |
| RPA Execution Engine | Automation, device | Writes approved records to OA and syncs them to BI after approval. |
| Workspace administrator | Human, desktop (implied) | Publishes the predefined workflow and the company-workspace source file. |

## 5. System context and components

| Component | Role | Reads | Writes |
| --- | --- | --- | --- |
| FlowRemote mobile app | Control plane and human gates | Task, device, validation and execution progress, exceptions, activity log | Task configuration, exception decisions, approval |
| Device agent on Office-PC-01 | Executes validation and the approved write on the office machine | Source workbook, task configuration | Progress and event stream, target systems |
| Company Workspace | File store for the source workbook | - | - |
| AI suggestion service | Field-level suggestions with confidence and reason | Customer registry, order history, source records | Suggestions attached to exceptions |
| OA - Order Administration | Primary target system | - | Approved records (99 in the storyboard) |
| BI - Business Intelligence | Secondary target system | - | The same approved record set (99, never a second copy) |
| Activity log | Append-only event store | - | One event per meaningful step, with actor and engine |

The phone never talks to OA or BI directly. It drives the device agent and owns the two human gates, review and approval.

## 6. Core concepts

| Term | Meaning |
| --- | --- |
| Task | A configured unit of work, identified by TASK-1001, bound to one device and one batch. |
| Batch | The set of source records in scope for the task. The storyboard uses 100. |
| Source | The workspace file a task reads, here `Orders_September.xlsx`. |
| Target | A destination for the approved record set. Exactly one primary (write) and one secondary (sync) in the storyboard. |
| Exception | One record plus the field or field group that failed validation, carrying the original value, the AI suggestion, the confidence, and the reason. |
| Decision | The operator's resolution of an exception: Accept, Edit, or Skip. |
| Tally | The review counters, shown as All / AI / Manual / Skip / Unresolved. |
| Gate | A point where automation stops and a human must act. There are two: review and approval. |
| Dispatched action | The instruction a target receives after approval, e.g. "99 records to be written". |

## 7. End-to-end flow

The storyboard's 11 screens map to 8 task states. Four of the screens are successive states of the same review screen, not four different pages.

| # | Screen | Task state | Purpose | Primary action |
| --- | --- | --- | --- | --- |
| 1 | Login | Unauthenticated | Identify the operator | Log In |
| 2 | Home | Idle | Show device status and the available predefined workflow | Set Up Task |
| 3 | Task Setup | Ready | Show source, batch size, and targets; state that approval is required | Start Validation (100 Records) |
| 4 | Validating | Validating | Show live validation progress and throughput | none (progress) |
| 5-8 | Awaiting Review | Review Required | Resolve 12 exceptions, four screens showing 9/12, 10/12, 11/12, 12/12 | Proceed to Approval |
| 9 | Execution Approval | Pending Approval | Show what will be written, where, and by which action; collect the approval | Approve & Execute |
| 10 | Executing | Executing | Show live execution progress | none (progress) |
| 11 | Results | Complete | Show the outcome, the statistics, and the activity log | Back to Home |

## 8. Functional requirements

### FR-1 Authentication and session

- FR-1.1 The login screen shows a product header, a one-line value statement, a work email field, a masked password field with a reveal control, and a Log In button.
- FR-1.2 A previously used account can be offered as a shortcut chip with name and role ("Alex Morgan, Operations Specialist"); selecting it starts the same session as an explicit sign-in.
- FR-1.3 The session persists across app restarts and is scoped to one operator. All decisions and approvals are attributed to that operator.
- FR-1.4 Signing out or an expired session returns the app to the Unauthenticated state; an in-flight task keeps running on the device and the operator can re-enter the same task after signing in again.
- FR-1.5 The seeded demo credential (`••••••••••••`) must never ship as a real password.

### FR-2 Home and device status

- FR-2.1 The app bar shows the product mark, the product name, a "Live RPA" subtitle, a notification control with a count badge, and the operator avatar with an online indicator.
- FR-2.2 The bound device card shows the operator name, the device name (Office-PC-01), and its status (Online).
- FR-2.3 A workflow card shows a "Predefined workflow" badge, a description line, the workflow name, and a short explanation of what it does, plus a single call to action.
- FR-2.4 When the device is offline, the card must state that the workflow cannot start and disable the call to action (see open question Q9).

### FR-3 Task setup

- FR-3.1 The screen header names the screen and identifies the task: id plus workflow name.
- FR-3.2 An Active Workflow card shows Task ID, Device and device status, Target Batch size, and the current task status badge (Ready).
- FR-3.3 A Source and Targets card shows a source location selector (Company Workspace), the resolved file with a record-count badge, the number of input records, and the target list (OA + BI).
- FR-3.4 A notice states the two rules that matter before starting: validation does not update OA or BI, and execution requires approval.
- FR-3.5 The primary action is Start Validation with the batch size in the label, e.g. "Start Validation (100 Records)".
- FR-3.6 If the source file is empty, unreadable, or its record count is zero, the action is disabled with an explanatory message.

### FR-4 Validation run

- FR-4.1 The screen shows the file and device being used, a "Validating" status badge, a live throughput figure, a progress bar with a percentage, records processed against the batch, and elapsed time.
- FR-4.2 Progress updates while the screen is open without a manual refresh. The storyboard shows 68% of 100 records in 3 seconds at 142 rec/sec; treat the figures as demo data and define real cadence in section 12.
- FR-4.3 Validation is read-only against the source and against both targets (BR-1).
- FR-4.4 When validation completes, the task moves to Review Required. In the demo the transition is simulated after a fixed delay (3 s); in production it is driven by the completion event.
- FR-4.5 If validation produces zero exceptions, the task must not force the review gate. The exception review step is skipped and the task goes directly to Pending Approval with an explicit "no exceptions" state (see Q4).
- FR-4.6 If validation fails, the task must leave the Validating state into a failed state that preserves the partial results and offers a retry (see Q5).

### FR-5 Exception review

- FR-5.1 The screen summarizes the run: records checked, records passed, and exceptions raised ("100 Checked · 88 Passed · 12 Exceptions"), plus the owning task id.
- FR-5.2 A review progress element shows reviewed against total with a percentage, for example 9/12 at 75%.
- FR-5.3 A filter row shows All (total) and the tally: AI, Manual, Skip, Unresolved. Filters narrow the list; the tally reflects the whole batch, not the filtered view.
- FR-5.4 Each exception is a card showing the record id, the failing field(s) in plain language ("Missing Customer ID", "Missing Quantity", "Missing Name + ID"), the current status badge, a confidence value where a suggestion exists, and one short rationale line.
- FR-5.5 Expanding a card reveals a field block: the field name, a Detail View affordance, the original value, the AI suggestion, and the reason. Blank values are rendered as "(blank)"; multiple blank fields are rendered together, for example "(both blank)".
- FR-5.6 Every expanded exception offers exactly three actions: Accept, Edit, Skip (BR-6).
- FR-5.7 Accept keeps the AI suggestion as the resolved value, including when the suggestion is a weak one the operator chooses to keep.
- FR-5.8 Edit opens an input pre-filled with the AI suggestion where one exists; the operator value overrides it and is the value that will be written.
- FR-5.9 Skip removes the record from the approved set; the record is counted as skipped and reported as such in the results.
- FR-5.10 An exception with no reliable suggestion must be resolvable: the operator can type a value with Edit, or Skip it. The storyboard shows both behaviours ("No reliable suggestion", then "6 (manual input)").
- FR-5.11 The primary action Proceed to Approval is disabled until Unresolved reaches 0 (BR-4, INV-1).
- FR-5.12 The screen must be resumable: reopening a task under review restores the tally, the decisions, and the position. The storyboard's own demo resumes at 9 of 12.
- FR-5.13 Decisions must be revisable. Returning from the approval screen ("Back to Review") must let the operator change a previous decision and keep the tally consistent.

### FR-6 Execution approval

- FR-6.1 The screen shows the status badge (Pending Approval) and an unresolved counter that must read 0.
- FR-6.2 A summary presents three numbers derived from the batch: records in, records skipped, records ready ("100 Input, 1 Skipped, 99 Ready").
- FR-6.3 A Source Document card shows the file name and a format badge ("XLSX DATA FEED").
- FR-6.4 A Target Endpoints and Actions card shows the number of targets and, per target, the target name, its role (Primary Target, Secondary Sync), the intended action in words, and the dispatched action ("99 records to be written", "Same 99 records synced to BI").
- FR-6.5 The primary action is Approve & Execute; the secondary action is Back to Review.
- FR-6.6 Approving is the only event that releases the write (BR-2). The approval records the operator and the timestamp.
- FR-6.7 The screen must state plainly that nothing has been written yet.

### FR-7 Execution

- FR-7.1 The screen shows the file, device, an "Executing" badge, throughput, a progress bar with a percentage, records written against the approved count, and elapsed time.
- FR-7.2 Progress runs against the approved count (99), not the input count (100).
- FR-7.3 The storyboard exposes no action while execution is in flight; leaving the screen must not cancel the run.
- FR-7.4 When execution completes, the task moves to Complete. The demo simulates this after a fixed delay (3 s).
- FR-7.5 A partial or failed write must land in a state that names the failed target and the affected records and offers a safe retry (BR-9, section 14).

### FR-8 Results and activity log

- FR-8.1 The screen shows a completion badge, a success mark, and a result sentence: records written and synced, and records skipped ("99 records written to OA and synced to BI. 1 record skipped.").
- FR-8.2 Three statistics are shown: Success as written over input (99/100), Duration (42.8 s), and Success Rate (99.0%).
- FR-8.3 An Activity Log lists events newest first with time, a one-line description, an actor or engine attribution, and an expand affordance. The storyboard shows 6 events, 5 of them visible.
- FR-8.4 The visible events are: Validation started (100 records) by FlowRemote Engine; Alex accepted AI, edited 6, skipped 1 by Alex Morgan; 12 exceptions found during validation; Alex approved execution; RPA wrote 99 to OA, synced 99 to BI by RPA Execution Engine.
- FR-8.5 The primary action is Back to Home, returning to Idle.
- FR-8.6 The activity log must be exportable or deep-linkable for audit purposes (see Q10).

### FR-9 Notifications

- FR-9.1 The app bar carries a notification count (2 in the storyboard).
- FR-9.2 Notifications must have a defined source: at minimum, a task reaching a human gate while the operator is elsewhere. The storyboard does not define the content (Q8).

## 9. Business rules and invariants

| ID | Rule | Evidence |
| --- | --- | --- |
| BR-1 | Validation never updates OA or BI. It only reads and flags. | "Validation does not update OA or BI." |
| BR-2 | No write happens before final approval. | "No write happens before final approval." (annotation) |
| BR-3 | The write set is the input set minus skipped records. | 100 input, 1 skipped, 99 written |
| BR-4 | Proceed to Approval is enabled only when unresolved exceptions are 0. | "Proceed enabled when unresolved = 0." (annotation) |
| BR-5 | OA and BI receive the same record set; the secondary target is a sync, not a second write. | "OA and BI sync the SAME 99 records, not 198." (annotation) |
| BR-6 | Each exception is resolved by exactly one of three decisions: Accept, Edit, Skip. | Accept / Edit / Skip controls on every expanded exception |
| BR-7 | An edited value replaces the AI suggestion for the written record. | "Manually entered quantity value by operator." |
| BR-8 | The tally is the review's source of truth: accepted + manual + skipped + unresolved equals the exception total. | 7 + 2 + 0 + 3 = 12 at 9/12 |
| BR-9 | Approval is explicit, attributable, and single-use per execution attempt. | Approve & Execute, "Alex approved execution" |
| BR-10 | Every meaningful state change appends one activity event with actor, engine, and time. | Activity Log, 6 events |
| BR-11 | Records that fail with an unreliable AI match and are skipped stay visible as skipped, not silently dropped. | "1 record skipped." |

## 10. Data model

| Entity | Key attributes | Relationships |
| --- | --- | --- |
| Operator | id, name, role, work email | Has many tasks through decisions and approvals |
| Device | id (Office-PC-01), status (Online) | Bound to tasks; runs validation and execution |
| Task | id (TASK-1001), workflow name, workflow type (predefined), batch size, state | Belongs to a device; has one source, many targets, many runs, many events |
| SourceArtifact | location (Company Workspace), file name, format, record count | Belongs to a task |
| Target | name (OA, BI), role (primary, secondary), intended action | Belongs to a task; receives dispatched actions |
| Record | record id (ORD-052), field values | Belongs to a batch; may raise exceptions |
| ValidationRun | started at, checked, passed, exception count, throughput, elapsed | Belongs to a task; produces exceptions |
| Exception | record id, fields, original values, AI suggestion, confidence, reason, status | Belongs to a validation run; resolved by one decision |
| Decision | type (Accept, Edit, Skip), resulting value, operator, timestamp | Resolves one exception |
| Approval | operator, timestamp, approved record count | Releases one execution attempt |
| ExecutionRun | approved count, written count, synced count, throughput, elapsed, duration, success rate | Belongs to a task; dispatches one action per target |
| ActivityEvent | timestamp, description, actor or engine | Belongs to a task |

Cardinality of note: one task has one source and exactly two targets in the storyboard, and the target-to-record relationship is one record to two destinations, not two records.

## 11. States

Eight task states, two human gates, and one gating condition carry the whole flow.

| State | Screen | Entered when | Leaves on |
| --- | --- | --- | --- |
| Unauthenticated | Login | No valid session | Successful sign-in |
| Idle | Home | Session valid, no active task | Set Up Task |
| Ready | Task Setup | Task configured, batch resolved | Start Validation |
| Validating | Validating | Validation dispatched to the device | Validation completes or fails |
| Review Required | Awaiting Review | Validation completed with at least one exception | Proceed to Approval, only when unresolved is 0 |
| Pending Approval | Execution Approval | Review complete | Approve & Execute, or Back to Review |
| Executing | Executing | Approval recorded, actions dispatched | Execution completes or fails |
| Complete | Results | All target actions finished | Back to Home |

The state machine specification defines events, guards, actions, back edges, and the failure states the storyboard does not show.

## 12. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Progress latency | Progress and tally updates must appear within 1 s of the underlying change; the storyboard's 142 rec/sec is demo data and must be replaced with measured throughput. |
| Responsiveness | Every screen must render its primary action without waiting on a network round trip where the data is already cached. |
| Reliability | A dropped connection must not lose decisions or approvals. The client queues the action, shows a pending indicator, and reconciles on reconnect. |
| Idempotency | Repeating an approval or a decision must not duplicate a write; the server keys on task, record, and attempt. |
| Resumability | Any task can be reopened by the operator and resumes at its current state with all counters intact. |
| Security | Work-email sign-in, session binding to the operator, no credentials in the client, TLS for all traffic, and personal data minimized in notifications. |
| Auditability | The activity log is append-only and complete; decisions and approvals are attributable and timestamped. |
| Accessibility | All controls reachable by screen reader with meaningful names; the tally and progress convey their values without relying on color. |
| Theming | The storyboard is a dark theme; the design system must support at least light and dark. |
| Localization | All strings externalized. The storyboard shows sentence-case English titles and Chinese-language date formatting risk is not covered. |
| Device scope | v1 binds one device per operator session. Multi-device routing is out of scope. |

## 13. Telemetry events

| Event | Key properties |
| --- | --- |
| `task_setup_viewed` | task id, workflow type, batch size |
| `validation_started` | task id, device id, batch size |
| `validation_completed` | checked, passed, exceptions, elapsed |
| `exception_expanded` | record id, field(s), confidence |
| `exception_decided` | record id, decision, previous status, tally after |
| `review_completed` | reviewed, total, unresolved, elapsed in review |
| `approval_gate_blocked` | unresolved count at the time of the attempt |
| `execution_approved` | operator, approved count, skipped count |
| `execution_progress_viewed` | elapsed, written, approved |
| `execution_completed` | written, skipped, duration, success rate |
| `activity_log_opened` | task id, event count |

## 14. Success metrics

| Metric | Definition | Target for the first release |
| --- | --- | --- |
| Median time from review start to approval | Review start to approved execution | Under 3 minutes for 12 exceptions |
| AI acceptance rate | Accepted divided by accepted plus manual for exceptions with a suggestion | Track, no target; it calibrates the confidence threshold |
| Write success rate | Written divided by approved | 99% or better |
| Skipped-record rate | Skipped divided by exceptions | Track; a rising rate signals source data quality |
| Rework rate | Approvals reversed or executions retried | Under 2% |
| Audit completeness | Tasks with a complete activity log divided by completed tasks | 100% |

## 15. Open questions

| ID | Question | Why it matters |
| --- | --- | --- |
| Q1 | Is the phone limited to review and approval, or will it also author and schedule workflows? | Decides whether v1 is a control terminal or a workflow composer. It is the largest scope fork in the storyboard, which shows exactly one predefined workflow. |
| Q2 | When BI sync fails but the OA write succeeded, is the task failed or partially complete? | BR-5 guarantees the same record set in both targets; the recovery path is undefined. |
| Q3 | Should high-confidence exceptions be batch-acceptable, or must each one be touched? | Affects the review screen: the storyboard requires per-record actions. |
| Q4 | What does the review gate do when validation returns zero exceptions? | The screen assumes at least one exception ("12 Exceptions"); the empty case needs a defined state. |
| Q5 | What are the failure and cancellation paths for validation and execution? | The storyboard shows only the happy path. |
| Q6 | The activity log timestamps are inconsistent: "Validation started" is stamped 14:32:04, later than "12 exceptions found" (14:31:42) and "RPA wrote 99 to OA" (14:31:02). | The order of events and the meaning of `Duration` (42.8 s against a 12 s execution) must be defined before the audit trail can be trusted. |
| Q7 | The log line "Alex accepted AI, edited 6, skipped 1" contradicts the tally (8 AI, 3 manual, 1 skipped). | One of the two is wrong; the tally is the value the review screen computes. |
| Q8 | What produces the notification badge (2)? | Notifications are visible product surface with no defined content. |
| Q9 | What happens when Office-PC-01 is offline at setup, during validation, or during execution? | The UI shows only the Online case. |
| Q10 | Does the activity log need export, retention limits, or a filter? | Drives the audit story and data retention requirements. |
| Q11 | Is `142 rec/sec` a single shared throughput figure for validation and execution, or two independent measurements? | The same number appears on both screens, which suggests placeholder data. |
| Q12 | Which target writes first when both are dispatched, and must the secondary wait for the primary? | Determines whether the targets are independent or ordered. |

Two cosmetic defects are also worth fixing in the next design pass: the task id in the Task Setup header collides with the back control (it reads close to "ASK-1001" although it is TASK-1001), and two labels are clipped inside their cards ("10/1" for 10/12 and "0 Unresolve" for 0 Unresolved).

## Appendix A - Screen inventory

| # | Screen title | Subtitle | Status badge | Key figures |
| --- | --- | --- | --- | --- |
| 1 | Login | - | - | - |
| 2 | Home | Live RPA | - | notification badge 2 |
| 3 | Task Setup | TASK-1001 · Order Data Validation & Sync | Ready | batch 100 records |
| 4 | Validating | TASK-1001 · Order Data Validation & Sync | Validating | 68%, 68/100, 3 s, 142 rec/sec |
| 5 | Awaiting Review | TASK-1001 · 12 Exceptions | Review Required | 9/12, 75%; AI 7, Manual 2, Skip 0, Unresolved 3 |
| 6 | Awaiting Review | TASK-1001 · 12 Exceptions | Review Required | 10/12, 83%; AI 8, Manual 2, Skip 0, Unresolved 2 |
| 7 | Awaiting Review | TASK-1001 · 12 Exceptions | Review Required | 11/12, 92%; AI 8, Manual 3, Skip 0, Unresolved 1 |
| 8 | Awaiting Review | TASK-1001 · 12 Exceptions | Review Required | 12/12, 100%; AI 8, Manual 3, Skip 1, Unresolved 0 |
| 9 | Execution Approval | TASK-1001 · Approval Stage | Pending Approval | 100 input, 1 skipped, 99 ready, 0 unresolved, 2 targets |
| 10 | Executing | TASK-1001 · Writing to OA & BI | Executing | 73%, 72/99, 12 s, 142 rec/sec |
| 11 | Results | TASK-1001 · Complete | Complete | 99/100, 42.8 s, 99.0%, 6 log events |

## Appendix B - Counter chain

```
100 input records
  -> 88 passed + 12 exceptions
     -> review tally at 9/12: 7 AI / 2 manual / 0 skipped / 3 unresolved
        -> ORD-052 Accept (AI match C-1024)      -> 8 / 2 / 0 / 2
        -> ORD-081 Edit (quantity = 6)           -> 8 / 3 / 0 / 1
        -> ORD-099 Skip (unreliable match)       -> 8 / 3 / 1 / 0
  -> 99 approved (1 skipped excluded)
     -> OA: write 99        BI: sync the same 99 (not 198)
        -> 99 / 100 written, 42.8 s, 99.0% success, 6 activity events
```

Tally order used throughout: accepted / manual / skipped / unresolved.

## Appendix C - Source annotations

The board carries four designer annotations. They are demo or design constraints, not product requirements, except where noted.

1. "Timed progress simulated - auto-transitions to Awaiting Review after 3s."
2. "Demo resumes Approval after 9 of 12 exceptions have been reviewed. Starting tally: 7 accepted / 2 manual / 0 skipped / 3 unresolved. ORD-052 to Accept (AI match C-1024) to 8/2/0/2; ORD-081 to Manual (quantity=6) to 8/3/0/1; ORD-099 to Skip (unreliable) to 8/3/1/0. Proceed enabled when unresolved = 0." The last sentence is a product rule (BR-4).
3. "OA and BI sync the SAME 99 records, not 198. No write happens before final approval." Both sentences are product rules (BR-2, BR-5).
4. "Timed execution simulated - auto-transitions to Results after 3s. RPA writes 99 records to OA, syncs same 99 to BI."
