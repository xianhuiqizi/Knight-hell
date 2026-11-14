# Demo Day source pack (synthetic)

Six files chosen to exercise different real-world export shapes. All customer
names, IDs and values are synthetic; there are no personal names, phone numbers
or company secrets in this folder.

| File | Format difference | Rows | Notable data |
| --- | --- | ---: | --- |
| `01_orders_header_offset.xlsx` | Title block, headers on row 4 | 30 | Missing `customer_id`; one side of both cross-file conflicts |
| `02_orders_thousand_cny.xlsx` | English aliases, `Price (CNY '000)` | 30 | Unit price entered in CNY for one row even though the header says thousand CNY |
| `03_orders_shuffled.csv` | CSV, shuffled columns, extra region/priority/note fields | 28 | Dates as `YYYY/MM/DD` |
| `04_orders_second_sheet.xlsx` | Cover sheet, data is the second worksheet | 30 | Mixed `DD/MM/YYYY` strings and Excel serial dates; other side of both conflicts |
| `05_orders_warehouse_boxes.xlsx` | Warehouse export in boxes | 30 | `Qty` in boxes, unit price per box; one row priced per piece |
| `06_orders_chinese_aliases.xlsx` | Chinese headers (`订单编号`, `客户名称`, …) | 26 | Missing `quantity` |

After normalization:

- 174 source rows;
- 36 merged records;
- exactly 6 confirmation items:
  - missing `customer_id` × 1 (`ORD-3004`);
  - missing `quantity` × 1 (`ORD-3030`);
  - thousand-CNY unit conflict × 1 (`ORD-3011`);
  - box/piece unit conflict × 1 (`ORD-3023`);
  - cross-file price/amount conflicts × 2 (`ORD-3008`, `ORD-3020`).

`customer_registry.csv` is a synthetic lookup table for future AI/grounded
customer-ID suggestions. Do not select it as a source file in the six-file
picker.

## Committed sample database

`demo_flowremote.db` is a clean, fully normalized snapshot of this pack. It
contains one demo account, one task, 174 source records, 36 primary normalized
records, 230 logged changes, 6 unresolved issues and the activity timeline.

The six upload files the database references are in `sample_uploads/`, so the
snapshot can be run without touching `data/runtime/`:

```powershell
$root = (Get-Location).Path
$env:FLOWREMOTE_DATABASE_URL = "sqlite:///$($root -replace '\\','/')/data/demoday/demo_flowremote.db"
$env:FLOWREMOTE_UPLOAD_DIR = "$root\data\demoday\sample_uploads"
.\.venv\Scripts\python.exe -m uvicorn flowremote.api.app:app --host 127.0.0.1 --port 8000
```

Log in as `demo@flowremote.dev / DemoDay2026!`. The task is already at
**Needs review**, so the result page and three-sheet download are available.
For a fresh "Start cleaning" rehearsal, use the seed command below instead.

Recreate everything with:

```powershell
python src\flowremote\devtools\seed_demoday.py --reset
```

`demo_flowremote.db` and `sample_uploads/` are only for review; they are not
loaded automatically by the normal seed.
