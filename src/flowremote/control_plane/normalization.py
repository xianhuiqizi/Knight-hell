"""Deterministic multi-source detection, mapping and normalization.

The layer is deliberately rule-first: a human can explain every value. AI is a
future fallback for fields the rules cannot map, not a dependency of this
module. Nothing here writes to the database, so the rules can be tested with
plain Python.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import PurePath
from typing import Any
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

from flowremote.contracts.normalization import (
    ALIASES,
    BOX_TO_PIECE,
    MAPPED_FIELDS,
    MAX_COLUMNS,
    MAX_HEADER_ROW,
    MAX_ROWS_PER_FILE,
    PRICE_THOUSAND_TOKENS,
    REQUIRED_FIELDS,
    UNIT_ALIASES,
    ColumnMapping,
    DetectedTable,
    MappingResult,
    NormalizedSourceRow,
)

DATE_FORMATS = ("iso", "day-first", "month-first", "excel-serial")
NUMERIC_FIELDS = {"quantity", "unit_price", "amount"}
MONEY_TOLERANCE = Decimal("0.005")


class NormalizationError(ValueError):
    """A source file or one of its columns cannot be normalized safely."""


def header_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            lookup[header_key(alias)] = field
    return lookup


ALIAS_LOOKUP = _alias_lookup()


def _header_matches(row: Sequence[Any]) -> dict[str, int]:
    matches: dict[str, int] = {}
    for index, value in enumerate(row):
        field = ALIAS_LOOKUP.get(header_key(value))
        if field and field not in matches:
            matches[field] = index
    return matches


def _score_header(row: Sequence[Any]) -> tuple[int, int]:
    matches = _header_matches(row)
    # A title row may contain "order" but not a full set of columns. Prefer the
    # row that maps the most fields and includes the record identifier.
    return len(matches), 1 if "order_id" in matches else 0


def _find_header(
    rows: Sequence[tuple[int, Sequence[Any]]],
) -> tuple[int, tuple[Any, ...], int]:
    best: tuple[tuple[int, int], int, tuple[Any, ...], int] | None = None
    for position, (physical_row, cells) in enumerate(rows):
        if physical_row > MAX_HEADER_ROW:
            break
        if not any(display_text(value) for value in cells):
            continue
        score = _score_header(cells)
        if score[0] < 3:
            continue
        candidate = (score, -physical_row, tuple(cells), position)
        if best is None or candidate[0] > best[0] or (
            candidate[0] == best[0] and candidate[1] > best[1]
        ):
            best = candidate
    if best is None:
        raise NormalizationError(
            "No header row with at least three recognizable order columns was found "
            "in the first 1,000 rows."
        )
    _, negative_row, header, position = best
    return -negative_row, header, position


def _rows_after_header(
    rows: Sequence[tuple[int, Sequence[Any]]],
    header_position: int,
) -> tuple[tuple[tuple[Any, ...], ...], tuple[int, ...]]:
    data: list[tuple[Any, ...]] = []
    numbers: list[int] = []
    for physical_row, cells in rows[header_position + 1 :]:
        if len(cells) > MAX_COLUMNS:
            raise NormalizationError(f"Use at most {MAX_COLUMNS} columns.")
        if not any(display_text(value) for value in cells):
            continue
        if len(data) >= MAX_ROWS_PER_FILE:
            raise NormalizationError(
                f"Use at most {MAX_ROWS_PER_FILE:,} non-empty data rows per file."
            )
        width = max(len(cells), 1)
        data.append(tuple(cells) + (None,) * max(0, width - len(cells)))
        numbers.append(physical_row)
    if not data:
        raise NormalizationError("The detected table has no data rows below its headers.")
    return tuple(data), tuple(numbers)


def _scan_xlsx(data: bytes) -> DetectedTable:
    try:
        with ZipFile(BytesIO(data)) as archive:
            if (
                len(archive.infolist()) > 1000
                or sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024
            ):
                raise NormalizationError("The expanded workbook is too large to inspect.")
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except NormalizationError:
        raise
    except (BadZipFile, OSError, ValueError) as exc:
        raise NormalizationError(
            "This file is not a readable .xlsx workbook. Re-save it as .xlsx or CSV."
        ) from exc
    try:
        best: DetectedTable | None = None
        best_score: tuple[int, int, int] = (0, 0, 0)
        for sheet in workbook.worksheets:
            sheet.reset_dimensions()
            scanned: list[tuple[int, Sequence[Any]]] = []
            try:
                for index, cells in enumerate(sheet.iter_rows(values_only=True), start=1):
                    if len(cells) > MAX_COLUMNS:
                        raise NormalizationError(f"Use at most {MAX_COLUMNS} columns.")
                    if any(display_text(value) for value in cells):
                        scanned.append((index, cells))
                    if index > MAX_HEADER_ROW + MAX_ROWS_PER_FILE + 1:
                        raise NormalizationError(
                            f"Use at most {MAX_ROWS_PER_FILE:,} non-empty data rows per file."
                        )
                if not scanned:
                    continue
                header_row, header, position = _find_header(scanned)
                rows, row_numbers = _rows_after_header(scanned, position)
            except NormalizationError:
                continue
            candidate = DetectedTable(
                file_type="xlsx",
                worksheet=sheet.title,
                header_row=header_row,
                headers=tuple(display_text(value) for value in header),
                rows=rows,
                row_numbers=row_numbers,
                header_index=position,
            )
            score = (_score_header(header), candidate.row_count, -candidate.header_row)
            if best is None or score > best_score:
                best = candidate
                best_score = score
        if best is None:
            raise NormalizationError(
                "No worksheet contains a recognizable order table (headers plus data)."
            )
        return best
    finally:
        workbook.close()


def _decode_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise NormalizationError("The CSV text encoding is not supported. Use UTF-8 CSV.")


def _detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample.splitlines() else ""
        return max((",", ";", "\t", "|"), key=first.count)


def _scan_csv(data: bytes) -> DetectedTable:
    text, _encoding = _decode_csv(data)
    delimiter = _detect_delimiter(text)
    scanned: list[tuple[int, Sequence[Any]]] = []
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    for index, cells in enumerate(reader, start=1):
        if len(cells) > MAX_COLUMNS:
            raise NormalizationError(f"Use at most {MAX_COLUMNS} columns.")
        if any(display_text(value) for value in cells):
            scanned.append((index, tuple(cells)))
        if index > MAX_HEADER_ROW + MAX_ROWS_PER_FILE + 1:
            raise NormalizationError(
                f"Use at most {MAX_ROWS_PER_FILE:,} non-empty data rows per file."
            )
    if not scanned:
        raise NormalizationError("The CSV file is empty.")
    header_row, header, position = _find_header(scanned)
    rows, row_numbers = _rows_after_header(scanned, position)
    return DetectedTable(
        file_type="csv",
        worksheet="CSV",
        header_row=header_row,
        headers=tuple(display_text(value) for value in header),
        rows=rows,
        row_numbers=row_numbers,
        header_index=position,
        delimiter=delimiter,
    )


def detect_table(filename: str, data: bytes) -> DetectedTable:
    """Locate the best table without trusting the first worksheet or row."""
    suffix = PurePath(str(filename or "")).suffix.lower()
    if not data:
        raise NormalizationError("The file is empty.")
    if suffix == ".csv":
        return _scan_csv(data)
    if suffix == ".xlsx":
        return _scan_xlsx(data)
    raise NormalizationError("Only .xlsx and .csv source files are accepted.")


def _price_multiplier(headers: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    for header in headers:
        key = header_key(header)
        lower = unicodedata.normalize("NFKC", str(header)).lower().replace(" ", "")
        if any(token in lower for token in ("千元", "thousand", "'000")):
            return 1000, (f"detected thousand-CNY unit in header: {header}",)
        if "cny" in lower and "000" in key:
            return 1000, (f"detected thousand-CNY unit in header: {header}",)
        if any(header_key(token) in key for token in PRICE_THOUSAND_TOKENS):
            return 1000, (f"detected thousand-CNY unit in header: {header}",)
    return 1, ()


def _sample_values(detected: DetectedTable, index: int, limit: int = 80) -> list[str]:
    values = []
    for row in detected.rows[:limit]:
        if index < len(row):
            text = display_text(row[index])
            if text:
                values.append(text)
    return values


def _numeric_column(detected: DetectedTable, index: int) -> bool:
    values = _sample_values(detected, index)
    if not values:
        return False
    parsed = 0
    for value in values:
        try:
            parse_number(value)
            parsed += 1
        except ValueError:
            pass
    return parsed >= max(1, int(len(values) * 0.8))


def _date_like_column(detected: DetectedTable, index: int) -> bool:
    values = _sample_values(detected, index)
    if not values:
        return False
    dates = 0
    for value in values:
        try:
            parse_date(value)
            dates += 1
        except ValueError:
            pass
    return dates >= max(1, int(len(values) * 0.8))


def _unit_like_column(detected: DetectedTable, index: int) -> bool:
    values = _sample_values(detected, index)
    if not values:
        return False
    recognized = sum(1 for value in values if canonical_unit(value) is not None)
    return recognized >= max(1, int(len(values) * 0.8))


def _infer_columns(
    detected: DetectedTable,
    mapped_fields: set[str],
) -> list[ColumnMapping]:
    """Type/distribution fallback for fields the synonym table did not find."""
    inferred: list[ColumnMapping] = []
    used = {
        index
        for field in mapped_fields
        for index in [next(
            (i for i, header in enumerate(detected.headers)
             if ALIAS_LOOKUP.get(header_key(header)) == field),
            -1,
        )]
        if index >= 0
    }
    candidates = [index for index in range(len(detected.headers)) if index not in used]

    # Dates are easiest and safest to identify from their distribution.
    if "order_date" not in mapped_fields:
        for index in candidates:
            if _date_like_column(detected, index):
                inferred.append(
                    ColumnMapping(
                        field="order_date",
                        index=index,
                        header=detected.headers[index],
                        confidence=0.82,
                        method="distribution",
                        evidence=(
                            "at least 80% of sampled values parse as dates",
                            f"column {index + 1}",
                        ),
                    )
                )
                mapped_fields.add("order_date")
                candidates.remove(index)
                break

    if "unit" not in mapped_fields:
        for index in candidates:
            if _unit_like_column(detected, index):
                inferred.append(
                    ColumnMapping(
                        field="unit",
                        index=index,
                        header=detected.headers[index],
                        confidence=0.78,
                        method="distribution",
                        evidence=("sampled values use known packaging units",),
                    )
                )
                mapped_fields.add("unit")
                candidates.remove(index)
                break

    # Numeric quantity is normally a small positive integer. Use the header's
    # distribution rather than a single value.
    if "quantity" not in mapped_fields:
        for index in candidates:
            values = _sample_values(detected, index)
            if not values:
                continue
            integers = 0
            for value in values:
                try:
                    number = parse_number(value)
                    if number > 0 and number == number.to_integral_value():
                        integers += 1
                except ValueError:
                    pass
            if integers >= max(1, int(len(values) * 0.8)):
                inferred.append(
                    ColumnMapping(
                        field="quantity",
                        index=index,
                        header=detected.headers[index],
                        confidence=0.7,
                        method="distribution",
                        evidence=("sampled values are positive whole numbers",),
                    )
                )
                mapped_fields.add("quantity")
                candidates.remove(index)
                break

    # Customer IDs look like codes; names are text that does not look like a
    # code. This only runs when the header aliases failed, so it stays cautious.
    if "customer_id" not in mapped_fields:
        for index in candidates:
            values = _sample_values(detected, index)
            if values and sum(_looks_like_id(value) for value in values) >= len(values) * 0.7:
                inferred.append(
                    ColumnMapping(
                        field="customer_id",
                        index=index,
                        header=detected.headers[index],
                        confidence=0.68,
                        method="distribution",
                        evidence=("sampled values look like customer codes",),
                    )
                )
                mapped_fields.add("customer_id")
                candidates.remove(index)
                break
    return inferred


def _looks_like_id(value: str) -> bool:
    return bool(re.fullmatch(r"(?i)(?:[a-z]{1,4}[-_]?)?\d{3,}", value.strip()))


def _match_header(header: str) -> tuple[str | None, str, float, tuple[str, ...]]:
    key = header_key(header)
    if key in ALIAS_LOOKUP:
        return ALIAS_LOOKUP[key], "synonym", 0.99, (f'synonym table: "{header}" -> {ALIAS_LOOKUP[key]}',)
    # Compound headers such as "Unit Price (CNY '000)" or "总金额(元)".
    matches: list[tuple[int, str]] = []
    for alias, field in ALIAS_LOOKUP.items():
        if len(alias) < 4:
            continue
        if key.startswith(alias) or key.endswith(alias):
            matches.append((len(alias), field))
    if matches:
        length, field = max(matches)
        return (
            field,
            "synonym-prefix",
            min(0.95, 0.88 + length / 100),
            (f'compound header "{header}" contains a synonym for {field}',),
        )
    return None, "", 0.0, ()


def _detect_date_order(detected: DetectedTable, index: int) -> tuple[str, tuple[str, ...]]:
    values = _sample_values(detected, index)
    for value in values:
        parts = re.split(r"[-/.]", value.strip())
        if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
            if int(parts[0]) > 12:
                return "day-first", (
                    f"day-first dates inferred from {value}",
                    "numeric dates use DD/MM/YYYY",
                )
            if int(parts[1]) > 12:
                return "month-first", (
                    f"month-first dates inferred from {value}",
                    "numeric dates use MM/DD/YYYY",
                )
    return "day-first", ("ambiguous numeric dates default to day-first (DD/MM/YYYY)",)


def build_mapping(detected: DetectedTable) -> MappingResult:
    """Rule-first column mapping with confidence and explainable evidence."""
    if len(detected.headers) > MAX_COLUMNS:
        raise NormalizationError(f"Use at most {MAX_COLUMNS} columns.")
    columns: list[ColumnMapping] = []
    mapped_fields: set[str] = set()
    unmapped_headers: list[str] = []
    for index, header in enumerate(detected.headers):
        if not display_text(header):
            continue
        field, method, confidence, evidence = _match_header(header)
        if field is None or field in mapped_fields:
            unmapped_headers.append(display_text(header))
            continue
        if field not in MAPPED_FIELDS:
            continue
        columns.append(
            ColumnMapping(
                field=field,
                index=index,
                header=display_text(header),
                confidence=confidence,
                method=method,
                evidence=evidence,
            )
        )
        mapped_fields.add(field)

    columns.extend(_infer_columns(detected, mapped_fields))
    mapped_fields = {column.field for column in columns}

    missing = [field for field in REQUIRED_FIELDS if field not in mapped_fields]
    if missing:
        raise NormalizationError(
            "Could not map required column(s): "
            + ", ".join(missing)
            + ". Add clear headers or use the order template."
        )

    if "unit" not in mapped_fields:
        columns.append(
            ColumnMapping(
                field="unit",
                index=-1,
                header="(not supplied)",
                confidence=0.6,
                method="default",
                evidence=("no unit column found; records default to piece",),
            )
        )
        mapped_fields.add("unit")

    multiplier, price_evidence = _price_multiplier(detected.headers)
    date_order = "day-first"
    date_evidence: tuple[str, ...] = ()
    date_column = next((column for column in columns if column.field == "order_date"), None)
    if date_column is not None:
        date_order, date_evidence = _detect_date_order(detected, date_column.index)

    # Record date ambiguity as evidence on the date mapping so the UI can explain
    # why 01/09/2026 became 2026-09-01.
    if date_evidence:
        columns = [
            ColumnMapping(
                field=column.field,
                index=column.index,
                header=column.header,
                confidence=column.confidence,
                method=column.method,
                evidence=tuple(column.evidence) + date_evidence,
            )
            if column.field == "order_date"
            else column
            for column in columns
        ]

    if multiplier != 1 and "unit_price" in mapped_fields:
        columns = [
            ColumnMapping(
                field=column.field,
                index=column.index,
                header=column.header,
                confidence=column.confidence,
                method=column.method,
                evidence=tuple(column.evidence) + price_evidence,
            )
            if column.field == "unit_price"
            else column
            for column in columns
        ]

    return MappingResult(
        columns=tuple(sorted(columns, key=lambda column: MAPPED_FIELDS.index(column.field))),
        price_multiplier=multiplier,
        price_evidence=price_evidence,
        unmapped_headers=tuple(unmapped_headers),
        date_order=date_order,
    )


def parse_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")  # noqa: TRY004
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = display_text(value)
        if not text or text.startswith("="):
            raise ValueError("empty or formula")
        text = re.sub(r"(?i)(cny|rmb|usd|eur|元|¥|￥|\$)", "", text)
        text = text.replace(",", "").replace("，", "").replace(" ", "")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"not a number: {value!r}") from exc
    if not number.is_finite() or abs(number) > Decimal(1000000000000):
        raise ValueError("number is outside the accepted range")
    return number


def canonical_unit(value: Any) -> str | None:
    key = unicodedata.normalize("NFKC", display_text(value)).strip().lower()
    return UNIT_ALIASES.get(key)


def parse_date(value: Any, order: str = "day-first") -> tuple[str, str]:
    """Return ISO date and the format evidence key."""
    if isinstance(value, datetime):
        return value.date().isoformat(), "datetime"
    if isinstance(value, date):
        return value.isoformat(), "date"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        serial = int(value)
        if 1 <= serial <= 100000:
            parsed = date(1899, 12, 30) + timedelta(days=serial)
            return parsed.isoformat(), "excel-serial"
        raise ValueError("not an Excel serial date")
    text = display_text(value)
    if not text:
        raise ValueError("empty date")
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        return date(*(int(part) for part in text.split("-"))).isoformat(), "iso"
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
        parts = [int(part) for part in text.split("/")]
        return date(parts[0], parts[1], parts[2]).isoformat(), "iso-slash"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T].+", text):
        try:
            return datetime.fromisoformat(text).date().isoformat(), "iso-datetime"
        except ValueError:
            pass
    parts = re.split(r"[-/.]", text)
    if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
        first, second, year = int(parts[0]), int(parts[1]), int(parts[2])
        if first > 12 and second <= 12:
            day, month = first, second
            format_key = "day-first"
        elif second > 12 and first <= 12 or order == "month-first":
            month, day = first, second
            format_key = "month-first"
        else:
            day, month = first, second
            format_key = "day-first"
        return date(year, month, day).isoformat(), format_key
    if re.fullmatch(r"\d{5}(?:\.0+)?", text):
        serial = int(float(text))
        if 1 <= serial <= 100000:
            parsed = date(1899, 12, 30) + timedelta(days=serial)
            return parsed.isoformat(), "excel-serial"
    raise ValueError(f"unsupported date: {value!r}")


def _money(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _close(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= MONEY_TOLERANCE


def _change(
    field: str,
    original: Any,
    new: Any,
    reason: str,
    method: str = "rule",
) -> dict[str, Any]:
    return {
        "field": field,
        "original_value": display_text(original),
        "new_value": display_text(new),
        "reason": reason,
        "method": method,
    }


def _issue(
    issue_type: str,
    field: str,
    original: Any,
    reason: str,
    *,
    suggested_value: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "field": field,
        "original_value": display_text(original),
        "suggested_value": suggested_value,
        "confidence": confidence,
        "reason": reason,
    }


def normalize_table(
    detected: DetectedTable,
    mapping: MappingResult,
    *,
    source_file: str,
    source_file_id: str = "",
    file_ordinal: int = 0,
    customer_lookup: dict[str, str] | None = None,
) -> list[NormalizedSourceRow]:
    """Turn one detected table into provenance-aware source rows."""
    columns = mapping.by_field()
    records: list[NormalizedSourceRow] = []
    lookup = customer_lookup or {}

    for row_number, cells in zip(detected.row_numbers, detected.rows, strict=False):
        def raw(field: str, cells=cells) -> Any:
            column = columns.get(field)
            if column is None or column.index < 0 or column.index >= len(cells):
                return None
            return cells[column.index]

        changes: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        missing: list[str] = []

        order_id = display_text(raw("order_id"))
        if not order_id:
            order_id = f"UNKNOWN-{file_ordinal + 1}-{row_number}"
            missing.append("order_id")

        customer_name = display_text(raw("customer_name"))
        if not customer_name:
            missing.append("customer_name")

        customer_id = display_text(raw("customer_id"))
        if not customer_id:
            missing.append("customer_id")

        quantity: int | None = None
        raw_quantity = raw("quantity")
        try:
            quantity_number = parse_number(raw_quantity)
            if quantity_number <= 0 or quantity_number != quantity_number.to_integral_value():
                raise ValueError("quantity must be a positive whole number")
            quantity = int(quantity_number)
        except ValueError:
            if display_text(raw_quantity):
                issues.append(
                    _issue(
                        "invalid_value",
                        "quantity",
                        raw_quantity,
                        "Quantity must be a positive whole number.",
                    )
                )
            else:
                missing.append("quantity")

        raw_unit = display_text(raw("unit"))
        unit = canonical_unit(raw_unit) or (raw_unit.lower() if raw_unit else "piece")
        if not raw_unit:
            unit = "piece"

        unit_price_decimal: Decimal | None = None
        raw_unit_price = raw("unit_price")
        try:
            unit_price_decimal = parse_number(raw_unit_price)
            if unit_price_decimal < 0:
                raise ValueError("unit price cannot be negative")
        except ValueError:
            unit_price_decimal = None
            if display_text(raw_unit_price):
                issues.append(
                    _issue(
                        "invalid_value",
                        "unit_price",
                        raw_unit_price,
                        "Unit price must be a non-negative number.",
                    )
                )
            else:
                missing.append("unit_price")

        amount_decimal: Decimal | None = None
        raw_amount = raw("amount")
        try:
            amount_decimal = parse_number(raw_amount)
            if amount_decimal < 0:
                raise ValueError("amount cannot be negative")
        except ValueError:
            amount_decimal = None
            if display_text(raw_amount):
                issues.append(
                    _issue(
                        "invalid_value",
                        "amount",
                        raw_amount,
                        "Amount must be a non-negative number.",
                    )
                )
            else:
                missing.append("amount")

        order_date: str | None = None
        raw_date = raw("order_date")
        try:
            order_date, date_format = parse_date(raw_date, mapping.date_order)
            if display_text(raw_date) != order_date:
                changes.append(
                    _change(
                        "order_date",
                        raw_date,
                        order_date,
                        f"Normalized {date_format} date to ISO YYYY-MM-DD.",
                    )
                )
        except ValueError:
            if display_text(raw_date):
                issues.append(
                    _issue(
                        "invalid_value",
                        "order_date",
                        raw_date,
                        "Date could not be parsed; use a real date.",
                    )
                )
            else:
                missing.append("order_date")

        # Price columns labelled in thousands need conversion before the total
        # check. If the total only works without conversion, keep the raw value
        # and ask a person rather than inventing a currency interpretation.
        if mapping.price_multiplier != 1 and unit_price_decimal is not None:
            converted_price = unit_price_decimal * mapping.price_multiplier
            if quantity is not None and amount_decimal is not None:
                if _close(amount_decimal, quantity * converted_price):
                    changes.append(
                        _change(
                            "unit_price",
                            raw_unit_price,
                            converted_price,
                            "Price column is in thousand CNY; multiplied by 1,000.",
                        )
                    )
                    unit_price_decimal = converted_price
                elif _close(amount_decimal, quantity * unit_price_decimal):
                    issues.append(
                        _issue(
                            "unit_conflict",
                            "unit_price",
                            raw_unit_price,
                            "Price column is labelled in thousand CNY, but the amount "
                            "matches the raw value as CNY. Confirm the currency unit.",
                            suggested_value=f"{_money(unit_price_decimal):.2f} CNY",
                            confidence=0.9,
                        )
                    )
                else:
                    unit_price_decimal = converted_price
                    changes.append(
                        _change(
                            "unit_price",
                            raw_unit_price,
                            converted_price,
                            "Price column is in thousand CNY; multiplied by 1,000.",
                        )
                    )
            else:
                unit_price_decimal = converted_price
                changes.append(
                    _change(
                        "unit_price",
                        raw_unit_price,
                        converted_price,
                        "Price column is in thousand CNY; multiplied by 1,000.",
                    )
                )

        # Boxes are converted to pieces. The amount is preserved by adjusting
        # both quantity (×12) and unit price (÷12). If the amount only matches
        # quantity × 12 × price, the source has mixed up boxes and pieces; keep
        # it and ask for confirmation.
        if unit == "box" and quantity is not None and unit_price_decimal is not None:
            if amount_decimal is not None and _close(amount_decimal, quantity * unit_price_decimal):
                new_quantity = quantity * BOX_TO_PIECE
                new_price = unit_price_decimal / BOX_TO_PIECE
                changes.extend(
                    [
                        _change(
                            "quantity",
                            raw_quantity,
                            new_quantity,
                            "Converted boxes to pieces (1 box = 12 pieces).",
                        ),
                        _change(
                            "unit",
                            raw_unit,
                            "piece",
                            "Converted packaging unit from box to piece.",
                        ),
                        _change(
                            "unit_price",
                            raw_unit_price,
                            new_price,
                            "Converted price from per box to per piece (1 box = 12 pieces).",
                        ),
                    ]
                )
                quantity = new_quantity
                unit = "piece"
                unit_price_decimal = new_price
            elif amount_decimal is not None and _close(
                amount_decimal, quantity * BOX_TO_PIECE * unit_price_decimal
            ):
                issues.append(
                    _issue(
                        "unit_conflict",
                        "unit",
                        raw_unit,
                        "The unit says box, but the amount equals quantity × 12 × price. "
                        "Confirm whether the quantity is already in pieces.",
                        suggested_value=(
                            f"{quantity * BOX_TO_PIECE} piece @ "
                            f"{_money(unit_price_decimal):.2f}"
                        ),
                        confidence=0.88,
                    )
                )

        if quantity is not None and unit_price_decimal is not None and amount_decimal is None:
            amount_decimal = quantity * unit_price_decimal
            if display_text(raw_amount):
                changes.append(
                    _change(
                        "amount",
                        raw_amount,
                        amount_decimal,
                        "Recalculated amount as quantity × unit price.",
                    )
                )
        if (
            quantity is not None
            and unit_price_decimal is not None
            and amount_decimal is not None
            and not any(issue["issue_type"] == "unit_conflict" for issue in issues)
            and not _close(amount_decimal, quantity * unit_price_decimal)
        ):
            issues.append(
                _issue(
                    "amount_mismatch",
                    "amount",
                    raw_amount,
                    "Amount does not equal quantity × unit price.",
                    suggested_value=f"{_money(quantity * unit_price_decimal):.2f}",
                    confidence=0.97,
                )
            )

        if missing:
            fields = ", ".join(missing)
            suggestion = None
            confidence = None
            if missing == ["customer_id"] and customer_name in lookup:
                suggestion = lookup[customer_name]
                confidence = 0.95
            issues.append(
                _issue(
                    "missing_value",
                    fields,
                    "(blank)",
                    "Required value missing from the source row: " + fields + ".",
                    suggested_value=(
                        f"{suggestion} (customer registry unique match)" if suggestion else None
                    ),
                    confidence=confidence,
                )
            )

        records.append(
            NormalizedSourceRow(
                order_id=order_id,
                customer_name=customer_name,
                customer_id=customer_id,
                quantity=quantity,
                unit=unit,
                unit_price=_money(unit_price_decimal),
                amount=_money(amount_decimal),
                order_date=order_date,
                source_file=source_file,
                source_row=row_number,
                source_file_id=source_file_id,
                file_ordinal=file_ordinal,
                changes=tuple(changes),
                issues=tuple(issues),
            )
        )
    return records


def _same_value(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 0.005
    return str(left).strip() == str(right).strip()


def merge_records(
    records: Iterable[NormalizedSourceRow],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge identical order IDs and surface every divergent duplicate.

    The first source row (file order, then spreadsheet row) wins provisionally;
    it is never presented as verified. Each conflict becomes an unresolved issue
    with both source references, so a human decides later.
    """
    ordered = sorted(records, key=lambda row: (row.file_ordinal, row.source_row))
    groups: dict[str, list[NormalizedSourceRow]] = {}
    for row in ordered:
        groups.setdefault(row.order_id, []).append(row)

    merged: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for order_id, group in groups.items():
        primary = group[0]
        duplicate_count = len(group)
        conflict_fields: list[str] = []
        conflict_details: list[str] = []
        for other in group[1:]:
            left = primary.comparison_values()
            right = other.comparison_values()
            differing = [
                field for field in left if not _same_value(left[field], right[field])
            ]
            if differing:
                conflict_fields.extend(field for field in differing if field not in conflict_fields)
                conflict_details.append(
                    f"{other.source_file} row {other.source_row}: "
                    + ", ".join(f"{field}={right[field]!r}" for field in differing)
                )
        sources = [
            {
                "file": row.source_file,
                "row": row.source_row,
                "source_file_id": row.source_file_id,
            }
            for row in group
        ]
        if conflict_fields:
            issues.append(
                {
                    "issue_type": "cross_file_conflict",
                    "field": ", ".join(conflict_fields),
                    "order_id": order_id,
                    "source_file": primary.source_file,
                    "source_row": primary.source_row,
                    "original_value": "; ".join(conflict_details),
                    "suggested_value": None,
                    "confidence": None,
                    "reason": (
                        f"Order {order_id} appears {duplicate_count} times with different "
                        f"normalized values in {', '.join(conflict_fields)}. The first record "
                        "is shown; nothing was silently overwritten."
                    ),
                }
            )

        merged.append(
            {
                **primary.values(),
                "duplicate_count": duplicate_count,
                "has_conflict": bool(conflict_fields),
                "source_refs": sources,
                "issue_count": sum(len(row.issues) for row in group)
                + (1 if conflict_fields else 0),
            }
        )
    return merged, issues


