# GigaAM Transcriber

A local web interface for transcribing audio files using [GigaAM](https://github.com/salute-developers/GigaAM) — an open-source Russian speech recognition model family. Everything runs on your machine. No audio is sent anywhere.

---

## Features

- Drag-and-drop audio upload (WAV, MP3, FLAC, OGG, M4A, WebM, and more)
- All GigaAM model variants (v1/v2/v3 CTC and RNNT, multilingual)
- Short file transcription with optional word-level timestamps
- Automatic longform transcription for files over 25 seconds (VAD-based segmentation)
- Speaker diarization — who said what, with color-coded speaker badges
- CPU / GPU toggle (GPU requires CUDA PyTorch, see below)
- Built-in call recorder — captures system audio output + microphone, with playback, download, and direct transcription
- Background job processing with live progress bar — no browser timeouts on long files

---

## Requirements

- Python 3.10 or newer
- [ffmpeg](https://ffmpeg.org/download.html) installed and on your PATH
- A free [HuggingFace](https://huggingface.co) account (for diarization and longform, one-time setup)

---

## Setup

### 1. Clone and install GigaAM

```bash
git clone https://github.com/salute-developers/GigaAM.git
cd GigaAM
pip install -e ".[torch,longform]"
cd ..
```

### 2. Clone this repo

```bash
git clone <this-repo-url>
cd <repo-folder>
```

### 3. Install app dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up HuggingFace token (required for diarization and longform)

Diarization and longform transcription use gated pyannote models. This is a one-time setup — after the models download they are cached locally and the token is never used again.

1. Create a free account at [huggingface.co](https://huggingface.co)
2. Go to **Settings → Access Tokens** → create a token with **read** access
3. Accept terms for the following models (just click Agree on each page):
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
4. Create a `.env` file in the project folder:

```
HF_TOKEN=hf_your_token_here
```

> Short audio files (under ~25 seconds) transcribed without diarization work with no token and no setup.

### 5. GPU support (optional but recommended for large files)

By default PyTorch runs on CPU. To enable GPU (NVIDIA only):

```bash
# Check your CUDA version first
nvidia-smi

# Install PyTorch with CUDA support (replace cu126 with your version if needed)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

After this the GPU button in the UI will become active. GPU inference is significantly faster — a 30-minute file that takes ~30 minutes on CPU may take ~5 minutes on a modern GPU.

---

## Running

```bash
python app.py
```

Open **http://localhost:5000** in Chrome or Edge (Firefox works for transcription but not for the call recorder).

To stop: `Ctrl+C` in the terminal.

---

## Recording calls (Teams, Discord, etc.)

The **Record a call** card captures all system audio output (everything playing through Windows audio) mixed with your microphone.

1. Click **Start Recording**
2. A screen-share dialog appears — pick any screen or window and check **"Share system audio"**
3. Click **Stop** when done
4. Download the recording and/or click **Transcribe recording** to run it through the pipeline

Requires Chrome or Edge — Firefox does not support system audio capture.

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

Model weights download from HuggingFace on first use and are cached locally.

---

## Notes

- Files over ~25 seconds automatically fall back to longform mode (requires HF token).
- Speaker diarization identifies speakers as SPEAKER_00, SPEAKER_01, etc. — it does not know their names.
- The loaded model stays in memory between requests. Switching models triggers a new load.
- Tested on Windows 11, Python 3.12, PyTorch 2.14 (CUDA 12.6), pyannote.audio 4.0.4.
