"""Human review actions for normalization issues.

Phase D: editable confirmation queue with revalidation and revision control.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import Database, new_id, utc_now


class ReviewError(ValueError):
    """Human review action cannot be applied."""


@dataclass(frozen=True)
class ReviewDecision:
    """Result of a confirm/skip action."""
    
    issue_id: str
    action: str  # 'confirm' or 'skip'
    resolved: bool
    message: str


def _validate_quantity(value: str) -> int:
    """Validate quantity is a positive whole number."""
    try:
        value = value.strip()
        if not value:
            raise ReviewError("Quantity is required.")
        qty = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ReviewError("Quantity must be a valid number.") from exc
    
    if qty <= 0:
        raise ReviewError("Quantity must be greater than zero.")
    if qty != qty.to_integral_value():
        raise ReviewError("Quantity must be a whole number.")
    if qty > 1_000_000:
        raise ReviewError("Quantity is unrealistically large.")
    
    return int(qty)


def _validate_price(value: str, field_name: str = "Price") -> Decimal:
    """Validate price is non-negative with at most 2 decimals."""
    try:
        price = Decimal(value.strip())
        if price < 0:
            raise ReviewError(f"{field_name} cannot be negative.")
        if price.as_tuple().exponent < -2:
            raise ReviewError(f"{field_name} can have at most 2 decimal places.")
        if price > Decimal("1000000000"):
            raise ReviewError(f"{field_name} is unrealistically large.")
        return price
    except (InvalidOperation, ValueError) as exc:
        raise ReviewError(f"{field_name} must be a valid number.") from exc


def _validate_date(value: str) -> str:
    """Validate date is in ISO format YYYY-MM-DD."""
    from datetime import datetime
    
    value = value.strip()
    try:
        # Try parsing as ISO date
        datetime.fromisoformat(value)
        return value
    except ValueError:
        pass
    
    raise ReviewError("Date must be in YYYY-MM-DD format.")


def _validate_amount_matches(quantity: int, unit_price: Decimal, amount: Decimal) -> None:
    """Validate amount equals quantity × unit_price within tolerance."""
    expected = Decimal(quantity) * unit_price
    diff = abs(expected - amount)
    if diff > Decimal("0.005"):
        raise ReviewError(
            f"Amount {amount} does not match quantity × unit price "
            f"({quantity} × {unit_price} = {expected})."
        )


def confirm_issue(
    db: Database,
    *,
    task_id: str,
    issue_id: str,
    decision_id: str,
    changes: dict[str, str],
    user_id: str,
    user_name: str,
) -> ReviewDecision:
    """Confirm an issue with optional field edits and revalidation.
    
    Args:
        db: Database connection
        task_id: Task ID
        issue_id: Issue ID to resolve
        decision_id: Client idempotency key
        changes: Dict of field -> new value
        user_id: User ID making decision
        user_name: User name for audit
        
    Returns:
        ReviewDecision with resolution status
        
    Raises:
        ReviewError: If validation fails or issue cannot be resolved
    """
    # Check idempotency: if decision already exists, return success
    existing = db.query(
        "SELECT id, action FROM normalization_decisions WHERE decision_id = ?",
        (decision_id,)
    )
    if existing:
        if existing[0]["action"] != "confirm":
            raise ReviewError("This decision was already recorded as skip.")
        return ReviewDecision(
            issue_id=issue_id,
            action="confirm",
            resolved=True,
            message="Already confirmed."
        )
    
    # Load issue
    issue_rows = db.query(
        "SELECT id, batch_id, task_id, issue_type, field, order_id, source_file, source_row, "
        "original_value, suggested_value, status, revision FROM normalization_issues "
        "WHERE id = ? AND task_id = ?",
        (issue_id, task_id)
    )
    if not issue_rows:
        raise ReviewError("Issue not found.")
    
    issue = dict(issue_rows[0])
    
    if issue["status"] in ("resolved", "skipped"):
        raise ReviewError(f"Issue is already {issue['status']}.")
    
    # Load normalized record to update
    record_rows = db.query(
        "SELECT id, order_id, customer_name, customer_id, quantity, unit, unit_price, amount, "
        "order_date, revision FROM normalized_records "
        "WHERE batch_id = ? AND order_id = ? AND is_primary = 1",
        (issue["batch_id"], issue["order_id"])
    )
    
    if not record_rows:
        raise ReviewError("Normalized record not found.")
    
    record = dict(record_rows[0])
    
    # Apply changes and validate
    updated_fields = {}
    
    # If no changes provided but issue has a suggested value, use it
    if not changes and issue.get("suggested_value"):
        # Auto-apply suggestion for this issue's field
        suggested_field = issue.get("field")
        suggested_value = issue.get("suggested_value")
        if suggested_field and suggested_value:
            changes = {suggested_field: suggested_value}
    
    for field, value in changes.items():
        value = value.strip()
        
        if field == "customer_id":
            if not value or len(value) > 100:
                raise ReviewError("Customer ID is required and must be ≤100 characters.")
            updated_fields[field] = value
            
        elif field == "customer_name":
            if not value or len(value) > 200:
                raise ReviewError("Customer name is required and must be ≤200 characters.")
            updated_fields[field] = value
            
        elif field == "quantity":
            qty = _validate_quantity(value)
            updated_fields[field] = qty
            
        elif field == "unit":
            unit = value.lower()
            if unit not in ("piece", "box", "kg"):
                raise ReviewError("Unit must be 'piece', 'box', or 'kg'.")
            
            # If unit is box, apply conversion immediately
            if unit == "box":
                # Get current or updated quantity
                current_qty = updated_fields.get("quantity", record.get("quantity", 0))
                if current_qty:
                    updated_fields["quantity"] = int(current_qty) * 12
                    updated_fields["unit"] = "piece"
                    # Also update amount to match new quantity
                    unit_price = updated_fields.get("unit_price", record.get("unit_price", 0))
                    if unit_price:
                        updated_fields["amount"] = float(updated_fields["quantity"] * Decimal(str(unit_price)))
            else:
                updated_fields[field] = unit
            
        elif field == "unit_price":
            updated_fields[field] = float(_validate_price(value, "Unit price"))
            
        elif field == "amount":
            updated_fields[field] = float(_validate_price(value, "Amount"))
            
        elif field == "order_date":
            updated_fields[field] = _validate_date(value)
            
        else:
            raise ReviewError(f"Unknown field: {field}")
    
    # Build final values (updated + existing)
    final_values = {**record, **updated_fields}
    
    # Cross-field validation (only if all involved fields present)
    if final_values.get("quantity") and final_values.get("unit_price") and final_values.get("amount"):
        _validate_amount_matches(
            int(final_values["quantity"]),
            Decimal(str(final_values["unit_price"])),
            Decimal(str(final_values["amount"]))
        )
    
    # Check required fields only if we're confirming (not just updating one field)
    # Allow partial updates for field-specific issues
    # Note: box conversion adds quantity/amount but counts as 1 field update (unit)
    explicit_field_count = len(changes)  # Original changes before conversion
    if updated_fields:
        required = ["customer_id", "customer_name", "quantity", "unit_price", "amount", "order_date"]
        missing = [f for f in required if not final_values.get(f)]
        if missing and explicit_field_count > 1:
            # Only enforce all required if updating multiple fields explicitly
            raise ReviewError(f"Required fields missing: {', '.join(missing)}")
    
    # Update database in transaction
    now = utc_now()
    
    with db.transaction():
        # Record decision
        db.execute(
            "INSERT INTO normalization_decisions (id, batch_id, task_id, issue_id, decision_id, "
            "action, changes_json, by_user, decided_at) VALUES (?, ?, ?, ?, ?, 'confirm', ?, ?, ?)",
            (new_id("DEC"), issue["batch_id"], task_id, issue_id, decision_id,
             json.dumps(changes), user_name, now)
        )
        
        # Update normalized record
        update_fields = []
        update_values = []
        for field, value in updated_fields.items():
            update_fields.append(f"{field} = ?")
            update_values.append(value)
        
        if update_fields:
            update_fields.append("revision = revision + 1")
            update_values.extend([record["id"]])
            
            db.execute(
                f"UPDATE normalized_records SET {', '.join(update_fields)} WHERE id = ?",
                tuple(update_values)
            )
            
            # Log changes
            for field, value in updated_fields.items():
                db.execute(
                    "INSERT INTO normalization_changes (id, batch_id, task_id, file_id, order_id, "
                    "source_file, source_row, field, original_value, new_value, reason, method, "
                    "created_at) SELECT ?, ?, ?, id, ?, ?, ?, ?, ?, ?, 'Human confirmation', 'human', ? "
                    "FROM normalization_files WHERE batch_id = ? AND ordinal = 0",
                    (new_id("CHG"), issue["batch_id"], task_id, issue["order_id"],
                     issue["source_file"], issue["source_row"], field,
                     record.get(field), value, now, issue["batch_id"])
                )
        
        # Mark issue as resolved
        db.execute(
            "UPDATE normalization_issues SET status = 'resolved', resolved_by = ?, "
            "resolved_at = ?, resolved_fields_json = ?, revision = revision + 1 WHERE id = ?",
            (user_name, now, json.dumps(updated_fields), issue_id)
        )
        
        # Update batch issue count
        unresolved_count = db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ? AND status = 'unresolved'",
            (issue["batch_id"],),
            0
        )
        
        db.execute(
            "UPDATE normalization_batches SET issue_count = ?, updated_at = ? WHERE id = ?",
            (unresolved_count, now, issue["batch_id"])
        )
        
        # Log activity event
        log_event(
            db,
            task_id=task_id,
            kind="normalize_human",
            actor=user_name,
            description=f"Confirmed {issue['issue_type']} for {issue['order_id'] or 'file-level'}",
        )
    
    return ReviewDecision(
        issue_id=issue_id,
        action="confirm",
        resolved=True,
        message=f"Issue confirmed{' with edits' if changes else ''}."
    )


def skip_issue(
    db: Database,
    *,
    task_id: str,
    issue_id: str,
    decision_id: str,
    reason: str,
    user_id: str,
    user_name: str,
) -> ReviewDecision:
    """Skip an issue with a required reason.
    
    Args:
        db: Database connection
        task_id: Task ID
        issue_id: Issue ID to skip
        decision_id: Client idempotency key
        reason: Human-readable reason (required)
        user_id: User ID making decision
        user_name: User name for audit
        
    Returns:
        ReviewDecision with skip status
        
    Raises:
        ReviewError: If issue cannot be skipped
    """
    reason = reason.strip()
    if not reason or len(reason) < 3:
        raise ReviewError("Skip reason is required (at least 3 characters).")
    if len(reason) > 500:
        raise ReviewError("Skip reason is too long (max 500 characters).")
    
    # Check idempotency
    existing = db.query(
        "SELECT id, action FROM normalization_decisions WHERE decision_id = ?",
        (decision_id,)
    )
    if existing:
        if existing[0]["action"] != "skip":
            raise ReviewError("This decision was already recorded as confirm.")
        return ReviewDecision(
            issue_id=issue_id,
            action="skip",
            resolved=True,
            message="Already skipped."
        )
    
    # Load issue
    issue_rows = db.query(
        "SELECT id, batch_id, task_id, issue_type, order_id, status FROM normalization_issues "
        "WHERE id = ? AND task_id = ?",
        (issue_id, task_id)
    )
    if not issue_rows:
        raise ReviewError("Issue not found.")
    
    issue = dict(issue_rows[0])
    
    if issue["status"] in ("resolved", "skipped"):
        raise ReviewError(f"Issue is already {issue['status']}.")
    
    now = utc_now()
    
    with db.transaction():
        # Record decision
        db.execute(
            "INSERT INTO normalization_decisions (id, batch_id, task_id, issue_id, decision_id, "
            "action, changes_json, reason, by_user, decided_at) VALUES (?, ?, ?, ?, ?, 'skip', '{}', ?, ?, ?)",
            (new_id("DEC"), issue["batch_id"], task_id, issue_id, decision_id, reason, user_name, now)
        )
        
        # Mark issue as skipped
        db.execute(
            "UPDATE normalization_issues SET status = 'skipped', resolved_by = ?, resolved_at = ?, "
            "revision = revision + 1 WHERE id = ?",
            (user_name, now, issue_id)
        )
        
        # Update batch issue count
        unresolved_count = db.scalar(
            "SELECT COUNT(*) FROM normalization_issues WHERE batch_id = ? AND status = 'unresolved'",
            (issue["batch_id"],),
            0
        )
        
        db.execute(
            "UPDATE normalization_batches SET issue_count = ?, updated_at = ? WHERE id = ?",
            (unresolved_count, now, issue["batch_id"])
        )
        
        # Log activity event
        log_event(
            db,
            task_id=task_id,
            kind="normalize_human",
            actor=user_name,
            description=f"Skipped {issue['issue_type']} for {issue['order_id'] or 'file-level'}: {reason}",
        )
    
    return ReviewDecision(
        issue_id=issue_id,
        action="skip",
        resolved=True,
        message=f"Issue skipped: {reason}"
    )


def get_unresolved_count(db: Database, task_id: str) -> int:
    """Get count of unresolved issues for a task."""
    return db.scalar(
        "SELECT COUNT(*) FROM normalization_issues ni "
        "JOIN normalization_batches nb ON ni.batch_id = nb.id "
        "WHERE nb.task_id = ? AND ni.status = 'unresolved'",
        (task_id,),
        0
    )


def get_decision_counts(db: Database, task_id: str) -> dict[str, int]:
    """Get counts of confirmed and skipped decisions."""
    counts = {"confirmed": 0, "skipped": 0}
    
    rows = db.query(
        "SELECT action, COUNT(*) as count FROM normalization_decisions nd "
        "JOIN normalization_batches nb ON nd.batch_id = nb.id "
        "WHERE nb.task_id = ? GROUP BY action",
        (task_id,)
    )
    
    for row in rows:
        if row["action"] == "confirm":
            counts["confirmed"] = row["count"]
        elif row["action"] == "skip":
            counts["skipped"] = row["count"]
    
    return counts
