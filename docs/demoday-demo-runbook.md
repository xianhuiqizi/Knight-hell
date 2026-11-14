# ENT207TC Demo Day runbook — phase 1

Target date: **18 November 2026** · 6-minute live demo + 4-minute Q&A.
This runbook covers the phase-one scope that is ready for review: multi-source
upload → recognition → normalization → progress → three-sheet Excel download.
The AI connection test (C) and the editable confirmation queue (D) are deliberately
the next increment; the script marks where they slot in.

---

## 60-second preparation checklist

Do this once before the room fills, then leave the browser on `/demo`.

- [ ] **0:00** Open PowerShell in the repository root.
- [ ] **0:05** Rebuild the deterministic pack and account:

  ```powershell
  .\.venv\Scripts\python.exe src\flowremote\devtools\seed_demoday.py --reset
  ```

  Expected last lines: `pack check ... OK`, `database check ... OK`, and
  `Demo login : demo@flowremote.dev / DemoDay2026!`.
- [ ] **0:15** Start the server:

  ```powershell
  .\.venv\Scripts\python.exe -m uvicorn flowremote.api.app:app --host 127.0.0.1 --port 8000
  ```

- [ ] **0:25** Open <http://127.0.0.1:8000/demo>. Do **not** register.
- [ ] **0:30** Click **Start the 6-minute demo**. If the welcome guide appears,
  click **Exit** once.
- [ ] **0:35** In File Explorer, open
  `C:\...\Knight-hell\data\demoday` and keep it open beside the browser.
- [ ] **0:45** Confirm all six files are visible:
  `01_orders_header_offset.xlsx`, `02_orders_thousand_cny.xlsx`,
  `03_orders_shuffled.csv`, `04_orders_second_sheet.xlsx`,
  `05_orders_warehouse_boxes.xlsx`, `06_orders_chinese_aliases.xlsx`.
  Do not select `customer_registry.csv`.
- [ ] **0:55** Close the Edge translate bubble if it appears. Set browser zoom
  to 100%. Keep the laptop on mains power.

**Recovery copy:** the seed also creates a pre-uploaded batch called
**Demo Day data cleanup** on the home page. It has the same six recognized files.
Use it if the native file picker misbehaves.

---

## 6-minute run script

### 0:00 — Open the demo (20 s)

- Show `/demo`: “Many files in. One clean dataset out.”
- Click **Start the 6-minute demo**. This logs into the seeded operator account,
  `demo@flowremote.dev`; no registration.
- Land on the workspace. Point out the preloaded six-file fallback batch, then
  click **+ New task**.

### 0:20 — Create the session (5 s)

- Task name: **Demo Day 数据整理**.
- Scroll once to the source picker.

### 0:25 — Upload six different files (20 s)

- Click **Choose files**.
- Select the six `data/demoday` order files in one picker (Ctrl+A in the folder
  selects `customer_registry.csv` too — Ctrl+click it off).
- The picker lists all six files and the total (≈34.3 KB / 20 MB).
- Click **Upload & detect**.

### 0:45 — Recognition is already done (15 s)

Say: “Recognition happens before the run, so it is cheap to check.”

- Show the green banner: **6 files uploaded · 6/6 formats recognized**.
- Read the table: every file has a worksheet, header row, row count and field
  count. Examples:
  - `01` — XLSX, header on row 4, 30 rows, 8 fields.
  - `03` — CSV, 28 rows, shuffled columns plus extra fields.
  - `04` — XLSX, data on the second sheet, 30 rows.
  - `05` — XLSX warehouse boxes, 30 rows.
  - `06` — XLSX Chinese aliases, 26 rows.
- Open one **Mapping evidence** disclosure and show the alias → field,
  confidence and evidence. Say: “Rule first, AI only as a future fallback.”

### 1:00 — Start the cleaning run (30 s)

- Click **Start cleaning**.
- Progress refreshes every 360 ms: current file, processed/total, elapsed time.
- While it runs, explain:
  - thousand-CNY prices are converted to CNY;
  - box quantities are converted to pieces (1 box = 12 pieces);
  - mixed dates become ISO;
  - duplicate `order_id`s merge, conflicts are kept as issues.
- The run ends in about 3–5 seconds (well under the 20-second budget).

### 1:30 — Summary and six items (30 s)

- Summary: **6 files · 174 source rows · 36 merged records · 143 auto-fixed
  rows · 0 human · 6 to confirm · 0 skipped · ~3 s**.
- Say: “Nobody has touched the data yet. The engine has recorded six items it
  will not decide alone.”
- Show the six cards:
  - two missing values (customer ID, quantity);
  - two unit conflicts (thousand-CNY and box/piece);
  - two cross-file conflicts (same order, different price/amount).

### 2:00 — Confirmation queue (C/D placeholder)

