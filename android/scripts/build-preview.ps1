param(
    [string]$SdkRoot = $env:ANDROID_SDK_ROOT,
    [string]$KeystorePath = (Join-Path $env:USERPROFILE '.android\debug.keystore')
)
$ErrorActionPreference = 'Stop'
$androidRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (!$SdkRoot) { $SdkRoot = $env:ANDROID_HOME }
if (!$SdkRoot) { throw 'Set ANDROID_SDK_ROOT or pass -SdkRoot for your Android SDK.' }
$SdkRoot = (Resolve-Path $SdkRoot).Path
$KeystorePath = (Resolve-Path $KeystorePath).Path
$expectedCert = '55d12445242c1cdcc248f6bc5026aba624e73de2f47496f328d8affb7222126b'
$version = [regex]::Match((Get-Content (Join-Path $androidRoot 'app\build.gradle.kts') -Raw), 'versionName\s*=\s*"([^"]+)"').Groups[1].Value
$code = [regex]::Match((Get-Content (Join-Path $androidRoot 'app\build.gradle.kts') -Raw), 'versionCode\s*=\s*(\d+)').Groups[1].Value
if (!$version -or !$code) { throw 'Missing Android version.' }
if (!$env:JAVA_HOME) { throw 'Set JAVA_HOME to your JDK 17 directory first.' }
$signer = Join-Path $SdkRoot 'build-tools\34.0.0\apksigner.bat'
$aapt = Join-Path $SdkRoot 'build-tools\34.0.0\aapt.exe'
$keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
$certReport = & $keytool -list -keystore $KeystorePath -storepass android -alias androiddebugkey 2>&1
if ($LASTEXITCODE -ne 0 -or (($certReport -join "`n") -replace ':', '').ToLowerInvariant() -notmatch $expectedCert) {
    throw 'The preview key is missing or has a different certificate. No key will be generated.'
}
$commit = (& git -C $androidRoot rev-parse HEAD).Trim()
$variables = @('PATH','ANDROID_HOME','ANDROID_SDK_ROOT','FLOW_PREVIEW_KEYSTORE_PATH','FLOW_PREVIEW_STORE_PASSWORD','FLOW_PREVIEW_KEY_ALIAS','FLOW_PREVIEW_KEY_PASSWORD')
$prior = @{}
foreach ($name in $variables) { $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$previousLocation = Get-Location
try {
    # A short process-only PATH avoids Windows test-worker launch failures.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:ANDROID_HOME = $SdkRoot
    $env:ANDROID_SDK_ROOT = $SdkRoot
    $env:FLOW_PREVIEW_KEYSTORE_PATH = $KeystorePath
    $env:FLOW_PREVIEW_STORE_PASSWORD = 'android'
    $env:FLOW_PREVIEW_KEY_ALIAS = 'androiddebugkey'
    $env:FLOW_PREVIEW_KEY_PASSWORD = 'android'
    Set-Location $androidRoot
    # Merge native stderr inside cmd so PowerShell 5 does not turn harmless
    # SDK warnings into terminating errors. The actual exit code still gates.
    & $env:ComSpec /d /c '.\gradlew.bat --no-daemon testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest -PflowAbi=universal 2>&1'
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests, lint or universal build failed.' }
    New-Item -ItemType Directory -Force -Path dist | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($abi in @('universal','arm64-v8a')) {
        if ($abi -eq 'arm64-v8a') {
            & $env:ComSpec /d /c '.\gradlew.bat --no-daemon assembleDebug -PflowAbi=arm64-v8a 2>&1'
            if ($LASTEXITCODE -ne 0) { throw 'Samsung ARM64 build failed.' }
        }
        $source = Join-Path $androidRoot 'app\build\outputs\apk\debug\app-debug.apk'
        $signature = & $signer verify --verbose --print-certs $source
        if ($LASTEXITCODE -ne 0 -or ($signature -join "`n") -notmatch "certificate SHA-256 digest: $expectedCert") { throw 'APK signature or certificate verification failed.' }
        $badging = & $aapt dump badging $source
        if ($LASTEXITCODE -ne 0) { throw 'APK manifest could not be read.' }
        $manifest = $badging -join "`n"
        if (!$manifest.Contains("package: name='com.flowdictation.android.preview' versionCode='$code' versionName='$version'")) { throw 'Unexpected package or version.' }
        if (!$manifest.Contains("sdkVersion:'26'") -or !$manifest.Contains("targetSdkVersion:'34'")) { throw 'Unexpected Android compatibility levels.' }
        $archive = [IO.Compression.ZipFile]::OpenRead($source)
        try {
            $names = @($archive.Entries | ForEach-Object { $_.FullName })
            if (@($names | Where-Object { $_ -like 'assets/models/*' -or $_ -match 'parakeet' }).Count) { throw 'Speech models must not be bundled.' }
            if ('assets/silero_vad.onnx' -notin $names) { throw 'Small offline VAD fallback missing.' }
            $actualAbis = @($names | Where-Object { $_ -match '^lib/[^/]+/.+\.so$' } | ForEach-Object { $_.Split('/')[1] } | Sort-Object -Unique)
            $expectedAbis = if ($abi -eq 'arm64-v8a') { @('arm64-v8a') } else { @('arm64-v8a','armeabi-v7a','x86_64') }
            if (@(Compare-Object $expectedAbis $actualAbis).Count) { throw 'Unexpected native library ABIs.' }
        } finally { $archive.Dispose() }
        $name = "Flow-Dictation-$version-$abi.apk"
        $destination = Join-Path $androidRoot "dist\$name"
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        # GNU sha256sum treats a CRLF's CR as part of the APK filename.
        [IO.File]::WriteAllText("$destination.sha256", "$hash  $name`n", [Text.Encoding]::ASCII)
        @("Flow Preview $version", "Package: com.flowdictation.android.preview", "Version code: $code", "ABI: $abi", "Source commit: $commit (working tree may contain pending changes)", "APK bytes: $((Get-Item -LiteralPath $destination).Length)", "SHA-256: $hash", '', $signature, '', $badging) | Set-Content -Encoding utf8 -LiteralPath ($destination -replace '\.apk$', '.build.txt')
        Write-Output "Verified $name ($((Get-Item -LiteralPath $destination).Length) bytes), SHA-256 $hash"
    }
    # Leave the build tree ready for the x86_64 native emulator suites.
    & $env:ComSpec /d /c '.\gradlew.bat --no-daemon assembleDebug assembleDebugAndroidTest -PflowAbi=universal 2>&1'
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the universal test build.' }
} finally {
    Set-Location $previousLocation
    foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process') }
}
