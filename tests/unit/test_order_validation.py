"""Boundary checks for actual order values, independent of the UI and database."""

from datetime import date

import pytest

from flowremote.control_plane.order_validation import FIELDS, validate_order


def order(**changes):
    raw = dict(zip(FIELDS, ("ID-001", "Customer", "C-001", "2", "10.50", "21", "2024-02-29")))
    raw.update(changes)
    return raw


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("quantity", "-1", "invalid_quantity"),
        ("quantity", "1.5", "invalid_quantity"),
        ("quantity", "0", "invalid_quantity"),
        ("quantity", "1000000001", "invalid_quantity"),
        ("quantity", "NaN", "invalid_number"),
        ("unit_price", "Infinity", "invalid_number"),
        ("amount", "-1", "invalid_money"),
        ("unit_price", "1.001", "invalid_money"),
        ("amount", "1000000000001", "invalid_number"),
        ("amount", "1,000", "invalid_number"),
        ("order_date", "2025-02-29", "invalid_date"),
        ("order_date", "18/10/2026", "invalid_date"),
        ("customer_name", "   ", "missing_value"),
        ("customer_id", "=A1", "formula"),
        ("order_id", "a" * 501, "value_too_long"),
    ],
)
def test_invalid_values_are_explicit_issues(field, value, code):
    issues, _, _ = validate_order(order(**{field: value}), {"ID-001": 1})
    assert any(item["field"] == field and item["code"] == code for item in issues)


@pytest.mark.parametrize("value", ["2024-02-29", "2024/2/29", date(2024, 2, 29)])
def test_supported_dates_are_normalized(value):
    issues, normalized, _ = validate_order(order(order_date=value), {"ID-001": 1})
    assert not issues
    assert normalized["order_date"] == "2024-02-29"


def test_exact_decimal_calculation_and_zero_price():
    for raw in (
        order(quantity="3", unit_price="0.10", amount="0.30"),
        order(unit_price="0", amount="0"),
    ):
        issues, _, suggestion = validate_order(raw, {"ID-001": 1})
        assert not issues
        assert suggestion is None


def test_only_arithmetic_fix_is_suggested_and_not_when_other_fields_are_bad():
    issues, _, suggestion = validate_order(order(amount=""), {"ID-001": 1})
    assert issues and suggestion == "21.00"
    _, _, suggestion = validate_order(order(amount="20", order_date="bad"), {"ID-001": 1})
    assert suggestion is None
    _, _, suggestion = validate_order(order(customer_id=""), {"ID-001": 1})
    assert suggestion is None
