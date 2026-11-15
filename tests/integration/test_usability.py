"""Business behavior for the user feedback improvements, using isolated data."""

from __future__ import annotations

import json
import secrets
import time
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from flowremote.api.app import create_app
from flowremote.contracts.normalization import MAPPED_FIELDS
from flowremote.control_plane.ai_disclosure import review_ai_context
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import MIGRATIONS_DIR, Database
from flowremote.control_plane.normalization_jobs import (
    create_normalization_task,
    start_normalization,
)
from flowremote.control_plane.normalization_review import issue_context
from flowremote.devtools.demoday_data import demo_sources


@pytest.fixture
def workspace(tmp_path):
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    uploads = tmp_path / "uploads"
    with Database(url) as db:
        db.apply_migrations()
        for who in ("A", "B"):
            create_user(db, name=who, email=f"{who}@example.com", password="password123", user_id=who)
    app = create_app(url, "usability-tests", uploads)
    with TestClient(app) as client:
        client.post("/login", data={"email": "A@example.com", "password": "password123"})
        yield SimpleNamespace(client=client, url=url, uploads=uploads, app=app)


def upload(w, files=None):
    response = w.client.post("/tasks/normalize", data={"name": "User feedback test"},
                             files=[("files", (name, data)) for name, data in
                                    (files if files is not None else demo_sources())],
                             follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0].rsplit("/", 1)[-1]


def sources(w, task):
    with Database(w.url) as db:
        return db.query("SELECT * FROM normalization_files WHERE task_id = ? ORDER BY ordinal", (task,))


def finish_processing(w, task):
    w.client.post(f"/tasks/{task}/normalize/start", follow_redirects=False)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        # GET only: processing must not depend on manual browser ticks.
        state = w.client.get(f"/tasks/{task}/normalize/status").json()
        if state["status"] != "running":
            assert state["status"] in ("complete", "needs_review"), state
            return state
        time.sleep(0.05)
    pytest.fail("Background processing did not finish")


def issue_rows(w, task):
    with Database(w.url) as db:
        return db.query("SELECT * FROM normalization_issues WHERE task_id = ? ORDER BY id", (task,))


def configure_url(task, file):
    return f"/tasks/{task}/files/{file['id']}/configure"


def config_form(**changes):
    form = {"worksheet": "CSV", "header_row": "1", "box_to_piece": "24",
            "date_order": "month-first", "price_multiplier": "1"}
    form.update({"column_" + field: str(index) for index, field in enumerate(MAPPED_FIELDS)})
    form.update(changes)
    return form


BOX_CSV = b"order_id,customer_name,customer_id,quantity,unit,unit_price,amount,order_date\nO-1,Customer,C-1,2,box,24,48,01/09/2026\n"


def test_example_entry_and_download_supply_the_same_six_files(workspace):
    w = workspace
    response = w.client.post("/tasks/example", follow_redirects=False)
    task = response.headers["location"].rsplit("/", 1)[-1]
    assert len(sources(w, task)) == 6
    assert w.client.get(response.headers["location"]).status_code == 200
    archive = w.client.get("/examples.zip")
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert set(bundle.namelist()) == {name for name, _ in demo_sources()}
    assert "Choose your AI service" in w.client.get("/tasks/new").text


