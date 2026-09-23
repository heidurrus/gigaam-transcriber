import threading
import time

import numpy as np
import pytest

from core.macos_permissions import AUTHORIZED, DENIED, NOT_DETERMINED, microphone_access
from core.realtime import realtime
from core.recorder import DualChannelRecorder, StreamingWavWriter, wav_peak
from tests.test_recorder import read_wav, wait_for

RATE = 16000


def blocking_forever(stop):
    """Like a device read that never returns (silent tap, denied microphone)."""
    threading.Event().wait()
    yield  # pragma: no cover


def bursts(chunks, gap_after=None, gap=0.0, value=7):
    def inner(stop):
        for i in range(chunks):
            yield np.full(1600, value, np.int16)          # 0.1 s at 16 kHz
            time.sleep(gap if i == gap_after else 0.1)
    return inner


def collect(source, seconds):
    stop, out = threading.Event(), []
    t = threading.Thread(target=lambda: out.extend(source(stop)), daemon=True)
    t.start()
    time.sleep(seconds)
    stop.set()
    t.join(1.0)
    return out, t


def test_stop_returns_even_when_the_device_read_blocks():
    out, t = collect(realtime(blocking_forever, RATE, poll=0.05), 0.2)
    assert not t.is_alive(), "Stop must not hang on a blocked device read"


def test_silence_is_filled_to_keep_pace_with_wall_clock():
    out, _ = collect(realtime(blocking_forever, RATE, fill_silence=True, poll=0.05, latency=0.1), 0.6)
    total = sum(len(c) for c in out)
    assert 0.4 * RATE <= total <= 0.6 * RATE           # ~elapsed minus latency
    assert all(not c.any() for c in out)


def test_real_audio_passes_through_and_gaps_are_filled():
    out, _ = collect(realtime(bursts(3, gap_after=0, gap=0.8), RATE, fill_silence=True, poll=0.05, latency=0.1), 1.3)
    audio = np.concatenate(out)
    assert (audio == 7).sum() == 3 * 1600               # every real sample kept, in order
    assert (audio == 0).sum() > 0.4 * RATE              # the 0.8 s gap became silence
    # The source ends ~1.0 s in; up to then the channel tracks wall clock (minus latency).
    assert 0.8 * RATE <= len(audio) <= 1.1 * RATE


def test_silent_microphone_fails_with_the_reason():
    src = realtime(blocking_forever, RATE, no_audio_error="microphone delivers no audio",
                   first_audio_timeout=0.2, poll=0.05)
    with pytest.raises(OSError, match="delivers no audio"):
        for _ in src(threading.Event()):
            pass


def test_inner_errors_propagate():
    def broken(stop):
        raise RuntimeError("device unplugged")
        yield  # pragma: no cover
    with pytest.raises(RuntimeError, match="unplugged"):
        list(realtime(broken, RATE, poll=0.05)(threading.Event()))


def test_recorder_with_blocking_channel_still_saves_the_other(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": realtime(bursts(3), RATE, poll=0.05),
                                             "sys": realtime(blocking_forever, RATE, fill_silence=True,
                                                             poll=0.05, latency=0.05)})
    rec.start()
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] == 3 * 1600)
    t0 = time.monotonic()
    result = rec.stop()
    assert time.monotonic() - t0 < 1.0, "stop must be quick"
    assert len(read_wav(result["mic"])) == 3 * 1600
    assert wav_peak(result["sys"]) == 0


def test_wav_peak(tmp_path):
    p = str(tmp_path / "a.wav")
    w = StreamingWavWriter(p)
    w.write(np.array([0, -300, 25, 12], np.int16))
    w.close()
    assert wav_peak(p) == 300


class FakeAV:
    AVMediaTypeAudio = "soun"

    def __init__(self, status, grant=None):
        test = self

        class Device:
            @staticmethod
            def authorizationStatusForMediaType_(kind):
                return status

            @staticmethod
            def requestAccessForMediaType_completionHandler_(kind, done):
                test.asked = True
                threading.Timer(0.05, done, args=(grant,)).start()
        self.AVCaptureDevice = Device
        self.asked = False


@pytest.mark.parametrize("status,grant,allowed", [
    (AUTHORIZED, None, True), (DENIED, None, False), (NOT_DETERMINED, True, True), (NOT_DETERMINED, False, False)])
def test_microphone_access(monkeypatch, status, grant, allowed):
    monkeypatch.setattr("sys.platform", "darwin")
    av = FakeAV(status, grant)
    ok, reason = microphone_access(timeout=2, av=av)
    assert ok is allowed
    assert av.asked is (status == NOT_DETERMINED)
    if not ok:
        assert "System Settings" in reason
