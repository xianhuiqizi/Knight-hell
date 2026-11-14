"""Unit tests for human review logic."""

import pytest
from flowremote.control_plane.db import Database
from flowremote.control_plane.normalization_review import (
    ReviewError,
    confirm_issue,
    skip_issue,
    get_unresolved_count,
    get_decision_counts,
)


@pytest.fixture
def db():
    """In-memory test database."""
    with Database("sqlite:///:memory:") as database:
        database.apply_migrations()
        yield database


@pytest.fixture
def sample_batch(db):
    """Create a sample normalization batch with issues."""
    # Create user
    db.execute(
        "INSERT INTO users (id, name, email, password_hash, role, created_at) "
        "VALUES ('USR-1', 'Test User', 'test@example.com', 'hash', 'operator', datetime('now'))"
    )
    
    # Create task (normalize mode tasks have different required fields)
    db.execute(
        "INSERT INTO tasks (id, workflow, batch_size, status, source_file, source_location, "
        "primary_target, secondary_target, owner_id, task_mode, created_at, updated_at) "
        "VALUES ('TASK-1', 'normalize', 1, 'ready', '', '', '', '', 'USR-1', 'normalize', datetime('now'), datetime('now'))"
    )
    
    # Create batch
    db.execute(
        "INSERT INTO normalization_batches (id, task_id, status, stage, cursor, total_files, "
        "processed_files, raw_records, normalized_records, auto_fixed, issue_count, "
        "rule_version, input_fingerprint, created_at, updated_at) "
        "VALUES ('BATCH-1', 'TASK-1', 'needs_review', 'complete', 0, 1, 1, 10, 10, 0, 2, "
        "'test-v1', 'test-fingerprint', datetime('now'), datetime('now'))"
    )
    
    # Create a file record BEFORE creating normalized_records
    db.execute(
        "INSERT INTO normalization_files (id, batch_id, task_id, ordinal, filename, storage_name, "
        "byte_size, file_type, status, created_at, updated_at) VALUES "
        "('FILE-1', 'BATCH-1', 'TASK-1', 0, 'orders.xlsx', 'test-storage', 1000, 'xlsx', "
        "'normalized', datetime('now'), datetime('now'))"
    )
    
    # Create normalized record
    db.execute(
        "INSERT INTO normalized_records (id, batch_id, task_id, file_id, source_file, source_row, "
        "order_id, customer_name, customer_id, quantity, unit, unit_price, amount, order_date, "
        "is_primary, revision, created_at) "
        "VALUES ('REC-1', 'BATCH-1', 'TASK-1', 'FILE-1', 'orders.xlsx', 2, 'ORD-001', 'Acme Corp', '', "
        "10, 'piece', 5.00, 50.00, '2026-01-15', 1, 1, datetime('now'))"
    )
    
    # Create issues
    db.execute(
        "INSERT INTO normalization_issues (id, batch_id, task_id, issue_type, field, order_id, "
        "source_file, source_row, original_value, suggested_value, confidence, reason, status, "
        "revision, created_at) VALUES "
        "('ISSUE-1', 'BATCH-1', 'TASK-1', 'missing_value', 'customer_id', 'ORD-001', "
        "'orders.xlsx', 2, '', 'C-1001', 0.95, 'Registry match', 'unresolved', 1, datetime('now'))"
    )
    
    db.execute(
        "INSERT INTO normalization_issues (id, batch_id, task_id, issue_type, field, order_id, "
        "source_file, source_row, original_value, suggested_value, confidence, reason, status, "
        "revision, created_at) VALUES "
        "('ISSUE-2', 'BATCH-1', 'TASK-1', 'unit_conflict', 'quantity', 'ORD-001', "
        "'orders.xlsx', 2, '10 box', '120', 0.99, 'Unit conversion', 'unresolved', 1, datetime('now'))"
    )
    
    return {"batch_id": "BATCH-1", "task_id": "TASK-1"}


def test_confirm_issue_with_no_changes(db, sample_batch):
    """Confirming an issue without edits marks it resolved."""
    result = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-1",
        changes={},
        user_id="USR-1",
        user_name="Test User",
    )
    
    assert result.resolved is True
    assert result.action == "confirm"
    assert "confirmed" in result.message.lower()
    
    # Check issue is resolved
    issue = db.query("SELECT status FROM normalization_issues WHERE id = 'ISSUE-1'")[0]
    assert issue["status"] == "resolved"
    
    # Check unresolved count decreased
    count = get_unresolved_count(db, sample_batch["task_id"])
    assert count == 1


