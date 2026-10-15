#!/usr/bin/env bash
# One-time download of STT/VAD models and short English bench fixtures.
# URLs from sherpa NeMo transducer / Moonshine / VAD docs (see plan Sources).
set -u

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
MODELS="${ROOT}/models"
FIXTURES="${ROOT}/bench/fixtures"
PY="${PYTHON:-${ROOT}/.venv/bin/python}"
ASR_BASE="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

usage() {
  cat <<'EOF'
Usage: scripts/fetch_models.sh [--help]

Download the speech models and short bench fixtures into this checkout.
Uses .venv/bin/python by default. Set PYTHON to use another interpreter.
That interpreter must be Python 3.10+ with numpy and soundfile installed.
EOF
}

die() {
  echo "fetch_models.sh: $*" >&2
  exit 1
}

if [ "$#" -gt 0 ]; then
  case "$1" in
    --help|-h)
      [ "$#" -eq 1 ] || { usage >&2; exit 2; }
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
fi

# Check the interpreter and conversion libraries before creating directories
# or downloading the model packs and fixtures.
command -v "$PY" >/dev/null 2>&1 || die "Python not found: ${PY}. Create .venv or set PYTHON to a Python executable."
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 \
  || die "Python 3.10 or newer is required: ${PY}"
if ! IMPORT_ERROR=$("$PY" -c 'import numpy, soundfile' 2>&1); then
  die "${PY} needs numpy and soundfile before downloads can start. Install them with: ${PY} -m pip install numpy soundfile${IMPORT_ERROR:+ (import error: ${IMPORT_ERROR})}"
fi

PARAKEET_TAR="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2"
PARAKEET_EXTRACTED="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
PARAKEET_DEST="parakeet-v2-int8"

MOONSHINE_TAR="sherpa-onnx-moonshine-base-en-int8.tar.bz2"
MOONSHINE_EXTRACTED="sherpa-onnx-moonshine-base-en-int8"
MOONSHINE_DEST="moonshine-base-en-int8"

SILERO_ONNX="silero_vad.onnx"

# Public English speech (LibriSpeech excerpts via Hugging Face asr_dummy).
# 1.flac / 2.flac are short (<=10s) English clips.
FIX1_URL="https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/1.flac"
FIX2_URL="https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/2.flac"

mkdir -p "${MODELS}" "${FIXTURES}"

download() {
  _url=$1
  _out=$2
  if [ -f "${_out}" ]; then
    echo "already have ${_out}"
    return 0
  fi
  echo "downloading ${_url}"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 -o "${_out}" "${_url}" || die "curl failed for ${_url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${_out}" "${_url}" || die "wget failed for ${_url}"
  else
    die "need curl or wget"
  fi
}

extract_rename() {
  _tar=$1
  _extracted=$2
  _dest=$3
  if [ -d "${MODELS}/${_dest}" ]; then
    echo "already extracted ${MODELS}/${_dest}"
    return 0
  fi
  _tmp="${MODELS}/.extract-$$"
  mkdir -p "${_tmp}"
  tar -xjf "${_tar}" -C "${_tmp}" || {
    rm -rf "${_tmp}"
    die "failed to extract ${_tar}"
  }
  if [ ! -d "${_tmp}/${_extracted}" ]; then
    echo "unexpected tarball layout in ${_tar}:" >&2
    ls -la "${_tmp}" >&2
    rm -rf "${_tmp}"
    die "expected directory ${_extracted}"
  fi
  mv "${_tmp}/${_extracted}" "${MODELS}/${_dest}"
  rm -rf "${_tmp}"
}

require() {
  _f=$1
  [ -f "${_f}" ] || die "missing ${_f} after extract"
}

download "${ASR_BASE}/${PARAKEET_TAR}" "${MODELS}/${PARAKEET_TAR}"
extract_rename "${MODELS}/${PARAKEET_TAR}" "${PARAKEET_EXTRACTED}" "${PARAKEET_DEST}"
require "${MODELS}/${PARAKEET_DEST}/encoder.int8.onnx"
require "${MODELS}/${PARAKEET_DEST}/decoder.int8.onnx"
require "${MODELS}/${PARAKEET_DEST}/joiner.int8.onnx"
require "${MODELS}/${PARAKEET_DEST}/tokens.txt"

download "${ASR_BASE}/${MOONSHINE_TAR}" "${MODELS}/${MOONSHINE_TAR}"
extract_rename "${MODELS}/${MOONSHINE_TAR}" "${MOONSHINE_EXTRACTED}" "${MOONSHINE_DEST}"
require "${MODELS}/${MOONSHINE_DEST}/preprocess.onnx"
require "${MODELS}/${MOONSHINE_DEST}/encode.int8.onnx"
require "${MODELS}/${MOONSHINE_DEST}/uncached_decode.int8.onnx"
require "${MODELS}/${MOONSHINE_DEST}/cached_decode.int8.onnx"
require "${MODELS}/${MOONSHINE_DEST}/tokens.txt"

download "${ASR_BASE}/${SILERO_ONNX}" "${MODELS}/${SILERO_ONNX}"
require "${MODELS}/${SILERO_ONNX}"

download "${FIX1_URL}" "${FIXTURES}/librispeech_1.flac"
download "${FIX2_URL}" "${FIXTURES}/librispeech_2.flac"

"${PY}" - "${FIXTURES}" <<'PY'
"""Convert downloaded clips to 16 kHz mono int16 WAV via soundfile."""
import os
import sys

import numpy as np
import soundfile as sf

fixtures = sys.argv[1]
src_names = ("librispeech_1.flac", "librispeech_2.flac")
dst_names = ("librispeech_1.wav", "librispeech_2.wav")
target_rate = 16000


def resample(y: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
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
    data = data[:, 0]
    data = resample(data, int(rate), target_rate)
    duration = data.size / target_rate
    if duration > 10.01:
        data = data[: int(target_rate * 10)]
        duration = data.size / target_rate
    pcm = np.clip(np.round(data * 32767.0), -32768, 32767).astype(np.int16)
    sf.write(dst, pcm, target_rate, subtype="PCM_16")
    print(f"wrote {dst} ({duration:.2f}s, 16k mono)")
PY

require "${FIXTURES}/librispeech_1.wav"
require "${FIXTURES}/librispeech_2.wav"

echo "fetch_models.sh: ok"
echo "  ${MODELS}/${PARAKEET_DEST}"
echo "  ${MODELS}/${MOONSHINE_DEST}"
echo "  ${MODELS}/${SILERO_ONNX}"
echo "  ${FIXTURES}/librispeech_1.wav"
echo "  ${FIXTURES}/librispeech_2.wav"
