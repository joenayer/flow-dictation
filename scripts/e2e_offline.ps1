<#.
SYNOPSIS
    Offline E2E proof for flow on Windows (port of scripts/e2e_offline.sh).
DESCRIPTION
    Runs the integrator-owned smoke contract:

        python -m flow.flowd --smoke --fixture <wav> --expect <substring>

    against the first bench\fixtures\*.wav and requires SMOKE_PASS.
    Never fetches models. Unlike the Linux runner there is no
    `unshare -n` network namespace on Windows, so this script verifies
    offline behaviour WITHOUT network isolation: for a strict offline
    proof, disconnect the network (airplane mode / unplug) before running.

        powershell -ExecutionPolicy Bypass -File scripts\e2e_offline.ps1 `
            [-AppDir <dir>] [-PythonExe <python>] [-Expect <substring>]

    UNVERIFIED-ON-WINDOWS: developed on Linux; first live run must be
    watched on a real Windows 10/11 machine.
#>
[CmdletBinding()]
param(
    [string]$AppDir = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "python",
    [string]$Expect = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FixturesDir = Join-Path $AppDir "bench\\fixtures"
$Wav = Get-ChildItem -Path $FixturesDir -Filter "*.wav" -File |
    Select-Object -First 1
if (-not $Wav) {
    Write-Error "e2e_offline.ps1: no .wav fixtures under $FixturesDir"
    exit 1
}

if (-not $Expect) {
    $Txt = [System.IO.Path]::ChangeExtension($Wav.FullName, ".txt")
    if (Test-Path $Txt) {
        $Expect = (Get-Content $Txt -TotalCount 1)
    } else {
        $Expect = $Wav.BaseName -replace "_", " "
    }
}
if (-not $Expect) {
    Write-Error "e2e_offline.ps1: empty --expect substring"
    exit 1
}

Push-Location $AppDir
try {
    $env:PYTHONPATH = "$AppDir$(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" })"
    Write-Host "e2e_offline.ps1: fixture=$($Wav.FullName) expect='$Expect'"
    Write-Warning ("e2e_offline.ps1: Windows has no network namespace; " +
        "for a strict offline proof, disconnect the network before running.")
    # PS 5.1 + Stop turns native stderr into a terminating error; the
    # smoke contract speaks through stdout + exit code instead.
    $PrevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Out = & $PythonExe -m flow.flowd --smoke `
            --fixture $Wav.FullName --expect $Expect 2>&1
        $Rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PrevEAP
    }
} finally {
    Pop-Location
}

$Text = ($Out | Out-String)
Write-Host $Text
if ($Rc -eq 0 -and $Text -match "SMOKE_PASS") {
    Write-Host "e2e_offline.ps1: PASS ($($Wav.FullName))"
    exit 0
}
Write-Error ("e2e_offline.ps1: FAIL rc={0} (expected SMOKE_PASS from: " -f $Rc +
    "$PythonExe -m flow.flowd --smoke --fixture $($Wav.FullName) --expect $Expect)")
exit 1
