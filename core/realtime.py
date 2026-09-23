"""Make audio sources safe to record from: never block, keep channels in sync.

Capture APIs block while no audio arrives: the macOS system-audio tap (and
WASAPI loopback) deliver nothing while nothing is playing, and a microphone
without permission delivers nothing at all. A blocked read meant Stop hung,
the system channel came out shorter than the mic channel (so mixing and
timestamps drifted), and a denied microphone looked like "no audio captured"
with no reason given.

``realtime(inner, rate, …)`` runs the inner source in its own thread and hands
chunks over through a queue:
- the recorder always regains control within ``poll`` seconds, so Stop works;
- ``fill_silence``: gaps longer than the normal delivery latency are filled
  with silence by wall-clock time, so the channel keeps pace with the mic;
- ``no_audio_error``: if the first audio hasn't arrived after
  ``first_audio_timeout`` seconds, the channel fails with that message.
"""
import queue
import threading
import time

import numpy as np

_END = object()


def realtime(inner, rate, fill_silence=False, no_audio_error=None, first_audio_timeout=4.0,
             poll=0.2, latency=0.3, clock=time.monotonic):
    def source(stop):
        q = queue.Queue(maxsize=256)
        inner_stop = threading.Event()

        def pump():
            try:
                for chunk in inner(inner_stop):
                    q.put(chunk)
                    if inner_stop.is_set():
                        break
            except Exception as e:   # handed to the consumer, which raises it
                q.put(e)
            finally:
                q.put(_END)

        threading.Thread(target=pump, daemon=True).start()
        started = clock()
        emitted = 0          # samples handed to the recorder (real + filled)
        real = 0             # samples that came from the device
        try:
            while not stop.is_set():
                try:
                    item = q.get(timeout=poll)
                except queue.Empty:
                    elapsed = clock() - started
                    if real == 0 and no_audio_error and elapsed > first_audio_timeout:
                        raise OSError(no_audio_error)
                    if fill_silence:
                        deficit = int((elapsed - latency) * rate) - emitted
                        if deficit > 0:
                            emitted += deficit
                            yield np.zeros(deficit, dtype=np.int16)
                    continue
                if item is _END:
                    return
                if isinstance(item, Exception):
                    raise item
                real += len(item)
                emitted += len(item)
                yield item
        finally:
            inner_stop.set()   # a blocked device read may linger; it's a daemon thread

    return source
