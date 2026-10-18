"""Real uploaded rows must drive results, corrections, gates and ownership."""

import json
from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from flowremote.api.app import create_app
from flowremote.control_plane.db import Database
from flowremote.control_plane.order_validation import FIELDS, save_analysis
from tests.integration.test_uploads import UploadFixture, order_row, workbook_bytes


def mixed_workbook():
    return workbook_bytes(
        [
            FIELDS,
            order_row("GOOD-1", order_date=datetime(2026, 10, 18)),
            order_row(
                "MISSING", customer_id=None, quantity=0, amount="oops", order_date="2026-02-30"
            ),
            order_row("TOTAL", quantity=3, unit_price=5, amount=14),
            order_row("DUP"),
            order_row("DUP"),
            (None,),
            order_row("FORMULA", amount="=D8*E8"),
            order_row("GOOD-2"),
        ]
    )


class OrderValidationTests(UploadFixture):
    def test_mixed_upload_counts_raw_values_locations_and_reasons(self):
        response = self.upload(data=mixed_workbook())
        self.assertEqual(response.status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT batch_size FROM tasks"), 7)
            self.assertEqual(
                db.scalar("SELECT COUNT(*) FROM source_records WHERE outcome='passed'"), 2
            )
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM exceptions"), 5)
            summary = json.loads(db.scalar("SELECT summary_json FROM task_validations"))
            self.assertEqual(sum(summary.values()), 8)
            self.assertEqual(summary["duplicate_order_id"], 2)
            self.assertEqual(
                db.scalar("SELECT excel_row FROM order_inputs WHERE record_id='ORD-006'"), 8
            )
            self.assertEqual(
                db.scalar("SELECT suggestion FROM exceptions WHERE record_id='ORD-003'"), "15.00"
            )
            self.assertIsNone(
                db.scalar("SELECT suggestion FROM exceptions WHERE record_id='ORD-002'")
            )
            self.assertIsNone(db.scalar("SELECT confidence FROM exceptions LIMIT 1"))
            original = json.loads(
                db.scalar("SELECT original_json FROM order_inputs WHERE record_id='ORD-002'")
            )
            self.assertEqual(original["amount"], "oops")
        page = self.client.get(response.headers["location"])
        for text in (
            "7 orders checked",
            "2 passed",
            "5 flagged orders",
            "8 issues found",
            "Excel row 8",
            "quantity: enter a positive",
            "2026-02-30",
            "Manual correction needed",
        ):
            self.assertIn(text, page.text)

    def test_missing_or_ambiguous_columns_leave_no_task_or_file(self):
        for headers in (FIELDS[:-1], (*FIELDS, "订单号"), ("Title",)):
            response = self.upload(data=workbook_bytes([headers, order_row()]))
            self.assertEqual(response.status_code, 400)
            self.assert_empty()

    def test_reordered_chinese_headers_with_leading_blanks(self):
        headers = ("订单日期", "金额", "单价", "数量", "客户编号", "客户名称", "订单号")
        data = workbook_bytes([(None,), headers, tuple(reversed(order_row("中文-001")))])
        self.assertEqual(self.upload(data=data).status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT header_row FROM task_validations"), 2)
            self.assertEqual(db.scalar("SELECT order_id FROM order_inputs"), "中文-001")
            self.assertEqual(db.scalar("SELECT outcome FROM source_records"), "passed")

    def test_accept_applies_calculation_and_preserves_original_file_and_values(self):
        data = workbook_bytes([FIELDS, order_row(amount=19)])
        path = self.upload(data=data).headers["location"]
        endpoint = path + "/exceptions/ORD-001/decisions"
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    endpoint,
                    data={"action": "accept", "decision_id": "ACCEPT-1"},
                    follow_redirects=False,
                ).status_code,
                303,
            )
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT amount FROM source_records"), 20)
            self.assertEqual(db.scalar("SELECT status FROM exceptions"), "accepted")
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM decisions"), 1)
            self.assertEqual(
                json.loads(db.scalar("SELECT original_json FROM order_inputs"))["amount"], "19"
            )
        self.assertEqual(self.client.get(path + "/source").content, data)
        self.assertIn("Proceed</button>", self.client.get(path).text)

    def test_edit_rechecks_all_fields_and_rolls_back_invalid_correction(self):
        data = workbook_bytes([FIELDS, order_row(quantity=0, customer_id=None)])
        path = self.upload(data=data).headers["location"]
        endpoint = path + "/exceptions/ORD-001/decisions"
        bad = self.client.post(endpoint, data={"action": "edit", "field_quantity": "2"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("customer_id: required", bad.text)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM decisions"), 0)
            self.assertEqual(db.scalar("SELECT status FROM exceptions"), "unresolved")
            self.assertEqual(
                json.loads(db.scalar("SELECT current_json FROM order_inputs"))["quantity"], "0"
            )
        good = self.client.post(
            endpoint,
            data={"action": "edit", "field_quantity": "2", "field_customer_id": "C-99"},
            follow_redirects=False,
        )
        self.assertEqual(good.status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT customer_id FROM source_records"), "C-99")
            self.assertEqual(db.scalar("SELECT status FROM exceptions"), "manual")

    def test_duplicate_order_ids_can_be_fixed_without_colliding_record_keys(self):
        path = self.upload(data=workbook_bytes([FIELDS, order_row(), order_row()])).headers[
            "location"
        ]
        first = path + "/exceptions/ORD-001/decisions"
        self.assertEqual(
            self.client.post(first, data={"action": "edit", "value": "A"}).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                first, data={"action": "edit", "value": "NEW"}, follow_redirects=False
            ).status_code,
            303,
        )
        second = path + "/exceptions/ORD-002/decisions"
        self.assertEqual(
            self.client.post(
                second, data={"action": "edit", "value": "A"}, follow_redirects=False
            ).status_code,
            303,
        )
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM exceptions WHERE status='manual'"), 2)

    def test_isolation_covers_validation_and_decisions_not_just_downloads(self):
        path = self.upload(data=mixed_workbook()).headers["location"]
        self.login("B")
        for endpoint in (path + "/validate", path + "/exceptions/ORD-002/decisions"):
            self.assertEqual(self.client.post(endpoint, data={"action": "skip"}).status_code, 404)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM decisions"), 0)

    def test_existing_ready_task_can_be_validated_once_and_restart_keeps_results(self):
        with patch("flowremote.control_plane.uploads.save_analysis"):
            path = self.upload(data=mixed_workbook()).headers["location"]
        self.assertIn("Validate uploaded orders", self.client.get(path).text)
        for _ in range(2):
            self.assertEqual(
                self.client.post(path + "/validate", follow_redirects=False).status_code, 303
            )
        self.client.post(path + "/exceptions/ORD-002/decisions", data={"action": "skip"})
        self.client.post(path + "/validate")
        with TestClient(create_app(self.url, "upload-test", self.uploads)) as restarted:
            self.login(client=restarted)
            self.assertIn("8 issues found", restarted.get(path).text)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM source_records"), 7)
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM task_validations"), 1)
            self.assertEqual(
                db.scalar("SELECT status FROM exceptions WHERE record_id='ORD-002'"), "skipped"
            )

    def test_existing_bad_headers_stay_ready_without_partial_results(self):
        path = self.upload().headers["location"]
        with Database(self.url) as db:
            db.execute("DELETE FROM task_validations")
            db.execute("DELETE FROM order_inputs")
            db.execute("DELETE FROM source_records")
            db.execute("UPDATE tasks SET status='ready'")
            file = self.uploads / db.scalar("SELECT storage_name FROM task_uploads")
        file.write_bytes(workbook_bytes([("Wrong",), (1,)]))
        self.assertEqual(self.client.post(path + "/validate").status_code, 400)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT status FROM tasks"), "ready")
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM source_records"), 0)

    def test_analysis_failure_rolls_back_the_whole_upload(self):
        def fail_after_rows(*args):
            save_analysis(*args)
            raise RuntimeError("failed after inserting rows")

        with (
            patch("flowremote.control_plane.uploads.save_analysis", side_effect=fail_after_rows),
            self.assertRaises(RuntimeError),
        ):
            self.upload(data=mixed_workbook())
        self.assert_empty()
        with Database(self.url) as db:
            for table in ("source_records", "order_inputs", "exceptions", "task_validations"):
                self.assertEqual(db.scalar(f"SELECT COUNT(*) FROM {table}"), 0)

    def test_more_than_100_exceptions_keep_the_gate_closed_on_every_page(self):
        path = self.upload(
            data=workbook_bytes([FIELDS] + [order_row(str(i), quantity=0) for i in range(101)])
        ).headers["location"]
        page = self.client.get(path + "?page=2")
        self.assertIn("Page 2 of 2", page.text)
        self.assertIn("101 unresolved", page.text)
        self.assertIn("Excel row 102", page.text)

    def test_internal_ids_beyond_999_can_be_reviewed(self):
        rows = [FIELDS] + [order_row(str(i)) for i in range(999)] + [order_row("LAST", amount=1)]
        path = self.upload(data=workbook_bytes(rows)).headers["location"]
        self.assertEqual(
            self.client.post(
                path + "/exceptions/ORD-1000/decisions",
                data={"action": "accept"},
                follow_redirects=False,
            ).status_code,
            303,
        )

    def test_downloadable_template_can_be_uploaded_and_validated(self):
        response = self.client.get("/orders-template.xlsx")
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(response.content), read_only=True)
        self.assertEqual(tuple(next(book.active.values)), FIELDS)
        book.close()
        self.assertEqual(self.upload(data=response.content).status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT outcome FROM source_records"), "passed")
