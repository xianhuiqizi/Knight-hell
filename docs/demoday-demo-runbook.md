# ENT207TC Demo Day runbook — phase D

Target date: **18 November 2026** · 6-minute live demo + 4-minute Q&A.
This runbook covers the current build: multi-source upload → recognition →
normalization → AI connection test → editable human review with **AI suggestion**
→ complete gate → three-sheet Excel download.

---

## 60-second preparation checklist

Do this once before the room fills, then leave the browser on `/demo`.

- [ ] **0:00** Open PowerShell in the repository root.
- [ ] **0:05** Rebuild the deterministic pack and account:

  ```powershell
  .\.venv\Scripts\python.exe src\flowremote\devtools\seed_demoday.py --reset
  ```

  Expected last lines: `pack check ... OK`, `database check ... OK`, and
  `Demo login : demo@flowremote.dev / DemoDay2026!`. If the six demo files are
  currently open in Excel, close them first, or use
  `seed_demoday.py --reset --skip-files` to rebuild only the database.
- [ ] **0:15** Start the server:

  ```powershell
  .\.venv\Scripts\python.exe -m uvicorn flowremote.api.app:app --host 127.0.0.1 --port 8000
  ```

- [ ] **0:25** Open <http://127.0.0.1:8000/demo>. The page opens in **English by
  default**; the top-right **EN / 中文** switch is available if you want Chinese.
  Do **not** register.
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
- [ ] **0:58** Have the AI key ready **outside the repository** (clipboard or
  password manager). Do not paste it into `.env`, a prompt, or a screenshot.
  If the room has no network, skip the key; **AI suggestion** still works with
  grounded Offline Demo AI advice.

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
  confidence and evidence. Say: “Rules handle the deterministic mapping; AI is
  optional advice, not the source of truth.”

### 1:00 — Test the AI connection (30 s)

- Point at the **AI connection · optional** card: “The cleanup is rules-only; AI
  is optional.”
- Click **Test online connection**. The dialog opens with OpenAI-compatible
  selected even while the current active provider is Offline Demo AI; pasting a
  key also switches the form automatically.
- Provider: **OpenAI-compatible**. The default target is **DeepSeek Flash**:
  model `deepseek-flash`, Base URL `https://api.deepseek.com`. These values are
  prefilled; adjust them only if you are using a different endpoint.
- Paste the key. Only a `••••ABCD` hint appears; the key field itself stays
  masked.
- Click **Connect**. The 5-second budget is visible. Success shows
  **Connected · model · latency**.
- If the test fails (bad key, quota or no network), show the red explanation and
  the yellow **Offline Demo AI active** notice. Say: “The flow still finishes;
  offline is a first-class path.”
- Close the dialog. The task card now shows the active provider/model.
- Optional one-click fallback: **Use Offline Demo AI** inside the same dialog.

### 1:30 — Start the cleaning run (10 s)

- Click **Start cleaning**.
- Progress refreshes every 360 ms: current file, processed/total, elapsed time.
- While it runs, explain:
  - thousand-CNY prices are converted to CNY;
  - box quantities are converted to pieces (1 box = 12 pieces);
  - mixed dates become ISO;
  - duplicate `order_id`s merge, conflicts are kept as issues.
- The run ends in about 3–5 seconds (well under the 20-second budget).

### 1:40 — Summary and six items (20 s)

- Summary: **6 files · 174 source rows · 36 merged records · 143 auto-fixed
  rows · 0 human · 6 to confirm · 0 skipped · ~3 s**.
- Say: “Nobody has touched the data yet. The engine has recorded six items it
  will not decide alone.”
- Show the six cards:
  - two missing values (customer ID, quantity);
  - two unit conflicts (thousand-CNY and box/piece);
  - two cross-file conflicts (same order, different price/amount).
- Point at the **Human gate**: **6 item(s) remaining**, **Complete cleaning
  (6 left)** disabled, download locked.

### 2:00 — Editable review and AI suggestion (50 s)

This is the Phase D moment. Do not download yet.

1. On the **missing customer ID** card, click **AI suggestion**.
   - Online (DeepSeek Flash connected): the AI box shows the model, confidence,
     reason and evidence, and fills `C-2104`.
   - Offline: the box says **Offline Demo AI** with the grounded match.
   - Say: “AI proposes, the server revalidates, and I still confirm.”
2. Click **Confirm**. The counter drops **6 → 5**, and the card becomes
   **Confirmed**.
3. On the **missing quantity** card, click **AI suggestion** → it derives the
   quantity from amount ÷ unit price → **Confirm** (5 → 4).
4. On the **box/piece conflict**, click **AI suggestion** → `quantity × 12`,
   unit `piece` → **Confirm** (4 → 3).
5. On the **thousand-CNY conflict**, the current values are already consistent
   as CNY. Show the editable fields, then click **Confirm** without changing
   them (3 → 2).