def test_confirm_issue_with_field_edits(db, sample_batch):
    """Confirming with edits updates the normalized record."""
    result = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-2",
        changes={"customer_id": "C-1001"},
        user_id="USR-1",
        user_name="Test User",
    )
    
    assert result.resolved is True
    
    # Check record was updated
    record = db.query("SELECT customer_id, revision FROM normalized_records WHERE id = 'REC-1'")[0]
    assert record["customer_id"] == "C-1001"
    assert record["revision"] == 2
    
    # Check change was logged
    changes = db.query("SELECT * FROM normalization_changes WHERE order_id = 'ORD-001' AND method = 'human'")
    assert len(changes) == 1
    assert changes[0]["field"] == "customer_id"


def test_confirm_issue_validates_quantity(db, sample_batch):
    """Quantity must be a positive whole number."""
    # Zero quantity
    with pytest.raises(ReviewError, match="greater than zero"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-2",
            decision_id="DEC-3",
            changes={"quantity": "0"},
            user_id="USR-1",
            user_name="Test User",
        )
    
    # Negative quantity
    with pytest.raises(ReviewError, match="greater than zero"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-2",
            decision_id="DEC-4",
            changes={"quantity": "-5"},
            user_id="USR-1",
            user_name="Test User",
        )
    
    # Decimal quantity
    with pytest.raises(ReviewError, match="whole number"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-2",
            decision_id="DEC-5",
            changes={"quantity": "5.5"},
            user_id="USR-1",
            user_name="Test User",
        )


def test_confirm_issue_validates_unit(db, sample_batch):
    """Unit must be canonical."""
    # Invalid unit
    with pytest.raises(ReviewError, match="must be 'piece', 'box', or 'kg'"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-2",
            decision_id="DEC-6",
            changes={"unit": "invalid"},
            user_id="USR-1",
            user_name="Test User",
        )
    
    # Valid unit
    result = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-2",
        decision_id="DEC-7",
        changes={"unit": "kg"},
        user_id="USR-1",
        user_name="Test User",
    )
    assert result.resolved is True


def test_confirm_issue_converts_box_to_pieces(db, sample_batch):
    """Box unit converts quantity to pieces and adjusts amount."""
    # First set customer_id so record is complete
    confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-7",
        changes={"customer_id": "C-1001"},
        user_id="USR-1",
        user_name="Test User",
    )
    
    # Now test box conversion
    result = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-2",
        decision_id="DEC-8",
        changes={"quantity": "10", "unit": "box"},
        user_id="USR-1",
        user_name="Test User",
    )
    
    assert result.resolved is True
    
    # Check conversion
    record = db.query("SELECT quantity, unit, amount FROM normalized_records WHERE id = 'REC-1'")[0]
    assert record["quantity"] == 120  # 10 * 12
    assert record["unit"] == "piece"
    assert record["amount"] == 600.00  # 120 * 5.00


def test_confirm_issue_validates_amount_matches(db, sample_batch):
    """Amount must equal quantity × unit_price."""
    # Mismatched amount
    with pytest.raises(ReviewError, match="does not match"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-9",
            changes={"amount": "100.00"},  # quantity=10, unit_price=5.00, expected=50.00
            user_id="USR-1",
            user_name="Test User",
        )


def test_confirm_issue_validates_date_format(db, sample_batch):
    """Date must be in ISO format."""
    # Invalid date format
    with pytest.raises(ReviewError, match="YYYY-MM-DD"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-10",
            changes={"order_date": "01/15/2026"},
            user_id="USR-1",
            user_name="Test User",
        )
    
    # Valid date
    result = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-11",
        changes={"order_date": "2026-01-15"},
        user_id="USR-1",
        user_name="Test User",
    )
    assert result.resolved is True


def test_confirm_issue_is_idempotent(db, sample_batch):
    """Confirming the same decision_id twice succeeds without duplicate."""
    # First confirm
    result1 = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-IDEMPOTENT",
        changes={"customer_id": "C-1001"},
        user_id="USR-1",
        user_name="Test User",
    )
    assert result1.resolved is True
    
    # Second confirm with same decision_id
    result2 = confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-IDEMPOTENT",
        changes={"customer_id": "C-1001"},
        user_id="USR-1",
        user_name="Test User",
    )
    assert result2.resolved is True
    assert "already" in result2.message.lower()
    
    # Check only one decision recorded
    decisions = db.query("SELECT COUNT(*) as count FROM normalization_decisions WHERE decision_id = 'DEC-IDEMPOTENT'")
    assert decisions[0]["count"] == 1


