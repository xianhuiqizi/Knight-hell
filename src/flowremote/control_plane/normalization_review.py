"""Human confirmation and AI advice for normalized data issues.

The rules here are the authority. AI advice is parsed, constrained and validated
before it can populate a review form, and a person still confirms or skips every
issue. Skipped records are removed from the normalized output and retained in
the unresolved export with the human reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from flowremote.contracts.models import User
from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import Database, new_id, utc_now
from flowremote.control_plane.normalization import canonical_unit, parse_date
from flowremote.control_plane.sync import touch_task

EDITABLE_FIELDS = (
    "customer_name",
    "customer_id",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "order_date",
)
FIELD_LABELS = {
    "customer_name": "Customer name",
    "customer_id": "Customer ID",
    "quantity": "Quantity",
    "unit": "Unit",
    "unit_price": "Unit price",
    "amount": "Amount",
    "order_date": "Order date",
}
MONEY_LIMIT = Decimal("1e12")
QUANTITY_LIMIT = 1_000_000_000
TOLERANCE = Decimal("0.005")


class ReviewError(ValueError):
    """A human decision or an AI candidate cannot be applied safely."""


@dataclass(frozen=True)
class ReviewOutcome:
    issue_id: str
    action: str
    status: str
    remaining: int
    confirmed: int
    skipped: int
    batch_status: str

    def as_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "action": self.action,
            "status": self.status,
            "remaining": self.remaining,
            "confirmed": self.confirmed,
            "skipped": self.skipped,
            "batch_status": self.batch_status,
        }


def _field_list(value: str | None) -> list[str]:
    fields = []
    for part in str(value or "").replace(",", " ").split():
        name = part.strip()
        if name in EDITABLE_FIELDS and name not in fields:
            fields.append(name)
    return fields


def editable_fields(issue: dict) -> list[str]:
    issue_type = issue["issue_type"]
    if issue_type == "file_error":
        return []
    if issue_type == "missing_value":
        return _field_list(issue.get("field")) or list(EDITABLE_FIELDS)
    if issue_type == "unit_conflict":
        return ["quantity", "unit", "unit_price", "amount"]
    if issue_type == "cross_file_conflict":
        fields = _field_list(issue.get("field"))
        if any(name in ("unit_price", "amount", "quantity") for name in fields):
            for name in ("quantity", "unit", "unit_price", "amount"):
                if name not in fields:
                    fields.append(name)
        if any(name in ("customer_id", "customer_name") for name in fields):
            for name in ("customer_name", "customer_id"):
                if name not in fields:
                    fields.append(name)
        if issue.get("field") and "order_date" in str(issue["field"]):
            fields.append("order_date")
        return fields or list(EDITABLE_FIELDS)
    if issue_type in ("amount_mismatch", "invalid_value"):
        fields = _field_list(issue.get("field"))
        if issue_type == "amount_mismatch":
            fields = ["quantity", "unit_price", "amount"]
        return fields or list(EDITABLE_FIELDS)
    return []


def _record_values(record: dict | None) -> dict[str, str]:
    if not record:
        return {name: "" for name in EDITABLE_FIELDS}
    result = {}
    for name in EDITABLE_FIELDS:
        value = record.get(name)
        result[name] = "" if value is None else str(value)
    return result


def issue_context(db: Database, task_id: str, issue_id: str) -> dict | None:
    rows = db.query(
        "SELECT i.*, b.task_id AS batch_task_id, b.status AS batch_status"
        " FROM normalization_issues i JOIN normalization_batches b ON b.id = i.batch_id"
        " WHERE i.id = ? AND b.task_id = ?",
        (issue_id, task_id),
    )
    if not rows:
        return None
    issue = dict(rows[0])
    record = None
    duplicates: list[dict] = []
    if issue.get("order_id"):
        record_rows = db.query(
            "SELECT * FROM normalized_records WHERE batch_id = ? AND order_id = ?"
            " AND is_primary = 1 ORDER BY id LIMIT 1",
            (issue["batch_id"], issue["order_id"]),
        )
        if record_rows:
            record = dict(record_rows[0])
        duplicates = [
            dict(row)
            for row in db.query(
                "SELECT r.*, f.ordinal FROM normalized_records r"
                " JOIN normalization_files f ON f.id = r.file_id"
                " WHERE r.batch_id = ? AND r.order_id = ? ORDER BY f.ordinal, r.source_row",
                (issue["batch_id"], issue["order_id"]),
            )
        ]
    return {
        "issue": issue,
        "record": record,
        "duplicates": duplicates,
        "current": _record_values(record),
        "allowed_fields": editable_fields(issue),
        "field_labels": FIELD_LABELS,
    }


def _unique_text(values: list[object]) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _other_unique_value(
    db: Database,
    *,
    batch_id: str,
    order_id: str,
    field: str,
    match_field: str,
    match_value: str,
) -> tuple[str | None, int]:
    if not match_value:
        return None, 0
    rows = db.query(
        f"SELECT DISTINCT {field} AS value FROM normalized_records"
        " WHERE batch_id = ? AND is_primary = 1 AND order_id <> ?"
        f" AND {match_field} = ? AND {field} IS NOT NULL AND {field} <> ''",
        (batch_id, order_id, match_value),
    )
    values = _unique_text([row["value"] for row in rows])
    return (values[0] if len(values) == 1 else None), len(values)


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _suggestion(
    fields: dict[str, str],
    *,
    confidence: float,
    reason: str,
    evidence: list[str] | None = None,
) -> dict:
    return {
        "fields": fields,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "reason": reason,
        "evidence": (evidence or [])[:10],
        "source": "offline",
        "source_label": "Offline Demo AI",
        "model": "grounded-rules-v1",
        "warning": None,
    }


def local_suggestion(db: Database, context: dict) -> dict:
    """Grounded, deterministic advice that never invents a customer."""
    issue = context["issue"]
    record = context["record"]
    current = context["current"]
    issue_type = issue["issue_type"]
    order_id = issue.get("order_id") or ""
    batch_id = issue["batch_id"]

    if issue_type == "file_error" or record is None:
        return _suggestion(
            {},
            confidence=0.0,
            reason="This item cannot be repaired in the current batch; skip it with a reason.",
            evidence=["file-level error"],
        )

    if issue_type == "missing_value":
        fields: dict[str, str] = {}
        reasons: list[str] = []
        confidence = 0.0
        evidence: list[str] = []
        missing = _field_list(issue.get("field")) or [
            name for name in EDITABLE_FIELDS if not current.get(name)
        ]
        for name in missing:
            if name in ("customer_id", "customer_name"):
                other_field = "customer_name" if name == "customer_id" else "customer_id"
                found, _ = _other_unique_value(
                    db,
                    batch_id=batch_id,
                    order_id=order_id,
                    field=name,
                    match_field=other_field,
                    match_value=current.get(other_field, ""),
                )
                if found:
                    fields[name] = found
                    confidence = max(confidence, 0.94)
                    reasons.append(f"One consistent match in other cleaned rows for {name}.")
                    evidence.append(f"unique match from batch: {found}")
            elif name == "quantity":
                amount = _decimal(current.get("amount"))
                price = _decimal(current.get("unit_price"))
                duplicate_values = _unique_text(
                    [row.get("quantity") for row in context["duplicates"] if row.get("quantity")]
                )
                if amount is not None and price is not None and price > 0:
                    calculated = amount / price
                    if (
                        calculated > 0
                        and calculated == calculated.to_integral_value()
                        and calculated <= QUANTITY_LIMIT
                    ):
                        fields[name] = str(int(calculated))
                        confidence = max(confidence, 0.92)
                        reasons.append("Quantity can be derived from amount ÷ unit price.")
                        evidence.append(f"{amount} ÷ {price} = {int(calculated)}")
                elif len(duplicate_values) == 1:
                    fields[name] = duplicate_values[0]
                    confidence = max(confidence, 0.8)
                    reasons.append("A duplicate source row supplies the quantity.")
            elif name == "unit":
                duplicate_values = _unique_text(
                    [row.get("unit") for row in context["duplicates"] if row.get("unit")]
                )
                fields[name] = duplicate_values[0] if len(duplicate_values) == 1 else "piece"
                confidence = max(confidence, 0.72)
                reasons.append("No conflicting unit remains; defaulting to piece.")
            elif name == "unit_price":
                amount = _decimal(current.get("amount"))
                quantity = _decimal(current.get("quantity"))
                if amount is not None and quantity and quantity > 0:
                    price = amount / quantity
                    if price >= 0 and price == price.quantize(Decimal("0.01")):
                        fields[name] = _money_text(price)
                        confidence = max(confidence, 0.85)
                        reasons.append("Unit price can be derived from amount ÷ quantity.")
            elif name == "amount":
                quantity = _decimal(current.get("quantity"))
                price = _decimal(current.get("unit_price"))
                if quantity is not None and price is not None:
                    fields[name] = _money_text(quantity * price)
                    confidence = max(confidence, 0.9)
                    reasons.append("Amount can be derived from quantity × unit price.")
        if not fields:
            return _suggestion(
                {},
                confidence=0.0,
                reason="No grounded value is available. Enter the missing field manually.",
                evidence=["no unique registry or arithmetic match"],
            )
        return _suggestion(
            fields,
            confidence=confidence,
            reason=" ".join(reasons),
            evidence=evidence,
        )

    if issue_type == "unit_conflict":
        quantity = _decimal(current.get("quantity"))
        price = _decimal(current.get("unit_price"))
        amount = _decimal(current.get("amount"))
        unit = str(current.get("unit") or "").lower()
        fields = {
            "quantity": current.get("quantity", ""),
            "unit": unit or "piece",
            "unit_price": current.get("unit_price", ""),
            "amount": current.get("amount", ""),
        }
        if (
            unit == "box"
            and quantity is not None
            and price is not None
            and amount is not None
            and abs(amount - quantity * 12 * price) <= TOLERANCE
        ):
            fields["quantity"] = str(int(quantity * 12))
            fields["unit"] = "piece"
            return _suggestion(
                fields,
                confidence=0.9,
                reason=(
                    "The amount equals quantity × 12 × price, so the quantity appears "
                    "to already be in pieces while the unit says box."
                ),
                evidence=["1 box = 12 pieces", "amount preserved"],
            )
        if (
            quantity is not None
            and price is not None
            and amount is not None
            and abs(amount - quantity * price) <= TOLERANCE
        ):
            return _suggestion(
                fields,
                confidence=0.82,
                reason=(
                    "The row is arithmetically consistent as CNY, so the header's "
                    "thousand-CNY label appears to be the error. Review and confirm "
                    "the current values if that interpretation is correct."
                ),
                evidence=["amount = quantity × unit price as shown"],
            )
        return _suggestion(
            fields,
            confidence=0.55,
            reason="The unit interpretation is ambiguous. Check the source and edit the values.",
            evidence=["amount does not match quantity × unit price"],
        )

    if issue_type == "cross_file_conflict":
        fields = {name: current.get(name, "") for name in context["allowed_fields"]}
        variants: dict[tuple, int] = {}
        for row in context["duplicates"]:
            key = tuple(str(row.get(name) or "") for name in context["allowed_fields"])
            variants[key] = variants.get(key, 0) + 1
        best_key = max(variants, key=lambda key: variants[key]) if variants else None
        if best_key and variants.get(best_key, 0) > 1:
            fields = dict(zip(context["allowed_fields"], best_key, strict=False))
            confidence = 0.72
            reason = "The most corroborated duplicate is shown. Confirm it or edit using the alternative values in the issue reason."
        else:
            confidence = 0.6
            reason = (
                "The duplicates are evenly split. The first source is provisionally shown; "
                "review the alternative values before confirming."
            )
        evidence = [
            f"{row.get('source_file')} row {row.get('source_row')}: "
            + ", ".join(f"{name}={row.get(name)!r}" for name in context["allowed_fields"])
            for row in context["duplicates"]
        ]
        return _suggestion(fields, confidence=confidence, reason=reason, evidence=evidence)

    if issue_type == "amount_mismatch":
        quantity = _decimal(current.get("quantity"))
        price = _decimal(current.get("unit_price"))
        if quantity is not None and price is not None:
            return _suggestion(
                {
                    "quantity": current.get("quantity", ""),
                    "unit_price": current.get("unit_price", ""),
                    "amount": _money_text(quantity * price),
                },
                confidence=0.98,
                reason="Amount is quantity × unit price.",
                evidence=[f"{quantity} × {price}"],
            )
        return _suggestion(
            {},
            confidence=0.0,
            reason="Quantity and unit price are needed before amount can be calculated.",
        )

    return _suggestion(
        {},
        confidence=0.0,
        reason="No grounded automatic correction is available; edit manually or skip.",
    )


def _required_text(value: object, name: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReviewError(f"{name} is required.")
    if len(text) > maximum:
        raise ReviewError(f"{name} must be at most {maximum} characters.")
    return text


def _money(value: object, name: str) -> float:
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ReviewError(f"{name} must be a number.") from exc
    if not number.is_finite() or number < 0 or number > MONEY_LIMIT:
        raise ReviewError(f"{name} must be between 0 and 1 trillion.")
    if number != number.quantize(Decimal("0.01")):
        raise ReviewError(f"{name} may have at most two decimal places.")
    return float(number.quantize(Decimal("0.01")))


def validate_issue_changes(context: dict, changes: dict[str, str]) -> tuple[dict, dict]:
    """Return normalized changed fields and the complete final record values."""
    issue = context["issue"]
    record = context["record"]
    if issue["issue_type"] == "file_error":
        raise ReviewError("A file-level error can only be skipped.")
    if record is None:
        raise ReviewError("The normalized record is missing.")
    unknown = set(changes) - set(context["allowed_fields"])
    if unknown:
        raise ReviewError(
            "These fields cannot be edited for this issue: " + ", ".join(sorted(unknown))
        )
    final = dict(context["current"])
    final.update(
        {name: str(changes.get(name, final.get(name, ""))) for name in context["allowed_fields"]}
    )
    cleaned: dict = {}
    cleaned["customer_name"] = _required_text(final.get("customer_name"), "Customer name", 200)
    cleaned["customer_id"] = _required_text(final.get("customer_id"), "Customer ID", 100)
    quantity_text = str(final.get("quantity") or "").strip()
    try:
        quantity = int(Decimal(quantity_text))
    except (InvalidOperation, ValueError) as exc:
        raise ReviewError("Quantity must be a whole number.") from exc
    if quantity <= 0 or quantity > QUANTITY_LIMIT:
        raise ReviewError("Quantity must be a positive whole number.")
    if Decimal(quantity_text) != Decimal(quantity):
        raise ReviewError("Quantity must be a whole number.")
    cleaned["quantity"] = quantity
    unit = canonical_unit(final.get("unit"))
    if unit is None:
        raise ReviewError("Unit must be piece, box or kg.")
    cleaned["unit"] = unit
    cleaned["unit_price"] = _money(final.get("unit_price"), "Unit price")
    cleaned["amount"] = _money(final.get("amount"), "Amount")
    date_text = str(final.get("order_date") or "").strip()
    try:
        parsed_date, _ = parse_date(date_text)
        date.fromisoformat(parsed_date)
    except (ValueError, TypeError) as exc:
        raise ReviewError("Order date must be a real date in ISO format.") from exc
    cleaned["order_date"] = parsed_date
    if (
        abs(
            Decimal(str(cleaned["amount"]))
            - Decimal(cleaned["quantity"]) * Decimal(str(cleaned["unit_price"]))
        )
        > TOLERANCE
    ):
        raise ReviewError(
            f"Amount must equal quantity × unit price "
            f"({cleaned['quantity']} × {cleaned['unit_price']:.2f} = "
            f"{cleaned['quantity'] * cleaned['unit_price']:.2f})."
        )
    updates = {}
    for name, value in cleaned.items():
        old = record.get(name)
        if isinstance(value, float):
            equal = old is not None and abs(float(old) - value) <= 0.005
        elif isinstance(value, int):
            equal = old is not None and int(old) == value
        else:
            equal = str(old or "") == str(value)
        if not equal:
            updates[name] = value
    return updates, cleaned


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def validate_suggestion_fields(context: dict, fields: dict[str, str]) -> dict[str, str]:
    """Validate model advice against the same rules as a manual confirmation."""
    allowed = set(context["allowed_fields"])
    filtered = {
        str(name): str(value).strip()
        for name, value in (fields or {}).items()
        if str(name) in allowed and str(value).strip()
    }
    if not filtered:
        return {}
    _, final = validate_issue_changes(context, filtered)
    return {name: _format_value(final[name]) for name in filtered}


def _save_ai_suggestion(
    db: Database,
    *,
    issue_id: str,
    suggestion: dict,
    now: str,
) -> None:
    db.execute(
        "UPDATE normalization_issues SET ai_suggestion_json = ?, ai_source = ?,"
        " ai_suggested_at = ? WHERE id = ?",
        (
            json.dumps(suggestion, ensure_ascii=False),
            suggestion.get("source_label") or suggestion.get("source") or "offline",
            now,
            issue_id,
        ),
    )


def save_suggestion(db: Database, *, issue_id: str, suggestion: dict) -> None:
    _save_ai_suggestion(db, issue_id=issue_id, suggestion=suggestion, now=utc_now())


def _refresh_counts(db: Database, batch_id: str, order_id: str | None = None) -> dict:
    unresolved = int(
        db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ? AND status = 'unresolved'",
            (batch_id,),
            0,
        )
        or 0
    )
    confirmed = int(
        db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ? AND status = 'resolved'",
            (batch_id,),
            0,
        )
        or 0
    )
    skipped = int(
        db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ? AND status = 'skipped'",
            (batch_id,),
            0,
        )
        or 0
    )
    primary = int(
        db.scalar(
            "SELECT COUNT(*) FROM normalized_records WHERE batch_id = ? AND is_primary = 1",
            (batch_id,),
            0,
        )
        or 0
    )
    db.execute(
        "UPDATE normalization_batches SET issue_count = ?, normalized_records = ? WHERE id = ?",
        (unresolved, primary, batch_id),
    )
    if order_id:
        per_order = int(
            db.scalar(
                "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
                " AND order_id = ? AND status = 'unresolved'",
                (batch_id, order_id),
                0,
            )
            or 0
        )
        db.execute(
            "UPDATE normalized_records SET issue_count = ? WHERE batch_id = ? AND order_id = ?",
            (per_order, batch_id, order_id),
        )
    return {
        "remaining": unresolved,
        "confirmed": confirmed,
        "skipped": skipped,
        "primary": primary,
    }


def _existing_decision(
    db: Database, decision_id: str, issue_id: str, task_id: str
) -> ReviewOutcome | None:
    rows = db.query(
        "SELECT d.issue_id, d.action, i.status, i.batch_id FROM normalization_decisions d"
        " JOIN normalization_issues i ON i.id = d.issue_id"
        " WHERE d.decision_id = ? AND d.task_id = ?",
        (decision_id, task_id),
    )
    if not rows:
        return None
    row = rows[0]
    if row["issue_id"] != issue_id:
        raise ReviewError("This decision ID belongs to another issue.")
    counts = _refresh_counts(db, row["batch_id"], None)
    batch_status = db.scalar(
        "SELECT status FROM normalization_batches WHERE id = ?", (row["batch_id"],), ""
    )
    return ReviewOutcome(
        issue_id=issue_id,
        action=row["action"],
        status=row["status"],
        remaining=counts["remaining"],
        confirmed=counts["confirmed"],
        skipped=counts["skipped"],
        batch_status=str(batch_status or ""),
    )


def _insert_decision(
    db: Database,
    *,
    batch_id: str,
    task_id: str,
    issue_id: str,
    decision_id: str,
    action: str,
    changes: dict,
    reason: str | None,
    user: User,
    now: str,
) -> None:
    db.execute(
        "INSERT INTO normalization_decisions (id, batch_id, task_id, issue_id, decision_id,"
        " action, changes_json, reason, by_user, decided_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_id("NDEC"),
            batch_id,
            task_id,
            issue_id,
            decision_id,
            action,
            json.dumps(changes, ensure_ascii=False, default=str),
            reason,
            user.id,
            now,
        ),
    )


def _reload_outcome(db: Database, task_id: str, issue_id: str, action: str) -> ReviewOutcome:
    issue = issue_context(db, task_id, issue_id)
    if issue is None:
        raise ReviewError("Issue not found.")
    counts = _refresh_counts(db, issue["issue"]["batch_id"], issue["issue"].get("order_id"))
    status = db.scalar(
        "SELECT status FROM normalization_batches WHERE id = ?",
        (issue["issue"]["batch_id"],),
        "",
    )
    return ReviewOutcome(
        issue_id=issue_id,
        action=action,
        status=issue["issue"]["status"],
        remaining=counts["remaining"],
        confirmed=counts["confirmed"],
        skipped=counts["skipped"],
        batch_status=str(status or ""),
    )


def confirm_issue(
    db: Database,
    *,
    task_id: str,
    issue_id: str,
    changes: dict[str, str],
    decision_id: str,
    user: User,
) -> ReviewOutcome:
    if not (decision_id or "").strip():
        raise ReviewError("A decision id is required.")
    if not isinstance(changes, dict):
        raise ReviewError("Changes must be an object.")
    with db.transaction():
        existing = _existing_decision(db, decision_id, issue_id, task_id)
        if existing:
            return existing
        context = issue_context(db, task_id, issue_id)
        if context is None:
            raise ReviewError("Issue not found.")
        issue = context["issue"]
        if issue["batch_status"] != "needs_review":
            raise ReviewError("This batch is not open for confirmation.")
        if issue["status"] != "unresolved":
            raise ReviewError(f"This issue is already {issue['status']}.")
        if issue["issue_type"] == "file_error":
            raise ReviewError("A file-level error can only be skipped.")
        updates, final = validate_issue_changes(context, changes)
        record = context["record"]
        if not updates and issue["issue_type"] == "missing_value":
            raise ReviewError("Fill the missing field before confirming.")
        now = utc_now()
        db.execute(
            "UPDATE normalized_records SET customer_name = ?, customer_id = ?, quantity = ?,"
            " unit = ?, unit_price = ?, amount = ?, order_date = ?, has_conflict = 0"
            " WHERE id = ?",
            (
                final["customer_name"],
                final["customer_id"],
                final["quantity"],
                final["unit"],
                final["unit_price"],
                final["amount"],
                final["order_date"],
                record["id"],
            ),
        )
        if updates:
            for name, value in updates.items():
                db.execute(
                    "INSERT INTO normalization_changes (id, batch_id, task_id, file_id, order_id,"
                    " source_file, source_row, field, original_value, new_value, reason, method,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'human', ?)",
                    (
                        new_id("NCH"),
                        issue["batch_id"],
                        task_id,
                        record["file_id"],
                        record["order_id"],
                        record["source_file"],
                        record["source_row"],
                        name,
                        record.get(name),
                        value,
                        f"Human confirmation of {issue['issue_type']}.",
                        now,
                    ),
                )
        else:
            db.execute(
                "INSERT INTO normalization_changes (id, batch_id, task_id, file_id, order_id,"
                " source_file, source_row, field, original_value, new_value, reason, method,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'resolution', ?, 'confirmed', ?,"
                " 'human', ?)",
                (
                    new_id("NCH"),
                    issue["batch_id"],
                    task_id,
                    record["file_id"],
                    record["order_id"],
                    record["source_file"],
                    record["source_row"],
                    issue["issue_type"],
                    f"Human confirmed the current values for {issue['issue_type']}.",
                    now,
                ),
            )
        resolution = {"fields": updates, "final": final}
        db.execute(
            "UPDATE normalization_issues SET status = 'resolved', resolved_value = ?,"
            " resolved_by = ?, resolved_at = ?, resolution_json = ?, skip_reason = NULL,"
            " revision = revision + 1 WHERE id = ?",
            (
                json.dumps(updates, ensure_ascii=False),
                user.id,
                now,
                json.dumps(resolution, ensure_ascii=False, default=str),
                issue_id,
            ),
        )
        _insert_decision(
            db,
            batch_id=issue["batch_id"],
            task_id=task_id,
            issue_id=issue_id,
            decision_id=decision_id,
            action="confirm",
            changes=updates,
            reason=None,
            user=user,
            now=now,
        )
        log_event(
            db,
            task_id=task_id,
            kind="normalize_human_confirm",
            actor=user.name,
            occurred_at=now,
            description=f"Confirmed {issue['issue_type']} for {issue.get('order_id') or issue_id}",
            payload={
                "issue_id": issue_id,
                "issue_type": issue["issue_type"],
                "order_id": issue.get("order_id"),
                "changed_fields": list(updates),
                "decision_id": decision_id,
            },
        )
        _refresh_counts(db, issue["batch_id"], issue.get("order_id"))
        touch_task(db, task_id)
    return _reload_outcome(db, task_id, issue_id, "confirm")


def skip_issue(
    db: Database,
    *,
    task_id: str,
    issue_id: str,
    reason: str,
    decision_id: str,
    user: User,
) -> ReviewOutcome:
    if not (decision_id or "").strip():
        raise ReviewError("A decision id is required.")
    clean_reason = (reason or "").strip()
    if len(clean_reason) > 500:
        raise ReviewError("The skip reason can be at most 500 characters.")
    stored_reason = clean_reason or "No reason provided."
    with db.transaction():
        existing = _existing_decision(db, decision_id, issue_id, task_id)
        if existing:
            return existing
        context = issue_context(db, task_id, issue_id)
        if context is None:
            raise ReviewError("Issue not found.")
        issue = context["issue"]
        if issue["batch_status"] != "needs_review":
            raise ReviewError("This batch is not open for confirmation.")
        if issue["status"] != "unresolved":
            raise ReviewError(f"This issue is already {issue['status']}.")
        now = utc_now()
        if issue.get("order_id"):
            db.execute(
                "UPDATE normalized_records SET is_primary = 0, has_conflict = 0"
                " WHERE batch_id = ? AND order_id = ?",
                (issue["batch_id"], issue["order_id"]),
            )
        db.execute(
            "UPDATE normalization_issues SET status = 'skipped', skip_reason = ?,"
            " resolved_by = ?, resolved_at = ?, resolved_value = NULL,"
            " resolution_json = ?, revision = revision + 1 WHERE id = ?",
            (
                stored_reason,
                user.id,
                now,
                json.dumps({"reason": stored_reason}, ensure_ascii=False),
                issue_id,
            ),
        )
        _insert_decision(
            db,
            batch_id=issue["batch_id"],
            task_id=task_id,
            issue_id=issue_id,
            decision_id=decision_id,
            action="skip",
            changes={},
            reason=stored_reason,
            user=user,
            now=now,
        )
        log_event(
            db,
            task_id=task_id,
            kind="normalize_human_skip",
            actor=user.name,
            occurred_at=now,
            description=f"Skipped {issue['issue_type']} for {issue.get('order_id') or issue_id}",
            payload={
                "issue_id": issue_id,
                "issue_type": issue["issue_type"],
                "order_id": issue.get("order_id"),
                "reason": stored_reason,
                "decision_id": decision_id,
            },
        )
        _refresh_counts(db, issue["batch_id"], issue.get("order_id"))
        touch_task(db, task_id)
    return _reload_outcome(db, task_id, issue_id, "skip")


def finish_review(db: Database, *, task_id: str, user: User) -> dict:
    with db.transaction():
        batch_rows = db.query("SELECT * FROM normalization_batches WHERE task_id = ?", (task_id,))
        if not batch_rows:
            raise ReviewError("Normalization batch not found.")
        batch = dict(batch_rows[0])
        if batch["status"] == "complete":
            return {
                "status": "complete",
                "remaining": 0,
                "normalized_records": batch.get("normalized_records", 0),
            }
        if batch["status"] != "needs_review":
            raise ReviewError("The cleanup is not waiting for confirmation.")
        remaining = int(
            db.scalar(
                "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ?"
                " AND status = 'unresolved'",
                (batch["id"],),
                0,
            )
            or 0
        )
        if remaining:
            raise ReviewError(f"{remaining} item(s) still need confirmation.")
        primary = int(
            db.scalar(
                "SELECT COUNT(*) FROM normalized_records WHERE batch_id = ? AND is_primary = 1",
                (batch["id"],),
                0,
            )
            or 0
        )
        now = utc_now()
        db.execute(
            "UPDATE normalization_batches SET status = 'complete', issue_count = 0,"
            " normalized_records = ?, review_completed_at = ?, updated_at = ? WHERE id = ?",
            (primary, now, now, batch["id"]),
        )
        db.execute(
            "UPDATE tasks SET status = 'complete', batch_size = ?, updated_at = ? WHERE id = ?",
            (max(1, primary), now, task_id),
        )
        touch_task(db, task_id)
        log_event(
            db,
            task_id=task_id,
            kind="normalize_review_complete",
            actor=user.name,
            occurred_at=now,
            description=f"Confirmed all review items; {primary} records are ready for download",
            payload={"records": primary, "review_completed_at": now},
        )
        return {
            "status": "complete",
            "remaining": 0,
            "normalized_records": primary,
        }
