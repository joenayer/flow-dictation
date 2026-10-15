#!/usr/bin/env python3
"""Run Android native suites on one verified, disposable flow-native-ci AVD.

All paths are explicit except the evidence folders, which are created below the
current working directory. This lets CI and local reviewers retain artifacts in
their chosen directory without depending on the caller's working directory for
the sibling test scripts.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import traceback

APP_PACKAGE = "com.flowdictation.android.preview"
TEST_PACKAGE = APP_PACKAGE + ".test"
AVD_NAME = "flow-native-ci"
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PREPARE_SPEC = importlib.util.spec_from_file_location("prepare_emulator", SCRIPT_DIR / "prepare-emulator.py")
PREPARE = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_SPEC.loader.exec_module(PREPARE)


class CommandRunner:
    def __call__(self, args, *, cwd=None, check=True, timeout=120):
        return subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=check, timeout=timeout)


def verify_disposable_emulator(run, expected_name=AVD_NAME):
    """Prove qemu and the exact AVD identity before any package/settings mutation."""
    qemu = run(["adb", "shell", "getprop", "ro.kernel.qemu"]).stdout.strip()
    if qemu != "1":
        raise RuntimeError("Refusing changes: target is not an Android emulator (ro.kernel.qemu != 1).")
    name = run(["adb", "shell", "getprop", "ro.boot.qemu.avd_name"]).stdout.strip()
    if name != expected_name:
        raise RuntimeError(f"Refusing changes: expected disposable AVD {expected_name!r}, got {name!r}.")


def package_inventory(run):
    output = run(["adb", "shell", "pm", "list", "packages"]).stdout
    lines = output.splitlines()
    if not lines or any(not line.startswith("package:") for line in lines):
        raise RuntimeError("Could not verify the installed package inventory.")
    return {line[len("package:"):] for line in lines}


def reset_flow_packages(run):
    """Remove only the preview app/test from the exact named disposable AVD."""
    verify_disposable_emulator(run)
    before = package_inventory(run)
    for package in (TEST_PACKAGE, APP_PACKAGE):
        if package in before:
            run(["adb", "uninstall", package], timeout=120)
    after = package_inventory(run)
    remaining = sorted({APP_PACKAGE, TEST_PACKAGE} & after)
    if remaining:
        raise RuntimeError("Package reset did not remove: " + ", ".join(remaining))
    return {"before": sorted({APP_PACKAGE, TEST_PACKAGE} & before), "after": []}


def set_ci_defaults(run):
    """Set repeatable light-mode/accessibility/animation defaults on this AVD."""
    verify_disposable_emulator(run)
    commands = [
        ["adb", "shell", "cmd", "uimode", "night", "no"],
        ["adb", "shell", "settings", "put", "system", "font_scale", "1.0"],
        ["adb", "shell", "settings", "put", "global", "window_animation_scale", "0"],
        ["adb", "shell", "settings", "put", "global", "transition_animation_scale", "0"],
        ["adb", "shell", "settings", "put", "global", "animator_duration_scale", "0"],
        ["adb", "shell", "settings", "delete", "secure", "enabled_accessibility_services"],
        ["adb", "shell", "settings", "put", "secure", "accessibility_enabled", "0"],
    ]
    for command in commands:
        run(command)
    services = run(["adb", "shell", "settings", "get", "secure", "enabled_accessibility_services"]).stdout.strip()
    enabled = run(["adb", "shell", "settings", "get", "secure", "accessibility_enabled"]).stdout.strip()
    if services not in ("", "null") or enabled != "0":
        raise RuntimeError("Could not verify accessibility is disabled and the service list is empty.")


class NativeCiOrchestrator:
    def __init__(self, apk, test_apk, model_dir, audio, model_ready, summary_json,
                 run=None, prepare=None, cwd=None):
        self.apk = pathlib.Path(apk).resolve()
        self.test_apk = pathlib.Path(test_apk).resolve()
        self.model_dir = pathlib.Path(model_dir).resolve()
        self.audio = pathlib.Path(audio).resolve()
        self.model_ready = model_ready
        self.summary_json = pathlib.Path(summary_json).resolve()
        self.run = run or CommandRunner()
        self.prepare = prepare or PREPARE.prepare
        self.cwd = pathlib.Path(cwd or pathlib.Path.cwd()).resolve()
        self.results = []
        self.guarded = False

    def call(self, args, timeout=120):
        result = self.run(args, cwd=self.cwd, timeout=timeout)
        return result

    def guard(self):
        verify_disposable_emulator(self.run)
        self.guarded = True

    def evidence_dir(self, name):
        path = self.cwd / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record_command(self, group, label, args, timeout=300):
        log = self.evidence_dir(group) / f"{label}.txt"
        try:
            result = self.call(args, timeout=timeout)
            log.write_text("$ " + " ".join(map(str, args)) + "\n\nSTDOUT:\n" + result.stdout +
                           "\nSTDERR:\n" + result.stderr,
                           encoding="utf-8")
            return result
        except Exception as error:
            stdout = getattr(error, "stdout", "") or ""
            stderr = getattr(error, "stderr", "") or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            log.write_text("$ " + " ".join(map(str, args)) + "\n\nSTDOUT:\n" + stdout +
                           "\nSTDERR:\n" + stderr +
                           f"\nERROR: {error}\n", encoding="utf-8")
            for stream_name, content in (("stdout", stdout), ("stderr", stderr)):
                if content:
                    tail = content[-65536:]
                    if len(content) > len(tail):
                        tail = "[earlier output omitted; full log retained]\n" + tail
                    print(f"\n--- {group} {label} {stream_name} (failure output) ---\n{tail}\n",
                          file=sys.stderr, flush=True)
            raise

    def prepare_home(self, group, allow_wait):
        self.guard()
        self.prepare(self.evidence_dir(group) / "startup", allow_startup_wait=allow_wait)

    def save_and_clear_logcat(self, group):
        # Evidence is best-effort; never hide the suite's actual result.
        try:
            output = self.call(["adb", "logcat", "-d"], timeout=30).stdout
            (self.evidence_dir(group) / "group-logcat.txt").write_text(output, encoding="utf-8")
            self.call(["adb", "logcat", "-c"], timeout=30)
        except Exception as error:
            (self.evidence_dir(group) / "group-logcat.error.txt").write_text(str(error), encoding="utf-8")

    def install_packages(self, need_test=True):
        self.guard()
        self.call(["adb", "install", "-r", str(self.apk)], timeout=180)
        if need_test:
            self.call(["adb", "install", "-r", str(self.test_apk)], timeout=180)

    def stage_model(self):
        required = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]
        missing = [name for name in required if not (self.model_dir / name).is_file()]
        if not self.model_ready or missing or not self.audio.is_file():
            why = "model download/checksum prerequisite failed" if not self.model_ready else "model fixture incomplete"
            if missing:
                why += ": missing " + ", ".join(missing)
            if not self.audio.is_file():
                why += ": reference WAV missing"
            raise RuntimeError("Parakeet suite prerequisite failed: " + why)
        self.guard()
        self.call(["adb", "shell", "mkdir", "-p", "/data/local/tmp/flow-parakeet/test_wavs"])
        self.call(["adb", "push", *[str(self.model_dir / name) for name in required],
                   "/data/local/tmp/flow-parakeet/"], timeout=180)
        self.call(["adb", "push", str(self.audio), "/data/local/tmp/flow-parakeet/test_wavs/0.wav"], timeout=180)
        self.call(["adb", "shell", "chmod", "-R", "a+rX", "/data/local/tmp/flow-parakeet"])
        self.call(["adb", "shell", "run-as", APP_PACKAGE, "mkdir", "-p", "files/flow-parakeet/test_wavs"])
        self.call(["adb", "shell", "run-as", APP_PACKAGE, "cp",
                   *[f"/data/local/tmp/flow-parakeet/{name}" for name in required], "files/flow-parakeet/"])
        self.call(["adb", "shell", "run-as", APP_PACKAGE, "cp",
                   "/data/local/tmp/flow-parakeet/test_wavs/0.wav", "files/flow-parakeet/test_wavs/0.wav"])

    def run_group(self, name, action):
        start = time.monotonic()
        print(f"Starting native suite group: {name}", flush=True)
        entry = {"name": name, "status": "FAIL", "elapsed_seconds": None, "error": None}
        try:
            action()
            entry["status"] = "PASS"
        except Exception as error:
            entry["error"] = f"{type(error).__name__}: {error}"
            (self.evidence_dir(name) / "group-error.txt").write_text(
                entry["error"] + "\n" + traceback.format_exc(), encoding="utf-8")
            print(f"Native suite group {name} failed: {entry['error']}", file=sys.stderr, flush=True)
        finally:
            entry["elapsed_seconds"] = round(time.monotonic() - start, 3)
            if self.guarded:
                self.save_and_clear_logcat(name)
                try:
                    set_ci_defaults(self.run)
                except Exception as error:
                    entry["status"] = "FAIL"
                    entry["error"] = (entry["error"] + "; " if entry["error"] else "") + f"CI setting reset failed: {error}"
            self.results.append(entry)
            self.write_summary()
            print(f"Finished native suite group: {name} {entry['status']} ({entry['elapsed_seconds']}s)", flush=True)

    def screens(self):
        reset_flow_packages(self.run)
        self.guard()
        set_ci_defaults(self.run)
        self.prepare_home("native-screens", allow_wait=True)
        self.call(["adb", "logcat", "-c"])
        self.record_command("native-screens", "capture-screens-runner", [
            sys.executable, str(SCRIPT_DIR / "capture-screens.py"), str(self.apk)], timeout=900)

    def auto_input(self):
        reset_flow_packages(self.run)
        set_ci_defaults(self.run)
        self.prepare_home("auto-input-tests", allow_wait=False)
        self.install_packages()
        # The suite itself enables the accessibility service and restores its
        # fixture settings. Discard platform boot chatter immediately before it.
        self.call(["adb", "logcat", "-c"])
        self.record_command("auto-input-tests", "auto-input-runner", [
            sys.executable, str(SCRIPT_DIR / "test-auto-input.py"), str(self.test_apk)], timeout=600)

    def flow15(self):
        reset_flow_packages(self.run)
        set_ci_defaults(self.run)
        self.prepare_home("flow15-evidence", allow_wait=False)
        self.install_packages()
        self.call(["adb", "logcat", "-c"])
        self.record_command("flow15-evidence", "flow15-runner", [
            sys.executable, str(SCRIPT_DIR / "test-flow15.py")], timeout=600)

    def parakeet(self):
        reset_flow_packages(self.run)
        set_ci_defaults(self.run)
        self.prepare_home("parakeet-evidence", allow_wait=False)
        self.install_packages()
        self.stage_model()
        self.call(["adb", "logcat", "-c"])
        self.record_command("parakeet-evidence", "parakeet-runner", [
            sys.executable, str(SCRIPT_DIR / "test-flow13.py")], timeout=900)

    def write_summary(self, github=False):
        self.summary_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"avd": AVD_NAME, "groups": self.results,
                   "overall": "PASS" if self.results and all(x["status"] == "PASS" for x in self.results) else "FAIL"}
        self.summary_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary and github:
            lines = ["\n### Android native suites on one disposable AVD\n\n",
                     "| Group | Result | Time | Details |\n|---|---:|---:|---|\n"]
            for item in self.results:
                detail = (item["error"] or "Completed").replace("|", "/")
                lines.append(f"| {item['name']} | **{item['status']}** | {item['elapsed_seconds']}s | {detail} |\n")
            pathlib.Path(summary).open("a", encoding="utf-8").writelines(lines)

    def run_all(self):
        # A failed safety gate is a hard stop: no packages or settings are touched.
        self.guard()
        groups = [("native-screens", self.screens), ("auto-input-tests", self.auto_input),
                  ("flow15-evidence", self.flow15), ("parakeet-evidence", self.parakeet)]
        self.execute_groups(groups)
        return 0 if all(item["status"] == "PASS" for item in self.results) else 1

    def execute_groups(self, groups):
        for name, action in groups:
            self.run_group(name, action)
        self.write_summary(github=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, help="the single packaged universal APK")
    parser.add_argument("--test-apk", required=True, help="the matching instrumentation APK")
    parser.add_argument("--model-dir", required=True, help="unpacked checksum-verified Parakeet fixture directory")
    parser.add_argument("--audio", required=True, help="official reference WAV inside the fixture")
    parser.add_argument("--model-ready", choices=("true", "false"), required=True,
                        help="whether the separate model download and checksum step succeeded")
    parser.add_argument("--summary-json", required=True, help="path for accumulated per-group results")
    args = parser.parse_args(argv)
    runner = NativeCiOrchestrator(args.apk, args.test_apk, args.model_dir, args.audio,
                                  args.model_ready == "true", args.summary_json)
    return_code = 1
    try:
        return_code = runner.run_all()
    finally:
        # Only reset the disposable CI display/accessibility defaults after the
        # exact AVD guard has passed. This also runs after failed groups.
        if runner.guarded:
            try:
                set_ci_defaults(runner.run)
            except Exception as error:
                print(f"Could not restore controlled CI device defaults: {error}", file=sys.stderr)
                return_code = 1
                if runner.results:
                    runner.results[-1]["status"] = "FAIL"
                    runner.results[-1]["error"] = (runner.results[-1]["error"] or "") + f"; final reset failed: {error}"
                    runner.write_summary(github=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
