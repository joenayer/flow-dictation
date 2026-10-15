# Building Flow for Android

This guide covers local Android builds. Phone installation steps are in
[INSTALL.md](../INSTALL.md); behavior of custom words and aliases is in
[the vocabulary guide](vocabulary.md).

## Requirements

- JDK 17
- Android SDK platform 34 and build-tools 34.0.0
- A POSIX shell with `curl`, `tar`, and `sha256sum` for fetching Android
  dependencies (Linux, WSL, or Git Bash; on macOS, install GNU coreutils and
  ensure its `sha256sum` is on `PATH`)

The app uses Android Gradle Plugin 8.5.2, Gradle 8.7, and Kotlin 1.9.24. The
Gradle wrapper is in `android/`. Set `JAVA_HOME` to JDK 17 and `ANDROID_HOME`
to your installed SDK, or set `sdk.dir` in an untracked `android/local.properties`.
Android 1.5.0 is version code 8; the
preview package ID is `com.flowdictation.android.preview`, with minimum SDK 26
and target/compile SDK 34.

## Fetch dependencies and build

From the `android` directory, fetch the Android runtime and small offline VAD
asset:

```sh
./scripts/fetch-deps.sh runtime-only
```

This downloads the pinned sherpa-onnx Android library and Silero VAD file.
Silero detects pauses; it is not a speech-recognition model. This command does
not fetch speech models. Use the explicit `runtime-only` argument to fetch only
the runtime and pause detector. The recommended Parakeet model and optional
Moonshine and Whisper models download in the app or can be imported there.

Build the universal debug APK:

```sh
./gradlew assembleDebug
```

Gradle writes the APK to
`app/build/outputs/apk/debug/app-debug.apk`. For an ARM64-only APK, build and
package it with:

```sh
./gradlew assembleDebug -PflowAbi=arm64-v8a
./scripts/package-apk.sh app/build/outputs/apk/debug/app-debug.apk dist arm64-v8a
```

The package script checks the Preview package, version, ABI, internet
permission, and APK signature, then writes the versioned APK, SHA-256 file, and
build details into `dist/`. It needs Android build-tools 34.0.0, including
`apksigner` and `aapt`; set `APKSIGNER` or `AAPT` if those tools are not on the
expected path. Packaging does not create or replace a signing key.

## Preview release builds

For update compatibility details, see [Preview signing](preview-signing.md).

The packaging script `scripts/build-preview.ps1` can build universal and ARM64
Preview APKs and write checksums and build details to `dist/`. It requires
JDK 17, Android SDK build-tools 34.0.0, and a signing key whose certificate
matches the official release certificate:

```text
55d12445242c1cdcc248f6bc5026aba624e73de2f47496f328d8affb7222126b
```

From the repository root in PowerShell, point it at the existing SDK and a
preview signing key:

```powershell
$env:JAVA_HOME = 'C:\path\to\jdk-17'
& .\android\scripts\build-preview.ps1 -SdkRoot 'C:\path\to\Android\Sdk' -KeystorePath 'C:\private\preview.keystore'
```

Both paths must already exist. The local signing key stays outside the
checkout. An ordinary local debug build does not need the official signing key.

Preview APK updates require the same signing certificate as the installed
Preview. Official APK checksums are on the
[1.5.0 release page](https://github.com/joenayer/flow-releases/releases/tag/android-v1.5.0).

## CI and official downloads

After checks pass, public source CI makes a development APK and checksum
available as build artifacts. The APK uses temporary signing and cannot update
the official Preview. Official matching-key APKs are distributed through the
[Flow Releases repository](https://github.com/joenayer/flow-releases/releases).
