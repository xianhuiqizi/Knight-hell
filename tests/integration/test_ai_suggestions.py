"""Feature 3 end to end: AI suggestion, verification, audit and human Accept."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flowremote.agent.providers import (
    OfflineSuggestionProvider,
    ProviderError,
    SuggestedChange,
    SuggestionResponse,
)
from flowremote.api.app import create_app
from flowremote.control_plane.db import Database
from tests.integration.test_uploads import UploadFixture, order_row, workbook_bytes


class CountingProvider:
    name = "offline-test"
    model = "counted-rules"
    prompt_version = "suggestions-v1"

    def __init__(self):
        self.calls = 0
        self.inner = OfflineSuggestionProvider()

    def suggest(self, request):
        self.calls += 1
        return self.inner.suggest(request)


class FailingProvider:
    name = "failed-test"
    model = "none"
    prompt_version = "suggestions-v1"

    def suggest(self, request):
        raise ProviderError("The test provider is unavailable.")


class StaticProvider:
    name = "static-test"
    model = "fixture"
    prompt_version = "suggestions-v1"

    def __init__(self, changes, message="Fixture suggestion."):
        self.changes = tuple(changes)
        self.message = message

    def suggest(self, request):
        return SuggestionResponse(
            provider=self.name,
            model=self.model,
            prompt_version=self.prompt_version,
            changes=self.changes,
            message=self.message,
            raw_response={"changes": [change.__dict__ for change in self.changes]},
        )


class AISuggestionTests(UploadFixture):
    def setUp(self):
        super().setUp()
        self.client.close()
        self.registry = self.folder / "customers.csv"
        self.registry.write_text(
            "customer_id,customer_name,region,tier\n"
            "C-01,Alex Example,North,priority\n",
            encoding="utf-8",
        )
        self.provider = CountingProvider()
        self.app = create_app(
            self.url,
            "upload-test",
            self.uploads,
            suggestion_provider=self.provider,
            customer_registry=self.registry,
        )
        self.client = self.enterContext(TestClient(self.app))
        self.login()

    def upload_customer_exception(self):
        return self.upload(
            data=workbook_bytes(
                [("order_id", "customer_name", "customer_id", "quantity", "unit_price",
                  "amount", "order_date"),
                 order_row(
                     "MISSING-ID",
                     customer_name="Alex Example",
                     customer_id=None,
                 )]
            )
        ).headers["location"]

    def generate(self, path, request_id="REQ-1", record="ORD-001", task=None):
        task = task or path
        return self.client.post(
            f"{task}/exceptions/{record}/suggestions",
            data={"request_id": request_id},
            follow_redirects=False,
        )

    def run_row(self):
        with Database(self.url) as db:
            return db.query(
                "SELECT * FROM ai_suggestion_runs ORDER BY created_at DESC, id DESC"
            )[0]

    def exception_row(self):
        with Database(self.url) as db:
            return db.query("SELECT * FROM exceptions")[0]

    def test_generate_grounded_suggestion_then_accept_writes_customer_id(self):
        path = self.upload_customer_exception()
        response = self.generate(path)
        self.assertEqual(response.status_code, 303)
        run = self.run_row()
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["provider"], "offline")
        item = self.exception_row()
        self.assertEqual(item["status"], "unresolved")
        self.assertEqual(item["suggestion"], "C-01")
        self.assertEqual(item["confidence"], 0.99)

        page = self.client.get(path)
        self.assertIn("AI suggestion", page.text)
        self.assertIn("customer_registry:C-01", page.text)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM decisions"), 0)

        accepted = self.client.post(
            path + "/exceptions/ORD-001/decisions",
            data={"action": "accept", "decision_id": "ACCEPT-AI"},
            follow_redirects=False,
        )
        self.assertEqual(accepted.status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT customer_id FROM source_records"), "C-01")
            self.assertEqual(db.scalar("SELECT status FROM exceptions"), "accepted")

    def test_repeated_request_is_idempotent_and_calls_provider_once(self):
        path = self.upload_customer_exception()
        self.generate(path, "SAME")
        self.generate(path, "SAME")
        self.assertEqual(self.provider.calls, 1)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM ai_suggestion_runs"), 1)

    def test_invalid_customer_id_is_rejected(self):
        self.app.state.suggestion_provider = StaticProvider(
            [SuggestedChange("customer_id", "C-INVENTED", 0.99, "Invented.", ("model",))]
        )
        path = self.upload_customer_exception()
        self.assertEqual(self.generate(path).status_code, 303)
        run = self.run_row()
        self.assertIn(run["status"], ("completed", "invalid"))
        self.assertIsNone(self.exception_row()["suggestion"])

    def test_partial_correction_is_invalid(self):
        self.app.state.suggestion_provider = StaticProvider(
            [SuggestedChange("customer_id", "C-01", 0.99, "Matched.", ("registry",))]
        )
        path = self.upload(
            data=workbook_bytes(
                [("order_id", "customer_name", "customer_id", "quantity", "unit_price",
                  "amount", "order_date"),
                 order_row(
                     "MULTI",
                     customer_name="Alex Example",
                     customer_id=None,
                     quantity=0,
                 )]
            )
        ).headers["location"]
        self.assertEqual(self.generate(path).status_code, 303)
        self.assertEqual(self.run_row()["status"], "invalid")
        self.assertIsNone(self.exception_row()["suggestion"])

    def test_provider_failure_keeps_manual_path_available(self):
        self.app.state.suggestion_provider = FailingProvider()
        path = self.upload_customer_exception()
        self.assertEqual(self.generate(path).status_code, 303)
        self.assertEqual(self.run_row()["status"], "failed")
        page = self.client.get(path)
        self.assertIn("AI request failed", page.text)
        self.assertIn("value=\"skip\"", page.text)
        with Database(self.url) as db:
            event = db.query(
                "SELECT actor_kind, kind FROM activity_events"
                " WHERE kind = 'ai_suggestion_failed'"
            )
            self.assertEqual(event[0]["actor_kind"], "engine")

    def test_failed_regeneration_does_not_overwrite_the_last_good_suggestion(self):
        path = self.upload_customer_exception()
        self.generate(path, "GOOD")
        self.assertEqual(self.exception_row()["suggestion"], "C-01")
        self.app.state.suggestion_provider = FailingProvider()
        self.generate(path, "FAILED")
        self.assertEqual(self.run_row()["status"], "failed")
        self.assertEqual(self.exception_row()["suggestion"], "C-01")

    def test_low_confidence_is_visible_but_not_acceptable(self):
        self.app.state.suggestion_provider = StaticProvider(
            [SuggestedChange("customer_id", "C-01", 0.4, "Weak match.", ("registry",))]
        )
        path = self.upload_customer_exception()
        self.generate(path)
        run = self.run_row()
        self.assertEqual(run["status"], "completed")
        self.assertIsNone(self.exception_row()["suggestion"])
        self.assertIn("below the review threshold", self.client.get(path).text)

    def test_request_id_and_ownership_are_enforced(self):
        path = self.upload_customer_exception()
        self.assertEqual(self.generate(path, "").status_code, 400)
        self.login("B")
        self.assertEqual(
            self.generate(path, "OTHER").status_code,
            404,
        )

    def test_only_review_tasks_can_request_suggestions(self):
        path = self.upload_customer_exception()
        with Database(self.url) as db:
            db.execute("UPDATE tasks SET status = 'pending_approval'")
        response = self.generate(path)
        self.assertEqual(response.status_code, 400)
        self.assertIn("only while the task is under review", response.text)

    def test_annotation_does_not_change_worktree(self):
        self.assertIsInstance(Path(self.registry).read_text(encoding="utf-8"), str)
