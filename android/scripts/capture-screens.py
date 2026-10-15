#!/usr/bin/env python3
"""Check permission denial/retry and capture native screens at default/1.5x fonts.

Runs only on a disposable emulator, downloads Whisper Tiny.en once, and never
starts microphone recording.
"""
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = "com.flowdictation.android.preview"
OUT = pathlib.Path("native-screens")
OUT.mkdir(exist_ok=True)


def adb(*args, binary=False):
    return subprocess.check_output(["adb", *args], text=not binary)


def diagnose_failure(exc_type, exc, traceback):
    # Collect evidence for failures anywhere in the script, including before the
    # first successful capture. Preserve the original exception and exit status.
    diagnostics = [
        ("failure.png", ("exec-out", "screencap", "-p"), True),
        ("failure-ui.xml", ("shell", "cat", "/sdcard/flow-ui.xml"), False),
        ("failure-logcat.txt", ("logcat", "-d", "-t", "2000"), False),
        ("failure-crash-logcat.txt", ("logcat", "-d", "-b", "crash"), False),
        ("failure-activities.txt", ("shell", "dumpsys", "activity", "activities"), False),
        ("failure-permissions.txt", ("shell", "dumpsys", "package", PACKAGE), False),
    ]
    for filename, args, binary in diagnostics:
        try:
            data = adb(*args, binary=binary)
            if binary:
                (OUT / filename).write_bytes(data)
            else:
                (OUT / filename).write_text(data)
        except Exception as diagnostic_error:
            print("Could not collect " + filename + ": " + str(diagnostic_error), file=sys.stderr)
    sys.__excepthook__(exc_type, exc, traceback)


sys.excepthook = diagnose_failure


def tree():
    # Transitions can briefly expose no accessibility root. Retry the dump, not
    # missing-control assertions, and remove the prior file to avoid stale trees.
    for attempt in range(3):
        try:
            adb("shell", "rm", "-f", "/sdcard/flow-ui.xml")
            adb("shell", "uiautomator", "dump", "/sdcard/flow-ui.xml")
            return ET.fromstring(adb("shell", "cat", "/sdcard/flow-ui.xml"))
        except (subprocess.CalledProcessError, ET.ParseError):
            if attempt == 2:
                raise
            time.sleep(.5)


