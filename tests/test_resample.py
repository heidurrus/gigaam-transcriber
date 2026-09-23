import numpy as np
import pytest

from core.resample import StreamResampler


def tone(freq, rate, seconds=1.0, amp=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run_chunked(src_rate, signal, chunk):
    r = StreamResampler(src_rate, 16000)
    return np.concatenate([r.process(signal[i:i + chunk]) for i in range(0, len(signal), chunk)])


def dominant_freq(x, rate):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / rate)[np.argmax(spec)]


def level_db(x):
    return 20 * np.log10(np.sqrt(np.mean((x.astype(np.float64) / 32767) ** 2)) + 1e-12)


@pytest.mark.parametrize("src", [48000, 44100, 32000])
def test_output_length_and_speech_tone_preserved(src):
    out = run_chunked(src, tone(1000, src), chunk=1024)
    assert abs(len(out) - 16000) <= 2
    assert abs(dominant_freq(out[200:], 16000) - 1000) < 5
    assert abs(level_db(out[200:]) - level_db((tone(1000, 16000) * 32767).astype(np.int16))) < 0.5


@pytest.mark.parametrize("src", [48000, 44100])
def test_content_above_new_nyquist_is_filtered_not_aliased(src):
    out = run_chunked(src, tone(11000, src), chunk=1024)  # would alias to 5 kHz without filtering
    assert level_db(out[200:]) < level_db((tone(1000, 16000) * 32767).astype(np.int16)) - 40


@pytest.mark.parametrize("src", [48000, 44100])
def test_chunked_equals_one_shot(src):
    sig = tone(700, src, 0.5) + tone(2300, src, 0.5, 0.2)
    one = StreamResampler(src).process(sig)
    for chunk in (1024, 999, 4800, 37):
        chunked = run_chunked(src, sig, chunk)
        n = min(len(one), len(chunked))
        assert abs(len(one) - len(chunked)) <= 1
        assert np.max(np.abs(one[:n].astype(int) - chunked[:n].astype(int))) <= 2, f"chunk={chunk}"


def test_passthrough_at_16k():
    sig = tone(440, 16000, 0.1)
    out = StreamResampler(16000).process(sig)
    assert np.array_equal(out, (np.clip(sig, -1, 1) * 32767).astype(np.int16))


def test_clipping_is_safe():
    out = StreamResampler(48000).process(np.full(4800, 3.0, np.float32))
    assert out.max() <= 32767 and out.dtype == np.int16
