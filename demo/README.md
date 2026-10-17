# FlowRemote - interactive demo

A self-contained prototype of the Week 5 flow: sign in, review the flagged
records, then approve the batch. It runs in any modern browser with **no
installation, no server and no build step**.

## Run it

Double-click `index.html`, or serve the folder if you prefer:

```powershell
cd 'E:\knight hell'
python -m http.server 8000 --directory demo
# then open http://127.0.0.1:8000
```

## Demo accounts

| Email | Password | Role | Sees |
| --- | --- | --- | --- |
| `alex.morgan@example.com` | `flowremote-demo` | operator | TASK-1001 and TASK-0999 |
| `bea.chen@example.com` | `flowremote-demo` | operator | TASK-1002 only |
| `admin@example.com` | `flowremote-demo` | admin | every task |

The login screen has buttons that fill these in for you. `Create one` registers
a new operator account, which starts with no tasks.

## What the demo shows

- Sign up, sign in, sign out, and a session that survives a page reload.
- Per-account visibility: an operator sees only their own tasks; an admin sees
  every task. Asking for another account's task shows "Task not found".
- **Review**: every unresolved row has Accept, Skip, and a value box with Save.
  Accept is disabled when there is no suggestion. Each action updates the row
  (status, value, who decided), the unresolved counter, and the ready count.
- **Gate**: a banner stays grey and says how many unresolved exceptions block
  approval; at zero it turns green and offers **Proceed**.
- **Approval page**: input / skipped / ready / unresolved, the source file, the
  two targets (write vs sync, never twice), and **Approve & Execute** or
  **Back to review**.
- After approval the task reads "Executing" with a record of who approved it,
  when, and how many records. The demo ends there; execution is the next phase.
- "Reset demo data" in the footer restores the seeded accounts and tasks.

## What is simulated

This is a front-end prototype: accounts, tasks and the session live in the
browser's `localStorage`, and the demo passwords are stored in plain text inside
`app.js` so the demo needs nothing installed. Approving here does **not** write
to OA or BI.

The real implementation keeps the same behaviour but on the server:

- `src/flowremote/api/` - FastAPI routes, signed session cookies, the decision
  endpoint and the approval transitions.
- `src/flowremote/control_plane/auth.py` - PBKDF2-HMAC-SHA256 password hashes.
- `src/flowremote/control_plane/review.py` - the Accept / Edit / Skip rules.
- `src/flowremote/control_plane/db.py` - SQLite/PostgreSQL storage; visibility
  filters by `owner_id` unless the user is an admin.

Run the real version with:

```powershell
uv run python src\flowremote\devtools\seed.py --reset --verify
uv run uvicorn flowremote.api.app:app --reload --host 127.0.0.1 --port 8000
```

## Files

| File | Purpose |
| --- | --- |
| `index.html` | shell: header, view container, footer |
| `app.js` | seed data, storage, routing, views, review and approval actions |
| `app.css` | dark theme, same palette as the server-rendered app |
| `README.md` | this file |
