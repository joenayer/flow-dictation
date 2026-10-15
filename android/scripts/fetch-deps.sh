#!/bin/sh
# fetch-deps.sh — one-time download of the sherpa-onnx AAR and STT model(s).
#
# The sherpa-onnx AAR is NOT on Maven Central, and the models are far too big
# to commit, so both are fetched on the build machine (needs curl + tar):
#
#   cd android
#   ./scripts/fetch-deps.sh            # AAR + default model (Moonshine Tiny)
#   ./scripts/fetch-deps.sh runtime-only # AAR + small VAD; models download in-app
#   ./scripts/fetch-deps.sh all        # AAR + legacy models (not Parakeet)
#   ./scripts/fetch-deps.sh whisper-tiny.en whisper-base.en
#
# Layout after fetching:
#   app/libs/sherpa-onnx-<version>.aar        (picked up by app/build.gradle.kts)
#   app/src/main/assets/models/<model-id>/…   (loaded via AssetManager)
#
# Set SHERPA_VERSION to pin a different sherpa-onnx release (default below).
#
# Reliability: downloads go to a temp dir, archives are integrity-checked
# before extraction, required files are verified, and only then are artifacts
# atomically published. Existing artifacts are re-validated (not trusted),
# so interrupted runs never poison retries. All downloads are HTTPS; for
# tamper-evidence beyond TLS, drop sha256 pins in checksums.sha256 next to
# this script (format: "<sha256>  <filename>") — they are enforced when
# present (see README).
set -eu

cd "$(dirname "$0")/.."

SHERPA_VERSION="${SHERPA_VERSION:-1.13.8}"
AAR_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/v${SHERPA_VERSION}/sherpa-onnx-${SHERPA_VERSION}.aar"
ASR_MODELS="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
DEFAULT_MODEL="moonshine-tiny-en-int8"
PINS_FILE="scripts/checksums.sha256"

# model-id -> tarball name. Keep in sync with ModelCatalog.kt.
tarball_for() {
    case "$1" in
        moonshine-tiny-en-int8) echo "sherpa-onnx-moonshine-tiny-en-int8.tar.bz2" ;;
        whisper-tiny.en)        echo "sherpa-onnx-whisper-tiny.en.tar.bz2" ;;
        whisper-base.en)        echo "sherpa-onnx-whisper-base.en.tar.bz2" ;;
        *) echo "Unknown model id: $1" >&2; return 1 ;;
    esac
}

kind_for() {
    case "$1" in
        moonshine-*) echo "moonshine" ;;
        whisper-*)   echo "whisper" ;;
    esac
}

# verify_pins <file>: enforce scripts/checksums.sha256 when it pins <file>.
verify_pins() (
    f="$1"
    base="$(basename "$f")"
    # Downloads use a .part suffix until validated; pins name published files.
    base="${base%.part}"
    if [ ! -f "$PINS_FILE" ]; then
        return 0
    fi
    want="$(grep -E " +$base\$" "$PINS_FILE" | awk '{print $1}' | head -n 1 || true)"
    if [ -z "$want" ]; then
        return 0
    fi
    if ! command -v sha256sum >/dev/null; then
        echo "ERROR: $PINS_FILE pins $base but sha256sum is missing" >&2
        exit 1
    fi
    got="$(sha256sum "$f" | awk '{print $1}')"
    if [ "$got" != "$want" ]; then
        echo "ERROR: sha256 mismatch for $base" >&2
        echo "  want: $want" >&2
        echo "  got:  $got" >&2
        exit 1
    fi
    echo "    sha256 OK: $base"
)

# verify_aar <file>: the AAR must be a readable zip. Returns nonzero (never
# exits) so callers can re-fetch; fatal call sites add their own exit.
verify_aar() {
    if command -v unzip >/dev/null; then
        unzip -tqq "$1" || { echo "corrupt AAR: $1" >&2; return 1; }
    elif command -v python3 >/dev/null; then
        python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).testzip()" "$1" \
            || { echo "corrupt AAR: $1" >&2; return 1; }
    else
        echo "WARNING: cannot integrity-check $1 (need unzip or python3)" >&2
    fi
}

