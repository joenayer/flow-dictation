#!/bin/sh
# Package the built debug APK with a user-friendly versioned filename.
set -eu

cd "$(dirname "$0")/.."

source_apk="${1:-app/build/outputs/apk/debug/app-debug.apk}"
output_dir="${2:-dist}"
delivery_abi="${3:-}"
case "$delivery_abi" in
    ""|arm64-v8a|universal) ;;
    *) echo "Delivery ABI must be arm64-v8a or universal" >&2; exit 1 ;;
esac

if [ ! -f "$source_apk" ]; then
    echo "APK not found: $source_apk" >&2
    echo "Build it first with ./gradlew assembleDebug" >&2
    exit 1
fi

version="$(sed -nE 's/^[[:space:]]*versionName[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' app/build.gradle.kts | head -n 1)"
if [ -z "$version" ]; then
    echo "Could not read versionName from app/build.gradle.kts" >&2
    exit 1
fi

# Fail before publishing if Android cannot verify the APK signature. Do not
# generate or rotate signing keys here: this must preserve the build's key.
apksigner="${APKSIGNER:-}"
if [ -z "$apksigner" ]; then
    if command -v apksigner >/dev/null 2>&1; then
        apksigner="$(command -v apksigner)"
    else
        sdk_root="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
        apksigner="$sdk_root/build-tools/34.0.0/apksigner"
    fi
fi
if [ ! -x "$apksigner" ]; then
    echo "apksigner is required; set APKSIGNER or install Android build-tools 34.0.0" >&2
    exit 1
fi
aapt="${AAPT:-$(dirname "$apksigner")/aapt}"
if [ ! -x "$aapt" ]; then
    echo "aapt is required; set AAPT or install Android build-tools 34.0.0" >&2
    exit 1
fi
manifest_report="$(mktemp)"
signature_report="$(mktemp)"
trap 'rm -f "$signature_report" "$manifest_report"' EXIT HUP INT TERM
"$apksigner" verify --verbose --print-certs "$source_apk" > "$signature_report"

"$aapt" dump badging "$source_apk" > "$manifest_report"
version_code="$(sed -nE 's/^[[:space:]]*versionCode[[:space:]]*=[[:space:]]*([0-9]+).*/\1/p' app/build.gradle.kts | head -n 1)"
expected_package="package: name='com.flowdictation.android.preview' versionCode='$version_code' versionName='$version'"
if ! grep -F "$expected_package" "$manifest_report" >/dev/null ||
    ! grep -qx 'application-debuggable' "$manifest_report" ||
    ! grep -F "uses-permission: name='android.permission.INTERNET'" "$manifest_report" >/dev/null; then
    echo "APK must be the expected debug Preview version with INTERNET permission for model downloads" >&2
    exit 1
fi

case "$delivery_abi" in
    arm64-v8a)
        grep -qx "native-code: 'arm64-v8a'" "$manifest_report" || {
            echo "Samsung APK must contain only arm64-v8a libraries" >&2; exit 1;
        } ;;
    universal)
        grep -qx "native-code: 'arm64-v8a' 'armeabi-v7a' 'x86_64'" "$manifest_report" || {
            echo "Universal APK must contain all three supported ABIs" >&2; exit 1;
        } ;;
esac

mkdir -p "$output_dir"
filename="Flow-Dictation-${version}${delivery_abi:+-$delivery_abi}.apk"
apk="$output_dir/$filename"
cp "$source_apk" "$apk"
(
    cd "$output_dir"
    sha256sum "$filename" > "$filename.sha256"
)
details="${apk%.apk}.build.txt"
{
    echo "Flow Preview $version (debug-signed)"
    echo "Package: com.flowdictation.android.preview"
    echo "Version code: $version_code"
    echo "Manifest checked: debug Preview; INTERNET permission for optional model downloads"
    echo "Source commit: ${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
    echo "Workflow run: ${GITHUB_RUN_ID:-local}"
    echo "APK bytes: $(wc -c < "$apk" | tr -d ' ')"
    echo "Speech recognition runs on-device; INTERNET enables optional catalog model downloads."
    echo "Update compatibility requires the same signing certificate as your installed Preview."
    echo
    cat "$signature_report"
    echo
    cat "$manifest_report"
} > "$details"
echo "Packaged $apk"
echo "Checksum: ${apk}.sha256"
