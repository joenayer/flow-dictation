#!/usr/bin/env python3
"""Require responsive emulator HOME before APK installation; save startup evidence.

Usage: prepare-emulator.py native-screens/startup
Readiness is bounded to 120 seconds. Diagnostic collection has separate bounded
command timeouts. A single recorded Wait action is allowed for a confirmed
platform/launcher startup ANR only while no Flow package is installed. No
processes are restarted and app failures receive no recovery.
"""
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def adb(*args, timeout=15, binary=False):
    return subprocess.check_output(["adb", *args], text=not binary, timeout=timeout)


def collect_evidence(out, full_logs=False, deadline=None, clock=time.monotonic):
    failures = []
    for filename, args, binary in (
        ("screen.png", ("exec-out", "screencap", "-p"), True),
        ("logcat.txt", ("logcat", "-d") if full_logs else ("logcat", "-d", "-t", "2000"), False),
        ("activities.txt", ("shell", "dumpsys", "activity", "activities"), False),
        ("windows.txt", ("shell", "dumpsys", "window", "windows"), False),
        ("memory.txt", ("shell", "cat", "/proc/meminfo"), False),
    ):
        try:
            remaining = 5 if deadline is None else min(5, deadline - clock())
            if remaining <= 0:
                raise TimeoutError("Startup evidence exceeded the readiness deadline")
            value = adb(*args, timeout=remaining, binary=binary)
            if binary:
                (out / filename).write_bytes(value)
            else:
                (out / filename).write_text(value)
        except (subprocess.SubprocessError, OSError) as error:
            failures.append(filename)
            (out / (filename + ".error.txt")).write_text(str(error))
    return failures


