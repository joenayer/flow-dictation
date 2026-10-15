# Windows desktop setup

Flow includes a Windows desktop backend, but it has not been run on a real
Windows computer. The installer, microphone capture, global shortcuts, typing,
tray, display scaling, and uninstall behavior remain unverified on Windows.
Treat these instructions as a setup preview, not a tested Windows release.

## Requirements

- 64-bit Windows 10 or 11.
- Python 3.10 or newer on `PATH`. The installer uses `python` by default.
- A microphone, with desktop-app microphone access allowed in Windows
  Settings.
- Internet access and about 2 GB of free space for the copied app, Python
  environment, models, and setup files. Model download is optional during
  installation with `-NoModels`.

## Install from a checkout

Open PowerShell in the repository checkout and run:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\Install-Flow.ps1
```

The installer copies the checkout to
`%LOCALAPPDATA%\flow-linux\app`, creates a private Python environment,
installs `packaging\windows\requirements-windows.txt`, and installs the
speech models unless `-NoModels` is supplied. It adds a Start Menu shortcut
and, by default, starts Flow at login through the current user's `HKCU Run`
entry. No administrator access is intended.

Options:

- `-NoModels` skips the model download. Later, open PowerShell in the installed
  app folder and run:

  ```powershell
  $appDir = "$env:LOCALAPPDATA\flow-linux\app"
  & "$appDir\scripts\fetch_models.ps1" -AppDir $appDir -PythonExe "$appDir\.venv\Scripts\python.exe"
  ```
- `-NoAutostart` skips the login entry.
- `-InstallDir <path>` changes the app install directory. Settings and user
  data remain in the Windows AppData locations listed below.
- `-PythonExe <path>` selects the Python used to create the environment.

After installation, launch **flow** from the Start Menu. The app also supports
launching from PowerShell in the installed directory:

```powershell
.\.venv\Scripts\python.exe -m flow.flowd
```

To uninstall the app and keep its settings, history, and notes:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\Uninstall-Flow.ps1
```

Add `-Purge` only when you also want the install directory and
`%APPDATA%\flow-linux` settings removed. The uninstaller removes Flow's Start
Menu shortcut and its `HKCU Run` login entry.

## Files and shortcuts

Settings are stored in `%APPDATA%\flow-linux\settings.json`. History and notes
are stored under `%LOCALAPPDATA%\flow-linux`. By default, the app and models
are under `%LOCALAPPDATA%\flow-linux\app`; `-InstallDir` changes this path.
The installer creates the Start
Menu shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\flow-linux`.

Current default shortcuts are:

| Action | Shortcut |
| --- | --- |
| Hold to dictate | `Alt+W` |
| Toggle hands-free | `Alt+E` or double-tap `Alt+W` |
| Command mode | `Alt+G` |
| Paste last transcript | `Alt+B` |
| Copy last transcript | `Alt+C` |
| Cancel | `Esc` |

You can change shortcuts in Settings. The Windows backend contains filtering
for configured shortcut and injected-key events, but actual key behavior and
conflicts need testing on Windows. Rebind any shortcut that conflicts with an
app or Windows feature.

Command mode starts with “hey flow”. Supported commands include “new line”,
“new paragraph”, “press enter”, “delete last word”, “undo”, “select all”,
“date”, “time”, “type …”, “spell …”, “shout …”, and “small …”. Text and key
actions are sent through the Windows typing backend. Target-app behavior has
not been verified; use the app's Copy control if typing does not work.

## Verification limits

The Python tests include mocked Windows-backend checks and a live listener
check that only runs on Windows. Running the mocked tests on Linux does not
verify Windows microphone capture, shortcut delivery, typing, installer
behavior, or user-data preservation. No Windows CI job currently covers these
paths.

Setup downloads Python packages and, unless `-NoModels` is used, speech models.
This repository has not completed Windows network testing, so it does not make
a verified claim about all network activity after installation. Physical
Windows testing is required before treating the installer or app behavior as
ready for general use.
