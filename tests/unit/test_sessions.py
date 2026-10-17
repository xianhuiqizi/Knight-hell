"""Signed cookies: valid, tampered, expired and foreign."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.api.sessions import SessionSigner  # noqa: E402


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.signer = SessionSigner("unit-test-secret", max_age_seconds=3600)

    def test_a_fresh_token_returns_the_user(self):
        token = self.signer.sign("USR-1")
        self.assertEqual(self.signer.verify(token), "USR-1")

    def test_a_tampered_payload_is_rejected(self):
        token = self.signer.sign("USR-1")
        payload, signature = token.rsplit(".", 1)
        forged = payload[:-4] + "AAAA" + "." + signature
        self.assertIsNone(self.signer.verify(forged))

    def test_a_token_from_another_secret_is_rejected(self):
        other = SessionSigner("a-different-secret")
        self.assertIsNone(self.signer.verify(other.sign("USR-1")))

    def test_an_expired_token_is_rejected(self):
        long_ago = datetime.now(timezone.utc) - timedelta(hours=3)
        token = self.signer.sign("USR-1", now=long_ago)
        self.assertIsNone(self.signer.verify(token))

    def test_garbage_is_rejected(self):
        for value in (None, "", "no-dot", "a.b", "...."):
            self.assertIsNone(self.signer.verify(value))


if __name__ == "__main__":
    unittest.main()
