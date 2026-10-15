#!/usr/bin/env python3
"""Offline startup readiness tests; mocks adb and time, requires no Android SDK."""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("prepare_emulator", pathlib.Path(__file__).with_name("prepare-emulator.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LAUNCHER = "com.google.android.apps.nexuslauncher"


class StartupTests(unittest.TestCase):
    def run_fixture(self, scenario, expected_error=None, allow_startup_wait=True):
        calls = []
        now = [0]
        dumps = [0]
        resolutions = [0]
        taps = [0]
        launcher = "com.android.launcher3" if scenario == "quickstep-wait" else LAUNCHER
        wait_scenarios = {
            "known-wait", "quickstep-wait", "recurring-anr", "recurring-after-health",
            "flow-present", "invalid-bounds", "disabled-wait",
        }

        def pause(seconds):
            now[0] += seconds

        def adb(*args, timeout=15, binary=False):
            calls.append(args)
            self.assertLessEqual(timeout, 15)
            if args == ("shell", "getprop", "ro.kernel.qemu"):
                return "0" if scenario == "physical" else "1"
            if "resolve-activity" in args:
                resolutions[0] += 1
                if scenario == "setup-transition" and resolutions[0] == 1:
                    return "com.google.android.googlesdksetup/.DefaultActivity\n"
                return launcher + "/.LauncherActivity\n"
            if args[:3] == ("shell", "settings", "get"):
                if scenario == "setup-pending" or (scenario == "setup-transition" and resolutions[0] == 0):
                    return "0"
                return "1"
            if args[:3] == ("shell", "am", "start"):
                return "Status: ok\n"
            if args[:3] == ("shell", "input", "tap"):
                taps[0] += 1
                return ""
            if args == ("shell", "pm", "list", "packages"):
                return "package:android\n" + ("package:com.flowdictation.android.preview\n" if scenario == "flow-present" else "")
            if args[:2] == ("logcat", "-d"):
                return "ANR in " + (launcher if scenario == "quickstep-wait" else "com.android.systemui") + "\n"
            if "uiautomator" in args:
                dumps[0] += 1
                if scenario == "dump-timeout":
                    raise subprocess.TimeoutExpired("adb", timeout)
            if args == ("shell", "cat", "/sdcard/flow-startup-ui.xml"):
                if scenario == "anr":
                    return '<hierarchy><node resource-id="android:id/aerr_wait" text="Other app isn\'t responding"/></hierarchy>'
                if scenario in wait_scenarios and (
                    taps[0] == 0
                    or scenario == "recurring-anr"
                    or (scenario == "recurring-after-health" and dumps[0] >= 4)
                ):
                    label = "Quickstep" if scenario == "quickstep-wait" else "System UI"
                    bounds = "[10,20][10,20]" if scenario == "invalid-bounds" else "[10,20][110,60]"
                    enabled = "false" if scenario == "disabled-wait" else "true"
                    return f'<hierarchy><node text="{label} isn\'t responding"/><node resource-id="android:id/aerr_wait" text="Wait" enabled="{enabled}" bounds="{bounds}"/></hierarchy>'
                if scenario == "unresponsive" or (scenario == "recovering" and dumps[0] == 2):
                    return '<hierarchy><node package="android" bounds="[0,0][100,100]"/></hierarchy>'
                return f'<hierarchy><node package="{launcher}" bounds="[0,0][100,100]"/></hierarchy>'
            if args == ("shell", "dumpsys", "activity", "activities"):
                return "mResumedActivity: ActivityRecord{fixture " + launcher + "/.LauncherActivity}"
            return b"fixture screenshot" if binary else "fixture diagnostic"

        with tempfile.TemporaryDirectory(prefix="flow-startup-fixture-") as temp:
            out = pathlib.Path(temp) / "startup"
            with patch.object(module, "adb", adb):
                if expected_error:
                    with self.assertRaisesRegex(expected_error[0], expected_error[1]):
                        module.prepare(out, seconds=8, clock=lambda: now[0], pause=pause,
                                       allow_startup_wait=allow_startup_wait)
                else:
                    module.prepare(out, seconds=12, clock=lambda: now[0], pause=pause,
                                   allow_startup_wait=allow_startup_wait)
            self.assertEqual((out / "screen.png").exists(), scenario != "physical")
            self.assertEqual((out / "logcat.txt").exists(), scenario != "physical")
            self.assertTrue((out / "probes.txt").exists())
            self.assertFalse(any("force-stop" in c or "install" in c for c in calls))
            expected_taps = 1 if allow_startup_wait and scenario in {
                "known-wait", "quickstep-wait", "recurring-anr", "recurring-after-health",
            } else 0
            self.assertEqual(taps[0], expected_taps)
            input_calls = [c for c in calls if "input" in c]
            self.assertEqual(input_calls, [("shell", "input", "tap", "60", "40")] * expected_taps)
            if expected_taps:
                original = out / "before-startup-wait"
                self.assertIn("aerr_wait", (original / "ui.xml").read_text())
                self.assertTrue((original / "screen.png").exists())
                self.assertTrue((original / "packages.txt").exists())
                self.assertTrue((out / "startup-wait.txt").exists())
                if not expected_error:
                    self.assertEqual(dumps[0], 4)
                    self.assertNotIn("aerr_wait", (out / "ui.xml").read_text())
            self.assertFalse(any(c[:3] == ("shell", "settings", "put") for c in calls))
            if scenario == "physical":
                self.assertEqual(calls, [("shell", "getprop", "ro.kernel.qemu")])
            if scenario == "anr":
                self.assertIn("aerr_wait", (out / "ui.xml").read_text())
            if scenario == "healthy":
                self.assertEqual(dumps[0], 2)
            if scenario == "recovering":
                self.assertEqual(dumps[0], 4)  # Interrupted health must reset streak.
            if scenario == "recurring-after-health":
                self.assertEqual(dumps[0], 4)
                probes = (out / "probes.txt").read_text()
                self.assertIn("consecutive healthy=1", probes)
                self.assertNotIn("consecutive healthy=2", probes)
            if scenario == "setup-transition":
                self.assertEqual(dumps[0], 3)
                self.assertIn("googlesdksetup", (out / "launcher.txt").read_text())
                self.assertIn(LAUNCHER, (out / "launcher.txt").read_text())
                self.assertIn("provisioned=0", (out / "probes.txt").read_text())
            if expected_error and expected_error[0] is TimeoutError:
                self.assertLessEqual(now[0], 8)

    def test_healthy_launcher(self):
        self.run_fixture("healthy")

    def test_health_streak_resets(self):
        self.run_fixture("recovering")

    def test_anr_preserved_and_reported(self):
        self.run_fixture("anr", (RuntimeError, "not a confirmed System UI/current launcher ANR"))

    def test_unresponsive_launcher_times_out(self):
        self.run_fixture("unresponsive", (TimeoutError, "time limit"))

    def test_dump_timeout_is_bounded(self):
        self.run_fixture("dump-timeout", (TimeoutError, "time limit"))

    def test_physical_device_is_refused(self):
        self.run_fixture("physical", (RuntimeError, "physical device"))

    def test_setup_activity_transitions_to_launcher(self):
        self.run_fixture("setup-transition")

    def test_setup_never_completes_times_out(self):
        self.run_fixture("setup-pending", (TimeoutError, "time limit"))

    def test_known_anr_preinstall_wait_once(self):
        self.run_fixture("known-wait")

    def test_current_quickstep_preinstall_wait_once(self):
        self.run_fixture("quickstep-wait")

    def test_second_anr_fails_after_single_wait(self):
        self.run_fixture("recurring-anr", (RuntimeError, "no further recovery"))

    def test_anr_returning_after_one_healthy_probe_fails_without_second_wait(self):
        self.run_fixture("recurring-after-health", (RuntimeError, "no further recovery"))

    def test_flow_installed_refuses_wait(self):
        self.run_fixture("flow-present", (RuntimeError, "Flow is already installed"))

    def test_empty_wait_button_bounds_refuses_tap(self):
        self.run_fixture("invalid-bounds", (RuntimeError, "empty bounds"))

    def test_disabled_wait_button_refuses_tap(self):
        self.run_fixture("disabled-wait", (RuntimeError, "disabled"))

    def test_strict_readiness_refuses_startup_wait(self):
        self.run_fixture("known-wait", (RuntimeError, "startup Wait is disabled"),
                         allow_startup_wait=False)


if __name__ == "__main__":
    unittest.main()
