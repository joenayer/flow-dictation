"""Release-to-typed latency harness (unit 2 fills the STT stage).

The product budget is median release-to-typed <= 800 ms for fixtures <= 10 s.
This harness gates on median transcribe_ms <= 700 ms and reserves 100 ms for
typing (owned by the typer backend). --gate exits nonzero when the transcribe
median exceeds 700 ms.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flow.stt_base import ENGINES, STTEngine  # noqa: E402

import flow.stt_moonshine  # noqa: E402,F401
import flow.stt_parakeet  # noqa: E402,F401

SAMPLE_RATE = 16000
TYPE_RESERVE_MS = 100.0
TRANSCRIBE_GATE_MS = 700.0
RELEASE_TO_TYPED_BUDGET_MS = TYPE_RESERVE_MS + TRANSCRIBE_GATE_MS  # 800


def _resample_int16(samples: np.ndarray, src_rate: int, dst_rate: int = SAMPLE_RATE) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.int16, copy=False)
    n_dst = int(round(samples.size * dst_rate / src_rate))
    if n_dst <= 0:
        return np.zeros(0, dtype=np.int16)
    x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    y = np.interp(x_new, x_old, samples.astype(np.float64))
    return np.clip(np.round(y), -32768, 32767).astype(np.int16)


def load_fixture_wav(path: str) -> np.ndarray:
    """Load a WAV as int16 mono 16 kHz (stdlib wave)."""
    with wave.open(path, "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    if sw == 1:
        samples = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)
        samples = (samples - 128) << 8
    elif sw == 2:
        samples = np.frombuffer(raw, dtype="<i2").copy()
    elif sw == 4:
        samples = np.frombuffer(raw, dtype="<i4")
        samples = (samples // 65536).astype(np.int16)
    else:
        raise ValueError(f"{path}: unsupported sample width {sw}")
    if nch > 1:
        samples = samples.reshape(-1, nch)[:, 0].copy()
    if rate != SAMPLE_RATE:
        samples = _resample_int16(samples, rate, SAMPLE_RATE)
    return np.asarray(samples, dtype=np.int16)


def fixture_paths(fixtures_dir: str | os.PathLike[str] | None = None) -> list[Path]:
    d = Path(fixtures_dir) if fixtures_dir is not None else Path(__file__).resolve().parent / "fixtures"
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".wav")


def measure_release_to_typed(
    engine_name: str,
    samples: np.ndarray,
    *,
    engine: STTEngine | None = None,
    models_dir: str = "models",
    threads: int = 8,
) -> dict:
    """Time a warm transcribe; return stage timings in milliseconds.

    Typing is not performed here (unit 4). ``type_reserve_ms`` is the 100 ms
    reserved for typing inside the 800 ms release-to-typed budget, so the
    transcribe gate is 700 ms.
    """
    if engine is None:
        if engine_name not in ENGINES:
            raise KeyError(
                f"unknown engine {engine_name!r}; registered={sorted(ENGINES)}"
            )
        engine = ENGINES[engine_name]()
        t_load = time.perf_counter()
        engine.load(models_dir, threads=threads)
        load_ms = (time.perf_counter() - t_load) * 1000.0
    else:
        load_ms = 0.0
    t0 = time.perf_counter()
    result = engine.transcribe(samples)
    transcribe_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "engine": engine_name,
        "text": result.text,
        "duration_s": result.duration_s,
        "load_ms": load_ms,
        "transcribe_ms": transcribe_ms,
        "type_reserve_ms": TYPE_RESERVE_MS,
        "total_ms": transcribe_ms + TYPE_RESERVE_MS,
    }


def _print_row(row: dict, fixture: str = "") -> None:
    label = fixture or row.get("engine", "")
    print(
        f"{label:40s}  transcribe={row['transcribe_ms']:8.1f} ms  "
        f"type_reserve={row['type_reserve_ms']:.0f} ms  "
        f"total={row['total_ms']:8.1f} ms  "
        f"dur={row['duration_s']:.2f}s  text={row.get('text', '')!r}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark STT transcribe latency. --gate exits nonzero if the "
            "median transcribe_ms exceeds 700 ms (100 ms is reserved for "
            "typing in the 800 ms release-to-typed budget)."
        )
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help=(
            "Exit 1 if median transcribe_ms > 700 "
            "(100 ms reserved for typing; 800 ms release-to-typed budget)."
        ),
    )
    parser.add_argument("--list", action="store_true", help="List fixture WAV paths and exit.")
    parser.add_argument("--engine", default="parakeet", help="ENGINES key (parakeet|moonshine).")
    parser.add_argument("--fixtures", default=None, help="Directory of 16 kHz mono WAV fixtures.")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args(argv)

    paths = fixture_paths(args.fixtures)
    if args.list:
        if not paths:
            print("(no fixture WAVs)")
            return 0
        for p in paths:
            print(p)
        return 0

    if not paths:
        print("no fixture WAVs found; run scripts/fetch_models.sh", file=sys.stderr)
        return 2

    if args.engine not in ENGINES:
        print(
            f"unknown engine {args.engine!r}; registered={sorted(ENGINES)}",
            file=sys.stderr,
        )
        return 2

    inst = ENGINES[args.engine]()
    inst.load(args.models_dir, threads=args.threads)

    rows: list[dict] = []
    for path in paths:
        samples = load_fixture_wav(str(path))
        row = measure_release_to_typed(
            args.engine,
            samples,
            engine=inst,
            models_dir=args.models_dir,
            threads=args.threads,
        )
        row["fixture"] = str(path)
        rows.append(row)
        _print_row(row, fixture=path.name)

    times = [r["transcribe_ms"] for r in rows]
    median = statistics.median(times)
    print(
        f"median transcribe_ms={median:.1f}  "
        f"gate={TRANSCRIBE_GATE_MS:.0f} ms  "
        f"(type reserve {TYPE_RESERVE_MS:.0f} ms; "
        f"release-to-typed budget {RELEASE_TO_TYPED_BUDGET_MS:.0f} ms)"
    )
    if args.gate and median > TRANSCRIBE_GATE_MS:
        print(
            f"GATE FAIL: median transcribe_ms {median:.1f} > {TRANSCRIBE_GATE_MS:.0f}",
            file=sys.stderr,
        )
        return 1
    if args.gate:
        print("GATE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