def test_configured_box_size_date_and_template_reach_export(workspace):
    w = workspace
    task = upload(w, [("warehouse.csv", BOX_CSV)])
    file = sources(w, task)[0]
    page = w.client.get(configure_url(task, file))
    assert page.status_code == 200 and "First five rows" in page.text
    save = w.client.post(configure_url(task, file), data=config_form(template_name="My warehouse"), follow_redirects=False)
    assert save.status_code == 303 and "configured=1" in save.headers["location"]
    finish_processing(w, task)
    response = w.client.get(f"/tasks/{task}/normalize/download")
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    values = list(workbook["normalized"].values)
    row = dict(zip(values[0], values[1], strict=True))
    assert row["quantity"] == 48 and row["unit_price"] == 1
    assert row["amount"] == 48 and row["order_date"] == "2026-01-09"
    workbook.close()
    with Database(w.url) as db:
        template = db.query("SELECT * FROM normalization_templates WHERE owner_id = 'A'")[0]
        assert json.loads(template["options_json"])["box_to_piece"] == "24"
    other = upload(w, [("next-month.csv", BOX_CSV)])
    loaded = w.client.get(configure_url(other, sources(w, other)[0]) + "?template=" + template["id"])
    assert 'value="24"' in loaded.text
    w.client.post("/login", data={"email": "B@example.com", "password": "password123"})
    own = upload(w, [("own.csv", BOX_CSV)])
    assert w.client.get(configure_url(own, sources(w, own)[0]) + "?template=" + template["id"]).status_code == 404


@pytest.mark.parametrize("changes", [{"column_customer_id": "1"}, {"column_order_id": ""},
                                   {"box_to_piece": "0"}, {"box_to_piece": "2.5"},
                                   {"date_order": "invalid"}, {"price_multiplier": "99"}])
