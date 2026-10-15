"""Audio capture backends: sounddevice (preferred) and pw-record fallback."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable

import numpy as np

from flow.audio_base import AudioCapture

SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 1600  # 100 ms at 16 kHz
_CHUNK_BYTES = _CHUNK_SAMPLES * 2  # int16


def _import_sounddevice():
    """Lazy-import sounddevice. Raises RuntimeError if PortAudio is missing."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice could not be imported. Use the project venv, or "
            "fall back to PwRecordCapture (pw-record)."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "PortAudio library not found; sounddevice cannot open the "
            "microphone. Install libportaudio2, or use PwRecordCapture "
            "(pw-record --channels 1 --rate 16000)."
        ) from exc
    return sd


class SounddeviceCapture(AudioCapture):
    """16 kHz mono int16 capture via PortAudio (sounddevice)."""

    sample_rate = SAMPLE_RATE

    def __init__(self) -> None:
        self._stream = None
        self._on_chunk: Callable[[np.ndarray], None] | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        chunk = np.array(indata, dtype=np.int16, copy=True).reshape(-1)
        with self._lock:
            self._chunks.append(chunk)
        cb = self._on_chunk
        if cb is not None:
            try:
                cb(chunk)
            except Exception:
                pass

    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        if self._stream is not None:
            self.stop()
        sd = _import_sounddevice()
        self._on_chunk = on_chunk
        with self._lock:
            self._chunks = []
        # PortAudioError inherits Exception (not RuntimeError), but the
        # service only handles RuntimeError: translate here, and always
        # close a partially opened stream on the failure path.
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=_CHUNK_SAMPLES,
                callback=self._callback,
            )
        except Exception as exc:
            raise RuntimeError(f"could not open microphone: {exc}") from exc
        self._stream = stream
        try:
            stream.start()
        except Exception as exc:
            self._stream = None
            try:
                stream.close()
            except Exception:
                pass
            raise RuntimeError(f"could not start recording: {exc}") from exc

    def stop(self) -> np.ndarray:
        stream = self._stream
        self._stream = None
        self._on_chunk = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._chunks)

    def list_inputs(self) -> list[str]:
        sd = _import_sounddevice()
        devices = sd.query_devices()
        names: list[str] = []
        for dev in devices:
            try:
                if int(dev.get("max_input_channels") or 0) > 0:
                    names.append(str(dev.get("name", "unknown")))
            except (TypeError, ValueError, AttributeError):
                continue
        return names


class PwRecordCapture(AudioCapture):
    """16 kHz mono int16 capture via `pw-record` raw stdout (PipeWire)."""

    sample_rate = SAMPLE_RATE

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._on_chunk: Callable[[np.ndarray], None] | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        if self._proc is not None:
            self.stop()
        if shutil.which("pw-record") is None:
            raise RuntimeError(
                "pw-record not found on PATH (PipeWire). Install pipewire-bin "
                "or use SounddeviceCapture."
            )
        self._on_chunk = on_chunk
        self._stop.clear()
        with self._lock:
            self._chunks = []
        # Flags from `pw-record --help`: --channels, --rate, --format, file `-`.
        cmd = [
            "pw-record",
            "--media-category",
            "Capture",
            "--channels",
            "1",
            "--rate",
            str(self.sample_rate),
            "--format",
            "s16",
            "-",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("pw-record not found on PATH.") from exc
        except OSError as exc:
            self._proc = None
            raise RuntimeError(f"could not start pw-record: {exc}") from exc
        if self._proc.stdout is None:
            raise RuntimeError("pw-record produced no stdout pipe.")
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        leftover = b""
        while not self._stop.is_set():
            data = proc.stdout.read(_CHUNK_BYTES)
            if not data:
                break
            buf = leftover + data
            n = len(buf) - (len(buf) % 2)
            leftover = buf[n:]
            if n == 0:
                continue
            chunk = np.frombuffer(buf[:n], dtype=np.int16).copy()
            with self._lock:
                self._chunks.append(chunk)
            cb = self._on_chunk
            if cb is not None:
                try:
                    cb(chunk)
                except Exception:
                    pass

    def stop(self) -> np.ndarray:
        self._stop.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2)
        self._on_chunk = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._chunks)

    def list_inputs(self) -> list[str]:
        return ["default"]


def default_capture() -> AudioCapture:
    """Prefer sounddevice/PortAudio; fall back to pw-record."""
    try:
        _import_sounddevice()
    except RuntimeError:
        return PwRecordCapture()
    return SounddeviceCapture()
