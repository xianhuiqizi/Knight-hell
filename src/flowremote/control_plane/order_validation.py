"""Deterministic rules for uploaded orders. No demo registry or AI guesses."""

import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flowremote.control_plane.db import new_id, utc_now

FIELDS = (
    "order_id",
    "customer_name",
    "customer_id",
    "quantity",
    "unit_price",
    "amount",
    "order_date",
)
ALIASES = {
    "order_id": ("orderid", "orderno", "ordernumber", "订单号", "订单编号"),
    "customer_name": ("customername", "客户名称", "客户姓名", "客户名"),
    "customer_id": ("customerid", "客户编号", "客户id", "客户号"),
    "quantity": ("quantity", "qty", "数量", "订单数量"),
    "unit_price": ("unitprice", "单价"),
    "amount": ("amount", "totalamount", "金额", "总金额", "订单金额"),
    "order_date": ("orderdate", "订单日期", "下单日期", "日期"),
}
RULE_VERSION = "orders-v1"


class ValidationError(ValueError):
    pass


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def header_mapping(header):
    lookup = {alias: field for field, aliases in ALIASES.items() for alias in aliases}
    mapping = {}
    for index, value in enumerate(header):
        key = re.sub(r"[\s_\-]+", "", text_value(value)).lower()
        field = lookup.get(key)
        if field:
            if field in mapping:
                raise ValidationError(f"Duplicate column for {field}. Keep one column per field.")
            mapping[field] = index
    missing = [field for field in FIELDS if field not in mapping]
    if missing:
        raise ValidationError(
            "Missing required columns: "
            + ", ".join(missing)
            + ". Use the order template; the first non-empty row must be headers."
        )
    return mapping


def validate_order(raw, id_counts):
    """Return all issues, normalized storage values, and an optional arithmetic fix."""
    values = {field: text_value(raw.get(field)) for field in FIELDS}
    issues = []
    normalized = dict(values)

    def issue(field, code, message):
        issues.append({"field": field, "code": code, "message": message})

    for field, value in values.items():
        if not value:
            issue(field, "missing_value", f"{field}: required value is missing.")
        elif value.startswith("="):
            issue(
                field,
                "formula",
                f"{field}: formulas are not evaluated; paste the calculated value.",
            )
        elif len(value) > 500:
            issue(field, "value_too_long", f"{field}: use at most 500 characters.")
    invalid = {item["field"] for item in issues}
    order_id = values["order_id"]
    if "order_id" not in invalid and id_counts.get(order_id, 0) > 1:
        issue(
            "order_id", "duplicate_order_id", "order_id: duplicate ID within this uploaded batch."
        )

    numbers = {}
    for field in ("quantity", "unit_price", "amount"):
        normalized[field] = None
        if field in invalid:
            continue
        try:
            number = Decimal(values[field])
            if not number.is_finite() or abs(number) > Decimal(1000000000000):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            issue(
                field,
                "invalid_number",
                f"{field}: enter a finite number no larger than 1 trillion.",
            )
            continue
        if field == "quantity":
            if number <= 0 or number != number.to_integral_value() or number > 1_000_000_000:
                issue(
                    field,
                    "invalid_quantity",
                    "quantity: enter a positive whole number up to 1 billion.",
                )
                continue
            normalized[field] = int(number)
        else:
            if number < 0 or number != number.quantize(Decimal("0.01")):
                issue(
                    field,
                    "invalid_money",
                    f"{field}: use a non-negative amount with at most 2 decimal places.",
                )
                continue
            normalized[field] = float(number)
        numbers[field] = number

    suggestion = None
    if "quantity" in numbers and "unit_price" in numbers:
        expected = numbers["quantity"] * numbers["unit_price"]
        if "amount" in numbers and numbers["amount"] != expected:
            issue(
                "amount",
                "amount_mismatch",
                f"amount: quantity × unit_price = {expected:.2f}, but the uploaded amount is {values['amount']}.",
            )

    normalized["order_date"] = None
    if "order_date" not in invalid:
        value = values["order_date"]
        try:
            if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value):
                parts = re.split(r"[-/]", value)
                parsed = date(*(int(part) for part in parts))
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", value):
                parsed = datetime.fromisoformat(value).date()
            else:
                raise ValueError
            normalized["order_date"] = parsed.isoformat()
        except ValueError:
            issue(
                "order_date",
                "invalid_date",
                "order_date: use a real Excel date or YYYY-MM-DD / YYYY/MM/DD.",
            )
    if (
        issues
        and {item["field"] for item in issues} == {"amount"}
        and "quantity" in numbers
        and "unit_price" in numbers
        and expected <= Decimal(1000000000000)
    ):
        suggestion = f"{expected:.2f}"
    return issues, normalized, suggestion


