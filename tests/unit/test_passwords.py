"""Password hashing must be salted, constant-time checked and strict."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flowremote.control_plane.auth import (  # noqa: E402
    AccountError,
    hash_password,
    verify_password,
)


class PasswordTests(unittest.TestCase):
    def test_a_hash_verifies_its_own_password(self):
        stored = hash_password("correct horse battery")
        self.assertTrue(verify_password("correct horse battery", stored))

    def test_a_wrong_password_does_not_verify(self):
        stored = hash_password("correct horse battery")
        self.assertFalse(verify_password("correct horse batterY", stored))

    def test_the_same_password_hashes_differently(self):
        first = hash_password("same password")
        second = hash_password("same password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("same password", first))
        self.assertTrue(verify_password("same password", second))

    def test_short_passwords_are_rejected(self):
        with self.assertRaises(AccountError):
            hash_password("short")

    def test_a_malformed_stored_hash_is_not_accepted(self):
        self.assertFalse(verify_password("anything", "not-a-hash"))
        self.assertFalse(verify_password("anything", "md5$1$aa$bb"))
        self.assertFalse(verify_password("anything", None))

    def test_the_stored_format_is_readable(self):
        stored = hash_password("long enough password")
        algorithm, iterations, salt, digest = stored.split("$")
        self.assertEqual(algorithm, "pbkdf2_sha256")
        self.assertEqual(int(iterations), 200_000)
        self.assertTrue(salt and digest)


if __name__ == "__main__":
    unittest.main()
