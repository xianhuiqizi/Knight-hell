"""One minimized payload shared by the disclosure screen and online request."""

from __future__ import annotations


def review_ai_context(db, context):
    issue = context["issue"]
    allowed = context["allowed_fields"]
    fields = set(allowed)
    if "customer_id" in fields:
        fields.add("customer_name")
    if fields & {"quantity", "unit", "unit_price", "amount"}:
        fields.update({"quantity", "unit", "unit_price", "amount"})
    candidates = []
    customer_name = context["current"].get("customer_name")
    if "customer_id" in allowed and customer_name:
        candidates = db.query(
            "SELECT DISTINCT customer_id, customer_name FROM normalized_records"
            " WHERE batch_id = ? AND is_primary = 1 AND order_id <> ? AND customer_name = ?"
            " AND customer_id IS NOT NULL AND customer_id <> '' LIMIT 10",
            (issue["batch_id"], issue.get("order_id") or "", customer_name),
        )
    return {
        "issue": {"type": issue["issue_type"], "field": issue["field"]},
        "current": {name: context["current"].get(name) for name in sorted(fields)},
        "allowed_fields": allowed,
        "alternatives": [{name: row.get(name) for name in sorted(fields)}
                         for row in context["duplicates"][:10]],
        "grounded_candidates": candidates,
    }
