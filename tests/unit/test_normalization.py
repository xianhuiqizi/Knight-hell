"""Rule-first multi-source normalization: parsing, mapping, units and merge."""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook

from flowremote.control_plane.normalization import (
    build_mapping,
    detect_table,
    merge_records,
    normalize_table,
    parse_date,
    run_full_normalization,
)
from flowremote.devtools.demoday_data import demo_sources


def workbook_bytes(rows, title="Orders", extra_sheet=None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(list(row))
    if extra_sheet:
        name, extra_rows = extra_sheet
        extra = workbook.create_sheet(name)
        for row in extra_rows:
            extra.append(list(row))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


HEADER = ["Order No.", "Customer", "Customer Code", "Qty", "Unit", "Unit Price",
          "Total", "Order Date"]


def one_file(rows, filename="orders.xlsx", sheet="Orders", extra_sheet=None):
    result = run_full_normalization(
        [(filename, workbook_bytes(rows, title=sheet, extra_sheet=extra_sheet))]
    )
    return result["files"][0], result


def test_detects_header_after_title_rows():
    data = workbook_bytes(
        [("September extract",), ("Synthetic demo",), (), HEADER,
         ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
    )
    detected = detect_table("orders.xlsx", data)
    assert detected.header_row == 4
    assert detected.row_count == 1
    assert detected.worksheet == "Orders"


def test_maps_english_and_chinese_aliases():
    rows = [["订单编号", "客户名称", "客户编号", "数量", "单位", "单价", "金额", "下单日期"],
            ["ORD-9", "Acme", "C-9", 3, "件", 2.5, 7.5, "2026/9/2"]]
    file, result = one_file(rows)
    mapping = build_mapping(detect_table("orders.xlsx", workbook_bytes(rows)))
    assert file["field_count"] == 8
    assert {column.field for column in mapping.columns} == {
        "order_id", "customer_name", "customer_id", "quantity", "unit",
        "unit_price", "amount", "order_date",
    }
    assert result["records"][0]["unit_price"] == 2.5


def test_uses_second_worksheet_when_cover_is_not_a_table():
    workbook = Workbook()
    first = workbook.active
    first.title = "Read me"
    first.append(["September orders"])
    first.append(["The table is on the next sheet."])
    second = workbook.create_sheet("Data")
    second.append(HEADER)
    second.append(("ORD-2", "Beta", "C-2", 1, "件", 5, 5, "2026-09-02"))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    result = run_full_normalization([("second_sheet.xlsx", output.getvalue())])
    assert result["files"][0]["worksheet"] == "Data"
    assert result["files"][0]["row_count"] == 1


def test_csv_with_bom_and_extra_columns_is_read():
    csv_text = (
        "\ufeffSales Region,Total,Order No.,Customer Code,Customer,Qty,Unit,Order Date,Unit Price,Note\n"
        "North,\"1,200.00\",ORD-3,C-3,Acme,2,件,2026/9/3,600,\n"
    )
    result = run_full_normalization([("orders.csv", csv_text.encode("utf-8"))])
    assert result["files"][0]["status"] == "normalized"
    assert result["records"][0]["amount"] == 1200.0
    assert result["records"][0]["order_id"] == "ORD-3"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-09-01", "2026-09-01"),
        ("2026/9/1", "2026-09-01"),
        ("01/09/2026", "2026-09-01"),
        ("25/09/2026", "2026-09-25"),
        (46266, "2026-09-01"),
    ],
)
def test_supported_date_formats(value, expected):
    assert parse_date(value)[0] == expected


def test_day_first_is_inferred_from_unambiguous_day():
    rows = [HEADER,
            ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "25/09/2026"),
            ("ORD-2", "Acme", "C-1", 2, "件", 10, 20, "01/09/2026")]
    detected = detect_table("orders.xlsx", workbook_bytes(rows))
    mapping = build_mapping(detected)
    assert mapping.date_order == "day-first"
    assert parse_date("01/09/2026", mapping.date_order)[0] == "2026-09-01"


