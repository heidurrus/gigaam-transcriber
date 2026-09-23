# GigaAM Transcriber

A local web app for transcribing audio using [GigaAM](https://github.com/salute-developers/GigaAM) — an open-source speech recognition model supporting Russian, English, and 70+ other languages. Supports speaker diarization, longform audio, word-level timestamps, and in-browser call recording. Runs entirely on your machine; no data leaves your PC. CPU and GPU inference supported (CUDA on Windows/Linux, MPS on Apple Silicon Mac).

---

## Features

- Drag-and-drop audio upload (WAV, MP3, FLAC, OGG, M4A, WebM, and more)
- All GigaAM model variants (v1/v2/v3 CTC and RNNT, multilingual)
- Short file transcription with optional word-level timestamps
- Automatic longform transcription for files over ~25 seconds
- Speaker diarization — who said what, with color-coded speaker labels
- CPU / GPU toggle (GPU requires CUDA PyTorch, see below)
- Built-in call recorder — captures all system audio + microphone, with playback, download, and direct transcription
- Live progress bar — no browser timeouts on long files

---

## Install

Nothing needs to be installed first: Python is bundled, and the app installs
everything else itself on first launch (Setup screen with progress).

### Windows 10/11 (x64)

1. Download **GigaAM-Transcriber-<version>-Setup.exe** from
   [Releases](https://github.com/heidurrus/gigaam-transcriber/releases)
   (or from the latest *build installers* run under Actions → Artifacts)
2. Run it: no admin rights needed. It installs the Microsoft WebView2 runtime if your PC lacks it
3. The app opens and finishes setup (PyTorch — the CUDA build if you have an NVIDIA GPU —,
   GigaAM, ffmpeg and the speech model, a few minutes on the first run only)

### macOS 13+ (Apple Silicon)

1. Download **GigaAM-Transcriber-<version>-macos-arm64.dmg** and drag the app to Applications
2. First open: builds are not notarized yet, so **right-click the app → Open → Open**
   (only needed once)
3. The app opens and finishes setup (same as on Windows, using the Apple GPU)

Downloaded components and models live in your user folder
(`%LOCALAPPDATA%\RequirementsWorkbench` / `~/Library/Application Support/RequirementsWorkbench`),
never inside the app, so updating or reinstalling keeps them.

### Building the installers yourself

```bash
python3 packaging/build.py --target macos-arm64   # on a Mac   → dist/*.dmg
python  packaging/build.py --target windows-x64   # on Windows → dist/*-Setup.exe (needs Inno Setup 6)
```

CI builds both on every push to `master` (*build installers* workflow); pushing a tag
`vX.Y.Z` publishes them as a GitHub release.

---

## Running from source (development)

You only need **Python 3.10+**. Everything else — PyTorch (the right build for
your GPU), GigaAM, ffmpeg and the speech model — is installed automatically by
the app's **Setup screen** on first launch.

```bash
git clone https://github.com/heidurrus/gigaam-transcriber.git
cd gigaam-transcriber
python3 -m pip install -r requirements.txt   # small base layer
python3 launcher.py                          # opens the app window
```

On first launch the window shows the Setup screen and installs, with progress:

| Step | What | Size |
|---|---|---|
| PyTorch | CUDA build on NVIDIA GPUs (Windows/Linux), MPS on Apple Silicon, CPU otherwise | ~300 MB – 2.5 GB |
| GigaAM | Speech recognition, pinned version, no git needed | ~50 MB |
| ffmpeg | Your system ffmpeg if present, otherwise a bundled static build | ~30 MB |
| Speech model | `v3_e2e_rnnt`, downloaded once and cached | ~500 MB |

Failed steps retry automatically; press **Retry** after fixing your connection —
finished steps are not repeated. On every start the app re-checks this list in
about a second and repairs anything missing (e.g. after an update or a GPU change).

### Hugging Face token (speaker separation and long files)

This is the one step that can't be automated, because it needs your consent to the
model licences. Setup lists it as optional:

1. Create a free account at [huggingface.co](https://huggingface.co) and a **Read** access token
2. Accept the terms of [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0),
   [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and
   [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
3. Paste the token in **Settings** (⚙) in the app — it's saved to `.env`

---

## Running

```bash
python3 launcher.py            # desktop window (default)
python3 launcher.py --browser  # optional: open in Chrome/Edge instead
```

The server listens on `127.0.0.1:5000` only and never accepts connections from
other machines. Starting the app a second time just shows the running one.

**macOS note:** on first launch macOS asks for microphone permission. In the desktop
window, system-audio capture on macOS isn't supported yet (it's planned). Use
browser mode in Chrome to record call audio; Chrome needs Screen Recording permission
(System Settings → Privacy & Security → Screen Recording).

### Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest          # runs without a GPU or model weights
```

---

## Recording calls (Teams, Discord, etc.)

The **Record a call** card captures all system audio output mixed with your microphone.

1. Click **Start Recording**
2. A screen-share dialog appears — pick any screen or window and check **"Share system audio"**
3. Record your call
4. Click **Stop**, then **Transcribe recording** to run it through the pipeline

Requires Chrome or Edge.

---

## Models

| Model | Notes |
|---|---|
| `v3_e2e_rnnt` | Best quality, includes punctuation **(recommended)** |
| `v3_e2e_ctc` | Fast, includes punctuation |
| `v3_rnnt` / `v3_ctc` | High quality, no punctuation |
| `v2_rnnt` / `v2_ctc` | Previous generation |
| `v1_rnnt` / `v1_ctc` | Original release |
| `multilingual_ctc` | 70+ languages, 220M params |
| `multilingual_large_ctc` | 70+ languages, 600M params |

Model weights download from HuggingFace on first use and are cached locally. Subsequent runs load from cache instantly.

---

## Troubleshooting

**"ffmpeg is missing"** — restart the app; the startup check reinstalls it.

**"HF_TOKEN is not set"** — add your token in Settings (see *Hugging Face token* above).

**"GPU requested but CUDA is not available"** — update your NVIDIA driver and restart the app; setup detects the GPU and installs the CUDA build of PyTorch.

**Diarization is slow** — expected on CPU. A supported GPU is used automatically and is much faster.

**macOS: call recorder doesn't capture system audio** — Safari and Firefox don't support `getDisplayMedia` with system audio. Use Chrome. When the screen-share dialog appears, check "Share system audio" (or "Share tab audio" if recording a specific tab).

**macOS: "command not found: python"** — use `python3` instead, or create an alias: `alias python=python3`.

**First transcription takes a while to start** — the model is loaded into memory once per session ("Loading model…"); the download itself already happened during setup.
