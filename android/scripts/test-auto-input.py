#!/usr/bin/env python3
"""Run real accessibility/overlay insertion tests on a disposable Android emulator.

Usage: test-auto-input.py path/to/app-debug-androidTest.apk
The target preview APK must already be installed. No speech model is needed;
recognized text is supplied in-process to the production bridge by instrumentation.
No microphone capture or recognition accuracy is claimed by this suite.
"""
import pathlib
import re
import subprocess
import sys

PACKAGE = "com.flowdictation.android.preview"
TEST_PACKAGE = PACKAGE + ".test"
SERVICE = PACKAGE + "/com.flowdictation.android.TypingAccessibilityService"
OUT = pathlib.Path("auto-input-tests")
OUT.mkdir(exist_ok=True)


def adb(*args, binary=False):
    options = {} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}
    return subprocess.check_output(["adb", *args], **options)


def evidence():
    commands = {
        "final.png": ("exec-out", "screencap", "-p"),
        "logcat.txt": ("logcat", "-d", "-t", "3000"),
        "crash-logcat.txt": ("logcat", "-d", "-b", "crash"),
        "windows.txt": ("shell", "dumpsys", "window", "windows"),
        "accessibility.txt": ("shell", "dumpsys", "accessibility"),
        "input-method.txt": ("shell", "dumpsys", "input_method"),
    }
    for name, command in commands.items():
        try:
            data = adb(*command, binary=name.endswith(".png"))
            if isinstance(data, bytes):
                (OUT / name).write_bytes(data)
            else:
                (OUT / name).write_text(data)
        except subprocess.CalledProcessError as error:
            print("Evidence collection failed:", name, error, file=sys.stderr)
    subprocess.run(["adb", "pull", f"/sdcard/Android/data/{PACKAGE}/files/auto-input-tests/.", str(OUT)], check=False)


def assert_no_flow_crash(crash_log):
    # Only fatal records from Flow or its separate fixture process count here.
    # The buffer is cleared before instrumentation; unrelated platform startup
    # failures are separately recorded by prepare-emulator.py.
    process_name = rf"{re.escape(PACKAGE)}(?:\.test)?(?:[:][A-Za-z0-9_.$-]+)?"
    process_pattern = rf"\bProcess:\s*({process_name})(?=[:,\s]|$)"
    native_pattern = rf">>>\s*({process_name})\s*<<<"
    crashed = sorted(set(re.findall(process_pattern, crash_log) + re.findall(native_pattern, crash_log)))
    if crashed:
        raise RuntimeError("Native verification crashed an app process: " + ", ".join(crashed))


def main():
    if len(sys.argv) != 2 or not pathlib.Path(sys.argv[1]).is_file():
        raise SystemExit(__doc__)
    # These grants/toggles are CI setup only, never a production onboarding path.
    if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise SystemExit("Refusing test permission changes on a physical device; use a disposable emulator.")
    original_services = adb("shell", "settings", "get", "secure", "enabled_accessibility_services").strip()
    original_enabled = adb("shell", "settings", "get", "secure", "accessibility_enabled").strip()
    # Match the CI emulator profile: touch coordinates must not race an activity
    # or IME transition. Preserve the device's settings after the suite.
    animation_names = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")
    original_animations = {name: adb("shell", "settings", "get", "global", name).strip()
                           for name in animation_names}
    adb("install", "-r", sys.argv[1])
    adb("shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
    adb("logcat", "-c")
    try:
        for name in animation_names:
            adb("shell", "settings", "put", "global", name, "0")
        adb("shell", "settings", "put", "secure", "enabled_accessibility_services", SERVICE)
        adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
        result = adb("shell", "am", "instrument", "-w", "-r", "-e", "class",
                     "com.flowdictation.android.AutoInputDeviceTest,com.flowdictation.android.DeliveryDeviceTest",
                     TEST_PACKAGE + "/androidx.test.runner.AndroidJUnitRunner")
        (OUT / "instrumentation.txt").write_text(result)
        print(result)
        crash_log = adb("logcat", "-d", "-b", "crash")
        (OUT / "checked-app-crashes.txt").write_text(crash_log)
        assert_no_flow_crash(crash_log)
        # am instrument may exit zero even when assertions or runner startup fail.
        if "OK (10 tests)" not in result or "FAILURES!!!" in result or "INSTRUMENTATION_FAILED" in result:
            raise RuntimeError("Automatic input instrumentation did not pass all ten tests")
    finally:
        evidence()
        for name, value in (("enabled_accessibility_services", original_services),
                            ("accessibility_enabled", original_enabled)):
            if value == "null":
                adb("shell", "settings", "delete", "secure", name)
            else:
                adb("shell", "settings", "put", "secure", name, value)
        for name, value in original_animations.items():
            if value == "null":
                adb("shell", "settings", "delete", "global", name)
            else:
                adb("shell", "settings", "put", "global", name, value)
    print("Ten native emulator tests passed. Automatic typing safety and clipboard recovery tested; speech recognition untested.")


if __name__ == "__main__":
    main()
