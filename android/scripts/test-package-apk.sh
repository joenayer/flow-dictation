#!/bin/sh
# Offline fixture: verify packaging rejects unsigned input before publishing.
# The signature tool is mocked here; CI also verifies the actual built APK.
set -eu
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/project/scripts" "$tmp/project/app" "$tmp/bin"
cp "$root/scripts/package-apk.sh" "$tmp/project/scripts/"
printf 'versionName = "1.1.1"\nversionCode = 3\n' > "$tmp/project/app/build.gradle.kts"
printf 'fixture APK bytes\n' > "$tmp/project/input.apk"
cat > "$tmp/bin/apksigner" <<'SIGNER'
#!/bin/sh
set -eu
test "$1" = verify
test "$2" = --verbose
test "$3" = --print-certs
test -f "$4"
test "${REJECT_SIGNATURE:-0}" = 0 || exit 1
printf 'Fixture signing certificate (not a real signature verification)\n'
SIGNER
cat > "$tmp/bin/aapt" <<'AAPT'
#!/bin/sh
set -eu
test "$1" = dump
test "$2" = badging
test -f "$3"
printf "package: name='com.flowdictation.android.preview' versionCode='3' versionName='1.1.1'\n"
printf 'application-debuggable\n'
printf "native-code: %s\n" "${NATIVE_ABIS:-'arm64-v8a' 'armeabi-v7a' 'x86_64'}"
if [ "${INTERNET_PERMISSION:-1}" = 1 ]; then
    printf "uses-permission: name='android.permission.INTERNET'\n"
fi
AAPT
chmod +x "$tmp/bin/apksigner" "$tmp/bin/aapt"
APKSIGNER="$tmp/bin/apksigner" GITHUB_SHA=fixture-commit GITHUB_RUN_ID=fixture-run \
    sh "$tmp/project/scripts/package-apk.sh" input.apk dist
cmp "$tmp/project/input.apk" "$tmp/project/dist/Flow-Dictation-1.1.1.apk"
(cd "$tmp/project/dist" && sha256sum -c Flow-Dictation-1.1.1.apk.sha256)
grep -q 'Source commit: fixture-commit' "$tmp/project/dist/Flow-Dictation-1.1.1.build.txt"
grep -q 'Fixture signing certificate' "$tmp/project/dist/Flow-Dictation-1.1.1.build.txt"
APKSIGNER="$tmp/bin/apksigner" sh "$tmp/project/scripts/package-apk.sh" input.apk universal universal
test -f "$tmp/project/universal/Flow-Dictation-1.1.1-universal.apk"
APKSIGNER="$tmp/bin/apksigner" NATIVE_ABIS="'arm64-v8a'" \
    sh "$tmp/project/scripts/package-apk.sh" input.apk arm64 arm64-v8a
test -f "$tmp/project/arm64/Flow-Dictation-1.1.1-arm64-v8a.apk"
if APKSIGNER="$tmp/bin/apksigner" sh "$tmp/project/scripts/package-apk.sh" input.apk wrong-abi arm64-v8a; then
    echo 'packaging accepted a universal APK as arm64-only' >&2
    exit 1
fi
test ! -d "$tmp/project/wrong-abi"
if APKSIGNER="$tmp/bin/apksigner" REJECT_SIGNATURE=1 \
    sh "$tmp/project/scripts/package-apk.sh" input.apk rejected; then
    echo 'packaging accepted rejected signature' >&2
    exit 1
fi
test ! -d "$tmp/project/rejected"
if APKSIGNER="$tmp/missing-tool" sh "$tmp/project/scripts/package-apk.sh" input.apk missing; then
    echo 'packaging accepted missing signature verifier' >&2
    exit 1
fi
test ! -d "$tmp/project/missing"
if APKSIGNER="$tmp/bin/apksigner" INTERNET_PERMISSION=0 \
    sh "$tmp/project/scripts/package-apk.sh" input.apk no-internet; then
    echo 'packaging accepted missing model-download permission' >&2
    exit 1
fi
test ! -d "$tmp/project/no-internet"
echo 'APK packaging regression fixture passed'