def test_three_sheet_demo_pack_has_exactly_six_issues():
    result = run_full_normalization(demo_sources())
    summary = result["summary"]
    assert summary["files_ok"] == 6
    assert summary["raw_records"] == 174
    assert summary["normalized_records"] == 36
    assert summary["issues"] == 6
    assert summary["missing_values"] == 2
    assert summary["unit_conflicts"] == 2
    assert summary["cross_file_conflicts"] == 2
    assert {issue["issue_type"] for issue in result["issues"]} == {
        "missing_value", "unit_conflict", "cross_file_conflict",
    }


def test_demo_pack_is_idempotent_for_same_files():
    first = run_full_normalization(demo_sources())
    second = run_full_normalization(list(reversed(demo_sources())))
    # Values must match even when the picker returns the same set in another
    # order: both runs sort duplicate groups by their input order in the pure
    # helper, so compare the issue signature rather than the primary source row.
    signature = lambda result: sorted(
        (issue["issue_type"], issue["order_id"], issue.get("field"))
        for issue in result["issues"]
    )
    assert signature(first) == signature(second)
    assert first["summary"]["normalized_records"] == second["summary"]["normalized_records"]


def test_duplicate_identical_orders_are_merged():
    rows = [HEADER,
            ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01"),
            ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
    result = run_full_normalization(
        [
            ("a.xlsx", workbook_bytes(rows)),
            ("b.xlsx", workbook_bytes(rows)),
        ]
    )
    record = next(item for item in result["records"] if item["order_id"] == "ORD-1")
    assert record["duplicate_count"] == 4
    assert result["summary"]["cross_file_conflicts"] == 0


def test_conflicting_duplicate_is_not_silently_overwritten():
    first_rows = [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
    second_rows = [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 11, 22, "2026-09-01")]
    result = run_full_normalization(
        [
            ("a.xlsx", workbook_bytes(first_rows)),
            ("b.xlsx", workbook_bytes(second_rows)),
        ]
    )
    assert result["summary"]["cross_file_conflicts"] == 1
    issue = result["issues"][0]
    assert "unit_price" in issue["field"]
    assert "nothing was silently overwritten" in issue["reason"]
    record = result["records"][0]
    assert record["has_conflict"] is True


def test_box_conversion_is_explained_and_amount_preserved():
    rows = [HEADER, ("ORD-1", "Acme", "C-1", 2, "箱", 120, 240, "2026-09-01")]
    result = run_full_normalization([("boxes.xlsx", workbook_bytes(rows))])
    record = result["records"][0]
    assert (record["quantity"], record["unit"], record["unit_price"], record["amount"]) == (
        24, "piece", 10.0, 240.0
    )
    reasons = [change["reason"] for change in result["changes"]]
    assert any("boxes to pieces" in reason for reason in reasons)
    assert any(change["field"] == "unit" and change["new_value"] == "piece"
               for change in result["changes"])


def test_box_mismatch_creates_unit_conflict():
    rows = [HEADER, ("ORD-1", "Acme", "C-1", 2, "箱", 10, 240, "2026-09-01")]
    result = run_full_normalization([("boxes.xlsx", workbook_bytes(rows))])
    assert result["issues"][0]["issue_type"] == "unit_conflict"
    assert "quantity × 12 × price" in result["issues"][0]["reason"]


def test_thousand_unit_conversion_and_conflict():
    header = ["Order No.", "Customer", "Customer Code", "Qty", "Unit",
              "Price (CNY '000)", "Total", "Order Date"]
    rows = [header,
            ("ORD-1", "Acme", "C-1", 2, "件", 0.01, 20, "2026-09-01"),
            ("ORD-2", "Beta", "C-2", 2, "件", 10, 20, "2026-09-02")]
    result = run_full_normalization([("thousand.xlsx", workbook_bytes(rows))])
    records = {record["order_id"]: record for record in result["records"]}
    assert records["ORD-1"]["unit_price"] == 10.0
    assert records["ORD-2"]["unit_price"] == 10.0
    assert result["summary"]["unit_conflicts"] == 1
    assert result["issues"][0]["order_id"] == "ORD-2"
    assert any("thousand CNY" in change["reason"] for change in result["changes"])


def test_missing_customer_id_and_quantity_are_reported():
    rows = [HEADER,
            ("ORD-1", "Acme", "", 2, "件", 10, 20, "2026-09-01"),
            ("ORD-2", "Beta", "C-2", "", "件", 10, 20, "2026-09-02")]
    result = run_full_normalization([("missing.xlsx", workbook_bytes(rows))])
    assert result["summary"]["missing_values"] == 2
    fields = {issue["field"] for issue in result["issues"]}
    assert fields == {"customer_id", "quantity"}


def test_unreadable_file_does_not_fail_the_other_file():
    good = workbook_bytes(
        [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
    )
    result = run_full_normalization(
        [("good.xlsx", good), ("broken.xlsx", b"not an xlsx")]
    )
    assert result["summary"]["files_ok"] == 1
    assert result["summary"]["file_errors"] == 1
    assert result["summary"]["normalized_records"] == 1
    assert result["files"][1]["status"] == "attention"
    assert "could not be normalized" in result["files"][1]["issue"]


def test_mapping_has_confidence_and_evidence_for_every_field():
    file, _ = one_file(
        [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
    )
    assert file["mapping"]["field_count"] == 8
    for column in file["mapping"]["columns"]:
        assert 0 < column["confidence"] <= 1
        assert column["evidence"]
        assert column["method"] in {"synonym", "synonym-prefix", "distribution", "default"}


def test_extra_columns_are_ignored_but_recorded_as_unmapped():
    rows = [HEADER + ["Region", "Internal note"],
            ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01", "North", "ignore")]
    detected = detect_table("orders.xlsx", workbook_bytes(rows))
    mapping = build_mapping(detected)
    assert set(mapping.unmapped_headers) == {"Region", "Internal note"}
    assert mapping.field_count == 8


def test_amount_mismatch_is_flagged():
    rows = [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 21, "2026-09-01")]
    result = run_full_normalization([("bad_total.xlsx", workbook_bytes(rows))])
    assert result["issues"][0]["issue_type"] == "amount_mismatch"
    assert result["issues"][0]["suggested_value"] == "20.00"


def test_missing_unit_defaults_to_piece_with_evidence():
    rows = [HEADER[:4] + HEADER[5:],
            ("ORD-1", "Acme", "C-1", 2, 10, 20, "2026-09-01")]
    result = run_full_normalization([("no_unit.xlsx", workbook_bytes(rows))])
    record = result["records"][0]
    assert record["unit"] == "piece"
    unit_mapping = next(
        column for column in result["files"][0]["mapping"]["columns"]
        if column["field"] == "unit"
    )
    assert unit_mapping["method"] == "default"
    assert unit_mapping["evidence"]


def test_merge_records_keeps_first_source_as_provisional_primary():
    rows_a = normalize_table(
        detect_table("a.xlsx", workbook_bytes(
            [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
        )),
        build_mapping(detect_table("a.xlsx", workbook_bytes(
            [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
        ))),
        source_file="a.xlsx",
        file_ordinal=1,
    )
    rows_b = normalize_table(
        detect_table("b.xlsx", workbook_bytes(
            [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
        )),
        build_mapping(detect_table("b.xlsx", workbook_bytes(
            [HEADER, ("ORD-1", "Acme", "C-1", 2, "件", 10, 20, "2026-09-01")]
        ))),
        source_file="b.xlsx",
        file_ordinal=2,
    )
    merged, issues = merge_records(rows_a + rows_b)
    assert merged[0]["source_file"] == "a.xlsx"
    assert merged[0]["duplicate_count"] == 2
    assert issues == []
