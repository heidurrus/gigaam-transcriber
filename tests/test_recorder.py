import os
import threading
import time
import wave

import numpy as np
import pytest

from core.recorder import DualChannelRecorder, StreamingWavWriter, mix_wavs

CHUNK = 1024


def tone_source(value, chunks=None, started=None):
    """Fake capture backend yielding constant-valued int16 chunks until stopped."""
    def source(stop):
        n = 0
        if started:
            started.set()
        while not stop.is_set() and (chunks is None or n < chunks):
            yield np.full(CHUNK, value, dtype=np.int16)
            n += 1
            time.sleep(0.002)
        while not stop.is_set():  # finite source: idle until stopped, like a quiet device
            time.sleep(0.002)
    return source


def failing_source(message, after_chunks=0):
    def source(stop):
        for _ in range(after_chunks):
            yield np.zeros(CHUNK, dtype=np.int16)
        raise OSError(message)
    return source


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def wait_for(cond, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_streaming_writer_file_is_valid_while_still_open(tmp_path):
    path = tmp_path / "x.wav"
    w = StreamingWavWriter(str(path))
    w.write(np.arange(1000, dtype=np.int16))
    w._file.flush()
    # Simulates a crash: read the file without closing the writer.
    assert len(read_wav(str(path))) == 1000
    w.write(np.arange(500, dtype=np.int16))
    w.close()
    assert len(read_wav(str(path))) == 1500


def test_channels_are_recorded_to_separate_files(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(100, 5), "sys": tone_source(-200, 3)})
    rec.start()
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] == 5 * CHUNK
                    and rec.status()["channels"]["sys"]["frames"] == 3 * CHUNK)
    result = rec.stop()

    assert result["errors"] == {}
    mic, sysa = read_wav(result["mic"]), read_wav(result["sys"])
    assert len(mic) == 5 * CHUNK and set(mic) == {100}
    assert len(sysa) == 3 * CHUNK and set(sysa) == {-200}
    assert os.path.dirname(result["mic"]) == result["folder"]


def test_audio_is_on_disk_during_recording_not_in_memory(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(1), "sys": None})
    rec.start()
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] >= 20 * CHUNK)
    on_disk = os.path.getsize(os.path.join(rec.folder, "mic.wav"))
    assert on_disk >= 10 * CHUNK * 2  # already written, not buffered until stop
    rec.stop()


def test_failing_channel_reports_error_and_other_channel_survives(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {
        "mic": tone_source(7, 4),
        "sys": failing_source("loopback device disappeared", after_chunks=2),
    })
    rec.start()
    assert wait_for(lambda: rec.status()["channels"]["sys"]["error"] is not None
                    and rec.status()["channels"]["mic"]["frames"] == 4 * CHUNK)
    status = rec.status()
    assert status["recording"] is True
    assert status["channels"]["sys"]["error"] == "loopback device disappeared"
    result = rec.stop()
    assert len(read_wav(result["sys"])) == 2 * CHUNK  # audio captured before the failure is kept
    assert len(read_wav(result["mic"])) == 4 * CHUNK
    assert result["errors"] == {"sys": "loopback device disappeared"}


def test_unavailable_channel_explains_why(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(1, 1), "sys": "not supported on macOS yet"})
    rec.start()
    assert rec.status()["channels"]["sys"]["error"] == "not supported on macOS yet"
    result = rec.stop()
    assert result["sys"] is None and result["errors"]["sys"] == "not supported on macOS yet"


def test_cannot_start_twice_or_stop_when_idle(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(1), "sys": None})
    with pytest.raises(RuntimeError):
        rec.stop()
    rec.start()
    with pytest.raises(RuntimeError):
        rec.start()
    rec.stop()
    rec.start()  # reusable after stop
    rec.stop()


def test_mix_sums_and_clips_and_pads_shorter_input(tmp_path):
    a, b = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    for path, data in ((a, np.array([100, 30000, -30000, 5], np.int16)), (b, np.array([1, 30000, -30000], np.int16))):
        w = StreamingWavWriter(path)
        w.write(data)
        w.close()
    out = mix_wavs([a, b], str(tmp_path / "m.wav"), block_frames=2)
    assert list(read_wav(out)) == [101, 32767, -32768, 5]


def test_stop_joins_capture_threads(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(1), "sys": tone_source(2)})
    before = threading.active_count()
    rec.start()
    rec.stop()
    assert wait_for(lambda: threading.active_count() <= before)
