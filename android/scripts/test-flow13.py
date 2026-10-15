#!/usr/bin/env python3
"""Run real separately downloaded Parakeet and large-font settings checks on CI's emulator."""
import pathlib
import subprocess
import sys

out = pathlib.Path('parakeet-evidence')
out.mkdir(exist_ok=True)
package = 'com.flowdictation.android.preview'
# Instrumentation can have a different scoped-storage view from adb's shell.
# Stage fixtures as the app user so both file checks and native decoding read
# the same bytes, without granting broad storage access to the app.
private_root = subprocess.check_output(['adb', 'shell', 'run-as', package, 'pwd'], text=True, encoding='utf-8', errors='replace').strip()
base = private_root + '/files/flow-parakeet'
listed = subprocess.check_output(['adb', 'shell', 'run-as', package, 'find', base, '-name', '*.wav'], text=True, encoding='utf-8', errors='replace').splitlines()
if not listed:
    sys.exit('The official Parakeet archive has no reference WAV; real decoding cannot be verified.')
args = ['adb', 'shell', 'am', 'instrument', '-w', '-r',
        '-e', 'class', 'com.flowdictation.android.Flow13DeviceTest,com.flowdictation.android.TranscriberIncrementalLatencyDeviceTest',
        '-e', 'parakeetModelDir', base, '-e', 'parakeetAudio', listed[0].strip(),
        'com.flowdictation.android.preview.test/androidx.test.runner.AndroidJUnitRunner']
result = subprocess.run(args, text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
(out / 'instrumentation.txt').write_text(result.stdout, encoding='utf-8')
print(result.stdout)
logs = subprocess.check_output(['adb', 'logcat', '-d'], text=True, encoding='utf-8', errors='replace')
(out / 'logcat.txt').write_text(logs, encoding='utf-8')
if result.returncode or 'FAILURES!!!' in result.stdout or 'INSTRUMENTATION_FAILED' in result.stdout or 'OK (4 tests)' not in result.stdout:
    sys.exit('Flow 1.3 native checks failed; see instrumentation.txt.')
