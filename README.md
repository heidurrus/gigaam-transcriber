# GigaAM Transcriber

A local web app for transcribing audio using [GigaAM](https://github.com/salute-developers/GigaAM) — an open-source speech recognition model supporting Russian, English, and 70+ other languages. Supports speaker diarization, longform audio, word-level timestamps, and in-browser call recording. Runs entirely on your machine; no data leaves your PC. CPU and GPU inference supported.

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

## Setup

### 1. Install Python

Python 3.10 or newer. Download from [python.org](https://www.python.org/downloads/).

Verify:
```bash
python --version
```

---

### 2. Install ffmpeg

ffmpeg is required for recording transcription (WebM → WAV conversion). The easiest way on Windows:

**Option A — winget (built into Windows 10/11):**
```bash
winget install ffmpeg
```

**Option B — chocolatey:**
```bash
choco install ffmpeg
```

**Option C — manual:** Download the "full build" from [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/), extract it, and add the `bin` folder to your system PATH.

Verify:
```bash
ffmpeg -version
```

---

### 3. Clone and install GigaAM

```bash
git clone https://github.com/salute-developers/GigaAM.git
cd GigaAM
pip install -e ".[torch,longform]"
cd ..
```

---

### 4. Clone this repo and install dependencies

```bash
git clone <this-repo-url>
cd <repo-folder>
pip install -r requirements.txt
```

---

### 5. Set up HuggingFace token

Required for **speaker diarization** and **longform transcription** (files over ~25 seconds). Basic short-file transcription works without this step.

1. Create a free account at [huggingface.co](https://huggingface.co)
2. Go to **Settings → Access Tokens** → **New token** → choose **Read** access → copy it
3. Accept terms for each of these models (just open the link, log in, click Agree):
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
4. Create a file called `.env` in the project folder with this content:

```
HF_TOKEN=hf_your_token_here
```

Model weights download automatically on first use and are cached locally. After that the token is never contacted again.

---

### 6. GPU support (optional)

Skip this if you don't have an NVIDIA GPU. The app works fine on CPU.

```bash
# Check your driver and CUDA version
nvidia-smi

# Install PyTorch with CUDA (replace cu126 with your version if needed)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

After this the GPU button in the UI will activate. GPU is significantly faster for long files and diarization.

---

## Running

```bash
python app.py
```

The terminal will print a status summary:

```
  GigaAM Transcriber
  ────────────────────────────────────────
  ffmpeg   : found
  GPU      : NVIDIA GeForce RTX 4070 Ti
  HF token : set
  ────────────────────────────────────────
  Open http://localhost:5000 in Chrome or Edge
```

Open **http://localhost:5000** in your browser. Use Chrome or Edge — Firefox works for transcription but not for the call recorder.

To stop: `Ctrl+C` in the terminal.

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

**"ffmpeg is not installed or not on PATH"** — follow step 2 above. Restart your terminal after installing.

**"HF_TOKEN is not set"** — create the `.env` file as described in step 5.

**"GPU requested but CUDA is not available"** — follow step 6. Make sure you install the CUDA version of PyTorch, not the default CPU version.

**Diarization is slow** — expected on CPU. Enable GPU (step 6) for a significant speedup.

**App appears frozen on first transcription** — it's downloading model weights (~500MB for v3_e2e_rnnt). This only happens once. The progress bar will show "Loading model…" while it loads.