def prepare(out, seconds=120, clock=time.monotonic, pause=time.sleep, allow_startup_wait=True):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    deadline = clock() + seconds
    probes = []
    confirmed_emulator = False

    def command(*args):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Emulator HOME readiness exceeded its time limit")
        return adb(*args, timeout=min(15, remaining))

    try:
        if command("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("Refusing preparation on a physical device; use a disposable emulator")
        confirmed_emulator = True
        result = command("shell", "am", "start", "-W", "-a", "android.intent.action.MAIN",
                         "-c", "android.intent.category.HOME")
        (out / "home-launch.txt").write_text(result)
        if "Error:" in result or "Status: timeout" in result:
            raise RuntimeError("Emulator could not launch HOME: " + result.strip())
        healthy = 0
        previous_launcher = None
        waited = False
        while clock() < deadline:
            try:
                provisioned = command("shell", "settings", "get", "global", "device_provisioned").strip()
                setup_complete = command("shell", "settings", "get", "secure", "user_setup_complete").strip()
                # HOME can change from an SDK setup activity to the launcher
                # during first boot. Resolve it each time, without bypassing setup.
                resolved = command("shell", "cmd", "package", "resolve-activity", "--brief",
                                   "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")
                with (out / "launcher.txt").open("a") as output:
                    output.write(resolved + "\n")
                matches = re.findall(r"^([\w.]+)/[^\s]+$", resolved, re.MULTILINE)
                launcher = matches[-1] if matches and matches[-1] != "android" else ""
                if launcher != previous_launcher:
                    healthy = 0
                previous_launcher = launcher
                command("shell", "rm", "-f", "/sdcard/flow-startup-ui.xml")
                command("shell", "uiautomator", "dump", "/sdcard/flow-startup-ui.xml")
                xml = command("shell", "cat", "/sdcard/flow-startup-ui.xml")
                (out / "ui.xml").write_text(xml)
                tree = ET.fromstring(xml)
                nodes = list(tree.iter("node"))
                dialogs = [n for n in nodes if n.get("resource-id", "").startswith("android:id/aerr_")]
                if dialogs:
                    texts = " | ".join(n.get("text", "") for n in nodes if n.get("text"))
                    kind = "ANR" if any(n.get("resource-id") == "android:id/aerr_wait" for n in dialogs) or re.search(r"(?:isn't|not) responding", texts, re.I) else "error"
                    if kind != "ANR" or waited:
                        raise RuntimeError(f"Emulator startup {kind} dialog blocks readiness; no further recovery: {texts}")
                    if not allow_startup_wait:
                        raise RuntimeError(f"Emulator startup ANR dialog blocks strict readiness; startup Wait is disabled: {texts}")
                    waits = [n for n in dialogs if n.get("resource-id") == "android:id/aerr_wait"]
                    labels = {"System UI": "com.android.systemui"}
                    if launcher == "com.android.launcher3":
                        labels.update({"Quickstep": launcher, "Launcher": launcher})
                    elif launcher == "com.google.android.apps.nexuslauncher":
                        labels["Pixel Launcher"] = launcher
                    affected = next((package for label, package in labels.items()
                                     if any(re.fullmatch(re.escape(label) + r" (?:isn't|isn’t|is not|not) responding[.!]?",
                                                         n.get("text", ""), re.I) for n in nodes)), None)
                    if len(waits) != 1 or affected is None:
                        raise RuntimeError("Emulator startup ANR dialog is not a confirmed System UI/current launcher ANR: " + texts)
                    if waits[0].get("enabled") != "true":
                        raise RuntimeError("Startup ANR Wait button is disabled")
                    bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", waits[0].get("bounds", ""))
                    if not bounds:
                        raise RuntimeError("Startup ANR Wait button has invalid bounds")
                    left, top, right, bottom = map(int, bounds.groups())
                    if right <= left or bottom <= top:
                        raise RuntimeError("Startup ANR Wait button has empty bounds")
                    original = out / "before-startup-wait"
                    original.mkdir()
                    (original / "ui.xml").write_text(xml)
                    (original / "probes.txt").write_text("\n".join(probes))
                    for name in ("home-launch.txt", "launcher.txt"):
                        (original / name).write_text((out / name).read_text())
                    if collect_evidence(original, full_logs=True, deadline=deadline, clock=clock):
                        raise RuntimeError("Cannot preserve complete original startup evidence; refusing Wait")
                    logs = (original / "logcat.txt").read_text()
                    if not re.search(r"\bANR in " + re.escape(affected) + r"(?:\s|$)", logs):
                        raise RuntimeError("Startup ANR package is not confirmed by logcat; refusing Wait")
                    if command("shell", "getprop", "ro.kernel.qemu").strip() != "1":
                        raise RuntimeError("Refusing startup Wait on a physical device")
                    packages = command("shell", "pm", "list", "packages")
                    (original / "packages.txt").write_text(packages)
                    lines = packages.splitlines()
                    if not lines or any(not line.startswith("package:") for line in lines):
                        raise RuntimeError("Cannot prove package inventory before startup Wait")
                    if any(line.startswith("package:com.flowdictation.android") for line in lines):
                        raise RuntimeError("Flow is already installed; refusing startup ANR recovery")
                    # Evidence collection can take several seconds. Prove the
                    # same real dialog/button is still present before tapping.
                    command("shell", "rm", "-f", "/sdcard/flow-startup-ui.xml")
                    command("shell", "uiautomator", "dump", "/sdcard/flow-startup-ui.xml")
                    current_xml = command("shell", "cat", "/sdcard/flow-startup-ui.xml")
                    (original / "before-tap-ui.xml").write_text(current_xml)
                    current_nodes = list(ET.fromstring(current_xml).iter("node"))
                    current_waits = [n for n in current_nodes if n.get("resource-id") == "android:id/aerr_wait"]
                    same_title = any(n.get("text") == old.get("text") for n in current_nodes for old in nodes
                                     if old.get("text") and re.search(r"responding", old.get("text", ""), re.I))
                    if (len(current_waits) != 1 or not same_title
                            or current_waits[0].get("enabled") != "true"
                            or current_waits[0].get("bounds") != waits[0].get("bounds")):
                        raise RuntimeError("Startup ANR dialog changed before Wait; refusing a stale tap")
                    waited = True
                    try:
                        command("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                    except subprocess.SubprocessError as error:
                        raise RuntimeError("Startup Wait command failed; refusing another action") from error
                    healthy = 0
                    note = f"Recorded one pre-install startup Wait for {affected}; original evidence retained."
                    (out / "startup-wait.txt").write_text(note)
                    probes.append(note)
                    print(note)
                    # The recovered screen must satisfy fresh setup/HOME checks.
                    remaining = deadline - clock()
                    if remaining > 0:
                        pause(min(2, remaining))
                    continue
                activities = command("shell", "dumpsys", "activity", "activities")
                (out / "activities.txt").write_text(activities)
                resumed = bool(launcher) and any(launcher + "/" in line and re.search(r"(?:mResumedActivity|topResumedActivity)", line)
                              for line in activities.splitlines())
                visible = any(n.get("package") == launcher and n.get("bounds") not in (None, "[0,0][0,0]")
                              for n in nodes)
                ready = provisioned == "1" and setup_complete == "1" and visible and resumed
                healthy = healthy + 1 if ready else 0
                probes.append(f"Setup provisioned={provisioned}; user complete={setup_complete}; launcher={launcher}; visible={visible}; resumed={resumed}; consecutive healthy={healthy}")
                if healthy >= 2:
                    print("Emulator HOME responded to two consecutive UI probes.")
                    return
            except (subprocess.SubprocessError, ET.ParseError) as error:
                healthy = 0
                probes.append("UI probe unavailable: " + str(error))
            remaining = deadline - clock()
            if remaining > 0:
                pause(min(2, remaining))
        raise TimeoutError("Emulator HOME did not respond to two consecutive probes within the time limit")
    finally:
        (out / "probes.txt").write_text("\n".join(probes))
        if confirmed_emulator:
            collect_evidence(out)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir")
    parser.add_argument("--no-startup-wait", action="store_true",
                        help="fail on any startup ANR instead of using the one pre-install Wait")
    options = parser.parse_args()
    prepare(options.evidence_dir, allow_startup_wait=not options.no_startup_wait)
