"""Interactive credential setup tests."""

import stat
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from backend.app.auth import Auth
from backend.app.setup_accounts import collect_users, main, write_credentials


class AccountSetupTests(unittest.TestCase):
    def test_creates_loadable_owner_only_file_without_plaintext(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "auth-users.yaml"
            with patch("builtins.input", side_effect=["viewer", ""]), \
                 patch("getpass.getpass", return_value="test password long enough"), \
                 patch("sys.stdin.isatty", return_value=True), redirect_stdout(StringIO()):
                main(["--output", str(target)])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertNotIn("test password long enough", target.read_text())
            auth = Auth({"credentials_file": target.name, "origins": ["http://localhost:8000"],
                         "secure_cookie": False}, target.parent)
            self.assertTrue(auth.authenticate("viewer", "test password long enough"))

    def test_collects_at_most_three_accounts(self) -> None:
        with patch("builtins.input", side_effect=["one", "two", "three"]) as prompt, \
             patch("getpass.getpass", return_value="test password long enough"):
            users = collect_users()
        self.assertEqual(len(users), 3)
        self.assertEqual(prompt.call_count, 3)

    def test_rejects_invalid_inputs(self) -> None:
        for names, passwords in [
            ([""], []),
            ([" viewer"], []),
            (["viewer"], ["short", "short"]),
            (["viewer"], ["test password long enough", "mismatched password"]),
            (["viewer", "viewer"], ["test password long enough"] * 2),
        ]:
            with self.subTest(names=names), patch("builtins.input", side_effect=names), \
                 patch("getpass.getpass", side_effect=passwords), self.assertRaises(ValueError):
                collect_users()

    def test_refuses_overwrite_and_symlink(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "auth-users.yaml"
            target.write_text("existing")
            with self.assertRaises(FileExistsError):
                write_credentials(target, [])
            self.assertEqual(target.read_text(), "existing")
            link = Path(directory) / "link.yaml"
            link.symlink_to(target)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(["--output", str(link)])
            self.assertEqual(target.read_text(), "existing")

    def test_noninteractive_mode_does_not_create_file(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "auth-users.yaml"
            with patch("sys.stdin.isatty", return_value=False), redirect_stderr(StringIO()), \
                 self.assertRaises(SystemExit):
                main(["--output", str(target)])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
