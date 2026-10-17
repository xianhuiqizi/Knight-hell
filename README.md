# FlowRemote

Mobile supervision and approval for AI-assisted data processing. Week 5 builds
the first working slices: the database and rules, then real sign-in and
per-user visibility.

## What works today

- `src/flowremote/contracts/` - enums and domain models; every field, its type
  and its rules live here once.
- `src/flowremote/control_plane/` - the database (migrations, one
  `DATABASE_URL` for SQLite and PostgreSQL), the review rules (tally, approval
  gate), and password/account handling.
- `src/flowremote/api/` - FastAPI app: sign-up, sign-in, sign-out, signed
  session cookies, task list and task detail filtered by role, and the
  Accept / Edit / Skip endpoint, the approval page and the approval write.
- `src/flowremote/ui/` - Jinja templates and one dark stylesheet.
- `src/flowremote/devtools/` - the demonstration data generator.
- `tests/` - 96 tests: model rules, review rules, database constraints,
  passwords, sessions, authentication, isolation, decisions and approval.

## Run it

```powershell
cd 'E:\knight hell'

# 1. dependencies (already installed by scripts\setup.ps1)
uv sync

# 2. demonstration data
uv run python src\flowremote\devtools\seed.py --reset --verify

# 3. the browser interface
uv run uvicorn flowremote.api.app:app --reload --host 127.0.0.1 --port 8000

# 4. tests
uv run python -m unittest discover -s tests
```

Open `http://127.0.0.1:8000`.

## Reviewing an exception

Open TASK-1001 as the operator account. Every unresolved row has three controls:

- **Accept** keeps the AI suggestion (disabled when there is no suggestion).
- **Skip** removes the record from the run.
- **Save** next to the value box records your own value.

Each action writes one row to Decisions and lowers the unresolved counter. The
banner above the table shows the approval gate: it opens only when the counter
reaches zero.

## Approving the batch

When the counter reaches zero the banner offers **Proceed**. The approval page
shows input / skipped / ready / unresolved, the source file and the two targets,
then **Approve & Execute** (or **Back to review**). Approving writes exactly one
row to Approvals, moves the task to `executing`, and cannot be repeated.
Execution progress and results are P5.

## Demo accounts

| Email | Password | Role | Sees |
| --- | --- | --- | --- |
| `alex.morgan@example.com` | `flowremote-demo` | operator | only TASK-1001 |
| `admin@example.com` | `flowremote-demo` | admin | every task |

`/signup` also works: a new account starts with no tasks and sees "No tasks
yet". The demo password exists only for local demos; remove those accounts
before any real deployment.

## The data behind it

The seed creates:

- `data\seed\customer_registry.csv` - 120 customers
- `data\seed\Orders_September.xlsx` - the 100 order source workbook
- `data\runtime\flowremote.db` - one task, 100 source records (88 passed,
  12 flagged), 12 unresolved exceptions, 0 decisions, 0 approvals

## Layout

```
src/flowremote/
  contracts/      enums, domain models, time format
  control_plane/  database, migrations, review rules, accounts
  api/            FastAPI app, sessions, routes
  ui/             templates and static assets
  agent/          the AI step (not built yet)
  rpa/            validation and execution engines (not built yet)
  connectors/     OA / BI adapters (not built yet)
  devtools/       seed data and local helpers
```

## Not built yet

The AI suggestion service, the execution layer (progress, results, retries) and
the OA/BI connectors.

## Notes

- `docs/project-summary.md` describes the whole project and its interfaces.
- `docs/p2-report.md` records what P2 changed and how it was verified.
- `docs/p3-report.md` records what P3 changed and how it was verified.
- `docs/p4-report.md` records what P4 changed and how it was verified.
- `prompts/prompt-log.md` is the AI-use log required by the course.
