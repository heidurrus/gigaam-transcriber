# Changelog

## 1.2.0 (2026-09-23)

- **Import a transcript you already have.** Drop it where you drop audio: no speech
  recognition, it opens instantly with speakers and timestamps kept. Supported:
  - Microsoft Teams: `.vtt` or `.docx` transcript export (speaker names kept)
  - Zoom / Google Meet: `.vtt`
  - Subtitles: `.srt`
  - Plain text: `Name: text` lines, timestamped lines, or text copied from this app
  - This app's own `.json` result
  - Russian text in any common encoding (UTF-8, UTF-16, Windows-1251)
- Transcript tables show times as `mm:ss`, and file content is always shown as text,
  never interpreted as HTML (important for files from outside).
- Results appear without the 1.5 s polling delay.

## 1.1.1 (2026-09-23)

- **Fixed: "Access to 127.0.0.1 was denied / HTTP ERROR 403" on startup.** The app used
  port 5000, which the macOS AirPlay Receiver (and sometimes other software) already
  uses. The app mistook it for an already-running copy of itself and showed that
  server's error page. It now uses its own port (47823), falls back to any free port
  when that's taken, and recognises a running copy only when it identifies itself.
- **Fixed: in browser mode the app quit right after first-run setup** instead of
  opening the app.
- Closing or killing the app always cleans up its instance record.

## 1.1.0 — Increment 0: stable base (2026-09-23)

First step from GigaAM Transcriber towards Requirements Workbench
(`docs/specs/requirements-workbench-spec.md`, §12.2 increment 0). No new
end-user features yet: this makes the existing transcriber safe, installable
without prerequisites, and a native app on both Windows and macOS.

### Renamed: GigaAM Transcriber → Requirements Workbench
The app, installers and macOS bundle now carry the product's name. The Windows
installer upgrades an existing GigaAM Transcriber 1.0 in place and removes its
old shortcuts. GigaAM remains the speech-recognition engine.

### Install & platform
- **No prerequisites.** Installers bundle Python 3.12; the app's **Setup screen**
  installs PyTorch (CUDA / Apple GPU / CPU, picked for the machine), GigaAM (pinned),
  ffmpeg and the speech model on first launch, with progress, automatic retries and
  resume. Every later start re-checks in ~0.01 s and repairs anything missing.
- **macOS app** (`.dmg`, Apple Silicon, macOS 13+) with a native launcher, so the
  Dock and permission prompts show the app's name.
- **Windows installer**: per-user, no admin rights, installs WebView2 if missing,
  asks before deleting your data on uninstall.
- Desktop window by default on both OSes; `--browser` / "Browser Mode" shortcut optional.
  Falls back to the browser if the window can't open.
- Downloaded components, models and recordings live in
  `%LOCALAPPDATA%\RequirementsWorkbench` / `~/Library/Application Support/RequirementsWorkbench`.

### Recording
- **macOS desktop app records call audio** (macOS 14.2+, Core Audio process taps):
  no browser, screen sharing or virtual audio driver needed.
- Mic and system audio are recorded as **separate channels**, streamed to disk while
  recording (constant memory; a crash no longer loses the call).
- Problems with a channel (device missing, permission denied) are shown live and after
  recording instead of being silently dropped.

### Reliability & security
- The local server accepts only local connections in every mode (browser mode used to
  be reachable from the whole LAN, including the settings endpoint).
- Transcriptions are queued and run one at a time, showing the queue position.
- Fixed: temp upload leaked after ffmpeg conversion; desktop recordings downloaded
  as `.webm` although they were WAV; recording start ignored server errors.

### Test checklist for this increment
Windows 10/11 PC (ideally with an NVIDIA GPU) and a Mac (Apple Silicon, macOS 14.2+):
1. Install from the installer / `.dmg` on a machine **without Python** → app opens.
   *Mac: first open via right-click → Open (not notarized yet).*
2. Setup screen runs by itself and opens the app (few minutes, first run only).
   On NVIDIA check the console summary / GPU button shows the GPU.
3. Settings → paste a Hugging Face token (see README) → speaker separation works.
4. Upload an audio file → transcript (with and without speaker separation, a file > 1 min).
5. Record a short Teams/Zoom/YouTube call in the **desktop window**: both your voice and
   the other side are in the recording. Allow the microphone / system audio prompts.
6. Unplug the mic mid-recording (or deny a permission) → the app says which channel failed
   and still saves the other one.
7. Close and reopen the app → starts straight into the app (no setup), in a few seconds.
8. From another device on your network, open `http://<your-PC-IP>:47823` → must not connect.