def test_skip_issue_with_reason(db, sample_batch):
    """Skipping an issue with reason marks it skipped."""
    result = skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-SKIP-1",
        reason="Customer confirmation pending",
        user_id="USR-1",
        user_name="Test User",
    )
    
    assert result.resolved is True
    assert result.action == "skip"
    assert "skipped" in result.message.lower()
    
    # Check issue is skipped
    issue = db.query("SELECT status FROM normalization_issues WHERE id = 'ISSUE-1'")[0]
    assert issue["status"] == "skipped"
    
    # Check unresolved count decreased
    count = get_unresolved_count(db, sample_batch["task_id"])
    assert count == 1


def test_skip_issue_requires_reason(db, sample_batch):
    """Skipping without reason fails."""
    with pytest.raises(ReviewError, match="reason is required"):
        skip_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-SKIP-2",
            reason="",
            user_id="USR-1",
            user_name="Test User",
        )
    
    # Too short reason
    with pytest.raises(ReviewError, match="at least 3 characters"):
        skip_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-SKIP-3",
            reason="OK",
            user_id="USR-1",
            user_name="Test User",
        )


def test_skip_issue_is_idempotent(db, sample_batch):
    """Skipping with same decision_id twice succeeds."""
    # First skip
    result1 = skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-SKIP-IDEMPOTENT",
        reason="Data quality issue",
        user_id="USR-1",
        user_name="Test User",
    )
    assert result1.resolved is True
    
    # Second skip
    result2 = skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-SKIP-IDEMPOTENT",
        reason="Data quality issue",
        user_id="USR-1",
        user_name="Test User",
    )
    assert result2.resolved is True
    assert "already" in result2.message.lower()


def test_get_unresolved_count(db, sample_batch):
    """Get count of unresolved issues."""
    count = get_unresolved_count(db, sample_batch["task_id"])
    assert count == 2
    
    # Confirm one
    confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-COUNT-1",
        changes={},
        user_id="USR-1",
        user_name="Test User",
    )
    
    count = get_unresolved_count(db, sample_batch["task_id"])
    assert count == 1


def test_get_decision_counts(db, sample_batch):
    """Get counts of confirmed and skipped decisions."""
    counts = get_decision_counts(db, sample_batch["task_id"])
    assert counts["confirmed"] == 0
    assert counts["skipped"] == 0
    
    # Confirm one, skip one
    confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-COUNTS-1",
        changes={},
        user_id="USR-1",
        user_name="Test User",
    )
    
    skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-2",
        decision_id="DEC-COUNTS-2",
        reason="Need more information",
        user_id="USR-1",
        user_name="Test User",
    )
    
    counts = get_decision_counts(db, sample_batch["task_id"])
    assert counts["confirmed"] == 1
    assert counts["skipped"] == 1


def test_cannot_confirm_already_resolved_issue(db, sample_batch):
    """Cannot confirm an issue that is already resolved."""
    # First confirm
    confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-FIRST",
        changes={},
        user_id="USR-1",
        user_name="Test User",
    )
    
    # Try to confirm again with different decision_id
    with pytest.raises(ReviewError, match="already resolved"):
        confirm_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-SECOND",
            changes={},
            user_id="USR-1",
            user_name="Test User",
        )


def test_cannot_skip_already_skipped_issue(db, sample_batch):
    """Cannot skip an issue that is already skipped."""
    # First skip
    skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-SKIP-FIRST",
        reason="First reason",
        user_id="USR-1",
        user_name="Test User",
    )
    
    # Try to skip again with different decision_id
    with pytest.raises(ReviewError, match="already skipped"):
        skip_issue(
            db,
            task_id=sample_batch["task_id"],
            issue_id="ISSUE-1",
            decision_id="DEC-SKIP-SECOND",
            reason="Second reason",
            user_id="USR-1",
            user_name="Test User",
        )


def test_confirm_logs_activity_event(db, sample_batch):
    """Confirming logs a normalize_human activity event."""
    confirm_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-ACTIVITY",
        changes={},
        user_id="USR-1",
        user_name="Test User",
    )
    
    events = db.query(
        "SELECT * FROM activity_events WHERE task_id = ? AND kind = 'normalize_human'",
        (sample_batch["task_id"],)
    )
    assert len(events) == 1
    assert "Confirmed" in events[0]["description"]


def test_skip_logs_activity_event(db, sample_batch):
    """Skipping logs a normalize_human activity event with reason."""
    skip_issue(
        db,
        task_id=sample_batch["task_id"],
        issue_id="ISSUE-1",
        decision_id="DEC-SKIP-ACTIVITY",
        reason="Data quality issue",
        user_id="USR-1",
        user_name="Test User",
    )
    
    events = db.query(
        "SELECT * FROM activity_events WHERE task_id = ? AND kind = 'normalize_human'",
        (sample_batch["task_id"],)
    )
    assert len(events) == 1
    assert "Skipped" in events[0]["description"]
    assert "Data quality issue" in events[0]["description"]
