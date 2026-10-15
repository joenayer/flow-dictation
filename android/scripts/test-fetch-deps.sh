#!/bin/sh
# Offline regression fixture for fetch-deps.sh variable scope and checksum names.
set -eu
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/project/scripts" "$tmp/project/app/libs" \
    "$tmp/project/app/src/main/assets/models" "$tmp/bin" "$tmp/fixture/model"
cp "$root/scripts/fetch-deps.sh" "$tmp/project/scripts/fetch-deps.sh"

TMP_TEST="$tmp" python3 - <<'PY'
import os, tarfile, zipfile
root = os.environ["TMP_TEST"]
open(root + "/fixture/silero_vad.onnx", "wb").write(b"vad")
with zipfile.ZipFile(root + "/fixture/sherpa-onnx-1.13.8.aar", "w") as z:
    z.writestr("AndroidManifest.xml", "<manifest/>")
for name in ("preprocess", "encode", "uncached_decode", "cached_decode"):
    open(root + "/fixture/model/" + name + ".onnx", "wb").write(b"model")
open(root + "/fixture/model/tokens.txt", "w").write("token\n")
with tarfile.open(root + "/fixture/sherpa-onnx-moonshine-tiny-en-int8.tar.bz2", "w:bz2") as t:
    t.add(root + "/fixture/model", arcname="model")
PY
cat > "$tmp/bin/curl" <<'CURL'
#!/bin/sh
set -eu
out=
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        *) url="$1"; shift ;;
    esac
done
case "$url" in
    *.aar) cp "$TMP_TEST/fixture/sherpa-onnx-1.13.8.aar" "$out" ;;
    *silero_vad.onnx) cp "$TMP_TEST/fixture/silero_vad.onnx" "$out" ;;
    *moonshine-tiny-en-int8.tar.bz2)
        cp "$TMP_TEST/fixture/sherpa-onnx-moonshine-tiny-en-int8.tar.bz2" "$out" ;;
    *) echo "unexpected fixture URL: $url" >&2; exit 2 ;;
esac
CURL
chmod +x "$tmp/bin/curl"
sha256sum "$tmp/fixture/sherpa-onnx-1.13.8.aar" | awk '{print $1 "  sherpa-onnx-1.13.8.aar"}' > "$tmp/project/scripts/checksums.sha256"
printf '%s  %s\n' "$(sha256sum "$tmp/fixture/sherpa-onnx-moonshine-tiny-en-int8.tar.bz2" | awk '{print $1}')" \
    sherpa-onnx-moonshine-tiny-en-int8.tar.bz2 >> "$tmp/project/scripts/checksums.sha256"
printf '%s  %s\n' "$(sha256sum "$tmp/fixture/silero_vad.onnx" | awk '{print $1}')" \
    silero_vad.onnx >> "$tmp/project/scripts/checksums.sha256"

# Valid pins pass, .part files are checked under their published names, and
# verify_model_dir cannot overwrite the caller's model/dest loop variables.
TMP_TEST="$tmp" PATH="$tmp/bin:$PATH" sh "$tmp/project/scripts/fetch-deps.sh" runtime-only
test -f "$tmp/project/app/libs/sherpa-onnx-1.13.8.aar"
test -f "$tmp/project/app/src/main/assets/silero_vad.onnx"
test ! -d "$tmp/project/app/src/main/assets/models/moonshine-tiny-en-int8"
TMP_TEST="$tmp" PATH="$tmp/bin:$PATH" sh "$tmp/project/scripts/fetch-deps.sh"
test -f "$tmp/project/app/libs/sherpa-onnx-1.13.8.aar"
test -f "$tmp/project/app/src/main/assets/models/moonshine-tiny-en-int8/tokens.txt"
test ! -d "$tmp/project/app/src/main/assets/models/model"

# A wrong AAR pin must fail before publishing the downloaded partial archive.
printf '%064d  sherpa-onnx-1.13.8.aar\n' 0 > "$tmp/project/scripts/checksums.sha256"
rm -f "$tmp/project/app/libs/sherpa-onnx-1.13.8.aar"
if TMP_TEST="$tmp" PATH="$tmp/bin:$PATH" sh "$tmp/project/scripts/fetch-deps.sh" >"$tmp/fail.log" 2>&1; then
    echo "fetch-deps unexpectedly accepted an incorrect AAR pin" >&2
    exit 1
fi
test ! -f "$tmp/project/app/libs/sherpa-onnx-1.13.8.aar"
echo "fetch-deps regression fixture passed"
