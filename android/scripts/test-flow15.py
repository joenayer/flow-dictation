#!/usr/bin/env python3
"""Run native gesture, appearance, processing, meter and dictionary-import checks.

Requires installed preview and test APKs on a disposable emulator. Audio levels
are injected through the production event bus; this does not test a physical mic.
"""
import pathlib
import subprocess
import sys

out = pathlib.Path('flow15-evidence')
out.mkdir(exist_ok=True)
if subprocess.check_output(['adb', 'shell', 'getprop', 'ro.kernel.qemu'], text=True, encoding='utf-8', errors='replace').strip() != '1':
    sys.exit('Use a disposable emulator for these UI and preference checks.')
result = subprocess.run([
    'adb', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'class',
    'com.flowdictation.android.Flow15DeviceTest',
    '-e', 'flow15Screens', 'true',
    'com.flowdictation.android.preview.test/androidx.test.runner.AndroidJUnitRunner',
], text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
(out / 'instrumentation.txt').write_text(result.stdout, encoding='utf-8')
print(result.stdout)
logs = subprocess.check_output(['adb', 'logcat', '-d', '-t', '3000'], text=True, encoding='utf-8', errors='replace')
(out / 'logcat.txt').write_text(logs, encoding='utf-8')
subprocess.run(['adb', 'pull',
    '/sdcard/Android/data/com.flowdictation.android.preview/files/flow15-ux-review',
    str(out / 'screens')], check=False)
if result.returncode or 'FAILURES!!!' in result.stdout or 'INSTRUMENTATION_FAILED' in result.stdout or 'OK (4 tests)' not in result.stdout:
    sys.exit('Flow 1.5 native checks failed; see instrumentation.txt.')
print('Four native UX checks passed. Physical microphone and Samsung behavior remain separate checks.')
