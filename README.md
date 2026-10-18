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
- `tests/` - model rules, review rules, database constraints, passwords, sessions,
  authentication, isolation, decisions, approval and workbook uploads.

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
uv run python -m pytest tests -q
```

Open `http://127.0.0.1:8000`.

## Creating a task

Sign in and choose **+ New task** on the home page, or open `/tasks/new`.
Enter a task name and choose an `.xlsx` workbook (up to 10 MB). The first
worksheet uses its first non-empty row as headers (within the first 1,000 rows),
followed by 1–10,000 rows, with at most 256 columns. Leading blank rows are
skipped; blank data rows are ignored when counting the batch size. A title or
explanatory text before the actual headers is not automatically detected.

The task belongs to the signed-in user. Uploading automatically validates the
orders and opens **Review required**, with counts and exceptions from that file.
The original workbook is saved under `data/runtime/uploads/` with a generated
filename; `FLOWREMOTE_UPLOAD_DIR` can override this directory. Back up this
directory together with the database. Owners and admins can download the
original from the task page; other operators cannot see or download it.

Download `/orders-template.xlsx` from the new-task form. Required fields:
`order_id`, `customer_name`, `customer_id`, `quantity`, `unit_price`, `amount`,
`order_date`. Common English and Chinese headers are supported, including
订单号、客户名称、客户编号、数量、单价、金额、订单日期. Columns may be reordered;
extra columns are ignored. Missing or ambiguous required columns reject the
upload without saving a partial task. Save IDs as text to retain leading zeros.

The current `orders-v1` rules check:

- All seven fields are required. IDs are compared exactly after trimming spaces;
  duplicate order IDs within the same file flag every affected row.
- Quantity is a positive whole number up to 1 billion.
- Unit price and amount are non-negative numbers with at most two decimal
  places, no larger than 1 trillion. Numeric text uses a dot decimal separator
  and no grouping separators. Amount must equal quantity × unit price exactly.
- Dates accept actual Excel dates, `YYYY-MM-DD` and `YYYY/MM/DD`; impossible
  dates are rejected. Formulas are not evaluated: paste their values first.
- Multiple issues on one order produce one exception with all reasons. Its Excel
  row number, original values, original workbook and rule version are retained.
  Only an amount-only error receives a quantity × unit price suggestion. No
  customer registry lookup or AI inference is performed.

**Accept** applies the calculated amount. **Edit order → Save & recheck** checks
all fields and uniqueness again before saving. **Skip** excludes an order.
Corrections and review decisions commit together, while original values and
initial analysis counts remain unchanged for audit. Unresolved exceptions block
approval. Exceptions paginate in groups of 100; the gate counts the whole task.

Tasks uploaded before this feature retain their files and have a **Validate
uploaded orders** button. Repeat validation does not erase existing decisions.
The existing seeded demonstration task and its exceptions remain explicitly
labelled demo data. Real OA/BI execution is still not implemented.

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
