"""Publication guard regressions use invented data only."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("public_guard", Path(__file__).resolve().parents[1] / "check_public_source.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

class PublicSourceTests(unittest.TestCase):
    def _git(self, root, *args, env=None, hooks=None):
        command = ["git", *args]
        if hooks is not None:
            command[1:1] = ["-c", f"core.hooksPath={hooks}", "-c", "commit.gpgSign=false"]
        git_env = os.environ.copy()
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            git_env.pop(key, None)
        if env:
            git_env.update(env)
        subprocess.run(command, cwd=root, env=git_env, check=True, capture_output=True)

    def _repo(self, root, hooks):
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "Flow Maintainer")
        self._git(root, "config", "user.email", "12345+flow@users.noreply.github.com")
        (root / "safe.txt").write_text("public example", encoding="utf-8")
        self._git(root, "add", "safe.txt")
        self._git(root, "commit", "-m", "initial", hooks=hooks)

    def test_rejects_contact_credentials_and_local_user_path(self):
        samples = [
            ("dev" + "@" + "corp.internal", "non-example contact address"),
            ("person" + "@github.com", "non-example contact address"),
            ("ghp_" + "A" * 36, "credential-shaped content"),
            ("-----BEGIN " + "PRIVATE KEY-----", "credential-shaped content"),
            ("C:/Users/" + "localaccount/project", "named local user path"),
        ]
        for value, category in samples:
            with self.subTest(category=category):
                self.assertIn(category, guard.scan_file("example.txt", value.encode()))
    def test_allows_reserved_examples_and_generic_runtime_paths(self):
        text = "demo@example.test test@example.com noreply@github.com /home/runner/work/project"
        self.assertEqual([], guard.scan_file("example.txt", text.encode()))
    def test_rejects_private_files_and_unknown_binaries(self):
        self.assertTrue(guard.scan_file("docs/prompts/draft.md", b"example"))
        self.assertTrue(guard.scan_file("data.sqlite", b"example"))
        self.assertTrue(guard.scan_file("picture.png", bytes([0, 255])))
    def test_requires_the_verified_wrapper(self):
        self.assertIn("unverified Gradle wrapper", guard.scan_file(guard.WRAPPER, b"not a wrapper"))

    def test_checks_staged_blob_instead_of_working_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hooks = root / "hooks"
            hooks.mkdir()
            self._repo(root, hooks)
            target = root / "staged.txt"
            target.write_text("dev" + "@" + "corp.internal", encoding="utf-8")
            self._git(root, "add", "staged.txt")
            target.write_text("clean@example.test", encoding="utf-8")

            issues, files, commits = guard.check_repository(root)

        self.assertIn("staged.txt: non-example contact address", issues)
        self.assertEqual(2, files)
        self.assertEqual(1, commits)

    def test_rejects_contact_in_reachable_history_after_file_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hooks = root / "hooks"
            hooks.mkdir()
            self._repo(root, hooks)
            target = root / "former.txt"
            address = "former-dev" + "@" + "corp.internal"
            target.write_text(address, encoding="utf-8")
            self._git(root, "add", "former.txt")
            self._git(root, "commit", "-m", "add example fixture", hooks=hooks)
            target.unlink()
            self._git(root, "add", "-u")
            self._git(root, "commit", "-m", "remove example fixture", hooks=hooks)

            issues, files, commits = guard.check_repository(root)

        self.assertIn("former.txt: non-example contact address", issues)
        self.assertTrue(all(address not in issue for issue in issues))
        self.assertEqual(1, files)
        self.assertEqual(3, commits)

if __name__ == "__main__":
    unittest.main()
