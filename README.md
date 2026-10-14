# FlowRemote

Mobile supervision and approval for AI-assisted data processing. Week 5 builds
the first real slice: a database that holds one demonstration task end to end.

## What runs today (slice 1)

- `src/flowremote/control_plane/db.py` - the only module that knows SQL. It
  opens the database, applies migrations, and keeps SQLite and PostgreSQL
  interchangeable through one `DATABASE_URL`.
- `src/flowremote/control_plane/migrations/0001_init.sql` - the six tables.
- `src/flowremote/devtools/seed.py` - generates the demonstration data and
  loads it. No third-party packages are needed.

## Run it

```powershell
cd 'E:\knight hell'
python src\flowremote\devtools\seed.py --reset --verify
```

The run creates:

- `data\seed\customer_registry.csv` - the registry the suggestion step looks ids up in
- `data\seed\Orders_September.xlsx` - the 100 order source workbook
- `data\runtime\flowremote.db` - the database

Then `python src\flowremote\devtools\seed.py --verify` prints the counts again
without changing anything, and `scripts\verify.sql` holds the same queries for
any SQL client.

## Not built yet

Models and tests (next slice), the API and the browser interface (P3 to P5), the
suggestion agent, and the execution layer. The tables exist; nothing writes to
them yet except the seed script.