def test_invalid_config_never_changes_saved_settings(workspace, changes):
    w = workspace
    task = upload(w, [("orders.csv", BOX_CSV)])
    file = sources(w, task)[0]
    response = w.client.post(configure_url(task, file), data=config_form(**changes), follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert sources(w, task)[0]["options_json"] == "{}"


def test_manual_sheet_header_and_unknown_columns_can_be_corrected(workspace):
    w = workspace
    book = Workbook()
    book.active.title = "Cover"
    book.active.append(["Monthly warehouse report"])
    sheet = book.create_sheet("Actual orders")
    sheet.append(["Report title"])
    sheet.append(["ID", "Buyer text", "Account text", "Qty text", "Pack text", "Price text", "Total text", "When text"])
    sheet.append(["O-2", "Customer", "C-2", 2, "box", 24, 48, "01/09/2026"])
    out = BytesIO()
    book.save(out)
    book.close()
    task = upload(w, [("unusual.xlsx", out.getvalue())])
    file = sources(w, task)[0]
    page = w.client.get(configure_url(task, file) + "?worksheet=Actual%20orders&header_row=2")
    assert page.status_code == 200 and "Buyer text" in page.text
    result = w.client.post(configure_url(task, file), data=config_form(worksheet="Actual orders", header_row="2"), follow_redirects=False)
    assert "configured=1" in result.headers["location"]
    state = finish_processing(w, task)
    assert state["status"] == "complete"


def test_cancel_restart_keeps_custom_rules(workspace):
    w = workspace
    task = upload(w, [("orders.csv", BOX_CSV)])
    file = sources(w, task)[0]
    w.client.post(configure_url(task, file), data=config_form(), follow_redirects=False)
    w.client.post(f"/tasks/{task}/normalize/start", follow_redirects=False)
    w.client.post(f"/tasks/{task}/normalize/cancel", follow_redirects=False)
    assert json.loads(sources(w, task)[0]["options_json"])["box_to_piece"] == "24"
    finish_processing(w, task)
    with Database(w.url) as db:
        assert db.scalar("SELECT quantity FROM normalized_records WHERE task_id = ? AND is_primary = 1", (task,)) == 48


def test_review_undo_restores_value_and_keeps_history(workspace):
    w = workspace
    task = upload(w)
    finish_processing(w, task)
    issue = next(i for i in issue_rows(w, task) if i["field"] == "customer_id" and i["issue_type"] == "missing_value")
    base = f"/tasks/{task}/normalize/issues/{issue['id']}"
    advice = w.client.post(base + "/ai-suggest").json()
    response = w.client.post(base + "/confirm", json={"decision_id": secrets.token_hex(8), "changes": advice["fields"]})
    assert response.status_code == 200
    assert w.client.post(base + "/reopen", follow_redirects=False).status_code == 303
    with Database(w.url) as db:
        context = issue_context(db, task, issue["id"])
        assert context["issue"]["status"] == "unresolved"
        assert context["current"]["customer_id"] == ""
        assert db.scalar("SELECT COUNT(*) FROM normalization_decisions WHERE issue_id = ?", (issue["id"],)) == 1
        assert db.scalar("SELECT COUNT(*) FROM normalization_reopens WHERE issue_id = ?", (issue["id"],)) == 1
        assert db.scalar("SELECT COUNT(*) FROM normalization_changes WHERE task_id = ?"
                         " AND reason = 'Undo confirmation; restored the previous value.'", (task,)) == 1


def test_undo_skip_restores_output_and_preview_is_paginated(workspace):
    w = workspace
    task = upload(w)
    finish_processing(w, task)
    issue = issue_rows(w, task)[0]
    base = f"/tasks/{task}/normalize/issues/{issue['id']}"
    assert w.client.post(base + "/skip", json={"decision_id": secrets.token_hex(8), "reason": "Check with owner"}).status_code == 200
    excluded = w.client.get(f"/tasks/{task}/normalize/preview?view=excluded")
    assert "Check with owner" in excluded.text
    w.client.post(base + "/reopen", follow_redirects=False)
    with Database(w.url) as db:
        assert db.scalar("SELECT COUNT(*) FROM normalized_records WHERE task_id = ? AND is_primary = 1", (task,)) == 36
    preview = w.client.get(f"/tasks/{task}/normalize/preview?page=2")
    assert preview.status_code == 200 and "Page 2 / 2" in preview.text
    assert "Draft preview" in preview.text
    assert w.client.get(f"/tasks/{task}/normalize/preview?view=changes").status_code == 200
    assert w.client.get(f"/tasks/{task}/normalize/preview?view=bad").status_code == 400
    assert w.client.get(f"/tasks/{task}/normalize/preview?page=bad").status_code == 400
    w.client.post("/login", data={"email": "B@example.com", "password": "password123"})
    assert w.client.get(f"/tasks/{task}/normalize/preview").status_code == 404
    assert w.client.post(base + "/reopen").status_code == 404


def test_ai_payload_excludes_unrelated_fields_and_provenance(workspace):
    w = workspace
    task = upload(w)
    finish_processing(w, task)
    with Database(w.url) as db:
        issue = next(i for i in issue_rows(w, task) if i["field"] == "quantity" and i["issue_type"] == "missing_value")
        payload = review_ai_context(db, issue_context(db, task, issue["id"]))
    serialized = json.dumps(payload)
    assert set(payload["current"]) == {"quantity", "unit", "unit_price", "amount"}
    assert "source_file" not in serialized and "customer_name" not in serialized
    assert "order_id" not in serialized and "api_key" not in serialized


def test_application_restart_resumes_persisted_job_without_a_browser(tmp_path):
    url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    uploads = tmp_path / "uploads"
    with Database(url) as db:
        db.apply_migrations()
        create_user(db, name="A", email="A@example.com", password="password123", user_id="A")
        task = create_normalization_task(db, uploads, "A", "Restart test", list(demo_sources()))
        start_normalization(db, task)
    # The running state was written before this application process started.
    app = create_app(url, "restart-secret", uploads)
    with TestClient(app):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with Database(url) as db:
                state = db.scalar("SELECT status FROM normalization_batches WHERE task_id = ?", (task,))
            if state != "running":
                break
            time.sleep(0.05)
        assert state == "needs_review"


def test_superseded_migration_upgrades_without_losing_data(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0010":
            (legacy / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    (legacy / "0010_normalization_human_review.sql").write_text(
        "ALTER TABLE normalization_issues ADD COLUMN resolved_by TEXT;\n"
        "ALTER TABLE normalization_issues ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;\n", encoding="utf-8")
    with Database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}") as db:
        db.apply_migrations(legacy)
        create_user(db, name="Old user", email="old@example.com", password="password123", user_id="OLD")
        db.apply_migrations()
        assert db.scalar("SELECT name FROM users WHERE id = 'OLD'") == "Old user"
        assert db.apply_migrations() == []
