"""English is the default; Chinese is an explicit browser choice."""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi.testclient import TestClient

from flowremote.api.app import create_app
from flowremote.control_plane.auth import create_user
from flowremote.control_plane.db import PROJECT_ROOT, Database


def visible_text(html: str) -> str:
    html = re.sub(
        r"<(script|style|pre|code)\b.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    html = re.sub(r"<[^>]+>", " ", html)
    return " ".join(html.split())


class LanguageSwitchTests(TestCase):
    def setUp(self):
        root = PROJECT_ROOT / "data" / "runtime" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        url = f"sqlite:///{(folder / 'i18n.db').as_posix()}"
        with Database(url) as db:
            db.apply_migrations()
            create_user(
                db,
                name="Alex Morgan",
                email="alex@example.com",
                password="password123",
                user_id="USR-A",
            )
        self.app = create_app(url, "i18n-test-secret", folder / "uploads")
        self.client = self.enterContext(TestClient(self.app))

    def test_new_visitor_defaults_to_english_even_with_chinese_browser(self):
        page = self.client.get("/login", headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        self.assertEqual(page.status_code, 200)
        self.assertIn('<html lang="en">', page.text)
        text = visible_text(page.text)
        self.assertIn("Work email", text)
        self.assertIn("Log in", text)
        self.assertIn(">中文</a>", page.text)
        self.assertNotIn("工作邮箱", text)
        self.assertNotIn("登录", text)
        self.assertNotIn("flowremote_lang", self.client.cookies)

    def test_switching_to_chinese_sets_a_cookie_and_translates(self):
        switch = self.client.get("/language/zh?next=/login", follow_redirects=False)
        self.assertEqual(switch.status_code, 303)
        self.assertEqual(switch.headers["location"], "/login")
        self.assertEqual(self.client.cookies.get("flowremote_lang"), "zh")
        page = self.client.get("/login")
        self.assertIn('<html lang="zh">', page.text)
        self.assertEqual(page.headers["content-language"], "zh-CN")
        text = visible_text(page.text)
        self.assertIn("工作邮箱", text)
        self.assertIn("登录", text)
        self.assertNotIn("Work email", text)

    def test_switch_back_to_english(self):
        self.client.get("/language/zh?next=/login")
        self.client.get("/language/en?next=/login")
        page = self.client.get("/login")
        self.assertIn('<html lang="en">', page.text)
        self.assertIn("Work email", visible_text(page.text))
        self.assertNotIn("工作邮箱", visible_text(page.text))

    def test_invalid_language_and_external_next_are_rejected(self):
        self.assertEqual(self.client.get("/language/fr").status_code, 404)
        switch = self.client.get("/language/zh?next=//evil.example", follow_redirects=False)
        self.assertEqual(switch.status_code, 303)
        self.assertEqual(switch.headers["location"], "/")
        backslash = self.client.get(
            "/language/zh?next=/%5Cevil.example", follow_redirects=False
        )
        self.assertEqual(backslash.headers["location"], "/")

    def test_authenticated_home_and_settings_translate(self):
        login = self.client.post(
            "/login",
            data={"email": "alex@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        self.client.get("/language/zh?next=/")
        home = self.client.get("/")
        text = visible_text(home.text)
        self.assertIn("任务", text)
        self.assertIn("你负责的任务", text)
        self.assertIn("新建任务", text)
        settings = self.client.get("/settings")
        settings_text = visible_text(settings.text)
        self.assertIn("AI 与 RPA 控制中心", settings_text)
        self.assertIn("当前工作区", settings_text)
        self.assertEqual(settings.headers["content-language"], "zh-CN")

    def test_i18n_client_asset_is_served(self):
        asset = self.client.get("/static/i18n.js?v=20261118r")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("FLOWREMOTE_LANG", asset.text)
