import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
import warnings

# Suppress pyannote's torchcodec warning — we pass waveform dicts so it's never used
warnings.filterwarnings("ignore", message=".*torchcodec.*")

import torch
import gigaam
from gigaam.preprocess import load_audio, SAMPLE_RATE
from gigaam.utils import AudioDataset
from torch.utils.data import DataLoader
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory

from core.jobs import JobStore, SerialQueue
from core.paths import recordings_dir
from core.recorder import SAMPLE_RATE as REC_SAMPLE_RATE, DualChannelRecorder, mix_wavs
from core.security import BIND_HOST, install_local_only_guard

load_dotenv()

hf_token = os.getenv("HF_TOKEN")
if hf_token:
    os.environ["HF_TOKEN"] = hf_token

PORT = 5000
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

app = Flask(__name__, static_folder="static")
install_local_only_guard(app)

CUDA_AVAILABLE = torch.cuda.is_available()
GPU_NAME = torch.cuda.get_device_name(0) if CUDA_AVAILABLE else None
MPS_AVAILABLE = torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False

# Check ffmpeg availability once at startup
try:
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    FFMPEG_AVAILABLE = True
except (FileNotFoundError, subprocess.CalledProcessError):
    FFMPEG_AVAILABLE = False

_models = {}
_model_lock = threading.Lock()

_diarization_pipeline = None
_diarization_lock = threading.Lock()

jobs = JobStore()
transcription_queue = SerialQueue()  # one transcription at a time (spec D-12)

_recorder = None
_recorder_lock = threading.Lock()
IS_DESKTOP = False

AVAILABLE_MODELS = [
    "v3_e2e_rnnt",
    "v3_e2e_ctc",
    "v3_rnnt",
    "v3_ctc",
    "v2_rnnt",
    "v2_ctc",
    "v1_rnnt",
    "v1_ctc",
    "multilingual_ctc",
    "multilingual_large_ctc",
]

# Formats that need ffmpeg conversion to WAV before GigaAM can read them
NEEDS_CONVERSION = {".webm", ".ogg", ".opus", ".mp4", ".m4a", ".weba"}


def convert_to_wav(input_path):
    if not FFMPEG_AVAILABLE:
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH. "
            "Install it from https://ffmpeg.org/download.html and add it to your PATH."
        )
    wav_path = input_path + ".wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True,
        capture_output=True,
    )
    return wav_path


def get_model(name, device):
    with _model_lock:
        if name not in _models:
            _models[name] = gigaam.load_model(name)
        return _models[name].to(device)


def get_diarization_pipeline(device):
    global _diarization_pipeline
    with _diarization_lock:
        if _diarization_pipeline is None:
            if not hf_token:
                raise RuntimeError(
                    "HF_TOKEN is not set. Create a .env file with HF_TOKEN=your_token. "
                    "See README for instructions."
                )
            from pyannote.audio import Pipeline
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=hf_token,
            )
        return _diarization_pipeline.to(torch.device(device))


def set_progress(job_id, pct, msg):
    jobs.set_progress(job_id, pct, msg)


def transcribe_with_diarization(job_id, model, audio_path, device):
    set_progress(job_id, 15, "Loading diarization pipeline…")
    pipeline = get_diarization_pipeline(device)

    set_progress(job_id, 25, "Loading audio…")
    audio = load_audio(audio_path)  # (time,) at 16kHz

    # Pass as waveform dict — pyannote uses it directly, bypassing file I/O and
    # the torchcodec dependency which is broken on Windows without full-shared FFmpeg DLLs.
    waveform_dict = {
        "waveform": audio.unsqueeze(0).float().cpu(),  # (1, time)
        "sample_rate": SAMPLE_RATE,
    }

    set_progress(job_id, 30, "Running speaker diarization…")
    diarization_output = pipeline(waveform_dict)
    # pyannote 4.x returns DiarizeOutput; exclusive variant has no overlapping turns
    annotation = diarization_output.exclusive_speaker_diarization

    chunks, boundaries, speakers = [], [], []
    for segment, _, speaker in annotation.itertracks(yield_label=True):
        start_sample = int(segment.start * SAMPLE_RATE)
        end_sample = int(segment.end * SAMPLE_RATE)
        chunk = audio[start_sample:end_sample]
        if chunk.shape[0] < 400:  # skip chunks shorter than ~25ms
            continue
        chunks.append(chunk)
        boundaries.append((segment.start, segment.end))
        speakers.append(speaker)

    if not chunks:
        return [], None

    total = len(chunks)
    set_progress(job_id, 55, f"Transcribing {total} segments…")

    ds = AudioDataset(chunks, tokenizer=None)
    dl = DataLoader(ds, batch_size=16, shuffle=False, collate_fn=AudioDataset.collate)

    result_segments = []
    idx = 0
    for wav_pad, wav_lens in dl:
        wav_pad = wav_pad.to(model._device).to(model._dtype)
        wav_lens = wav_lens.to(model._device)
        encoded, encoded_len = model.forward(wav_pad, wav_lens)
        for text, _ in model._decode(encoded, encoded_len, wav_lens, False):
            start, end = boundaries[idx]
            result_segments.append({
                "speaker": speakers[idx],
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            })
            idx += 1
        pct = 55 + int((idx / total) * 40)
        set_progress(job_id, pct, f"Transcribing segments… {idx}/{total}")

    return result_segments, None


