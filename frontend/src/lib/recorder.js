// Call recording in two modes (ported from the classic page):
// - desktop app: the Python side captures mic + system audio as separate channels;
// - browser: getDisplayMedia (system audio) + getUserMedia (mic) → MediaRecorder.

import { api } from "./api.js";

export class DesktopRecorder {
  constructor() { this.statusTimer = null; }

  async start(micDevice, onStatus) {
    await api("/desktop-record/start", { method: "POST", body: { mic_device: micDevice } });
    this.statusTimer = setInterval(async () => {
      try { onStatus(await api("/desktop-record/status")); } catch (_) { /* transient */ }
    }, 1500);
  }

  // Resolves { sourceId, errors }. The recording is saved as a source on the server.
  async stop(title) {
    clearInterval(this.statusTimer);
    const res = await fetch("/desktop-record/stop", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new Error(body.error || "Recording failed");
      err.errors = body.errors || {};
      throw err;
    }
    return {
      sourceId: res.headers.get("X-Source-Id"),
      errors: JSON.parse(res.headers.get("X-Recording-Errors") || "{}"),
    };
  }
}

export class BrowserRecorder {
  async start(micDeviceId, onWarning) {
    this.display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: micDeviceId ? { ideal: micDeviceId } : undefined,
                 echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (_) {
      this.mic = null;
      onWarning("mic");
    }
    this.display.getVideoTracks().forEach(t => t.stop());
    this.ctx = new AudioContext();
    const dest = this.ctx.createMediaStreamDestination();
    this.sysTracks = this.display.getAudioTracks();
    if (this.sysTracks.length) this.ctx.createMediaStreamSource(new MediaStream(this.sysTracks)).connect(dest);
    else onWarning("sys");
    if (this.mic) {
      const gain = this.ctx.createGain();
      gain.gain.value = 1.5;
      this.ctx.createMediaStreamSource(this.mic).connect(gain);
      gain.connect(dest);
    }
    this.chunks = [];
    this.rec = new MediaRecorder(dest.stream);
    this.rec.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start(1000);
  }

  // Resolves a webm Blob; the caller uploads it as a recording.
  stop() {
    return new Promise(resolve => {
      this.rec.onstop = () => {
        if (this.mic) this.mic.getTracks().forEach(t => t.stop());
        this.sysTracks.forEach(t => t.stop());
        this.ctx.close();
        resolve(new Blob(this.chunks, { type: "audio/webm" }));
      };
      this.rec.stop();
    });
  }
}

export async function listMicrophones(desktop) {
  if (desktop) {
    const devices = await api("/audio-devices").catch(() => []);
    if (!Array.isArray(devices)) return [];
    return devices.filter(d => d.index !== "loopback").map(d => ({ id: String(d.index), name: d.name }));
  }
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter(d => d.kind === "audioinput" && d.deviceId && d.deviceId !== "default")
    .map((d, i) => ({ id: d.deviceId, name: d.label || `Microphone ${i + 1}` }));
}