- **Phase 1:** the cards are readable but not editable; each says
  **Pending confirmation**. The full editable cards land in the next increment.
- **After C/D:** at this point the presenter fills each card, presses Confirm,
  and the counter drops from 6 → 0. Do not claim this interaction until the
  next increment is merged.
- For now, say explicitly: “This build records and exports the six items; the
  human edit step is the next slice.”

### 2:30 — Download the result (20 s)

- Click **Download cleaned .xlsx** (top right or under the summary).
- Filename: `FlowRemote_normalized_YYYYMMDD_HHMM.xlsx`.
- If the download shelf appears, open it to show three sheets:
  - **normalized** — 36 records, ten standard columns including source file/row;
  - **changes** — 230 rule-based changes with original, new value and reason;
  - **unresolved** — exactly six rows with reasons.

### 3:00 — Activity timeline (30 s)

Scroll to **Activity timeline**. Read the order rather than every timestamp:

```text
Upload → Detect → Map → Start → Normalize → Complete
```

Point out the audit detail in the mid-line: “29 thousand-CNY prices converted,
29 box rows converted to pieces, 114 dates normalized”. Every event has an
actor (Demo Day Operator or FlowRemote Normalizer).

### 3:30 — Why this is multi-source (20 s)

Return to the file table. Read down the Sheet column: title-offset sheet, second
sheet, CSV, warehouse sheet, Chinese headers. Say: “One file type was not
allowed to fail the batch; a broken file becomes a confirmation item and the
rest continue.”

### 3:50 — Close (10 s)

“Six messy files become one normalized workbook, with a change log and an
unresolved list a human can audit. The live AI connection test and the editable
confirmation cards are the next increment.”

### 4:00–6:00 — Q&A on the delivered surface

Likely questions and short answers:

- **Why doesn’t it just use AI for everything?** Rules are deterministic and
  auditable; AI is a fallback for ambiguous mapping and is never allowed to
  approve.
- **What happens to duplicates?** Identical rows merge; differing duplicates
  become `cross_file_conflict` issues; the first source is provisional, never
  silently final.
- **Can it run offline?** Yes — the normalizer does no network call at all.
  The online AI adapter is not part of this increment.
- **What if a file is corrupt?** That file gets `Needs attention` and a
  `file_error` item; the other files still normalize and the download still works.
- **Can I re-run?** Yes. Cancel removes derived rows but keeps uploads, and Start
  rebuilds from the same deterministic inputs.

---

## Three failure fallbacks

### 1. Wrong/missing demo account at `/demo`

**Symptom:** Start the demo shows “The demo account is not seeded yet.”

**Fix (≈15 s):**

1. Stop the server with `Ctrl+C`.
2. Run `python src\flowremote\devtools\seed_demoday.py --reset`.
3. Start uvicorn again, refresh `/demo`, click Start the demo.

Never register a new account on stage; the seeded path is the tested one.

### 2. File picker / six-file selection fails

**Symptom:** fewer than six files in the picker, or the native dialog cannot
multi-select.

**Fix (≈20 s):**

1. Go **Back to tasks**.
2. Open the seeded batch **Demo Day data cleanup** — it already contains the same
   six recognized files.
3. Press **Start cleaning** and continue from 1:00 in the script. The summary,
   issue count and download are identical.

The live upload is the intended path; the fallback batch is the safety net.

### 3. Port/PWA/stale-asset failure

**Symptom:** `/demo` is unreachable, the page looks unstyled, or an old error
message is still visible after a code change.

**Fix (≈30 s):**

1. Stop uvicorn and restart:
   `python -m uvicorn flowremote.api.app:app --host 127.0.0.1 --port 8000`.
2. Hard refresh with `Ctrl+F5`.
3. If a stale service worker still serves old assets: Edge → **Settings >
   Privacy, search and services > Site permissions > All sites > 127.0.0.1 >
   Delete data**, then reopen `/demo`.
4. Last resort for the download: restart once, open the fallback batch, run the
   cleaning again, and download. The run is deterministic and takes seconds.

Do not clear the whole browser profile in the room; clear only this site.

---

## Rehearsal acceptance

Run this three times and confirm the same values every time:

| Check | Expected |
| --- | --- |
| Recognized files | 6 / 6 |
| Source rows | 174 |
| Merged records | 36 |
| Auto-fixed source rows | 143 |
| Confirmation items | 6 (missing 2, unit 2, cross-file 2) |
| Visible cleaning duration | ≤ 20 s (observed ~3–5 s) |
| Download sheets | normalized / changes / unresolved |
| Download rows | 37 / 231 / 7 (including headers) |
| Clicks from `/demo` to download | 7 |
| Whole flow | under 4 minutes |

Pytest proof:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
# 272 passed, 11 subtests passed
```
