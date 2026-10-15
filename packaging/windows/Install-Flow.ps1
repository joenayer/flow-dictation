<#.
SYNOPSIS
    Install flow (Windows 10/11): app copy, venv, pip install, STT models,
    Start Menu shortcut, start-at-login entry.
DESCRIPTION
    Fully offline after install. Run once from an elevated-or-user
    PowerShell (no admin needed; everything installs per-user):

        powershell -ExecutionPolicy Bypass -File packaging\windows\Install-Flow.ps1

    What it does:
      1. Checks for Python 3.10+ on PATH.
      2. Copies the repo tree to %LOCALAPPDATA%\flow-linux\app (default).
      3. Creates .venv there and installs requirements-windows.txt.
      4. Downloads STT/VAD models + bench fixtures (scripts\fetch_models.ps1)
         unless -NoModels is given.
      5. Verifies `import sounddevice` (PortAudio) and prints guidance if the
         audio backend is missing.
      6. Creates a Start Menu shortcut and an HKCU Run value for
         start-at-login (unless -NoAutostart).
      7. Writes an install receipt used by Uninstall-Flow.ps1.

    UNVERIFIED-ON-WINDOWS: developed on Linux; first live run must be
    watched on a real Windows 10/11 machine.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "flow-linux"),
    [switch]$NoModels,
    [switch]$NoAutostart,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\\..")).Path
$AppDir = Join-Path $InstallDir "app"
$VenvDir = Join-Path $AppDir ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\\python.exe"
$Receipt = Join-Path $InstallDir "install.json"
# Windowless interpreter for shortcuts/autostart (no console flash);
# falls back to python.exe if the venv lacks it.
$VenvPyw = $VenvPy -replace 'python\.exe$', 'pythonw.exe'

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

# 1. Python 3.10+ ------------------------------------------------------------
try {
    $PyVersion = & $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
} catch {
    Fail "Python 3.10+ is required on PATH (got error running '$PythonExe'). Install from python.org and retry."
}
if (-not $PyVersion) { Fail "Could not determine the Python version from '$PythonExe'." }
$Parts = $PyVersion.Split(".")
if ([int]$Parts[0] -lt 3 -or ([int]$Parts[0] -eq 3 -and [int]$Parts[1] -lt 10)) {
    Fail "Python 3.10+ is required (found $PyVersion)."
}
Write-Host "Using $PythonExe (Python $PyVersion)"

# 2. Copy the repo tree ------------------------------------------------------
$Exclude = @(".venv", "__pycache__", ".git", ".pytest_cache", "models")
Write-Host "Copying $RepoRoot -> $AppDir"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Path (Join-Path $RepoRoot "*") -Destination $AppDir -Recurse -Force -Exclude $Exclude
# Keep any already-downloaded models if the user re-runs the installer.
$RepoModels = Join-Path $RepoRoot "models"
$AppModels = Join-Path $AppDir "models"
if ((Test-Path $RepoModels) -and -not (Test-Path $AppModels)) {
    Copy-Item -Path $RepoModels -Destination $AppModels -Recurse -Force
}

# 3. Venv + pip install ------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating venv at $VenvDir"
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "'python -m venv' failed." }
}
Write-Host "Installing requirements-windows.txt"
& $VenvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
& $VenvPy -m pip install -r (Join-Path $ScriptDir "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install of requirements failed." }
Write-Host "Installing flow (editable) into the venv"
& $VenvPy -m pip install -e $AppDir
if ($LASTEXITCODE -ne 0) { Fail "pip install -e failed." }

# 4. Models ------------------------------------------------------------------
if (-not $NoModels) {
    Write-Host "Fetching STT/VAD models (one-time, ~1GB)"
    & (Join-Path $AppDir "scripts\\fetch_models.ps1") -AppDir $AppDir -PythonExe $VenvPy
    if ($LASTEXITCODE -ne 0) { Fail "Model download failed. Re-run with -NoModels to skip, then run scripts\fetch_models.ps1 manually." }
} else {
    Write-Host "Skipping model download (-NoModels). Run scripts\fetch_models.ps1 later."
}

# 5. Audio backend check -----------------------------------------------------
$AudioOk = $true
try {
    & $VenvPy -c "import sounddevice; print(sounddevice.query_hostapis()[0]['name'])" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $AudioOk = $false }
} catch {
    $AudioOk = $false
}
if (-not $AudioOk) {
    Write-Warning ("sounddevice/PortAudio did not initialise. flow needs a working input device. " +
        "If 'pip show sounddevice' looks fine, install the PortAudio runtime (sounddevice ships " +
        "a bundled DLL on most setups; otherwise use the vendor installer) and re-run this script.")
} else {
    Write-Host "Audio backend OK"
}

# 6. Shortcuts ---------------------------------------------------------------
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\flow-linux"
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$ShortcutPath = Join-Path $StartMenuDir "flow.lnk"

if (-not (Test-Path $VenvPyw)) { $VenvPyw = $VenvPy }
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $VenvPyw
$Shortcut.Arguments = "-m flow.flowd"
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "flow: offline voice dictation"
$Shortcut.Save()
Write-Host "Start Menu shortcut: $ShortcutPath"

if (-not $NoAutostart) {
    $RunKey = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    $RunCmd = "`"$VenvPyw`" -m flow.flowd"
    New-ItemProperty -Path $RunKey -Name "flow-linux" -Value $RunCmd -PropertyType String -Force | Out-Null
    Write-Host "Start-at-login: HKCU Run value 'flow-linux'."
} else {
    Write-Host "Skipping start-at-login entry (-NoAutostart)."
}

# 7. Receipt -----------------------------------------------------------------
$ReceiptData = @{
    install_dir  = $InstallDir
    app_dir      = $AppDir
    venv_python  = $VenvPy
    venv_pythonw = $VenvPyw
    shortcut     = $ShortcutPath
    run_value    = "flow-linux"
    autostart    = (-not $NoAutostart.IsPresent)
    installed_at = (Get-Date).ToString("o")
} | ConvertTo-Json
[System.IO.File]::WriteAllText($Receipt, $ReceiptData, [System.Text.Encoding]::UTF8)

Write-Host ""
Write-Host "Installed. Start flow from the Start Menu ('flow'), or run:"
Write-Host "  $VenvPy -m flow.flowd"
Write-Host "To uninstall: packaging\windows\Uninstall-Flow.ps1"
