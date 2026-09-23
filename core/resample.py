"""Streaming resampler to the 16 kHz mono the recorder stores (numpy only).

Integer ratios (48 kHz → 16 kHz, 32 kHz → 16 kHz) use a windowed-sinc low-pass
plus decimation, carrying filter state across chunks so there are no clicks at
chunk boundaries. Other rates (44.1 kHz) fall back to filtered linear
interpolation, which is plenty for speech recognition.
"""
import numpy as np

TAPS = 97


def _lowpass(cutoff_ratio, taps=TAPS):
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff_ratio * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float32)


class StreamResampler:
    def __init__(self, src_rate, dst_rate=16000):
        self.src_rate, self.dst_rate = int(src_rate), int(dst_rate)
        self.passthrough = self.src_rate == self.dst_rate
        ratio = self.src_rate / self.dst_rate
        self.factor = int(round(ratio)) if abs(ratio - round(ratio)) < 1e-9 else None
        # Cut a little below the new Nyquist frequency to leave room for the filter slope.
        self._h = _lowpass(0.45 * self.dst_rate / self.src_rate)
        self._history = np.zeros(TAPS - 1, dtype=np.float32)
        self._phase = 0          # integer path: offset of the next kept sample
        self._t = 0.0            # fractional path: position of the next output sample
        self._prev_tail = None

    def process(self, mono_float):
        """Takes float32 samples in [-1, 1] at src_rate, returns int16 at dst_rate."""
        x = np.asarray(mono_float, dtype=np.float32)
        if self.passthrough:
            return _to_int16(x)
        buf = np.concatenate([self._history, x])
        filtered = np.convolve(buf, self._h, mode="valid")  # len == len(x)
        self._history = buf[-(TAPS - 1):]
        if self.factor:
            out = filtered[self._phase::self.factor]
            self._phase = (self._phase - len(filtered)) % self.factor
            return _to_int16(out)
        return _to_int16(self._interp(filtered))

    def _interp(self, filtered):
        step = self.src_rate / self.dst_rate
        seq = filtered if self._prev_tail is None else np.concatenate([[self._prev_tail], filtered])
        offset = 0 if self._prev_tail is None else 1
        positions = np.arange(self._t, len(filtered) - 1 + 1e-9, step)
        out = np.interp(positions + offset, np.arange(len(seq)), seq)
        self._t = (positions[-1] + step - len(filtered)) if len(positions) else self._t - len(filtered)
        self._prev_tail = filtered[-1] if len(filtered) else self._prev_tail
        return out


def _to_int16(x):
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