def do_longform(model, audio_path):
    if not hf_token:
        return None, (
            "Audio is too long for short-form transcription (max ~25s). "
            "Add HF_TOKEN to .env to enable longform mode. See README."
        )
    segments = model.transcribe_longform(audio_path)
    result_segments = [
        {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text}
        for seg in segments
    ]
    full_text = "\n".join(
        f"[{gigaam.format_time(seg['start'])} - {gigaam.format_time(seg['end'])}] {seg['text']}"
        for seg in result_segments
    )
    return {"text": full_text, "segments": result_segments}, None


def run_job(job_id, upload_path, audio_path, model_name, diarize, word_timestamps, device):
    """Queue and run one transcription, then delete its temp files.

    upload_path is the file as uploaded; audio_path is what GigaAM reads (the
    same file, or its ffmpeg-converted WAV). Both are removed afterwards.
    """
    def on_wait(ahead):
        set_progress(job_id, 0, f"Queued — waiting for {ahead} job(s) to finish…")

    result, error = None, None
    try:
        result = transcription_queue.run(
            job_id,
            lambda: _transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device),
            on_wait=on_wait,
        )
    except Exception as e:
        error = e
    finally:
        for path in {upload_path, audio_path}:
            try:
                os.unlink(path)
            except OSError:
                pass
    # Report completion only after cleanup, so "done" means nothing is left behind.
    if error is not None:
        jobs.fail(job_id, error)
    else:
        jobs.finish(job_id, result)


def _transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device):
    set_progress(job_id, 5, f"Loading model on {device.upper()}…")
    model = get_model(model_name, device)

    if diarize:
        set_progress(job_id, 10, "Starting diarization…")
        segments, error = transcribe_with_diarization(job_id, model, audio_path, device)
        if error:
            raise RuntimeError(error)
        full_text = "\n".join(
            f"[{s['speaker']}] [{gigaam.format_time(s['start'])} - {gigaam.format_time(s['end'])}] {s['text']}"
            for s in segments
        )
        result = {"text": full_text, "segments": segments, "diarized": True}

    elif word_timestamps:
        set_progress(job_id, 10, "Transcribing…")
        try:
            res = model.transcribe(audio_path, word_timestamps=True)
        except Exception as e:
            if "too long" in str(e).lower():
                set_progress(job_id, 20, "Long file — running VAD segmentation…")
                result, error = do_longform(model, audio_path)
                if error:
                    raise RuntimeError(error)
            else:
                raise
        else:
            words = [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in res.words
            ]
            result = {"text": " ".join(w["text"] for w in words), "words": words}

    else:
        set_progress(job_id, 10, "Transcribing…")
        try:
            res = model.transcribe(audio_path)
        except Exception as e:
            if "too long" in str(e).lower():
                set_progress(job_id, 20, "Long file — running VAD segmentation…")
                result, error = do_longform(model, audio_path)
                if error:
                    raise RuntimeError(error)
            else:
                raise
        else:
            text = res if isinstance(res, str) else str(res)
            result = {"text": text}

    return result


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/models")
def list_models():
    return jsonify(AVAILABLE_MODELS)


