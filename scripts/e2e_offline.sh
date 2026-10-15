#!/bin/sh
# Offline E2E proof for flow-linux.
#
# Integrator contract for `flowd --smoke` (integrator owns flow/flowd.py):
#   python -m flow.flowd --smoke --fixture <wav> --expect <substring>
# exits 0 and prints SMOKE_PASS when the transcription contains <substring>.
# This runner never fetches models and, when `unshare -n` works, runs with
# an empty network namespace so a pass is proof the loop is offline.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
FIXTURE_DIR="$REPO_ROOT/bench/fixtures"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

wav=
for f in "$FIXTURE_DIR"/*.wav; do
    if [ -f "$f" ]; then
        wav=$f
        break
    fi
done
if [ -z "$wav" ]; then
    echo "e2e_offline.sh: no .wav fixtures under $FIXTURE_DIR" >&2
    exit 1
fi

base=$(basename "$wav" .wav)
expect=${EXPECT:-$(printf "%s" "$base" | tr '_' ' ')}
txt="${wav%.wav}.txt"
if [ -z "${EXPECT+x}" ] && [ -f "$txt" ]; then
    expect=$(head -n 1 "$txt")
fi

cd "$REPO_ROOT" || exit 1
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cmd="$PYTHON -m flow.flowd --smoke --fixture $wav --expect $expect"

unshare_ok=0
if command -v unshare >/dev/null 2>&1 && unshare -n true >/dev/null 2>&1; then
    unshare_ok=1
fi

rc=0
if [ "$unshare_ok" -eq 1 ]; then
    out=$(unshare -n "$PYTHON" -m flow.flowd --smoke --fixture "$wav" --expect "$expect" 2>&1) || rc=$?
else
    echo "e2e_offline.sh: warning: unshare -n not available; running without network isolation" >&2
    out=$("$PYTHON" -m flow.flowd --smoke --fixture "$wav" --expect "$expect" 2>&1) || rc=$?
fi

printf "%s\n" "$out"
case "$out" in
    *SMOKE_PASS*)
        if [ "$rc" -eq 0 ]; then
            echo "e2e_offline.sh: PASS ($wav)"
            exit 0
        fi
        ;;
esac
echo "e2e_offline.sh: FAIL rc=$rc (expected SMOKE_PASS from: $cmd)" >&2
exit 1
