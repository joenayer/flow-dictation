<#.
SYNOPSIS
    One-time download of STT/VAD models + short English bench fixtures.
DESCRIPTION
    PowerShell port of scripts/fetch_models.sh for Windows installs.
    Downloads the sherpa-onnx Parakeet + Moonshine int8 packs and the
    Silero VAD model, extracts them under <AppDir>\models, fetches two
    short English clips, and converts them to 16 kHz mono int16 WAV
    fixtures via the install venv (numpy + soundfile).

        powershell -ExecutionPolicy Bypass -File scripts\fetch_models.ps1 `
            -AppDir %LOCALAPPDATA%\flow-linux\app `
            -PythonExe %LOCALAPPDATA%\flow-linux\app\.venv\Scripts\python.exe

    Idempotent: existing files are kept only when their SHA-256 matches.
    UNVERIFIED-ON-WINDOWS.
#>
[CmdletBinding()]
param(
    [string]$AppDir = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"  # PS 5.1 crawls on big downloads

# Pinned SHA-256, measured 2026-09-18 from the Linux mirror of these files.
$Hashes = @{
    "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2" = "157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad"
    "sherpa-onnx-moonshine-base-en-int8.tar.bz2"          = "21870cecaa2e44e4e2bf63e02d1072bed183ccd10284871353bd9d24dad14e5e"
    "silero_vad.onnx"                                    = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
    "librispeech_1.flac"                                 = "30885601173f96b0d8ddd020dc959b055c6c1582b85a33e3fcab8c4b08ed94c2"
    "librispeech_2.flac"                                 = "3fc09ec6d4cc496c530b2019b17bd8fc8ef8a43d6697090971dd1d52cc3d4d89"
}

function Resolve-AppDir([string]$Dir) {
    $Full = [System.IO.Path]::GetFullPath($Dir)
    foreach ($Need in @("flow", "pyproject.toml")) {
        if (-not (Test-Path (Join-Path $Full $Need))) {
            throw "AppDir $Full is missing $Need; pass -AppDir explicitly."
        }
    }
    return $Full
}

$AppDir = Resolve-AppDir $AppDir

$ModelsDir = Join-Path $AppDir "models"
$FixturesDir = Join-Path $AppDir "bench\\fixtures"
$AsrBase = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

$ParakeetTar = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2"
$ParakeetExtracted = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
$ParakeetDest = "parakeet-v2-int8"

$MoonshineTar = "sherpa-onnx-moonshine-base-en-int8.tar.bz2"
$MoonshineExtracted = "sherpa-onnx-moonshine-base-en-int8"
$MoonshineDest = "moonshine-base-en-int8"

$SileroOnnx = "silero_vad.onnx"

$Fix1Url = "https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/1.flac"
$Fix2Url = "https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/2.flac"

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
New-Item -ItemType Directory -Force -Path $FixturesDir | Out-Null

function Get-FileIfMissing([string]$Url, [string]$Out) {
    $Leaf = Split-Path -Leaf $Out
    $Sha256 = $Hashes[$Leaf]
    if (-not $Sha256) { throw "no pinned hash for $Leaf" }
    if ((Test-Path $Out) -and ((Get-FileHash $Out -Algorithm SHA256).Hash -ieq $Sha256)) {
        Write-Host "already have $Out (hash ok)"
        return
    }
    # Partial/corrupt files never count: download aside, verify, publish.
    $Part = "$Out.part"
    Write-Host "downloading $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Part
        $Got = (Get-FileHash $Part -Algorithm SHA256).Hash
        if ($Got -ine $Sha256) { throw "SHA-256 mismatch for $Out (got $Got)" }
        Move-Item -Force $Part $Out
    } catch {
        Remove-Item $Part -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Expand-ModelTar([string]$Tar, [string]$Extracted, [string]$Dest) {
    $DestDir = Join-Path $ModelsDir $Dest
    if (Test-Path $DestDir) {
        Write-Host "already extracted $DestDir"
        return
    }
    # Pin the inbox bsdtar (1803+); a bare `tar` may resolve to Git's.
    $TarExe = Join-Path ([Environment]::GetFolderPath("System")) "tar.exe"
    $Tmp = Join-Path $ModelsDir (".extract-{0}" -f [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    try {
        & $TarExe -xjf $Tar -C $Tmp
        if ($LASTEXITCODE -ne 0) { throw "tar failed for $Tar" }
        $Src = Join-Path $Tmp $Extracted
        if (-not (Test-Path $Src)) { throw "expected directory $Extracted inside $Tar" }
        Move-Item -Path $Src -Destination $DestDir
    } finally {
        if (Test-Path $Tmp) { Remove-Item $Tmp -Recurse -Force }
    }
}

function Assert-Exists([string]$Path) {
    if (-not (Test-Path $Path)) { throw "missing $Path after extract" }
}

Get-FileIfMissing "$AsrBase/$ParakeetTar" (Join-Path $ModelsDir $ParakeetTar)
Expand-ModelTar (Join-Path $ModelsDir $ParakeetTar) $ParakeetExtracted $ParakeetDest
Assert-Exists (Join-Path $ModelsDir "$ParakeetDest\\encoder.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$ParakeetDest\\decoder.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$ParakeetDest\\joiner.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$ParakeetDest\\tokens.txt")

Get-FileIfMissing "$AsrBase/$MoonshineTar" (Join-Path $ModelsDir $MoonshineTar)
Expand-ModelTar (Join-Path $ModelsDir $MoonshineTar) $MoonshineExtracted $MoonshineDest
Assert-Exists (Join-Path $ModelsDir "$MoonshineDest\\preprocess.onnx")
Assert-Exists (Join-Path $ModelsDir "$MoonshineDest\\encode.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$MoonshineDest\\uncached_decode.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$MoonshineDest\\cached_decode.int8.onnx")
Assert-Exists (Join-Path $ModelsDir "$MoonshineDest\\tokens.txt")

Get-FileIfMissing "$AsrBase/$SileroOnnx" (Join-Path $ModelsDir $SileroOnnx)
Assert-Exists (Join-Path $ModelsDir $SileroOnnx)

Get-FileIfMissing $Fix1Url (Join-Path $FixturesDir "librispeech_1.flac")
Get-FileIfMissing $Fix2Url (Join-Path $FixturesDir "librispeech_2.flac")

# Convert clips to 16 kHz mono int16 WAV via the install venv.
& $PythonExe -m pip install -q soundfile numpy
if ($LASTEXITCODE -ne 0) { throw "pip install soundfile/numpy failed" }

$ConvertPy = @'
"""Convert downloaded clips to 16 kHz mono int16 WAV via soundfile."""
import os
import sys

import numpy as np
import soundfile as sf

fixtures = sys.argv[1]
src_names = ("librispeech_1.flac", "librispeech_2.flac")
dst_names = ("librispeech_1.wav", "librispeech_2.wav")
target_rate = 16000


def resample(y, src_rate, dst_rate):
    if src_rate == dst_rate or y.size == 0:
        return y
    n_dst = int(round(y.size * dst_rate / src_rate))
    if n_dst <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=y.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    return np.interp(x_new, x_old, y).astype(np.float32)


for src_name, dst_name in zip(src_names, dst_names):
    src = os.path.join(fixtures, src_name)
    dst = os.path.join(fixtures, dst_name)
    if not os.path.isfile(src):
        raise SystemExit(f"missing fixture source {src}")
    data, rate = sf.read(src, dtype="float32", always_2d=True)
    data = resample(data[:, 0], int(rate), target_rate)
    duration = data.size / target_rate
    if duration > 10.01:
        data = data[: int(target_rate * 10)]
        duration = data.size / target_rate
    pcm = np.clip(np.round(data * 32767.0), -32768, 32767).astype(np.int16)
    sf.write(dst, pcm, target_rate, subtype="PCM_16")
    print(f"wrote {dst} ({duration:.2f}s, 16k mono)")
'@

$ConvertFile = Join-Path ([System.IO.Path]::GetTempPath()) "flow_convert_fixtures.py"
[System.IO.File]::WriteAllText($ConvertFile, $ConvertPy, [System.Text.Encoding]::UTF8)
try {
    & $PythonExe $ConvertFile $FixturesDir
    if ($LASTEXITCODE -ne 0) { throw "fixture conversion failed" }
} finally {
    Remove-Item $ConvertFile -Force -ErrorAction SilentlyContinue
}

Assert-Exists (Join-Path $FixturesDir "librispeech_1.wav")
Assert-Exists (Join-Path $FixturesDir "librispeech_2.wav")

Write-Host "fetch_models.ps1: ok"
Write-Host "  $(Join-Path $ModelsDir $ParakeetDest)"
Write-Host "  $(Join-Path $ModelsDir $MoonshineDest)"
Write-Host "  $(Join-Path $ModelsDir $SileroOnnx)"
Write-Host "  $(Join-Path $FixturesDir 'librispeech_1.wav')"
Write-Host "  $(Join-Path $FixturesDir 'librispeech_2.wav')"
