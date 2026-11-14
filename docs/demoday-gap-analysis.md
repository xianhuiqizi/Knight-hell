# ENT207TC Demo Day — current state → gap analysis

Baseline: `main` @ `1c79fe6` (v0.5.0). Baseline suite: **234 passed, 11 subtests**.
This document was written after reading the routes, control plane, agent layer,
templates, migrations and tests — not from assumptions.

## What already exists and must be reused

| Capability | Evidence | Decision |
| --- | --- | --- |
| Registration, login, signed cookie, owner/admin isolation | `routes/session.py`, `control_plane/auth.py`, `api/deps.py`, `routes/tasks.py` | Reuse unchanged; normalization routes use the same visibility rule. |
| Single `.xlsx` upload (10 MB, 1–10k rows, header search, EN/CN aliases) | `control_plane/uploads.py`, `routes/uploads.py` | Keep `/tasks` and `/tasks/new` single-file path intact; add a separate multi-source path. |
| Deterministic `orders-v1` validation | `control_plane/order_validation.py` | Do not change. The normalization layer is additive and does not replace it. |
| AI suggestion runs, encrypted keys, 70% threshold | `agent/service.py`, `agent/providers.py`, `control_plane/ai_settings.py` | Reuse later for C/D; do not duplicate the key store or the suggestion run audit. |
| Human review / approval / execution / activity JSON | `routes/review.py`, `routes/approval.py`, `routes/execution.py`, `control_plane/decisions.py` | Keep for legacy orders tasks. New tasks need their own confirm queue in the C/D increment. |
| Append-only activity log | `control_plane/activity.py`, migration 0004 | Reuse; new event kinds are plain rows, no schema change needed. |
| PWA, offline cache, local sync | `ui/static/sw.js`, `sync.py`, `routes/sync.py` | Do not touch. |
| Seed and demo entry | `devtools/seed.py`, `templates/demo_landing.html` | Add `seed_demoday.py`; leave old seed working. |

## Gaps against the Demo Day brief

| Requirement | Current reality | Gap / action in this increment |
| --- | --- | --- |
| A. 6 files, one selection, ≤6 / ≤20 MB | Only one `.xlsx` (`max_files=1`, `/tasks`) | **Add** multi-file form + parser, per-file rows, aggregate bound; retain single-file form. |
| A. CSV and second-sheet support | `read_workbook` always reads the first worksheet; no CSV parser | **Add** independent source reader: `.csv` + best worksheet, header search. |
| A. Per-file failure does not fail the batch | A bad workbook rejects the whole request | **Add** per-file status `attention`, readable error, unresolved issue, continue. |
| A. File metadata (sheet, rows, fields, status) | Only worksheet + row count stored for one file | **Add** `normalization_files` table and UI list. |
| B. Unified schema in `contracts/` | Only the 7-field `orders-v1` tuple | **Add** `contracts/normalization.py` with 10-field schema (adds `unit`, `source_file`, `source_row`) and mapping dataclasses. |
| B. Mapping with rule first + confidence/evidence | `order_validation.ALIASES` is exact-match only and raises on missing | **Add** broader synonym table, normalisation, type/distribution fallback, per-field confidence/evidence; fail per file, not per batch. AI fallback hook deferred to C. |
| B. Units (thousand CNY, box→piece), logged and explainable | No unit column, no conversion, no change log | **Add** deterministic conversions with `normalization_changes` rows and stage summaries. |
| B. Cross-file merge by `order_id`, conflicts recorded | No second file | **Add** merge tick; identical duplicates collapse, divergent values produce `cross_file_conflict` issues and are never silently overwritten. |
| B. Idempotency | N/A | Content fingerprint plus deterministic ordering; repeated tick is a no-op, cancel/retry rebuilds cleanly. |
| C. AI connection test window | Settings save exists; connection test explicitly absent (`ai_settings.html`) | Deferred to the next increment as requested. |
| D. 6 human confirmation cards | Only `orders-v1` exception table exists | Deferred to the next increment; this increment creates and counts the 6 unresolved normalization issues so D can attach to them. |
| E. Normalization progress 0→100, current file, counts, elapsed, cancel | Only execution progress exists; normalization is immediate/synchronous | **Add** a deterministic tick-driven job, 300–500 ms client refresh, elapsed time, cancel with derived-row cleanup, idempotent restart, under 20 s. |
| F. Normalization summary + activity timeline | Execution results/log only | **Add** summary card and stage events `normalize_upload → normalize_detect → normalize_map → normalize_started → normalize_normalize → normalize_complete`. |
| F. Download normalized `.xlsx` (3 sheets) | Only original file + activity JSON | **Add** `FlowRemote_normalized_YYYYMMDD_HHMM.xlsx` with `normalized`, `changes`, `unresolved`; owner/admin check reused. |
| G. No regression | 234 tests, migrations through 0008 | **Keep** old routes/statuses; add migration 0009 only; run all old tests unchanged. |
| Demo pack | Old seed has one 100-row workbook | **Add** 6 deterministic files in `data/demoday/`, exactly 6 issues (missing×2, unit×2, conflict×2), synthetic companies only; `seed_demoday.py --reset`. |

## Guardrails for this increment

- Phase 1 intentionally does **not** connect a real AI provider and does **not**
  implement the human confirmation editor. It produces the queue, counts and
  the downloadable unresolved sheet so C and D can be added without redesign.
- `orders-v1` rule semantics, PWA/offline sync and packaging remain untouched.
- No real API keys, names, phone numbers or company secrets are committed.

## Phase 1 result (implemented)

| Gap | Status now |
| --- | --- |
| A. Multi-file upload, CSV/second sheet, per-file failure isolation | **Done** — 6-file picker, 10 MB/file + 20 MB total, upload-time recognition, visible file metadata, `file_error` item instead of batch failure. |
| B. Normalized contract, mapping evidence, units, merge, idempotency | **Done** — `contracts/normalization.py`, rule mapping with confidence/evidence, thousand-CNY/box/date conversions, duplicate merge and conflict issues, deterministic fingerprint. AI mapping fallback remains deferred to C. |
| E. Progress, current file, counts, elapsed, cancel, restart | **Done** — persisted tick job, 360 ms refresh, cancel deletes derived rows, restart is deterministic; observed 3.0 s. |
| F. Timeline, summary, 3-sheet download | **Done** — upload/detect/map/start/normalize/complete events; normalized/changes/unresolved workbook; owner/admin guard. |
| C. Visible AI connection test | Deferred, as requested. Existing encrypted settings and AI suggestion layer untouched. |
| D. Editable human confirmation queue | Deferred. The six items are recorded, counted and exported in `unresolved`; the cards are read-only in this phase. |
| G. Existing behaviour | **Preserved** — 234 baseline tests unchanged and passing; 38 new tests (272 total). |

Evidence: `docs/demoday-demo-runbook.md`, `docs/demoday-phase1-change-report.md`,
`output/demoday-phase1/`.
