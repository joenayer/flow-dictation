#!/usr/bin/env python3
"""Offline safety and orchestration tests; no Android SDK/device is required."""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name("run-native-ci-suites.py")
spec = importlib.util.spec_from_file_location("run_native_ci_suites", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeAdb:
    def __init__(self, qemu="1", name="flow-native-ci", packages=()):
        self.qemu = qemu
        self.name = name
        self.packages = set(packages)
        self.calls = []

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        if args == ["adb", "shell", "getprop", "ro.kernel.qemu"]:
            out = self.qemu
        elif args == ["adb", "shell", "getprop", "ro.boot.qemu.avd_name"]:
            out = self.name
        elif args == ["adb", "shell", "pm", "list", "packages"]:
            out = "\n".join("package:" + p for p in sorted(self.packages)) + "\n"
        elif len(args) == 3 and args[:2] == ["adb", "uninstall"]:
            self.packages.discard(args[2])
            out = "Success"
        elif args[:3] == ["adb", "shell", "settings"] and args[3:5] == ["get", "secure"]:
            out = "0" if args[-1] == "accessibility_enabled" else "null"
        else:
            out = ""
        return SimpleNamespace(stdout=out, stderr="", returncode=0)


class NativeCiSafetyTests(unittest.TestCase):
    def test_emulator_runner_gets_one_command_and_preflight_bash_parses(self):
        action_path = pathlib.Path(__file__).parents[2] / ".github" / "actions" / "android-check" / "action.yml"
        action = action_path.read_text(encoding="utf-8")
        native_step = action[action.index("id: native-suites"):]
        script_line = re.search(r"(?m)^        script: (.+)$", native_step)
        self.assertIsNotNone(script_line)
        command = script_line.group(1)
        self.assertNotIn("|", command)
        self.assertNotIn("\\\n", command)
        self.assertIn("--model-ready", command)
        self.assertIn("steps.fetch-model.outcome", command)

        preflight = action[action.index("id: native-apk"):action.index("id: fetch-model")]
        self.assertIn("Expected one universal APK", preflight)
        self.assertIn("sha256sum -c", preflight)
        self.assertIn("GITHUB_OUTPUT", preflight)
        match = re.search(r"(?m)^      run: \|\n((?:        .*\n)+)", preflight)
        self.assertIsNotNone(match)
        bash_script = textwrap.dedent(match.group(1))
        bash = shutil.which("bash")
        if os.name == "nt":
            git_bash = pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
            if git_bash.is_file():
                bash = str(git_bash)
        self.assertIsNotNone(bash, "Bash is required for the CI script syntax check")
        subprocess.run([bash, "-n"], input=bash_script, text=True, capture_output=True, check=True)
        command = command.replace("${{ steps.native-apk.outputs.path }}", "android/dist/example.apk")
        command = command.replace("${{ steps.fetch-model.outcome == 'success' }}", "true")
        subprocess.run([bash, "-n"], input=command + "\n", text=True, capture_output=True, check=True)

    def test_physical_or_other_avd_is_rejected_before_any_mutation(self):
        for fake in (FakeAdb(qemu="0"), FakeAdb(name="input5558")):
            with self.assertRaises(RuntimeError):
                module.reset_flow_packages(fake)
            self.assertEqual(len(fake.calls), 1 if fake.qemu != "1" else 2)
            self.assertFalse(any(call[1] in ("uninstall", "install") for call in fake.calls if len(call) > 1))
            self.assertFalse(any("settings" in call for call in fake.calls))

    def test_verified_reset_removes_only_preview_app_and_test_and_checks_absence(self):
        unrelated = "com.android.launcher3"
        fake = FakeAdb(packages={module.APP_PACKAGE, module.TEST_PACKAGE, unrelated})
        result = module.reset_flow_packages(fake)
        self.assertEqual(result["before"], sorted([module.APP_PACKAGE, module.TEST_PACKAGE]))
        self.assertEqual(result["after"], [])
        self.assertEqual(fake.packages, {unrelated})
        uninstalls = [call[2] for call in fake.calls if call[:2] == ["adb", "uninstall"]]
        self.assertEqual(uninstalls, [module.TEST_PACKAGE, module.APP_PACKAGE])
        self.assertEqual(sum(call == ["adb", "shell", "pm", "list", "packages"] for call in fake.calls), 2)

    def test_all_remaining_groups_run_and_failure_stays_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = FakeAdb()
            runner = module.NativeCiOrchestrator("a.apk", "t.apk", "model", "audio.wav", False,
                                                 pathlib.Path(temp) / "summary.json", run=fake, cwd=temp)
            runner.guarded = True
            called = []

            def fail_first():
                called.append("first")
                raise AssertionError("fixture failure")

            def pass_later():
                called.append("later")

            console = StringIO()
            with redirect_stderr(console):
                runner.execute_groups([("first", fail_first), ("later", pass_later)])
            self.assertEqual(called, ["first", "later"])
            self.assertEqual([row["status"] for row in runner.results], ["FAIL", "PASS"])
            self.assertIn("Native suite group first failed: AssertionError: fixture failure", console.getvalue())
            self.assertEqual((pathlib.Path(temp) / "summary.json").exists(), True)
            # Each group's finally path writes evidence and reapplies the
            # controlled display/accessibility defaults even after a failure.
            puts = [call for call in fake.calls if call[:4] == ["adb", "shell", "settings", "put"]]
            self.assertGreaterEqual(len(puts), 10)
            deletes = [call for call in fake.calls if call[:5] == ["adb", "shell", "settings", "delete", "secure"]]
            self.assertGreaterEqual(len(deletes), 2)
            self.assertIn(["adb", "shell", "cmd", "uimode", "night", "no"], fake.calls)

    def test_unverified_target_never_reaches_group_or_final_device_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = FakeAdb(name="input5558")
            runner = module.NativeCiOrchestrator("a.apk", "t.apk", "model", "audio.wav", False,
                                                 pathlib.Path(temp) / "summary.json", run=fake, cwd=temp)
            called = []
            with self.assertRaisesRegex(RuntimeError, "expected disposable AVD"):
                runner.run_all()
            self.assertEqual(called, [])
            self.assertEqual(len(fake.calls), 2)
            self.assertFalse(any("settings" in call or "uninstall" in call for call in fake.calls))

    def test_timeout_diagnostics_keep_partial_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            def timeout(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], 1, output=b"partial out", stderr=b"partial err")

            runner = module.NativeCiOrchestrator("a.apk", "t.apk", "model", "audio.wav", False,
                                                 pathlib.Path(temp) / "summary.json", run=timeout, cwd=temp)
            console = StringIO()
            with redirect_stderr(console):
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner.record_command("auto-input-tests", "runner", ["fake-command"], timeout=1)
            contents = (pathlib.Path(temp) / "auto-input-tests" / "runner.txt").read_text()
            self.assertIn("partial out", contents)
            self.assertIn("partial err", contents)
            self.assertIn("timed out", contents)
            self.assertIn("partial out", console.getvalue())
            self.assertIn("partial err", console.getvalue())
            self.assertIn("failure output", console.getvalue())


if __name__ == "__main__":
    unittest.main()
