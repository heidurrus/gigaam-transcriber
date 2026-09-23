"""Desktop call recorder: mic and system audio captured as separate channels.

Spec refs:
- NFR-REL-02: audio is streamed to disk while recording (constant memory, and a
  crash keeps everything captured so far). The WAV header is rewritten on every
  write, so the file on disk is always a valid, playable WAV.
- D-11 / FR-SRC-01 AC6: mic and system audio are kept as separate files (the mic
  is the BA); a mixed file is produced only for playback.
- Gap #23 / FR-SRC-01 AC3, AC5: per-channel errors are exposed while recording.

Audio sources are injected, so capture backends can differ per OS (WASAPI
loopback on Windows now; a native macOS backend comes with FR-PLAT-02) and
tests can use fakes.

A source is a callable ``source(stop_event)`` returning an iterable of 1-D
int16 numpy arrays; it must end the iteration once ``stop_event`` is set.
"""
import os
import threading
import time
import uuid
import wave

import numpy as np

SAMPLE_RATE = 16000
FLUSH_INTERVAL_SECONDS = 2.0
CHANNELS = ("mic", "sys")


class StreamingWavWriter:
    def __init__(self, path, samplerate=SAMPLE_RATE, clock=time.monotonic):
        self.path = path
        self._file = open(path, "wb")
        self._wav = wave.open(self._file, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(samplerate)
        self._clock = clock
        self._last_flush = clock()
        self.frames = 0

    def write(self, chunk):
        # wave rewrites the header length fields whenever the data length changes.
        self._wav.writeframes(chunk.astype("<i2", copy=False).tobytes())
        self.frames += len(chunk)
        if self._clock() - self._last_flush >= FLUSH_INTERVAL_SECONDS:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._last_flush = self._clock()

    def close(self):
        self._wav.close()
        self._file.close()


def mix_wavs(paths, out_path, block_frames=SAMPLE_RATE * 10):
    """Sum mono 16-bit WAVs into one (clipped), block by block to keep memory flat.

    Replaces the baseline's ffmpeg ``amix=normalize=0`` step, so recording no
    longer depends on ffmpeg. Shorter inputs are treated as silence at the end.
    """
    readers = [wave.open(p, "rb") for p in paths]
    try:
        rate = readers[0].getframerate()
        with wave.open(out_path, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            while True:
                blocks = [np.frombuffer(r.readframes(block_frames), dtype="<i2") for r in readers]
                longest = max(len(b) for b in blocks)
                if longest == 0:
                    break
                acc = np.zeros(longest, dtype=np.int32)
                for b in blocks:
                    acc[:len(b)] += b
                out.writeframes(np.clip(acc, -32768, 32767).astype("<i2").tobytes())
    finally:
        for r in readers:
            r.close()
    return out_path


class DualChannelRecorder:
    def __init__(self, out_root, sources, samplerate=SAMPLE_RATE, clock=time.monotonic):
        self._out_root = out_root
        self._sources = sources  # {"mic": source or None, "sys": source or None}
        self._samplerate = samplerate
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []
        self._channels = {}
        self._started_at = None
        self.recording_id = None
        self.folder = None

    @property
    def recording(self):
        with self._lock:
            return self._started_at is not None and not self._stop.is_set()

    def start(self):
        with self._lock:
            if self._started_at is not None and not self._stop.is_set():
                raise RuntimeError("A recording is already in progress")
            self.recording_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            self.folder = os.path.join(self._out_root, self.recording_id)
            os.makedirs(self.folder, exist_ok=True)
            self._stop = threading.Event()
            self._channels = {name: {"frames": 0, "error": None, "path": None} for name in CHANNELS}
            self._threads = []
            self._started_at = self._clock()
        for name in CHANNELS:
            source = self._sources.get(name)
            if source is None or isinstance(source, str):
                # A string explains why this channel can't be captured here.
                self._channels[name]["error"] = source or "not available on this system"
                continue
            t = threading.Thread(target=self._capture, args=(name, source), daemon=True)
            t.start()
            self._threads.append(t)
        return self.recording_id

    def _capture(self, name, source):
        path = os.path.join(self.folder, f"{name}.wav")
        writer = None
        try:
            for chunk in source(self._stop):
                if writer is None:
                    writer = StreamingWavWriter(path, self._samplerate)
                    self._channels[name]["path"] = path
                writer.write(chunk)
                self._channels[name]["frames"] = writer.frames
                if self._stop.is_set():
                    break
        except Exception as e:  # device unplugged, permission denied, driver error…
            self._channels[name]["error"] = str(e) or e.__class__.__name__
        finally:
            if writer is not None:
                writer.close()

    def status(self):
        with self._lock:
            started = self._started_at
            active = started is not None and not self._stop.is_set()
            channels = {n: {"frames": c["frames"], "seconds": round(c["frames"] / self._samplerate, 1),
                            "error": c["error"]} for n, c in self._channels.items()}
        return {
            "recording": active,
            "recording_id": self.recording_id,
            "elapsed": round(self._clock() - started, 1) if active else 0,
            "channels": channels,
        }

    def stop(self, join_timeout=5.0):
        """Stop capture; returns {"mic": path|None, "sys": path|None, "errors": {...}}."""
        with self._lock:
            if self._started_at is None or self._stop.is_set():
                raise RuntimeError("No recording in progress")
            self._stop.set()
        for t in self._threads:
            t.join(timeout=join_timeout)
        with self._lock:
            self._started_at = None
            paths = {n: c["path"] for n, c in self._channels.items()}
            errors = {n: c["error"] for n, c in self._channels.items() if c["error"]}
        return {**paths, "errors": errors, "folder": self.folder, "recording_id": self.recording_id}