def _flatten_row_issues(rows: Sequence[NormalizedSourceRow]) -> list[dict[str, Any]]:
    issues = []
    for row in rows:
        for issue in row.issues:
            issues.append(
                {
                    **issue,
                    "order_id": row.order_id,
                    "source_file": row.source_file,
                    "source_row": row.source_row,
                }
            )
    return issues


def run_full_normalization(
    sources: Sequence[tuple[str, bytes]],
    *,
    customer_lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Pure end-to-end run used by tests, seed verification and idempotency checks.

    ``sources`` is an ordered list of ``(filename, bytes)``. The result is
    deterministic for the same input order and content.
    """
    fingerprint = hashlib.sha256()
    files: list[dict[str, Any]] = []
    all_rows: list[NormalizedSourceRow] = []
    errors: list[dict[str, Any]] = []
    for ordinal, (filename, data) in enumerate(sources):
        fingerprint.update(filename.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(hashlib.sha256(data).digest())
        file_id = f"SRC-{ordinal + 1:03d}"
        entry: dict[str, Any] = {
            "file_id": file_id,
            "filename": filename,
            "byte_size": len(data),
            "file_type": PurePath(filename).suffix.lower().lstrip("."),
            "worksheet": "",
            "header_row": None,
            "row_count": 0,
            "field_count": 0,
            "detected_columns": 0,
            "mapping": {},
            "error": None,
            "status": "uploaded",
        }
        try:
            detected = detect_table(filename, data)
            mapping = build_mapping(detected)
            rows = normalize_table(
                detected,
                mapping,
                source_file=filename,
                source_file_id=file_id,
                file_ordinal=ordinal,
                customer_lookup=customer_lookup,
            )
        except NormalizationError as exc:
            entry.update(
                status="attention",
                error=str(exc),
                issue=(
                    "This file could not be normalized: " + str(exc) + " "
                    "The other files were processed normally."
                ),
            )
            errors.append(
                {
                    "issue_type": "file_error",
                    "field": "",
                    "order_id": "",
                    "source_file": filename,
                    "source_row": None,
                    "original_value": "",
                    "suggested_value": None,
                    "confidence": None,
                    "reason": str(exc),
                }
            )
            files.append(entry)
            continue
        entry.update(
            worksheet=detected.worksheet,
            header_row=detected.header_row,
            row_count=detected.row_count,
            field_count=mapping.field_count,
            detected_columns=len(detected.headers),
            mapping=mapping.as_dict(),
            status="normalized",
        )
        files.append(entry)
        all_rows.extend(rows)
    merged, merge_issues = merge_records(all_rows)
    issues = _flatten_row_issues(all_rows) + merge_issues + errors
    # Missing issues are generated per source row; identical duplicates can
    # repeat them. De-duplicate by source location and issue content.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for issue in issues:
        key = (
            issue.get("source_file"),
            issue.get("source_row"),
            issue.get("issue_type"),
            issue.get("field"),
            issue.get("original_value"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    changes = [
        {
            **_change_item,
            "order_id": row.order_id,
            "source_file": row.source_file,
            "source_row": row.source_row,
        }
        for row in all_rows
        for _change_item in row.changes
    ]
    total_raw = sum(entry["row_count"] for entry in files)
    normalized_count = len(merged)
    return {
        "fingerprint": fingerprint.hexdigest(),
        "files": files,
        "records": merged,
        "changes": changes,
        "issues": deduped,
        "summary": {
            "files_total": len(sources),
            "files_ok": sum(1 for entry in files if entry["status"] == "normalized"),
            "raw_records": total_raw,
            "normalized_records": normalized_count,
            "auto_fixed": sum(1 for row in all_rows if row.changes),
            "changes": len(changes),
            "issues": len(deduped),
            "cross_file_conflicts": sum(
                1 for issue in deduped if issue["issue_type"] == "cross_file_conflict"
            ),
            "unit_conflicts": sum(
                1 for issue in deduped if issue["issue_type"] == "unit_conflict"
            ),
            "missing_values": sum(
                1 for issue in deduped if issue["issue_type"] == "missing_value"
            ),
            "file_errors": sum(
                1 for issue in deduped if issue["issue_type"] == "file_error"
            ),
        },
    }


def fingerprint_sources(sources: Sequence[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for filename, data in sources:
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