def analyse_rows(header, rows):
    mapping = header_mapping(header)
    orders = []
    for excel_row, cells in rows:
        raw = {
            field: text_value(cells[index]) if index < len(cells) else ""
            for field, index in mapping.items()
        }
        orders.append((excel_row, raw))
    counts = Counter(raw["order_id"] for _, raw in orders if raw["order_id"])
    results = []
    summary = Counter()
    for index, (excel_row, raw) in enumerate(orders, start=1):
        issues, normalized, suggestion = validate_order(raw, counts)
        summary.update(item["code"] for item in issues)
        results.append(
            {
                "record_id": f"ORD-{index:03d}",
                "excel_row": excel_row,
                "raw": raw,
                "issues": issues,
                "normalized": normalized,
                "suggestion": suggestion,
            }
        )
    return results, dict(summary)


def save_analysis(db, task_id, header_row, results, summary):
    """Caller owns the transaction: all rows and task status commit together."""
    now = utc_now()
    for result in results:
        record_id, raw = result["record_id"], result["raw"]
        values, issues = result["normalized"], result["issues"]
        db.execute(
            "INSERT INTO source_records (task_id, record_id, customer_name, customer_id, quantity,"
            " unit_price, amount, order_date, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                record_id,
                values["customer_name"],
                values["customer_id"],
                values["quantity"],
                values["unit_price"],
                values["amount"],
                values["order_date"],
                "flagged" if issues else "passed",
            ),
        )
        encoded = json.dumps(raw, ensure_ascii=False)
        db.execute(
            "INSERT INTO order_inputs (task_id, record_id, excel_row, order_id, original_json, current_json, issues_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                record_id,
                result["excel_row"],
                raw["order_id"],
                encoded,
                encoded,
                json.dumps(issues, ensure_ascii=False),
            ),
        )
        if issues:
            fields = list(dict.fromkeys(item["field"] for item in issues))
            original = json.dumps({field: raw[field] for field in fields}, ensure_ascii=False)
            db.execute(
                "INSERT INTO exceptions (id, task_id, record_id, issue, flagged_fields, original_value,"
                " suggestion, confidence, reason, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 'unresolved', ?)",
                (
                    new_id("EXC"),
                    task_id,
                    record_id,
                    "; ".join(dict.fromkeys(i["code"] for i in issues)),
                    ", ".join(fields),
                    original,
                    result["suggestion"],
                    "\n".join(item["message"] for item in issues),
                    now,
                ),
            )
    db.execute(
        "INSERT INTO task_validations (task_id, header_row, rule_version, summary_json, validated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (task_id, header_row, RULE_VERSION, json.dumps(summary), now),
    )
    db.execute(
        "UPDATE tasks SET status = 'review_required', batch_size = ?, updated_at = ? WHERE id = ?",
        (len(results), now, task_id),
    )


def apply_correction(db, task_id, record_id, changes):
    """Recheck every field and batch uniqueness before resolving a real order."""
    row = db.query(
        "SELECT current_json FROM order_inputs WHERE task_id = ? AND record_id = ?",
        (task_id, record_id),
    )[0]
    raw = json.loads(row["current_json"])
    raw.update({field: text_value(value) for field, value in changes.items() if field in FIELDS})
    others = db.query(
        "SELECT i.order_id FROM order_inputs i LEFT JOIN exceptions e"
        " ON e.task_id = i.task_id AND e.record_id = i.record_id"
        " WHERE i.task_id = ? AND i.record_id <> ? AND (e.status IS NULL OR e.status <> 'skipped')",
        (task_id, record_id),
    )
    counts = Counter(item["order_id"] for item in others)
    counts[raw["order_id"]] += 1
    issues, values, _ = validate_order(raw, counts)
    if issues:
        raise ValidationError(" ".join(item["message"] for item in issues))
    db.execute(
        "UPDATE order_inputs SET current_json = ?, order_id = ? WHERE task_id = ? AND record_id = ?",
        (json.dumps(raw, ensure_ascii=False), raw["order_id"], task_id, record_id),
    )
    db.execute(
        "UPDATE source_records SET customer_name = ?, customer_id = ?, quantity = ?, unit_price = ?,"
        " amount = ?, order_date = ? WHERE task_id = ? AND record_id = ?",
        (
            values["customer_name"],
            values["customer_id"],
            values["quantity"],
            values["unit_price"],
            values["amount"],
            values["order_date"],
            task_id,
            record_id,
        ),
    )