@app.route("/device-info")
def device_info():
    return jsonify({"cuda": CUDA_AVAILABLE, "gpu_name": GPU_NAME, "mps": MPS_AVAILABLE, "desktop": IS_DESKTOP})


@app.route("/audio-devices")
def audio_devices():
    try:
        import sounddevice as sd
        import soundcard as sc
        inputs = [
            {"index": i, "name": d["name"]}
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0 and "loopback" not in d["name"].lower()
        ]
        # Add system audio (loopback) option
        try:
            spk = sc.default_speaker()
            inputs.insert(0, {"index": "loopback", "name": f"System audio ({spk.name})"})
        except Exception:
            pass
        return jsonify(inputs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _mic_source(device_index):
    def source(stop):
        import sounddevice as sd
        with sd.InputStream(device=device_index, samplerate=REC_SAMPLE_RATE, channels=1, dtype="int16") as s:
            while not stop.is_set():
                chunk, _ = s.read(1024)
                yield chunk[:, 0].copy()
    return source


def _system_source():
    """System-audio loopback. soundcard loopback supports Windows (WASAPI) and Linux only."""
    if sys.platform == "darwin":
        # Native macOS capture (ScreenCaptureKit / Core Audio taps) is spec FR-PLAT-02.
        return ("system audio capture in the desktop app is not supported on macOS yet — "
                "use browser mode (Open in browser) to include call audio")

    def source(stop):
        import numpy as np
        import soundcard as sc
        spk = sc.default_speaker()
        lb = sc.get_microphone(id=str(spk.name), include_loopback=True)
        with lb.recorder(samplerate=REC_SAMPLE_RATE, channels=1, blocksize=1024) as rec:
            while not stop.is_set():
                chunk = rec.record(numframes=1024)[:, 0]
                yield (np.clip(chunk, -1.0, 1.0) * 32767).astype("int16")
    return source


@app.route("/desktop-record/start", methods=["POST"])
def desktop_record_start():
    """Start recording mic + system audio as separate channels (desktop app mode)."""
    global _recorder
    data = request.get_json(silent=True) or {}
    mic_index = data.get("mic_device")  # sounddevice index or None for default

    with _recorder_lock:
        if _recorder is not None and _recorder.recording:
            return jsonify({"error": "A recording is already in progress"}), 409
        _recorder = DualChannelRecorder(
            recordings_dir(),
            {"mic": _mic_source(mic_index), "sys": _system_source()},
        )
        recording_id = _recorder.start()
    return jsonify({"ok": True, "recording_id": recording_id})


@app.route("/desktop-record/status")
def desktop_record_status():
    """Live recorder state, including per-channel errors (spec gap #23)."""
    with _recorder_lock:
        if _recorder is None:
            return jsonify({"recording": False, "channels": {}})
        return jsonify(_recorder.status())


@app.route("/desktop-record/stop", methods=["POST"])
def desktop_record_stop():
    """Stop recording; keep mic.wav / sys.wav on disk and return a mixed WAV for playback."""
    with _recorder_lock:
        if _recorder is None or not _recorder.recording:
            return jsonify({"error": "No recording in progress"}), 409
        result = _recorder.stop()

    captured = [result[c] for c in ("sys", "mic") if result.get(c)]
    if not captured:
        details = "; ".join(f"{c}: {e}" for c, e in result["errors"].items())
        return jsonify({"error": "No audio captured" + (f" ({details})" if details else ""),
                        "errors": result["errors"]}), 400

    playback_path = captured[0] if len(captured) == 1 else mix_wavs(
        captured, os.path.join(result["folder"], "mixed.wav"))

    response = send_file(playback_path, mimetype="audio/wav", as_attachment=False,
                         download_name="recording.wav")
    response.headers["X-Recording-Id"] = result["recording_id"]
    response.headers["X-Recording-Errors"] = json.dumps(result["errors"])
    return response


def ollama_reachable(timeout=0.5):
    try:
        with urllib.request.urlopen(OLLAMA_URL.rstrip("/") + "/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


@app.route("/health")
def health():
    """Environment checks for the UI (spec FR-SET-01)."""
    return jsonify({
        "ffmpeg": FFMPEG_AVAILABLE,
        "gpu": {"cuda": CUDA_AVAILABLE, "gpu_name": GPU_NAME, "mps": MPS_AVAILABLE},
        "hf_token": bool(hf_token),
        "ollama": ollama_reachable(),
        "platform": sys.platform,
        "system_audio_capture": not isinstance(_system_source(), str),
    })


def _update_env_file(key, value):
    """Write or update a single key in .env without touching other lines."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    if value:
                        lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found and value:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


@app.route("/settings", methods=["GET"])
def get_settings():
    return jsonify({"hf_token_set": bool(hf_token)})


@app.route("/settings", methods=["POST"])
def save_settings():
    global hf_token, _diarization_pipeline
    data = request.get_json()
    new_token = (data.get("hf_token") or "").strip()

    _update_env_file("HF_TOKEN", new_token)

    hf_token = new_token or None
    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
    else:
        os.environ.pop("HF_TOKEN", None)

    # Reset pipeline so it reloads with the new token next time
    with _diarization_lock:
        _diarization_pipeline = None

    return jsonify({"ok": True, "hf_token_set": bool(hf_token)})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    model_name = request.form.get("model", "v3_e2e_rnnt")
    word_timestamps = request.form.get("word_timestamps", "false").lower() == "true"
    diarize = request.form.get("diarize", "false").lower() == "true"
    device = request.form.get("device", "cpu")

    if model_name not in AVAILABLE_MODELS:
        return jsonify({"error": f"Unknown model: {model_name}"}), 400

    if device == "cuda" and not CUDA_AVAILABLE:
        return jsonify({"error": "GPU requested but CUDA is not available. Install PyTorch with CUDA support — see README."}), 400

    if device == "mps" and not MPS_AVAILABLE:
        return jsonify({"error": "MPS requested but Apple Silicon GPU is not available."}), 400

    audio_file = request.files["audio"]
    suffix = os.path.splitext(audio_file.filename)[1].lower() or ".wav"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        audio_file.save(tmp_path)

    if suffix in NEEDS_CONVERSION:
        try:
            audio_path = convert_to_wav(tmp_path)
        except Exception as e:
            os.unlink(tmp_path)
            return jsonify({"error": str(e)}), 500
    else:
        audio_path = tmp_path

    job_id = jobs.create()
    t = threading.Thread(
        target=run_job,
        args=(job_id, tmp_path, audio_path, model_name, diarize, word_timestamps, device),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


def _run_flask_background():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host=BIND_HOST, port=PORT, debug=False, use_reloader=False)


def _wait_for_server(timeout=15):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://{BIND_HOST}:{PORT}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


if __name__ == "__main__":
    try:
        import webview
        _webview_available = True
    except ImportError:
        _webview_available = False

    browser_mode = "--browser" in sys.argv or not _webview_available

    print()
    print("  GigaAM Transcriber")
    print("  " + "-" * 40)
    print(f"  ffmpeg   : {'found' if FFMPEG_AVAILABLE else 'NOT FOUND — install from ffmpeg.org and add to PATH'}")
    if CUDA_AVAILABLE:
        gpu_str = GPU_NAME
    elif MPS_AVAILABLE:
        gpu_str = "Apple Silicon (MPS)"
    else:
        gpu_str = "not available (CPU only)"
    print(f"  GPU      : {gpu_str}")
    print(f"  HF token : {'set' if hf_token else 'not set — diarization and longform disabled'}")
    print("  " + "-" * 40)

    if browser_mode:
        print(f"  Open http://localhost:{PORT} in Chrome or Edge")
        print()
        # Loopback only: never expose transcripts or /settings to the LAN (spec NFR-SEC-04).
        app.run(host=BIND_HOST, port=PORT, debug=False)
    else:
        print("  Starting desktop window...")
        print()
        t = threading.Thread(target=_run_flask_background, daemon=True)
        t.start()
        _wait_for_server()
        IS_DESKTOP = True

        import webbrowser

        class _Api:
            def open_in_browser(self):
                webbrowser.open(f"http://{BIND_HOST}:{PORT}")

        storage = os.path.join(os.path.expanduser("~"), ".gigaam_transcriber")
        os.makedirs(storage, exist_ok=True)
        webview.create_window(
            "GigaAM Transcriber",
            f"http://{BIND_HOST}:{PORT}",
            width=1200,
            height=820,
            min_size=(800, 600),
            js_api=_Api(),
        )
        webview.start(private_mode=False, storage_path=storage)
