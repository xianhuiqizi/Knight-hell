"""End-to-end multi-source cleanup: upload → detect → normalize → download."""

from __future__ import annotations

import secrets
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from flowremote.agent.normalization_ai import NormalizationAISuggestion
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
        response = self.client.post(f"/tasks/{task_id}/normalize/start", follow_redirects=False)
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

    def issue_rows(self, task_id, status=None):
        with self.db() as db:
            sql = "SELECT * FROM normalization_issues WHERE task_id = ?"
            params = [task_id]
            if status:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY issue_type, source_file, source_row"
            return [dict(row) for row in db.query(sql, tuple(params))]

    def suggest_issue(self, task_id, issue_id):
        response = self.client.post(
            f"/tasks/{task_id}/normalize/issues/{issue_id}/ai-suggest",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200, response.text[:800])
        return response.json()

    def confirm_issue(self, task_id, issue_id, changes, decision_id=None):
        return self.client.post(
            f"/tasks/{task_id}/normalize/issues/{issue_id}/confirm",
            json={"decision_id": decision_id or secrets.token_hex(8), "changes": changes},
        )

    def skip_issue(
        self, task_id, issue_id, reason="Needs a source-system follow-up.", decision_id=None
    ):
        return self.client.post(
            f"/tasks/{task_id}/normalize/issues/{issue_id}/skip",
            json={"reason": reason, "decision_id": decision_id or secrets.token_hex(8)},
        )

    def resolve_all(self, task_id, *, skip_ids=()):
        skip_ids = set(skip_ids)
        for _ in range(20):
            unresolved = self.issue_rows(task_id, "unresolved")
            if not unresolved:
                break
            issue = unresolved[0]
            if issue["issue_type"] == "file_error" or issue["id"] in skip_ids:
                response = self.skip_issue(task_id, issue["id"])
                self.assertEqual(response.status_code, 200, response.text[:800])
                continue
            suggestion = self.suggest_issue(task_id, issue["id"])
            fields = suggestion.get("fields") or {}
            response = self.confirm_issue(task_id, issue["id"], fields)
            self.assertEqual(response.status_code, 200, response.text[:800])
        self.assertEqual(self.issue_rows(task_id, "unresolved"), [])
        finish = self.client.post(f"/tasks/{task_id}/normalize/finish", follow_redirects=False)
        self.assertEqual(finish.status_code, 303, finish.text[:800])
        return finish

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
            "01_orders_header_offset.xlsx",
            "02_orders_thousand_cny.xlsx",
            "03_orders_shuffled.csv",
            "04_orders_second_sheet.xlsx",
            "05_orders_warehouse_boxes.xlsx",
            "06_orders_chinese_aliases.xlsx",
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
            response = self.upload([("a.csv", b"x" * 600), ("b.csv", b"y" * 600)])
        self.assertEqual(response.status_code, 413)
        self.assertIn("20 MB", response.text)
        with self.db() as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 0)

    def test_cleanup_page_exposes_the_optional_ai_connection(self):
        task_id = self.task_id(self.upload())
        page = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("data-ai-connection-bar", page.text)
        self.assertIn("Test online connection", page.text)
        self.assertIn("Offline Demo AI", page.text)
        self.assertIn("data-ai-settings-open", page.text)

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
        cancel = self.client.post(f"/tasks/{task_id}/normalize/cancel", follow_redirects=False)
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
        self.assertIn("Human review", page.text)
        self.assertIn("AI suggestion", page.text)
        self.assertIn("Complete cleaning (6 left)", page.text)
        self.assertIn("Download unlocks after Complete cleaning", page.text)
        self.assertNotIn(f'href="/tasks/{task_id}/normalize/download"', page.text)
        self.assertIn("174", page.text)
        self.assertIn("36", page.text)
        self.assertIn("Missing value", page.text)
        self.assertIn("Unit conflict", page.text)
        self.assertIn("Cross-file conflict", page.text)

        blocked = self.client.get(f"/tasks/{task_id}/normalize/download")
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("Resolve every confirmation item", blocked.text)

        self.resolve_all(task_id)
        snapshot = self.client.get(
            f"/tasks/{task_id}/normalize/status", headers={"Accept": "application/json"}
        ).json()
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["unresolved"], 0)
        self.assertEqual(snapshot["confirmed"], 6)
        self.assertEqual(snapshot["skipped"], 0)
        page = self.client.get(f"/tasks/{task_id}")
        self.assertIn("Review complete", page.text)
        self.assertIn("Download cleaned .xlsx", page.text)

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
            [
                "order_id",
                "customer_name",
                "customer_id",
                "quantity",
                "unit",
                "unit_price",
                "amount",
                "order_date",
                "source_file",
                "source_row",
            ],
        )
        self.assertEqual(normalized.max_row, 37)
        self.assertEqual(workbook["unresolved"].max_row, 1)
        methods = {
            workbook["changes"].cell(row=row, column=6).value
            for row in range(2, workbook["changes"].max_row + 1)
        }
        self.assertEqual(methods, {"rule", "human"})
        self.assertGreater(workbook["changes"].max_row, 231)

    def test_activity_timeline_contains_all_stages(self):
        task_id = self.completed_task()
        page = self.client.get(f"/tasks/{task_id}")
        for label in ("Upload", "Start", "Detect", "Map", "Normalize", "Complete"):
            self.assertIn(label, page.text)
        export = self.client.get(f"/tasks/{task_id}/activity.json")
        self.assertEqual(export.status_code, 200)
        kinds = {event["kind"] for event in export.json()["events"]}
        for kind in (
            "normalize_upload",
            "normalize_started",
            "normalize_detect",
            "normalize_map",
            "normalize_normalize",
            "normalize_complete",
        ):
            self.assertIn(kind, kinds)
        normalize_event = next(
            event for event in export.json()["events"] if event["kind"] == "normalize_normalize"
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
        self.resolve_all(task_id)
        other = self.enterContext(TestClient(self.app))
        self.login("B", client=other)
        for path in (
            f"/tasks/{task_id}",
            f"/tasks/{task_id}/normalize/status",
            f"/tasks/{task_id}/normalize/download",
        ):
            self.assertEqual(other.get(path).status_code, 404, path)
        self.assertEqual(other.post(f"/tasks/{task_id}/normalize/tick").status_code, 404)

        admin = self.enterContext(TestClient(self.app))
        self.login("Admin", client=admin)
        self.assertEqual(admin.get(f"/tasks/{task_id}").status_code, 200)
        self.assertEqual(admin.get(f"/tasks/{task_id}/normalize/download").status_code, 200)

    def test_status_json_requires_sign_in(self):
        self.client.post("/logout")
        task_id = "TASK-does-not-matter"
        response = self.client.get(f"/tasks/{task_id}/normalize/status")
        self.assertEqual(response.status_code, 401)

    # -- Phase D: human review and AI advice --------------------------
    def test_review_page_exposes_ai_option_and_finish_gate(self):
        task_id = self.completed_task()
        page = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Human review", page.text)
        self.assertIn("AI suggestion", page.text)
        self.assertIn("Complete cleaning (6 left)", page.text)
        self.assertIn("Download unlocks after Complete cleaning", page.text)
        self.assertEqual(page.text.count("data-ai-suggest"), 6)
        self.assertEqual(page.text.count("data-issue-form"), 6)
        self.assertIn("data-skip-toggle", page.text)
        self.assertIn("data-issue-error", page.text)

        blocked = self.client.post(f"/tasks/{task_id}/normalize/finish", follow_redirects=False)
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("6 item(s) still need confirmation", blocked.text)
        snapshot = self.client.get(
            f"/tasks/{task_id}/normalize/status", headers={"Accept": "application/json"}
        ).json()
        self.assertEqual(snapshot["status"], "needs_review")
        self.assertEqual(snapshot["review_ready"], False)

    def test_offline_ai_suggestion_is_validated_and_confirmable(self):
        task_id = self.completed_task()
        issues = self.issue_rows(task_id, "unresolved")
        missing = next(
            row
            for row in issues
            if row["issue_type"] == "missing_value" and "customer_id" in row["field"]
        )
        data = self.suggest_issue(task_id, missing["id"])
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["source"], "offline")
        self.assertEqual(data["source_label"], "Offline Demo AI")
        self.assertTrue(data["fields"].get("customer_id", "").startswith("C-"))
        self.assertGreater(data["confidence"], 0)
        with self.db() as db:
            stored = db.query(
                "SELECT ai_source, ai_suggestion_json FROM normalization_issues WHERE id = ?",
                (missing["id"],),
            )[0]
            self.assertIn("Offline Demo AI", stored["ai_source"])
            self.assertIn("customer_id", stored["ai_suggestion_json"])
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM activity_events WHERE task_id = ?"
                    " AND kind = 'normalize_ai_suggestion'",
                    (task_id,),
                ),
                1,
            )

        decision_id = secrets.token_hex(8)
        first = self.confirm_issue(task_id, missing["id"], data["fields"], decision_id=decision_id)
        self.assertEqual(first.status_code, 200, first.text[:800])
        self.assertEqual(first.json()["remaining"], 5)
        replay = self.confirm_issue(task_id, missing["id"], data["fields"], decision_id=decision_id)
        self.assertEqual(replay.status_code, 200, replay.text[:800])
        with self.db() as db:
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalization_decisions WHERE issue_id = ?",
                    (missing["id"],),
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    "SELECT status FROM normalization_issues WHERE id = ?",
                    (missing["id"],),
                ),
                "resolved",
            )
            self.assertEqual(
                db.scalar(
                    "SELECT customer_id FROM normalized_records WHERE task_id = ?"
                    " AND order_id = ? AND is_primary = 1",
                    (task_id, missing["order_id"]),
                ),
                data["fields"]["customer_id"],
            )

    @patch.object(normalization_routes, "suggest_with_ai")
    def test_online_ai_suggestion_uses_saved_provider(self, fake_suggest):
        fake_suggest.return_value = NormalizationAISuggestion(
            fields={"customer_id": "C-2104"},
            confidence=0.93,
            reason="One other cleaned row for Delta Works uses C-2104.",
            evidence=("customer name matches C-2104",),
            provider="openai",
            model="deepseek-flash",
        )
        saved = self.client.post(
            "/settings/ai",
            data={
                "provider": "openai",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com",
                "api_key": "not-a-real-key",
            },
            follow_redirects=True,
        )
        self.assertEqual(saved.status_code, 200)
        task_id = self.completed_task()
        issues = self.issue_rows(task_id, "unresolved")
        missing = next(
            row
            for row in issues
            if row["issue_type"] == "missing_value" and "customer_id" in row["field"]
        )
        data = self.suggest_issue(task_id, missing["id"])
        self.assertEqual(data["source"], "openai")
        self.assertEqual(data["source_label"], "AI · deepseek-flash")
        self.assertEqual(data["fields"], {"customer_id": "C-2104"})
        self.assertIsNone(data["warning"])
        self.assertTrue(fake_suggest.called)
        ai_context = fake_suggest.call_args.args[0]
        self.assertTrue(
            any(
                candidate["customer_id"] == "C-2104"
                for candidate in ai_context["grounded_candidates"]
            )
        )
        self.assertEqual(fake_suggest.call_args.kwargs["model"], "deepseek-flash")
        self.assertTrue(fake_suggest.call_args.kwargs["api_key"])

    def test_ai_suggestion_values_survive_confirming_another_card(self):
        task_id = self.completed_task()
        issues = self.issue_rows(task_id, "unresolved")
        missing_id = next(
            row for row in issues
            if row["issue_type"] == "missing_value" and "customer_id" in row["field"]
        )
        missing_qty = next(
            row for row in issues
            if row["issue_type"] == "missing_value" and "quantity" in row["field"]
        )
        id_advice = self.suggest_issue(task_id, missing_id["id"])
        qty_advice = self.suggest_issue(task_id, missing_qty["id"])
        confirmed = self.confirm_issue(task_id, missing_id["id"], id_advice["fields"])
        self.assertEqual(confirmed.status_code, 200, confirmed.text[:800])
        page = self.client.get(f"/tasks/{task_id}")
        block = page.text.split(f'id="issue-{missing_qty["id"]}"', 1)[1].split(
            "</article>", 1
        )[0]
        self.assertIn('name="quantity"', block)
        self.assertIn(f'value="{qty_advice["fields"]["quantity"]}"', block)
        self.assertIn("Last AI advice", block)

    @patch.object(normalization_routes, "suggest_with_ai")
    def test_online_model_empty_fields_falls_back_with_specific_warning(self, fake_suggest):
        fake_suggest.return_value = NormalizationAISuggestion(
            fields={},
            confidence=0.3,
            reason="No grounded candidate.",
            evidence=(),
            provider="openai",
            model="deepseek-flash",
        )
        self.client.post(
            "/settings/ai",
            data={
                "provider": "openai",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com",
                "api_key": "not-a-real-key",
            },
            follow_redirects=True,
        )
        task_id = self.completed_task()
        issue = next(
            row for row in self.issue_rows(task_id, "unresolved")
            if row["issue_type"] == "missing_value" and "customer_id" in row["field"]
        )
        data = self.suggest_issue(task_id, issue["id"])
        self.assertEqual(data["source"], "offline")
        self.assertIn("replied, but returned no field", data["warning"])
        self.assertIn("grounded_candidates", fake_suggest.call_args.args[0])
        with self.db() as db:
            stored = db.query(
                "SELECT ai_suggestion_json FROM normalization_issues WHERE id = ?",
                (issue["id"],),
            )[0]
            self.assertIn("replied, but returned no field", stored["ai_suggestion_json"])

    @patch.object(normalization_routes, "suggest_with_ai")
    def test_online_ai_cannot_invent_a_customer_id(self, fake_suggest):
        fake_suggest.return_value = NormalizationAISuggestion(
            fields={"customer_id": "C-9999"},
            confidence=0.99,
            reason="Invented ID",
            evidence=(),
            provider="openai",
            model="deepseek-flash",
        )
        self.client.post(
            "/settings/ai",
            data={
                "provider": "openai",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com",
                "api_key": "not-a-real-key",
            },
            follow_redirects=True,
        )
        task_id = self.completed_task()
        issue = next(
            row
            for row in self.issue_rows(task_id, "unresolved")
            if row["issue_type"] == "missing_value" and "customer_id" in row["field"]
        )
        data = self.suggest_issue(task_id, issue["id"])
        self.assertEqual(data["source"], "offline")
        self.assertIn("not present in this batch", data["warning"])
        self.assertNotEqual(data["fields"].get("customer_id"), "C-9999")

    def test_confirm_rejects_arithmetic_mismatch(self):
        task_id = self.completed_task()
        issue = next(
            row
            for row in self.issue_rows(task_id, "unresolved")
            if row["issue_type"] == "cross_file_conflict"
        )
        response = self.confirm_issue(task_id, issue["id"], {"amount": "999999.00"})
        self.assertEqual(response.status_code, 400, response.text[:800])
        self.assertIn("Amount must equal", response.json()["error"])
        with self.db() as db:
            self.assertEqual(
                db.scalar(
                    "SELECT status FROM normalization_issues WHERE id = ?",
                    (issue["id"],),
                ),
                "unresolved",
            )

    def test_skip_keeps_unresolved_export_and_excludes_record(self):
        task_id = self.completed_task()
        issue = self.issue_rows(task_id, "unresolved")[0]
        order_id = issue["order_id"]
        skipped = self.skip_issue(
            task_id, issue["id"], reason="Vendor must confirm the source value."
        )
        self.assertEqual(skipped.status_code, 200, skipped.text[:800])
        self.assertEqual(skipped.json()["remaining"], 5)
        with self.db() as db:
            self.assertEqual(
                db.scalar(
                    "SELECT COUNT(*) FROM normalized_records WHERE task_id = ? AND is_primary = 1",
                    (task_id,),
                ),
                35,
            )
        self.resolve_all(task_id)
        snapshot = self.client.get(
            f"/tasks/{task_id}/normalize/status", headers={"Accept": "application/json"}
        ).json()
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["confirmed"], 5)
        self.assertEqual(snapshot["skipped"], 1)
        self.assertEqual(snapshot["normalized_records"], 35)
        page = self.client.get(f"/tasks/{task_id}")
        self.assertIn("Review complete", page.text)
        self.assertIn("Skipped:", page.text)

        download = self.client.get(f"/tasks/{task_id}/normalize/download")
        self.assertEqual(download.status_code, 200)
        workbook = load_workbook(BytesIO(download.content))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook["normalized"].max_row, 36)
        self.assertEqual(workbook["unresolved"].max_row, 2)
        normalized_orders = {
            workbook["normalized"].cell(row=row, column=1).value
            for row in range(2, workbook["normalized"].max_row + 1)
        }
        self.assertNotIn(order_id, normalized_orders)
        headers = [cell.value for cell in workbook["unresolved"][1]]
        reason_column = headers.index("reason") + 1
        self.assertIn(
            "Vendor must confirm",
            workbook["unresolved"].cell(row=2, column=reason_column).value,
        )

    def test_skip_without_reason_uses_a_default_audit_reason(self):
        task_id = self.completed_task()
        issue = self.issue_rows(task_id, "unresolved")[0]
        response = self.skip_issue(task_id, issue["id"], reason="")
        self.assertEqual(response.status_code, 200, response.text[:800])
        self.assertEqual(response.json()["status"], "skipped")
        with self.db() as db:
            self.assertEqual(
                db.scalar(
                    "SELECT status FROM normalization_issues WHERE id = ?",
                    (issue["id"],),
                ),
                "skipped",
            )
            self.assertEqual(
                db.scalar(
                    "SELECT skip_reason FROM normalization_issues WHERE id = ?",
                    (issue["id"],),
                ),
                "No reason provided.",
            )

    def test_finish_after_all_actions_timeline_has_human_and_ai(self):
        task_id = self.completed_task()
        self.resolve_all(task_id)
        with self.db() as db:
            kinds = {
                row["kind"]
                for row in db.query(
                    "SELECT DISTINCT kind FROM activity_events WHERE task_id = ?", (task_id,)
                )
            }
        self.assertIn("normalize_ai_suggestion", kinds)
        self.assertIn("normalize_human_confirm", kinds)
        self.assertIn("normalize_review_complete", kinds)
        self.assertEqual(self.client.get(f"/tasks/{task_id}/normalize/download").status_code, 200)

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
        task_id = self.completed_task()
        response = self.client.get(f"/tasks/{task_id}/normalize/download")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Resolve every confirmation item", response.text)
        self.assertIn("Human review", response.text)
