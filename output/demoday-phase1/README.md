# Phase 1 evidence — live walkthrough

Captured on 2026-11-14 against the local build (v0.6.0), using the seeded Demo
Day account and the six files in `data/demoday/`.

| File | Shows |
| --- | --- |
| `00-demo-landing.jpg` | `/demo` entry; no registration needed |
| `01-upload-six-files.jpg` | Six files selected in one picker, 34.3 KB total |
| `02-ready-to-start.jpg` | 6/6 recognized before Start; sheet, header, rows, fields, Mapped status |
| `03-progress.jpg` | Normalizing records at 43%, current file, 3/6, elapsed |
| `04-summary.jpg` | 6 files / 174 rows / 36 records / 143 auto-fixed / 6 to confirm / 3.0 s |
| `05-six-confirmations.jpg` | The six issue cards (missing ×2, unit ×2, cross-file ×2) |
| `06-activity-timeline.jpg` | Upload → Detect → Map → Start → Normalize → Complete |
| `07-tablet-390.jpg` | Narrow-window responsive check |
| `FlowRemote_normalized_20261114_1642.xlsx` | Actual downloaded result: normalized / changes / unresolved |

The downloadable workbook was checked with `openpyxl`: sheet sizes are 37, 231
and 7 rows including headers. The six unresolved rows are: missing customer ID,
missing quantity, thousand-CNY unit conflict, box/piece unit conflict and two
cross-file conflicts.

This is phase-one evidence. The editable confirmation cards and the visible AI
connection test are not in these screenshots.