6. On the two **cross-file conflicts**, show the alternative source values in
   the reason, then **Confirm** the first source (2 → 1 → 0). No field is saved
   silently.
7. The counter now says **0 item(s) remaining**. **Complete cleaning** is
   enabled. Click it.

If a confirm is rejected, read the red validation message (for example
`Amount must equal quantity × unit price`) and correct the field. This is part of
the story: the gate is not a rubber stamp.

**Skip option:** each card also has **Skip**. The reason is optional: leave it
blank to skip directly and the audit log records `No reason provided.`. A skipped
order leaves the clean sheet and is retained in the `unresolved` sheet. Do not use
it in the happy-path run unless you want to show that audit path.

### 2:50 — Complete cleaning and download (20 s)

- After **Complete cleaning**, the page says **Review complete** and the
  **Download cleaned .xlsx** button appears.
- Filename: `FlowRemote_normalized_YYYYMMDD_HHMM.xlsx`.
- If the download shelf appears, open it to show three sheets:
  - **normalized** — 36 records, ten standard columns including source file/row;
  - **changes** — 230 rule-based rows plus human confirmation rows, each with
    original, new value, reason and method (`rule`/`human`);
  - **unresolved** — header only when all six items were confirmed.

### 3:10 — Activity timeline (25 s)

Scroll to **Activity timeline**. Read the order rather than every timestamp:

```text
Upload → Detect → Map → Start → Normalize → AI suggestion → Human confirm
→ Review complete
```

Point out that every event has an actor: the model for **AI suggestion**, the
signed-in presenter for **Human confirm**, and the engine for normalization.
Then show the source table: one file type did not block the batch.

### 3:30 — Why this is multi-source (20 s)

Return to the file table. Read down the Sheet column: title-offset sheet, second
sheet, CSV, warehouse sheet, Chinese headers. Say: “One file type was not allowed
to fail the batch; a broken file becomes a confirmation item and the rest
continue.”

### 3:50 — Close (10 s)

“Six messy files become one normalized workbook, with a change log, an
AI-suggested human review and an unresolved list a person can audit. AI proposes;
the human gate decides.”

### 4:00–6:00 — Q&A on the delivered surface

Likely questions and short answers:

- **Why doesn’t it just use AI for everything?** Rules are deterministic and
  auditable; AI is advisory for ambiguous review items and is never allowed to
  confirm or approve.
- **What happens if AI invents a value?** The server filters to editable fields,
  re-runs the same validation as a manual edit, rejects an unknown customer ID,
  and falls back to Offline Demo AI advice. A person still has to press Confirm.
- **Can it run offline?** Yes. The normalizer is rules-only; the editable review
  and **AI suggestion** work with grounded Offline Demo AI advice, and the
  workbook downloads normally.
- **What happens to duplicates?** Identical rows merge; differing duplicates
  become `cross_file_conflict` issues; the first source is provisional, never
  silently final. The human can choose the alternative or skip.
- **What if a file is corrupt?** That file gets `Needs attention` and a
  `file_error` item; the other files still normalize. The error card can only be
  skipped with an optional reason, then the gate opens.
- **What does skip do?** It excludes the order from the clean sheet and keeps the
  item and human reason in the `unresolved` sheet. It is not a silent delete.
- **Can I re-run?** Yes. Cancel removes derived rows but keeps uploads, and Start
  rebuilds from the same deterministic inputs.

---

## Failure fallbacks

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

### 4. AI Connect or AI suggestion fails / has no network

**Symptom:** red error such as “rejected this API key”, quota or network during
Connect, or an AI suggestion that does not return.

**Fix (≈5 s):**

1. Do not debug the key in front of the room.
2. Click **Use Offline Demo AI**, or close the dialog; the page card will show
   **Offline Demo AI**.
3. Press **Start cleaning** and continue from 1:30. Normalization is fully local
   and the result is identical.
4. At review, **AI suggestion** still works through Offline Demo AI. If the
   online call times out, the response shows a warning and fills the grounded
   offline advice.
5. If even that advice is empty, the fields remain editable; enter the value
   manually and Confirm.

A wrong key is never stored. The AI path is advisory and bounded; it can never
block cleaning, confirmation, Complete cleaning or download.

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
| AI Connect success | Model name + latency shown within 3 s |
| AI Connect failure | Yellow Offline Demo AI notice; cleanup still starts |
| AI suggestion | Fields filled, confidence/reason shown, no auto-confirm |
| Human gate | 6 → 0 before Complete cleaning enables |
| Download lock | 409 / locked link until Complete cleaning |
| Download sheets | normalized / changes / unresolved |
| Download rows | 37 / ≥231 / 1 (including headers; all six confirmed) |
| Clicks from `/demo` to download | 18 (limit 22) |
| Whole flow | under 4 minutes 30 seconds |
| Language default | English on a fresh browser; 中文 is opt-in |
| Language switch | EN / 中文 swaps labels and survives reload |

Pytest proof:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
# 321 passed, 11 subtests passed
```
