# Demo Day phase 1 — change report

Baseline: `main` @ `1c79fe6` (v0.5.0) → working tree **0.6.0**.
Scope delivered: **A + B + E + F download skeleton** (multi-file upload,
recognition/normalization, progress, activity timeline, 3-sheet Excel). C
(visible AI connection test) and D (editable confirmation queue) are deliberately
left for the next increment. `orders-v1`, approval, execution, PWA and packaging
semantics are unchanged.

## What changed and why

| Path | Change | Why |
| --- | --- | --- |
| `src/flowremote/contracts/normalization.py` | New | Single 10-field normalized schema, alias table, mapping/evidence dataclasses, limits. |
| `src/flowremote/control_plane/normalization.py` | New | Pure rules: header detection, XLSX/CSV parsing, synonym + distribution mapping, thousand-CNY and box conversions, date parsing, merge/conflict handling. |
| `src/flowremote/control_plane/normalization_jobs.py` | New | Upload-time recognition, staged deterministic job, progress snapshot, cancel, idempotent restart, result workbook builder. |
| `src/flowremote/control_plane/migrations/0009_normalization.sql` | New | Additive tables for batches, files, source rows, changes and unresolved issues. No existing table or rule is altered except a defaulted `tasks.task_mode` column. |
| `src/flowremote/api/routes/normalization.py` | New | Multi-file upload, start/tick/status/cancel/download/JSON endpoints with owner/admin checks. |
| `src/flowremote/api/app.py` | Modified | Register the new router; version 0.6.0. |
| `src/flowremote/api/routes/tasks.py` | Modified | Add task mode and normalization summary fields; route normalize tasks to their own page. Legacy context unchanged. |
| `src/flowremote/api/routes/session.py` | Modified | `/demo/enter` one-click seeded login with fallback to the legacy demo account and readable error if unseeded. |
| `src/flowremote/ui/templates/normalize_task.html` | New | Ready, progress, summary, six issue cards, mapping evidence, timeline, download. |
| `src/flowremote/ui/templates/new_task.html` | Modified | Multi-source form becomes the primary path; single-file `orders-v1` form remains under a disclosure. |
| `src/flowremote/ui/templates/demo_landing.html` | Modified | Demo Day positioning and one-click entry. |
| `src/flowremote/ui/templates/home.html` | Modified | Normalize task cards show mode/status and summary without breaking orders cards. |
| `src/flowremote/ui/templates/base.html` | Modified | Bump static asset cache version only. |
| `src/flowremote/ui/static/app.js` | Modified | Multi-file client validation/list, seamless upload, 360 ms progress polling, fault messages, file status updates. |
| `src/flowremote/ui/static/app.css` | Modified | Normalize upload, progress, file table, mapping evidence, issue cards and ≤640 px layout. |
| `src/flowremote/ui/static/sw.js` | Modified | Cache-version bump; no offline/PWA behaviour change. |
| `src/flowremote/devtools/demoday_data.py` | New | Deterministic generator for the six source files and customer registry. |
| `src/flowremote/devtools/seed_demoday.py` | New | `--reset` rebuild of database, demo account, six recognized files, fallback batch and verification counts. |
| `data/demoday/*.xlsx`, `*.csv` | New | The six committed Demo Day files plus synthetic registry. |
| `tests/unit/test_normalization.py` | New | 24 unit tests (parse, aliases, sheet/CSV, dates, units, merge, conflicts, exact pack). |
| `tests/integration/test_normalization.py` | New | 14 HTTP/DB tests (limits, upload, recognition, progress, cancel/restart, download, permissions, bad file). |
| `docs/demoday-gap-analysis.md` | New | Current state → gap audit required before changing code. |
| `docs/demoday-demo-runbook.md` | New | 60-second prep, 6-minute script and three fallbacks. |
| `README.md`, `pyproject.toml`, `uv.lock` | Modified | Document the feature and bump to 0.6.0. |

## Migration

`0009_normalization.sql` only adds:

- `tasks.task_mode TEXT NOT NULL DEFAULT 'orders'` (legacy rows stay `orders`);
- `normalization_batches`, `normalization_files`, `normalized_records`,
  `normalization_changes`, `normalization_issues` and their indexes.

Re-running migrations is idempotent. No existing migration, column type, check
constraint or `orders-v1` semantic was edited.

## Verification

```text
pytest tests -q
272 passed, 11 subtests passed
```

- Existing 234 tests were **not modified** and still pass.
- Added 38 tests (24 unit + 14 integration), above the ≥25 requirement.
- `python -m compileall src/flowremote` passed.
- `node --check src/flowremote/ui/static/app.js` passed.
- Demo pack: 6/6 files, 174 source rows, 36 merged records, 143 auto-fixed source
  rows, exactly 6 issues (missing 2 / unit 2 / cross-file 2).
- Observed visible cleaning run: 3.0–5.0 s (limit 20 s).
- Download: `normalized` 37 rows, `changes` 231 rows, `unresolved` 7 rows
  including headers; resolved filename matches `FlowRemote_normalized_YYYYMMDD_HHMM.xlsx`.
- Screenshots and the downloaded workbook: `output/demoday-phase1/`.

## Deliberate gaps in this phase

- No visible AI connection test; the normalizer is rules-only and makes no
  network call as requested for phase 1.
- The six confirmation cards are read-only; the download is enabled while they
  are unresolved so the phase-one skeleton can be demonstrated. Phase D will
  wire edit/recheck/resolve and tighten the gate.
- No real AI call or API key is involved.

## Rollback

The migration is additive, so a code-only rollback is safe: old code ignores the
new tables and the defaulted `task_mode` column.

For an uncommitted working tree:

```powershell
git restore README.md pyproject.toml uv.lock `
  src/flowremote/api/app.py `
  src/flowremote/api/routes/session.py `
  src/flowremote/api/routes/tasks.py `
  src/flowremote/ui/static/app.css `
  src/flowremote/ui/static/app.js `
  src/flowremote/ui/static/sw.js `
  src/flowremote/ui/templates/base.html `
  src/flowremote/ui/templates/demo_landing.html `
  src/flowremote/ui/templates/home.html `
  src/flowremote/ui/templates/new_task.html

Remove-Item -Recurse -Force `
  src/flowremote/api/routes/normalization.py, `
  src/flowremote/contracts/normalization.py, `
  src/flowremote/control_plane/normalization.py, `
  src/flowremote/control_plane/normalization_jobs.py, `
  src/flowremote/control_plane/migrations/0009_normalization.sql, `
  src/flowremote/devtools/demoday_data.py, `
  src/flowremote/devtools/seed_demoday.py, `
  src/flowremote/ui/templates/normalize_task.html, `
  tests/unit/test_normalization.py, `
  tests/integration/test_normalization.py, `
  docs/demoday-gap-analysis.md, `
  docs/demoday-demo-runbook.md, `
  docs/demoday-phase1-change-report.md, `
  data/demoday
```

Then delete/recreate the local demo database, because it contains data written
through migration 0009:

```powershell
Remove-Item data\runtime\flowremote.db*, data\runtime\uploads\* -Force
python src\flowremote\devtools\seed.py --reset --verify
```

For a committed branch: `git revert <phase-1-commit>` (the new tables can remain
in an existing database; they are unreferenced by the old code).