def click_id(identifier, scroll=False, activate=True):
    for attempt in range(12 if scroll else 1):
        for node in tree().iter("node"):
            if node.get("resource-id", "").endswith(":id/" + identifier):
                bounds = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
                if len(bounds) == 4:
                    left, top, right, bottom = bounds
                    if right > left and bottom > top:
                        if activate:
                            adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                            time.sleep(1)
                        return
        if scroll:
            width, height = map(int, re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1])
            adb("shell", "input", "swipe", str(width // 2), str(height * 3 // 4), str(width // 2), str(height // 4), "350")
            time.sleep(.5)
    raise RuntimeError("Visible control missing: " + identifier)


def assert_no_microphone_access(ui=None):
    # Permission may be granted, but this screen suite must never open the mic.
    # AppOps retains access timestamps after recording stops or the app relaunches,
    # so a mistaken overlay tap cannot be hidden by the next force-stop.
    access = adb("shell", "cmd", "appops", "get", PACKAGE, "RECORD_AUDIO")
    (OUT / "microphone-access.txt").write_text(access)
    if re.search(r"\b(?:time|duration)=|\brunning\b", access, re.IGNORECASE):
        raise RuntimeError("Screen verification unexpectedly accessed microphone: " + access.strip())
    if ui is not None:
        active_statuses = {"Getting the microphone ready", "Listening", "Discarding recording", "Turning speech into text"}
        if any(n.get("resource-id", "").endswith(":id/tv_status") and n.get("text") in active_statuses
               for n in ui.iter("node")):
            raise RuntimeError("Screen verification unexpectedly started dictation")


def click_settings():
    click_id("btn_settings")
    # Verify the actual destination. A visible non-focusable overlay may intercept
    # an underlying control's center; locating that control is not navigation proof.
    wait_visible("automatic_typing_heading")
    assert_no_microphone_access()


def click_text(label, scroll=False):
    # A visible RadioGroup can include off-screen choices. Find the actual
    # enabled row, rather than assuming revealing its parent reveals every row.
    for attempt in range(12 if scroll else 1):
        ui = tree()
        for node in ui.iter("node"):
            if node.get("text") == label and node.get("enabled") == "true":
                bounds = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
                if len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                    adb("shell", "input", "tap", str((bounds[0] + bounds[2]) // 2), str((bounds[1] + bounds[3]) // 2))
                    time.sleep(1)
                    return
        if scroll and attempt < 11:
            width, height = map(int, re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1])
            adb("shell", "input", "swipe", str(width // 2), str(height * 3 // 4), str(width // 2), str(height // 4), "350")
            time.sleep(.5)
    # The log remains usable when Actions artifact storage is unavailable.
    print("Visible choices at selection failure:", ET.tostring(ui, encoding="unicode"), flush=True)
    raise RuntimeError("Enabled visible choice missing: " + label)


def launch():
    adb("shell", "am", "force-stop", PACKAGE)
    result = adb("shell", "am", "start", "-W", "-n", PACKAGE + "/com.flowdictation.android.MainActivity")
    with (OUT / "launch-results.txt").open("a") as output:
        output.write(result + "\n")
    if "Error:" in result or "Status: timeout" in result:
        raise RuntimeError("Android did not launch Flow successfully: " + result)
    time.sleep(1)


def visible_node(ui, identifier):
    for node in ui.iter("node"):
        if node.get("resource-id", "").endswith(":id/" + identifier):
            bounds = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
            if len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                return node
    raise RuntimeError("Visible control missing: " + identifier)


def capture(name, expected_id=None, expected_packages=()):
    ui = tree()
    # Keep the actual screen even when the strict expected-control assertion
    # fails, so foreground obstructions and app errors are reviewable.
    (OUT / (name + ".xml")).write_text(ET.tostring(ui, encoding="unicode"))
    (OUT / (name + ".png")).write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    assert_no_microphone_access(ui)
    if expected_id is not None:
        visible_node(ui, expected_id)
    if expected_packages and not any(n.get("package") in expected_packages for n in ui.iter("node")):
        raise RuntimeError("Screen did not expose expected app: " + ", ".join(expected_packages))
    return ui


def wait_visible(identifier, seconds=30):
    deadline = time.monotonic() + seconds
    while True:
        ui = tree()
        assert_no_microphone_access(ui)
        try:
            return visible_node(ui, identifier)
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)


def read_model_ui(operation, deadline):
    # Progress updates can prevent UIAutomator's idle wait while a healthy model
    # installation runs. Retry only dump/parse errors within the same deadline;
    # missing controls and app failure statuses must still fail immediately.
    while True:
        try:
            return operation()
        except (subprocess.CalledProcessError, ET.ParseError) as exc:
            with (OUT / "phone-model-ui-waits.txt").open("a") as output:
                output.write(f"{time.monotonic() - download_started:.1f}s: {exc}\n")
            (OUT / "phone-model-busy.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
            if time.monotonic() >= deadline:
                raise RuntimeError("Native model UI remained unavailable within the 5-minute verification limit") from exc
            time.sleep(.5)


apk = sys.argv[1]
adb("install", "-r", apk)
launch()
# Cold app/emulator startup may still be settling after am start returns. Wait
# for the required setup affordance, with no relaunches or skipped assertions.
wait_visible("btn_permission")
try:
    visible_node(tree(), "model_setup_start")
except RuntimeError:
    capture("phone-model-existing-install", "btn_talk")
else:
    first_run = capture("phone-model-first-run", "model_setup_start")
    setup_status = visible_node(first_run, "model_setup_status").get("text", "")
    if "Nothing downloads until you tap" not in setup_status and "previous download is saved" not in setup_status:
        raise RuntimeError("First-run model setup should wait for an explicit tap")
capture("phone-setup", "btn_permission")
click_id("btn_permission")
capture("phone-microphone-request", "permission_deny_button")
click_id("permission_deny_button")
if re.search(r"android.permission.RECORD_AUDIO:\s*granted=true", adb("shell", "dumpsys", "package", PACKAGE)):
    raise RuntimeError("Denying microphone permission unexpectedly granted it")
# Denying the feature permission must leave navigation and the retry affordance
# usable. The second request grants it through Android's actual system dialog.
click_settings()
click_id("back")
capture("phone-microphone-denied", "btn_permission")
click_id("btn_permission")
click_id("permission_allow_foreground_only_button")
if not re.search(r"android.permission.RECORD_AUDIO:\s*granted=true", adb("shell", "dumpsys", "package", PACKAGE)):
    raise RuntimeError("Retry did not grant microphone permission")
adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
launch()
capture("phone-ready", "btn_talk")
click_settings()
capture("phone-settings", "automatic_typing_heading")
click_id("automatic_typing_settings", scroll=True, activate=False)
capture("phone-automatic-typing-setup", "automatic_typing_settings")
click_id("model_download", scroll=True)
capture("phone-model-catalog", "select_dialog_listview")
click_id("text1")
ui = capture("phone-model-download-confirmation", "button1")
if visible_node(ui, "button1").get("text", "").lower() != "download":
    raise RuntimeError("Model confirmation did not offer an explicit Download action")
# Cancel before starting any network request; the first-run setup remains
# available and optional file import is checked independently below.
click_id("button2")
click_id("import_model", scroll=True, activate=False)
capture("phone-model-settings", "import_model")
click_id("import_model")
capture("phone-model-picker", expected_packages=("com.google.android.documentsui", "com.android.documentsui"))
adb("shell", "input", "keyevent", "4")
time.sleep(1)
visible_node(tree(), "import_model")
launch()
click_id("btn_history", scroll=True)
capture("phone-history", "search_history")
adb("shell", "cmd", "uimode", "night", "yes")
launch()
capture("phone-dark", "btn_talk")
click_settings()
click_id("automatic_typing_settings", scroll=True, activate=False)
capture("phone-dark-automatic-typing-setup", "automatic_typing_settings")
adb("shell", "cmd", "uimode", "night", "no")
adb("shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
launch()
click_id("bubble_switch", scroll=True)
click_id("transcript_editor", scroll=True)
ui = capture("phone-keyboard-bubble", "transcript_editor")
if visible_node(ui, "transcript_editor").get("focused") != "true":
    raise RuntimeError("Transcript editor did not receive keyboard focus")
# UIAutomator dumps only the focused app on this emulator. Save separate window
# evidence for the keyboard and non-focusable overlay rather than assuming they
# are present because the transcript editor exists.
ime = adb("shell", "dumpsys", "input_method")
windows = adb("shell", "dumpsys", "window", "windows")
(OUT / "phone-keyboard-bubble-ime.txt").write_text(ime)
(OUT / "phone-keyboard-bubble-windows.txt").write_text(windows)
if not re.search(r"mInputShown\s*=\s*true", ime):
    raise RuntimeError("Keyboard was not shown")
overlay_windows = [block for block in re.split(r"\n\s*Window #", windows)
                   if PACKAGE in block and re.search(r"ty=(?:2038|APPLICATION_OVERLAY)", block)]
if not overlay_windows or not any(re.search(r"(?:m)?hasSurface\s*=\s*true", block, re.IGNORECASE)
                                  for block in overlay_windows):
    raise RuntimeError("Flow overlay did not have a visible surface")

# Font scaling is a phone preference. Restore its original value even when an
# assertion fails; these screens verify scroll reachability, not speech capture.
original_scale = adb("shell", "settings", "get", "system", "font_scale").strip()
try:
    adb("shell", "settings", "put", "system", "font_scale", "1.5")
    launch()
    capture("phone-large-font-ready", "btn_talk")
    click_settings()
    capture("phone-large-font-settings", "automatic_typing_heading")
    click_id("automatic_typing_settings", scroll=True, activate=False)
    capture("phone-large-font-automatic-typing-setup", "automatic_typing_settings")
    for identifier in ("model_download", "import_model"):
        click_id(identifier, scroll=True, activate=False)
    capture("phone-large-font-model-settings", "import_model")
    # Reopen Settings at the top so the catalog button is reached by scrolling
    # down rather than assuming both model actions share the same viewport.
    launch()
    click_settings()
    click_id("model_download", scroll=True)
    capture("phone-large-font-model-catalog", "select_dialog_listview")
    adb("shell", "input", "keyevent", "4")
    time.sleep(1)
    click_id("app_permissions", scroll=True, activate=False)
    capture("phone-large-font-settings-privacy", "app_permissions")
    launch()
    # Verify transcript actions and navigation remain reachable without requiring
    # a recording or inventing a saved transcript.
    for identifier in ("btn_copy", "btn_share", "btn_save", "btn_export"):
        click_id(identifier, scroll=True, activate=False)
    capture("phone-large-font-transcript-actions", "btn_export")
    click_id("btn_history", scroll=True)
    capture("phone-large-font-history", "search_history")
finally:
    if original_scale == "null":
        adb("shell", "settings", "delete", "system", "font_scale")
    else:
        adb("shell", "settings", "put", "system", "font_scale", original_scale)

# Exercise the primary model flow once, after screenshots of the initial catalog
# and large fonts. Native initialization checks the downloaded model before the
# app exposes its enabled selection; this smoke test does not record speech.
launch()
click_settings()
click_id("model_download", scroll=True)
click_text("Whisper Tiny.en")
click_id("button1")
download_statuses = []
download_started = time.monotonic()
download_deadline = download_started + 300
try:
    # A fast successful download can hide Cancel before the first dump. Status
    # remains visible during and after the job, so accept progress or completed
    # installation here and require persisted selection below in both cases.
    (OUT / "phone-model-download-state.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    read_model_ui(lambda: click_id("model_import_status", scroll=True, activate=False), download_deadline)
    read_model_ui(lambda: capture("phone-model-download-state", "model_import_status"), download_deadline)
    while time.monotonic() < download_deadline:
        ui = read_model_ui(tree, download_deadline)
        status = visible_node(ui, "model_import_status").get("text", "")
        download_statuses.append(f"{time.monotonic() - download_started:.1f}s: {status}")
        (OUT / "phone-model-download-status.txt").write_text("\n".join(download_statuses))
        if status.startswith("Whisper Tiny.en installed."):
            break
        if re.search(r"could not install model|could not finish setup|failed|cancelled|canceled", status, re.IGNORECASE):
            raise RuntimeError("Model download did not complete: " + status)
        time.sleep(2)
    else:
        click_id("model_cancel")
        raise RuntimeError("Model download exceeded the 5-minute verification limit")
    launch()
    click_settings()
    click_id("rg_models", scroll=True, activate=False)
    click_text("Whisper Tiny.en", scroll=True)
    ui = capture("phone-model-installed-selected", "rg_models")
    if not any(n.get("text") == "Whisper Tiny.en" and n.get("checked") == "true"
               and n.get("enabled") == "true" for n in ui.iter("node")):
        raise RuntimeError("Downloaded Whisper Tiny.en could not be selected for use")
except Exception:
    (OUT / "phone-model-download-failure.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    (OUT / "phone-model-download-logcat.txt").write_text(adb("logcat", "-d", "-t", "250"))
    raise
assert_no_microphone_access()
print("Captured native screens; first-run model setup, native permissions, larger fonts and Whisper Tiny.en download/install/selection passed. Microphone capture was not started.")