# verify_model_dir <model-id> <dir>: required Transcriber.kt inputs present.
verify_model_dir() (
    model="$1"
    dest="$2"
    if [ -z "$(ls -A "$dest" 2>/dev/null)" ]; then
        return 1
    fi
    if [ "$(kind_for "$model")" = "moonshine" ]; then
        for f in preprocess encode uncached_decode cached_decode; do
            ls "$dest" | grep -qi "$f.*\.onnx" || return 1
        done
    else
        ls "$dest" | grep -qi "encoder.*\.onnx" || return 1
        ls "$dest" | grep -qi "decoder.*\.onnx" || return 1
    fi
    ls "$dest" | grep -qi "tokens.txt" || return 1
    return 0
)

if [ "${1:-}" = "runtime-only" ]; then
    MODELS=""
elif [ "${1:-}" = "all" ]; then
    MODELS="moonshine-tiny-en-int8 whisper-tiny.en whisper-base.en"
elif [ "$#" -gt 0 ]; then
    MODELS="$*"
else
    MODELS="$DEFAULT_MODEL"
fi

command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v tar >/dev/null || { echo "tar is required" >&2; exit 1; }

mkdir -p app/libs "app/src/main/assets/models"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "==> sherpa-onnx AAR v${SHERPA_VERSION}"
AAR_DEST="app/libs/sherpa-onnx-${SHERPA_VERSION}.aar"
if [ -f "$AAR_DEST" ] && verify_aar "$AAR_DEST" 2>/dev/null; then
    verify_pins "$AAR_DEST"
    echo "    already present and valid: $AAR_DEST"
else
    rm -f "$AAR_DEST"
    part="$TMP_DIR/sherpa-onnx-${SHERPA_VERSION}.aar.part"
    curl -fSL --retry 3 -o "$part" "$AAR_URL"
    verify_pins "$part"
    verify_aar "$part" || exit 1
    mv "$part" "$AAR_DEST"
fi
ls -lh "$AAR_DEST"

# Small pause detector only. Parakeet itself is downloaded in-app and never bundled.
VAD_DEST="app/src/main/assets/silero_vad.onnx"
if [ ! -f "$VAD_DEST" ]; then
    curl -fSL --retry 3 -o "$TMP_DIR/silero_vad.onnx" "$ASR_MODELS/silero_vad.onnx"
    verify_pins "$TMP_DIR/silero_vad.onnx"
    mv "$TMP_DIR/silero_vad.onnx" "$VAD_DEST"
else
    verify_pins "$VAD_DEST"
fi

for model in $MODELS; do
    tarball="$(tarball_for "$model")" || exit 1
    dest="app/src/main/assets/models/$model"
    echo "==> model $model"
    if verify_model_dir "$model" "$dest" 2>/dev/null; then
        echo "    already extracted and valid: $dest"
        continue
    fi
    echo "    downloading $tarball ..."
    archive="$TMP_DIR/$tarball"
    curl -fSL --retry 3 -o "$archive" "$ASR_MODELS/$tarball"
    verify_pins "$archive"
    tar -tjf "$archive" >/dev/null || {
        echo "ERROR: corrupt tarball $tarball" >&2; exit 1
    }
    stage="$TMP_DIR/stage-$model"
    rm -rf "$stage"
    mkdir -p "$stage"
    tar -xjf "$archive" -C "$stage" --strip-components=1 --no-same-owner
    rm -f "$archive"
    # Slim the APK: drop test wavs and (for whisper) the fp32 duplicates —
    # the app prefers the .int8.onnx files (see Transcriber.kt).
    rm -rf "$stage/test_wavs"
    if [ "$(kind_for "$model")" = "whisper" ]; then
        # Delete ONLY the fp32 files (*-encoder.onnx); the int8 files
        # (*-encoder.int8.onnx) do not match these globs and are kept.
        rm -f "$stage/"*-encoder.onnx "$stage/"*-decoder.onnx
    fi
    verify_model_dir "$model" "$stage" || {
        echo "ERROR: $tarball is missing files Transcriber.kt needs" >&2
        exit 1
    }
    # Atomic publish: a failed run never leaves a half-written model dir.
    rm -rf "$dest"
    mv "$stage" "$dest"
    echo "    --- $dest ---"
    ls -lh "$dest"
    echo "    OK: $model"
done

echo
echo "Done. Next:"
echo "  ./gradlew assembleDebug"
echo "  adb install -r app/build/outputs/apk/debug/app-debug.apk"
