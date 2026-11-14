"""End-to-end multi-source cleanup: upload → detect → normalize → download."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from flowremote.api.app import create_app
from flowremote.api.routes import normalization as normalization_routes
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database
from flowremote.devtools.demoday_data import demo_sources


class NormalizeFixture(TestCase):
    def setUp(self):
        root = PROJECT_ROOT / "data" / "runtime" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.uploads = folder / "uploads"
        self.url = f"sqlite:///{(folder / 'normalize.db').as_posix()}"
        with Database(self.url) as db:
            db.apply_migrations()
            for name, role in (("A", "operator"), ("B", "operator"), ("Admin", "admin")):
                create_user(
                    db,
                    name=name,
                    email=f"{name.lower()}@example.com",
                    password="password123",
                    user_id=name,
                    role=role,
                )
        self.app = create_app(self.url, "normalize-test-secret", self.uploads)
        self.client = self.enterContext(TestClient(self.app))
        self.login("A")

    def login(self, who="A", client=None):
        client = client or self.client
        response = client.post(
            "/login",
            data={"email": f"{who.lower()}@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def upload(self, files=None, name="Demo cleanup"):
        files = files if files is not None else list(demo_sources())
        return self.client.post(
            "/tasks/normalize",
            data={"name": name},
            files=[("files", (filename, data)) for filename, data in files],
            follow_redirects=False,
        )

    def task_id(self, response):
        self.assertEqual(response.status_code, 303, response.text[:500])
        return response.headers["location"].split("?", 1)[0].rsplit("/", 1)[-1]

    def db(self):
        return Database(self.url)

    def start_and_tick(self, task_id, limit=80):
        response = self.client.post(
            f"/tasks/{task_id}/normalize/start", follow_redirects=False
        )
        self.assertIn(response.status_code, (303, 400))
        last = None
        for _ in range(limit):
            response = self.client.post(
                f"/tasks/{task_id}/normalize/tick", headers={"Accept": "application/json"}
            )
            self.assertEqual(response.status_code, 200, response.text[:500])
            last = response.json()
            if last["status"] != "running":
                return last
        raise AssertionError(f"normalization did not finish: {last}")

    def completed_task(self):
        response = self.upload()
        task_id = self.task_id(response)
        self.start_and_tick(task_id)
        return task_id

    # -- upload ---------------------------------------------------------
    def test_six_files_create_a_batch_and_show_entries(self):
        response = self.upload()
        task_id = self.task_id(response)
        page = self.client.get(response.headers["location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("6 files uploaded", page.text)
        self.assertIn("6/6 recognized", page.text)
        self.assertIn("formats recognized", page.text)
        self.assertIn("Start cleaning", page.text)
        self.assertIn("01_orders_header_offset.xlsx", page.text)
        self.assertIn("06_orders_chinese_aliases.xlsx", page.text)
        for filename in (
            "01_orders_header_offset.xlsx", "02_orders_thousand_cny.xlsx",
            "03_orders_shuffled.csv", "04_orders_second_sheet.xlsx",
            "05_orders_warehouse_boxes.xlsx", "06_orders_chinese_aliases.xlsx",
        ):
            self.assertIn(filename, page.text)
        with self.db() as db:
            task = db.query("SELECT task_mode, status FROM tasks WHERE id = ?", (task_id,))[0]
            self.assertEqual((task["task_mode"], task["status"]), ("normalize", "ready"))
            self.assertEqual(
                db.scalar("SELECT COUNT(*) FROM normalization_files WHERE task_id = ?", (task_id,)),
                6,
            )
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalization_files"
                    " WHERE task_id = ? AND status = 'mapped'",
                    (task_id,),
                ),
                6,
            )
            batch = db.query(
                "SELECT stage, raw_records FROM normalization_batches WHERE task_id = ?",
                (task_id,),
            )[0]
            self.assertEqual((batch["stage"], batch["raw_records"]), ("normalize", 174))

    def test_more_than_six_files_is_rejected(self):
        files = list(demo_sources()) + [("extra.csv", b"a,b\n1,2\n")]
        response = self.upload(files)
        self.assertEqual(response.status_code, 400)
        self.assertIn("6", response.text)
        with self.db() as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 0)

    def test_combined_size_limit_is_enforced(self):
        with patch.object(normalization_routes, "MAX_TOTAL_BYTES", 1000):
            response = self.upload(
                [("a.csv", b"x" * 600), ("b.csv", b"y" * 600)]
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("20 MB", response.text)
        with self.db() as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 0)

    def test_wrong_extension_is_rejected_readably(self):
        response = self.upload([("notes.txt", b"hello")])
        self.assertEqual(response.status_code, 400)
        self.assertIn("not an .xlsx or .csv", response.text)
        with self.db() as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 0)

    # -- progress -------------------------------------------------------
    def test_progress_snapshot_has_current_file_counts_and_elapsed(self):
        task_id = self.task_id(self.upload())
        self.client.post(f"/tasks/{task_id}/normalize/start")
        response = self.client.post(
            f"/tasks/{task_id}/normalize/tick", headers={"Accept": "application/json"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["stage"], "normalize")
        self.assertEqual(data["total_files"], 6)
        self.assertEqual(data["phase_done"], 1)
        self.assertEqual(data["current_file"], "02_orders_thousand_cny.xlsx")
        self.assertEqual(data["recognized"], 6)
        self.assertGreaterEqual(data["percent"], 1)
        self.assertGreaterEqual(data["duration_ms"], 0)
        self.assertIn("stage_label", data)
        page = self.client.get(f"/tasks/{task_id}")
        self.assertIn("normalize-progress", page.text)
        self.assertIn("Current file", page.text)
        self.assertIn("Processed / total", page.text)

    def test_cancel_removes_partial_rows_and_allows_clean_restart(self):
        task_id = self.task_id(self.upload())
        self.client.post(f"/tasks/{task_id}/normalize/start")
        # Recognition and mapping happen at upload, so two ticks already create
        # normalized rows for two source files.
        for _ in range(2):
            self.client.post(
                f"/tasks/{task_id}/normalize/tick", headers={"Accept": "application/json"}
            )
        with self.db() as db:
            self.assertGreater(
                db.scalar("SELECT COUNT(*) FROM normalized_records WHERE task_id = ?", (task_id,)),
                0,
            )
        cancel = self.client.post(
            f"/tasks/{task_id}/normalize/cancel", follow_redirects=False
        )
        self.assertEqual(cancel.status_code, 303)
        with self.db() as db:
            for table in ("normalized_records", "normalization_changes", "normalization_issues"):
                self.assertEqual(
                    db.scalar(f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task_id,)),
                    0,
                    table,
                )
            self.assertEqual(
                db.scalar("SELECT status FROM normalization_batches WHERE task_id = ?", (task_id,)),
                "canceled",
            )
            self.assertEqual(
                db.scalar("SELECT status FROM tasks WHERE id = ?", (task_id,)), "ready"
            )
        page = self.client.get(f"/tasks/{task_id}")
        self.assertIn("Start cleaning", page.text)
        final = self.start_and_tick(task_id)
        self.assertEqual(final["status"], "needs_review")
        with self.db() as db:
            self.assertEqual(
                db.scalar("SELECT COUNT(*) FROM normalized_records WHERE task_id = ?", (task_id,)),
                174,
            )
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalized_records WHERE task_id = ? AND is_primary = 1",
                    (task_id,),
                ),
                36,
            )

    def test_start_is_idempotent_and_tick_after_finish_is_a_noop(self):
        task_id = self.task_id(self.upload())
        self.start_and_tick(task_id)
        with self.db() as db:
            before = db.query(
                "SELECT status, normalized_records, issue_count FROM normalization_batches"
                " WHERE task_id = ?",
                (task_id,),
            )[0]
        self.client.post(f"/tasks/{task_id}/normalize/start")
        response = self.client.post(
            f"/tasks/{task_id}/normalize/tick", headers={"Accept": "application/json"}
        )
        self.assertEqual(response.status_code, 200)
        with self.db() as db:
            after = db.query(
                "SELECT status, normalized_records, issue_count FROM normalization_batches"
                " WHERE task_id = ?",
                (task_id,),
            )[0]
            self.assertEqual(dict(before), dict(after))
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalized_records WHERE task_id = ?",
                    (task_id,),
                ),
                174,
            )

    # -- results and download ------------------------------------------
    def test_full_run_has_six_issues_and_three_sheet_download(self):
        task_id = self.completed_task()
        snapshot = self.client.get(
            f"/tasks/{task_id}/normalize/status", headers={"Accept": "application/json"}
        ).json()
        self.assertEqual(snapshot["status"], "needs_review")
        self.assertEqual(snapshot["percent"], 100)
        self.assertEqual(snapshot["raw_records"], 174)
        self.assertEqual(snapshot["normalized_records"], 36)
        self.assertEqual(snapshot["unresolved"], 6)
        with self.db() as db:
            types = {
                row["issue_type"]: row["n"]
                for row in db.query(
                    "SELECT issue_type, COUNT(*) AS n FROM normalization_issues"
                    " WHERE task_id = ? GROUP BY issue_type",
                    (task_id,),
                )
            }
        self.assertEqual(
            types,
            {"missing_value": 2, "unit_conflict": 2, "cross_file_conflict": 2},
        )
        page = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Needs your confirmation", page.text)
        self.assertIn("Download cleaned .xlsx", page.text)
        self.assertIn("174", page.text)
        self.assertIn("36", page.text)
        self.assertIn("Missing value", page.text)
        self.assertIn("Unit conflict", page.text)
        self.assertIn("Cross-file conflict", page.text)

        download = self.client.get(f"/tasks/{task_id}/normalize/download")
        self.assertEqual(download.status_code, 200)
        self.assertRegex(
            download.headers["content-disposition"],
            r'^attachment; filename="FlowRemote_normalized_\d{8}_\d{4}\.xlsx"$',
        )
        workbook = load_workbook(BytesIO(download.content))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["normalized", "changes", "unresolved"])
        normalized = workbook["normalized"]
        self.assertEqual(
            [cell.value for cell in normalized[1]],
            ["order_id", "customer_name", "customer_id", "quantity", "unit",
             "unit_price", "amount", "order_date", "source_file", "source_row"],
        )
        self.assertEqual(normalized.max_row, 37)
        self.assertEqual(workbook["changes"].max_row, 231)
        self.assertEqual(workbook["unresolved"].max_row, 7)
        methods = {
            workbook["changes"].cell(row=row, column=6).value
            for row in range(2, workbook["changes"].max_row + 1)
        }
        self.assertEqual(methods, {"rule"})
        issue_types = {
            workbook["unresolved"].cell(row=row, column=1).value
            for row in range(2, workbook["unresolved"].max_row + 1)
        }
        self.assertEqual(
            issue_types, {"missing_value", "unit_conflict", "cross_file_conflict"}
        )

    def test_activity_timeline_contains_all_stages(self):
        task_id = self.completed_task()
        page = self.client.get(f"/tasks/{task_id}")
        for label in ("Upload", "Start", "Detect", "Map", "Normalize", "Complete"):
            self.assertIn(label, page.text)
        export = self.client.get(f"/tasks/{task_id}/activity.json")
        self.assertEqual(export.status_code, 200)
        kinds = {event["kind"] for event in export.json()["events"]}
        for kind in (
            "normalize_upload", "normalize_started", "normalize_detect",
            "normalize_map", "normalize_normalize", "normalize_complete",
        ):
            self.assertIn(kind, kinds)
        normalize_event = next(
            event for event in export.json()["events"]
            if event["kind"] == "normalize_normalize"
        )
        self.assertGreater(normalize_event["payload"]["box_to_piece_conversions"], 0)
        self.assertGreater(normalize_event["payload"]["thousand_cny_conversions"], 0)

    def test_bad_file_is_isolated_and_other_file_still_normalizes(self):
        response = self.upload(
            [("good.xlsx", demo_sources()[0][1]), ("broken.xlsx", b"not a workbook")]
        )
        task_id = self.task_id(response)
        final = self.start_and_tick(task_id)
        self.assertIn(final["status"], ("needs_review", "complete"))
        with self.db() as db:
            statuses = {
                row["filename"]: row["status"]
                for row in db.query(
                    "SELECT filename, status FROM normalization_files WHERE task_id = ?",
                    (task_id,),
                )
            }
            self.assertEqual(statuses["good.xlsx"], "normalized")
            self.assertEqual(statuses["broken.xlsx"], "attention")
            self.assertGreater(
                db.scalar(
                    "SELECT COUNT(*) FROM normalized_records WHERE task_id = ? AND is_primary = 1",
                    (task_id,),
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalization_issues WHERE task_id = ?"
                    " AND issue_type = 'file_error'",
                    (task_id,),
                ),
                1,
            )
        page = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Needs attention", page.text)

    def test_other_owner_gets_404_and_admin_can_download(self):
        task_id = self.completed_task()
        other = self.enterContext(TestClient(self.app))
        self.login("B", client=other)
        for path in (
            f"/tasks/{task_id}",
            f"/tasks/{task_id}/normalize/status",
            f"/tasks/{task_id}/normalize/download",
        ):
            self.assertEqual(other.get(path).status_code, 404, path)
        self.assertEqual(
            other.post(f"/tasks/{task_id}/normalize/tick").status_code, 404
        )

        admin = self.enterContext(TestClient(self.app))
        self.login("Admin", client=admin)
        self.assertEqual(admin.get(f"/tasks/{task_id}").status_code, 200)
        self.assertEqual(admin.get(f"/tasks/{task_id}/normalize/download").status_code, 200)

    def test_status_json_requires_sign_in(self):
        self.client.post("/logout")
        task_id = "TASK-does-not-matter"
        response = self.client.get(f"/tasks/{task_id}/normalize/status")
        self.assertEqual(response.status_code, 401)

    def test_demo_enter_signs_in_a_seeded_account_without_registration(self):
        with self.db() as db:
            create_user(
                db,
                name="Demo Day Operator",
                email="demo@flowremote.dev",
                password="DemoDay2026!",
                user_id="USR-DEMO",
            )
        client = self.enterContext(TestClient(self.app))
        response = client.post("/demo/enter", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Tasks", home.text)

    def test_download_before_completion_is_refused_with_a_page(self):
        task_id = self.task_id(self.upload())
        response = self.client.get(f"/tasks/{task_id}/normalize/download")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Finish the normalization run", response.text)
        self.assertIn("Start cleaning", response.text)
