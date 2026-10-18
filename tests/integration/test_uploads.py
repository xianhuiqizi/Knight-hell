"""Workbook persistence, validation boundaries and account isolation."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database
from flowremote.control_plane.order_validation import FIELDS
from flowremote.control_plane.uploads import MAX_FILE_BYTES, create_uploaded_task


def order_row(order_id="A", **changes):
    values = dict(zip(FIELDS, (order_id, "Customer", "C-01", 2, 10, 20, "2026-10-18")))
    values.update(changes)
    return tuple(values[field] for field in FIELDS)


def workbook_bytes(rows=None):
    book = Workbook()
    sheet = book.active
    sheet.title = "Orders"
    for row in rows if rows is not None else [FIELDS, order_row("A"), (None, None), order_row("B")]:
        sheet.append(row)
    data = BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


class UploadFixture(TestCase):
    def setUp(self):
        root = PROJECT_ROOT / "data" / "runtime" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.uploads = self.folder / "uploads"
        self.url = f"sqlite:///{(self.folder / 'test.db').as_posix()}"
        with Database(self.url) as db:
            db.apply_migrations()
            for name, role in (("A", "operator"), ("B", "operator"), ("Admin", "admin")):
                create_user(
                    db,
                    name=name,
                    email=f"{name}@example.com",
                    password="password123",
                    user_id=name,
                    role=role,
                )
        self.app = create_app(self.url, "upload-test", self.uploads)
        self.client = self.enterContext(TestClient(self.app))
        self.login()
        self.data = workbook_bytes()

    def login(self, who="A", client=None):
        client = client or self.client
        response = client.post(
            "/login",
            data={"email": f"{who}@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def upload(self, name="October orders", filename="orders.xlsx", data=None, **extra):
        return self.client.post(
            "/tasks",
            data={"name": name, **extra},
            files={"file": (filename, self.data if data is None else data)},
            follow_redirects=False,
        )

    def assert_empty(self):
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 0)
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM task_uploads"), 0)
        self.assertEqual(list(self.uploads.glob("*")), [])


class UploadTests(UploadFixture):
    def test_create_persists_file_owner_and_analysis(self):
        response = self.upload(name="  十月订单  ", owner_id="B")
        self.assertEqual(response.status_code, 303)
        page = self.client.get(response.headers["location"])
        self.assertIn("十月订单", page.text)
        self.assertIn("Analysis of your uploaded orders", page.text)
        self.assertIn("No exceptions in this batch", page.text)
        with Database(self.url) as db:
            task = db.query("SELECT * FROM tasks")[0]
            self.assertEqual(
                (task["owner_id"], task["workflow"], task["batch_size"], task["status"]),
                ("A", "十月订单", 2, "review_required"),
            )
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM source_records"), 2)
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM exceptions"), 0)
        downloaded = self.client.get(response.headers["location"] + "/source")
        self.assertEqual(downloaded.content, self.data)
        self.assertIn("attachment", downloaded.headers["content-disposition"])

    def test_other_account_cannot_see_task_or_download_file(self):
        path = self.upload().headers["location"]
        self.login("B")
        self.assertNotIn("October orders", self.client.get("/").text)
        for suffix in ("", "/source", "/approval"):
            self.assertEqual(self.client.get(path + suffix).status_code, 404)
        for suffix in ("/proceed", "/approval", "/back-to-review"):
            self.assertEqual(self.client.post(path + suffix).status_code, 404)
        self.login("Admin")
        self.assertEqual(self.client.get(path + "/source").content, self.data)

    def test_anonymous_cannot_create_or_download(self):
        path = self.upload().headers["location"]
        self.client.post("/logout")
        for response in (
            self.client.get("/tasks/new", follow_redirects=False),
            self.upload(),
            self.client.get(path + "/source", follow_redirects=False),
        ):
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers["location"].startswith("/login"))
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM tasks"), 1)

    def test_unresolved_upload_cannot_enter_approval(self):
        path = self.upload(data=workbook_bytes([FIELDS, order_row(quantity=0)])).headers["location"]
        for suffix in ("/back-to-review", "/proceed", "/approval"):
            self.client.post(path + suffix, follow_redirects=False)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT status FROM tasks"), "review_required")
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM approvals"), 0)

    def test_same_filename_never_overwrites_another_task(self):
        first = self.upload().headers["location"]
        second_data = workbook_bytes([FIELDS, order_row("C")])
        second = self.upload(data=second_data).headers["location"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.get(first + "/source").content, self.data)
        self.assertEqual(self.client.get(second + "/source").content, second_data)
        self.assertEqual(len(list(self.uploads.glob("*.xlsx"))), 2)

    def test_task_and_file_survive_new_app_instance(self):
        path = self.upload().headers["location"]
        with TestClient(create_app(self.url, "upload-test", self.uploads)) as restarted:
            self.login(client=restarted)
            self.assertEqual(restarted.get(path).status_code, 200)
            self.assertEqual(restarted.get(path + "/source").content, self.data)

    def test_invalid_names_are_rejected(self):
        for name in ("   ", "a" * 121):
            with self.subTest(name=name):
                self.assertEqual(self.upload(name=name).status_code, 400)
                self.assert_empty()

    def test_non_excel_and_corrupt_excel_are_rejected(self):
        for filename, data in (
            ("orders.xls", self.data),
            ("evil.html", b"<html>"),
            ("broken.xlsx", b"not a workbook"),
            ("empty.xlsx", b""),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(self.upload(filename=filename, data=data).status_code, 400)
                self.assert_empty()

    def test_header_only_empty_and_missing_header_are_rejected(self):
        for rows in ([], [("Id",)], [(None,), ("A",)]):
            with self.subTest(rows=rows):
                self.assertEqual(self.upload(data=workbook_bytes(rows)).status_code, 400)
                self.assert_empty()

    def test_leading_blank_and_whitespace_rows_are_skipped(self):
        data = workbook_bytes(
            [(None,), ("  ", "\t"), FIELDS, order_row("A"), (None,), order_row("B")]
        )
        response = self.upload(data=data)
        self.assertEqual(response.status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT batch_size FROM tasks"), 2)
        self.assertEqual(self.client.get(response.headers["location"] + "/source").content, data)

    def test_leading_blanks_do_not_reduce_data_row_limit(self):
        data = workbook_bytes(
            [(None,), (None,), FIELDS] + [order_row(str(i)) for i in range(10_000)]
        )
        self.assertEqual(self.upload(data=data).status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT batch_size FROM tasks"), 10_000)

    def test_empty_sheet_error_explains_which_sheet_to_fix(self):
        response = self.upload(data=workbook_bytes([(None,), ("  ",)]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Orders", response.text)
        self.assertIn("is empty", response.text)
        self.assertIn("move your data worksheet first", response.text)
        self.assert_empty()

    def test_header_search_is_bounded(self):
        response = self.upload(data=workbook_bytes([(None,)] * 1000 + [("Id",), (1,)]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("first 1,000 rows", response.text)
        self.assert_empty()

    def test_file_and_total_request_size_limits(self):
        for size in (MAX_FILE_BYTES + 1, MAX_FILE_BYTES + 100_000):
            with self.subTest(size=size):
                self.assertEqual(self.upload(data=b"a" * size).status_code, 413)
                self.assert_empty()

    def test_row_and_column_limits(self):
        for rows in ([tuple(range(257)), (1,)], [("Id",)] + [(i,) for i in range(10_001)]):
            self.assertEqual(self.upload(data=workbook_bytes(rows)).status_code, 400)
            self.assert_empty()

    def test_missing_file_and_malformed_multipart(self):
        for response in (
            self.client.post("/tasks", data={"name": "Test"}),
            self.client.post("/tasks", files={"name": (None, "Test")}),
            self.client.post(
                "/tasks", content=b"invalid", headers={"Content-Type": "multipart/form-data"}
            ),
        ):
            self.assertEqual(response.status_code, 400)
            self.assert_empty()

    def test_untrusted_filename_cannot_choose_storage_path(self):
        response = self.upload(filename="../../outside.xlsx")
        self.assertEqual(response.status_code, 303)
        with Database(self.url) as db:
            self.assertEqual(db.scalar("SELECT source_file FROM tasks"), "outside.xlsx")
            storage = db.scalar("SELECT storage_name FROM task_uploads")
        self.assertEqual((self.uploads / storage).read_bytes(), self.data)
        self.assertFalse((self.folder / "outside.xlsx").exists())

    def test_failed_metadata_insert_rolls_back_task_and_removes_file(self):
        with Database(self.url) as db:
            original = db.execute

            def fail_metadata(sql, params=()):
                if sql.startswith("INSERT INTO task_uploads"):
                    raise RuntimeError("simulated database failure")
                return original(sql, params)

            with (
                patch.object(db, "execute", side_effect=fail_metadata),
                self.assertRaises(RuntimeError),
            ):
                create_uploaded_task(db, self.uploads, "A", "Orders", "orders.xlsx", self.data)
        self.assert_empty()
