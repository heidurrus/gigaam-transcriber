# Requirements Workbench

**A local-first assistant for business analysts: from recorded client calls to a
traceable requirements document and a Jira backlog.**

Record or import your elicitation material: calls, audio, transcripts, emails,
earlier specs. The workbench turns it into managed requirements:

```
record / import → transcribe → extract requirement "atoms" → review → FRD document → stories & AC → Jira
```

Every requirement keeps a link back to the exact quote, timestamp and speaker it
came from, from the FRD statement to the Jira issue. The AI proposes and you
decide. Nothing goes to Jira until you press Push.

Audio stays on your machine. Speech recognition runs locally with
[GigaAM](https://github.com/salute-developers/GigaAM); the text stages can use
Claude or a local model via Ollama, and a project can be set to *local only*.

> **Status: early development.** The app currently does **stage 1** of the
> pipeline, recording and transcribing calls, and it grew out of the
> *GigaAM Transcriber* app this repository started as. The rest is specified
> and being built increment by increment; see [Roadmap](#roadmap).

---

## Roadmap

Full requirements: [`docs/specs/requirements-workbench-spec.md`](docs/specs/requirements-workbench-spec.md)
(decisions in §13, delivery plan in §12). Clickable prototype of the target UI:
[`docs/prototype/ba-helper-prototype.html`](docs/prototype/ba-helper-prototype.html).

| # | Increment | What you get | Status |
|---|---|---|---|
| 0 | **Stable base** | Installers with no prerequisites and automatic setup, native app on Windows and macOS, call recording with separate mic/system channels (incl. macOS system audio), local-only server | ✅ **v2.0** |
| 1 | Source library | Projects, everything saved locally, sources list, transcript viewer with playback, Russian + English UI | 🟡 **2.2.0**: projects, library, new UI; emails and earlier specs next |
| 2 | Atoms | AI extraction of requirement atoms with source quotes, review (accept / edit / reject, keyboard), duplicates, conflicts between sources, open questions | planned |
| 3 | FRD | Document built from accepted atoms, versions and diff, stale-section detection, quality check, DOCX export (neutral or GOST template) | planned |
| 4 | Backlog & Jira | Epics / stories / acceptance criteria, INVEST check, dry-run preview and push to Jira Cloud through the Atlassian MCP | planned |

See [`CHANGELOG.md`](CHANGELOG.md) for what changed in each release.

---

## What works today (stage 1)

- **Call recording** from Teams, Zoom, Discord, etc. Your microphone and the other side of
  the call are recorded as **separate channels** and streamed to disk, so a crash
  doesn't lose the call.
  - Windows: system audio via WASAPI loopback
  - macOS 14.2+: system audio via Core Audio taps, right in the app. No screen sharing or
    virtual audio driver needed
- **Transcription** of recordings or uploaded files (WAV, MP3, FLAC, OGG, M4A, WebM, video…)
  with every GigaAM model, including long files and word timestamps
- **Import existing transcripts**: Teams (`.vtt`, `.docx`), Zoom / Meet (`.vtt`), `.srt`,
  PDF (with a text layer), plain text with `Name: text` lines. They open instantly, with speakers and timestamps kept
- **Speaker separation** (who said what) with pyannote
- **AI summaries** of any transcript: key points, requirements, decisions, open questions,
  action items, each citing speaker and timestamp. Uses **Claude** (add your Anthropic API key
  in Settings; only text is sent) or a **local model via Ollama** (nothing leaves your computer)
- Runs on **CPU or GPU**: NVIDIA CUDA on Windows, Apple GPU on Apple Silicon
- One transcription at a time, with a queue and live progress
- The local server only accepts connections from your own computer

---

## Install

Nothing needs to be installed first: Python is bundled, and the app installs
everything else itself on first launch (Setup screen with progress).

### Windows 10/11 (x64)

1. Download **RequirementsWorkbench-<version>-Setup.exe** from
   [Releases](https://github.com/heidurrus/gigaam-transcriber/releases)
   (or from the latest *build installers* run under Actions → Artifacts)
2. Run it: no admin rights needed. It installs the Microsoft WebView2 runtime if your PC
   lacks it, and upgrades an existing *GigaAM Transcriber 1.0* in place
3. The app opens and finishes setup: PyTorch (the CUDA build if you have an NVIDIA GPU),
   GigaAM, ffmpeg and the speech model. This takes a few minutes, on the first run only

### macOS 13+ (Apple Silicon)

1. Download **RequirementsWorkbench-<version>-macos-arm64.dmg** and drag the app to Applications
2. First open: builds are not notarized yet, so **right-click the app → Open → Open**
   (only needed once)
3. The app opens and finishes setup (same as on Windows, using the Apple GPU)
4. On the first recording, allow the **microphone** and **system audio recording** prompts

Downloaded components, models and recordings live in your user folder
(`%LOCALAPPDATA%\RequirementsWorkbench` / `~/Library/Application Support/RequirementsWorkbench`),
never inside the app, so updating or reinstalling keeps them.

### Hugging Face token (speaker separation and long files)

This is the one step that can't be automated, because it needs your consent to the
model licences. Setup lists it as optional:

1. Create a free account at [huggingface.co](https://huggingface.co) and a **Read** access token
2. Accept the terms of [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0),
   [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and
   [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
3. Paste the token in **Settings** (⚙) in the app. It's stored privately in your user folder

### AI summaries

Open **Settings (⚙) → AI summaries** and choose one:

- **Claude**: paste an API key from [console.anthropic.com](https://console.anthropic.com/settings/keys).
  Default model: Claude Opus 5 (best quality); Sonnet 5 and Haiku 4.5 are faster and cheaper.
- **Local model**: install [Ollama](https://ollama.com/download), run `ollama pull qwen3:8b` once,
  and choose it in Settings. Private, but slower and less accurate

---

## Recording a call

1. Click **Start Recording** in the desktop app and hold your call
2. Click **Stop**, then **Transcribe recording**

If a channel can't be captured (no permission, device unplugged), the app tells you
which one and still saves the other.

**Browser mode** (optional, *Browser Mode* shortcut or `--browser`): works in Chrome or Edge.
When the share dialog appears, pick any screen and tick **"Share system audio"**. On macOS 13,
this is the way to include call audio.

---

## Models

| Model | Notes |
|---|---|
| `v3_e2e_rnnt` | Best quality, includes punctuation **(recommended, installed by setup)** |
| `v3_e2e_ctc` | Fast, includes punctuation |
| `v3_rnnt` / `v3_ctc` | High quality, no punctuation |
| `v2_rnnt` / `v2_ctc` | Previous generation |
| `v1_rnnt` / `v1_ctc` | Original release |
| `multilingual_ctc` | 70+ languages, 220M params |
| `multilingual_large_ctc` | 70+ languages, 600M params |

Other models download on first use and are cached with the app's data.

---

## Development

```bash
git clone https://github.com/heidurrus/gigaam-transcriber.git
cd gigaam-transcriber
python3 -m pip install -r requirements.txt   # small base layer (Python 3.10+)
python3 launcher.py                          # desktop window; --browser for the browser
```

On first launch the Setup screen installs the heavy components:

| Step | What | Size |
|---|---|---|
| PyTorch | CUDA build on NVIDIA GPUs (Windows/Linux), Apple GPU on Apple Silicon, CPU otherwise | ~300 MB – 2.5 GB |
| GigaAM | Speech recognition, pinned version, no git needed | ~50 MB |
| ffmpeg | Your system ffmpeg if present, otherwise a bundled static build | ~30 MB |
| Speech model | `v3_e2e_rnnt`, downloaded once | ~500 MB |

Failed steps retry automatically. After fixing your connection, press **Retry**; finished
steps are not repeated. Every start re-checks this list in about 0.01 s and repairs anything missing.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest                  # runs without a GPU or model weights
```

**Building the installers**

```bash
python3 packaging/build.py --target macos-arm64   # on a Mac   → dist/*.dmg
python  packaging/build.py --target windows-x64   # on Windows → dist/*-Setup.exe (needs Inno Setup 6)
```

CI runs the tests on Windows, macOS and Linux, and builds both installers on every push to
`master`. Pushing a tag `vX.Y.Z` publishes them as a GitHub release.

**Layout:** `launcher.py` (entry point, setup → app handoff) · `boot.py` (bundled-Python
first stage) · `app.py` (Flask app + API) · `core/` (store, recorder, jobs, setup, security,
platform audio, summaries) · `frontend/` (Svelte UI, built into `static/app` and committed) ·
`static/` (setup screen, classic page) · `packaging/`, `installer/` (builds) · `docs/` (spec, brief, prototype).

**UI development:**

```bash
cd frontend && npm install
npm run dev             # hot reload against a running app (WORKBENCH_PORT, default 47823)
npm run build           # writes static/app; commit the result
node e2e/smoke.mjs URL  # end-to-end smoke test with your installed Chrome
```

---

## Troubleshooting

**"ffmpeg is missing"**: restart the app; the startup check reinstalls it.

**"HF_TOKEN is not set"**: add your token in Settings (see *Hugging Face token* above).

**GPU not used**: update your NVIDIA driver and restart the app; setup detects the GPU and
installs the CUDA build of PyTorch.

**Speaker separation is slow**: that's expected on CPU. A supported GPU is used automatically and is much faster.

**macOS: recording has no call audio**: check System Settings → Privacy & Security →
*Screen & System Audio Recording* and allow Requirements Workbench (macOS 14.2+). In browser
mode, use Chrome and tick "Share system audio" in the share dialog.

**First transcription takes a while to start**: the model is loaded into memory once per
session ("Loading model…"). The download itself already happened during setup.

---

## Credits

Speech recognition by [GigaAM](https://github.com/salute-developers/GigaAM) (Salute Developers),
speaker separation by [pyannote.audio](https://github.com/pyannote/pyannote-audio).
This project started as *GigaAM Transcriber* and keeps its full history.
