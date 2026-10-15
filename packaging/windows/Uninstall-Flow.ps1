<#.
SYNOPSIS
    Uninstall the per-user flow installation created by Install-Flow.ps1.
DESCRIPTION
    Stops any running flowd (current user only), removes the Start Menu
    shortcut and the HKCU Run start-at-login value, and — unless -KeepApp is
    given — deletes the app copy plus the install receipt. User data
    (notes.json, history.jsonl) is preserved unless -Purge is given, which
    also deletes settings (%APPDATA%\flow-linux) and the install dir.
    Refuses drive roots, home dirs, and dirs without install markers.

        powershell -ExecutionPolicy Bypass -File packaging\windows\Uninstall-Flow.ps1 [-Purge]

    UNVERIFIED-ON-WINDOWS: developed on Linux; verify on Windows 10/11.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "flow-linux"),
    [switch]$KeepApp,
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Receipt = Join-Path $InstallDir "install.json"
$ShortcutPath = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\flow-linux\\flow.lnk"
$StartMenuDir = Split-Path -Parent $ShortcutPath
$StartupTarget = Join-Path ([Environment]::GetFolderPath("Startup")) "flow-linux.bat"

if (Test-Path $Receipt) {
    try {
        $Saved = Get-Content $Receipt -Raw | ConvertFrom-Json
        if ($Saved.shortcut) { $ShortcutPath = [string]$Saved.shortcut }
        if ($Saved.startup) { $StartupTarget = [string]$Saved.startup }
    } catch {
        Write-Warning "Could not parse $Receipt; using default paths."
    }
}

# Stop a running flowd owned by this user (best effort).
Get-CimInstance Win32_Process -Filter "name='python.exe' or name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match "-m flow\.flowd" } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped flowd (pid $($_.ProcessId))"
        } catch {
            Write-Warning "Could not stop pid $($_.ProcessId): $_"
        }
    }

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Removed $ShortcutPath"
}
if ((Test-Path $StartMenuDir) -and @(Get-ChildItem $StartMenuDir -Force).Count -eq 0) {
    Remove-Item $StartMenuDir -Force
}
if (Test-Path $StartupTarget) {
    Remove-Item $StartupTarget -Force
    Write-Host "Removed legacy $StartupTarget"
}
$RunKey = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
try {
    if (Get-ItemProperty -Path $RunKey -Name "flow-linux" -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $RunKey -Name "flow-linux" -Force
        Write-Host "Removed start-at-login (HKCU Run)."
    }
} catch {
    Write-Warning "Could not remove HKCU Run value: $_"
}

$AppDir = Join-Path $InstallDir "app"

function Assert-SafeInstallDir([string]$Dir) {
    if ([string]::IsNullOrWhiteSpace($Dir)) {
        throw "Refusing to delete an empty install dir."
    }
    $Full = [System.IO.Path]::GetFullPath($Dir)
    $Root = [System.IO.Path]::GetPathRoot($Full).TrimEnd('\')
    if ($Full.TrimEnd('\') -ieq $Root) {
        throw "Refusing to delete drive root: $Full"
    }
    $HomeDir = [Environment]::GetFolderPath("UserProfile")
    if ($Full.TrimEnd('\') -ieq $HomeDir.TrimEnd('\')) {
        throw "Refusing to delete home dir: $Full"
    }
    return $Full
}

$InstallFull = Assert-SafeInstallDir $InstallDir
$AppFull = Join-Path $InstallFull "app"
$ReceiptFull = Join-Path $InstallFull "install.json"
$LooksInstalled = (Test-Path $ReceiptFull) -or (Test-Path (Join-Path $AppFull "flow\flowd.py"))

if (-not $KeepApp) {
    if (-not $LooksInstalled) {
        Write-Warning "$InstallFull does not look like a flow install; leaving it alone."
    } else {
        # Delete ONLY the app copy + receipt. User data (notes.json,
        # history.jsonl) lives in $InstallFull and survives unless -Purge.
        if ($PSCmdlet.ShouldProcess($AppFull, "Remove app dir")) {
            if (Test-Path $AppFull) {
                Remove-Item $AppFull -Recurse -Force
                Write-Host "Removed $AppFull"
            }
        }
        if ((Test-Path $ReceiptFull) -and $PSCmdlet.ShouldProcess($ReceiptFull, "Remove receipt")) {
            Remove-Item $ReceiptFull -Force
        }
    }
} else {
    Write-Host "Kept $AppFull (-KeepApp)."
}

if ($Purge) {
    foreach ($Path in @(
        (Join-Path $env:APPDATA "flow-linux"),
        $InstallFull
    )) {
        if ((Test-Path $Path) -and $PSCmdlet.ShouldProcess($Path, "Purge")) {
            Remove-Item $Path -Recurse -Force
            Write-Host "Purged $Path"
        }
    }
}

Write-Host "Uninstall complete."
