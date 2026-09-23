import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import warnings

# Suppress pyannote's torchcodec warning — we pass waveform dicts so it's never used
warnings.filterwarnings("ignore", message=".*torchcodec.*")

import torch
import gigaam
from gigaam.preprocess import load_audio, SAMPLE_RATE
from gigaam.utils import AudioDataset
from torch.utils.data import DataLoader
from flask import Flask, request, jsonify, send_file, send_from_directory

from core.ffmpeg import ensure_ffmpeg_on_path
from core import macos_audio, settings
from core.summarize import SummaryError, summarize
from core.jobs import JobStore, SerialQueue
from core.paths import models_dir, recordings_dir, use_app_model_cache
from core.macos_permissions import microphone_access
from core.realtime import realtime
from core.recorder import (SAMPLE_RATE as REC_SAMPLE_RATE, DualChannelRecorder, mix_wavs, speech_bounds,
                           wav_duration, wav_peak)
from core.security import install_local_only_guard
from core.store import Store, StoreError
from core.emails import EMAIL_EXTENSIONS, parse_email_file
from core.transcripts import (MAX_BYTES as MAX_TRANSCRIPT_BYTES, TranscriptError,
                              is_transcript_file, parse_transcript)

settings.load_env()
use_app_model_cache()

hf_token = os.getenv("HF_TOKEN")
if hf_token:
    os.environ["HF_TOKEN"] = hf_token

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

app = Flask(__name__, static_folder="static")
install_local_only_guard(app)

CUDA_AVAILABLE = torch.cuda.is_available()
GPU_NAME = torch.cuda.get_device_name(0) if CUDA_AVAILABLE else None
MPS_AVAILABLE = torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False

# System ffmpeg if present, else the one setup installs (imageio-ffmpeg), exposed on
# PATH because GigaAM's load_audio calls a bare "ffmpeg"
FFMPEG_EXE = ensure_ffmpeg_on_path()
FFMPEG_AVAILABLE = FFMPEG_EXE is not None

_models = {}
_model_lock = threading.Lock()

_diarization_pipeline = None
_diarization_lock = threading.Lock()

jobs = JobStore()
library = Store()  # projects, sources, transcripts, summaries (spec increment 1)
transcription_queue = SerialQueue()  # one transcription at a time (spec D-12)

_recorder = None
_recorder_lock = threading.Lock()
_active_tap = None  # macOS system-audio tap while recording
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
# Everything ffmpeg/GigaAM can read that people actually upload; anything else gets a
# clear message instead of an ffmpeg error (the desktop file picker allows all files).
AUDIO_VIDEO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".webm",
                          ".weba", ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".aiff", ".aif", ".amr", ".3gp"}


def convert_to_wav(input_path):
    if not FFMPEG_AVAILABLE:
        raise RuntimeError("ffmpeg is missing. Restart the app to let setup reinstall it.")
    wav_path = input_path + ".wav"
    subprocess.run(
        [FFMPEG_EXE, "-y", "-i", input_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True,
        capture_output=True,
    )
    return wav_path


def get_model(name, device):
    with _model_lock:
        if name not in _models:
            _models[name] = gigaam.load_model(name, download_root=models_dir("gigaam"))
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


def run_job(job_id, upload_path, audio_path, model_name, diarize, word_timestamps, device,
            source_id=None, channels=None):
    """Queue and run one transcription.

    With a source_id the files belong to a saved source and are kept; the result
    is stored in the library. Without one (legacy temp uploads) both files are
    deleted afterwards.
    """
    def on_wait(ahead):
        set_progress(job_id, 0, f"Queued — waiting for {ahead} job(s) to finish…")

    result, error = None, None
    try:
        work = ((lambda: _transcribe_channels(job_id, *channels, model_name, diarize, device)) if channels
                else (lambda: _transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device)))
        result = transcription_queue.run(job_id, work, on_wait=on_wait)
    except Exception as e:
        error = e
    finally:
        if source_id is None:
            for path in {upload_path, audio_path}:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    if source_id is not None:
        try:
            if error is not None:
                library.fail_source(source_id, error)
            else:
                library.save_transcript(source_id, result, asr_model=model_name)
                result = {**result, "source_id": source_id}
        except Exception as e:  # never lose the job result because saving failed
            error = error or e
    # Report completion only after cleanup and saving, so "done" means it's all in place.
    if error is not None:
        jobs.fail(job_id, error)
    else:
        jobs.finish(job_id, result)


# Recordings keep the microphone (the BA) and system audio (everyone else) apart,
# so the BA never needs diarization (spec D-11, FR-SRC-01 AC6).
BA_LABEL, OTHER_LABEL = "BA", "OTHER"


def _channel_segments(job_id, path, model_name, diarize, device, label):
    result = _transcribe(job_id, path, model_name, diarize, False, device)
    segments = result.get("segments")
    if not segments:  # short audio comes back as plain text: one segment where the speech is
        text = (result.get("text") or "").strip()
        start, end = speech_bounds(path) or (0.0, round(wav_duration(path), 3))
        segments = [{"start": start, "end": end, "text": text}] if text else []
    out = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if text:
            speaker = s.get("speaker") if diarize and s.get("speaker") else label
            out.append({"speaker": speaker, "start": s.get("start"), "end": s.get("end"), "text": text})
    return out


def _transcribe_channels(job_id, mic_path, sys_path, model_name, diarize, device):
    """Transcribe each recorded channel on its own and merge them in time order.

    Mic segments are the BA; system-audio segments are diarized when asked (the
    remote participants), otherwise labelled OTHER. A silent channel is skipped.
    """
    segments = []
    if mic_path and os.path.exists(mic_path) and wav_peak(mic_path) > 0:
        set_progress(job_id, 1, "Transcribing your microphone…")
        segments += _channel_segments(job_id, mic_path, model_name, False, device, BA_LABEL)
    if sys_path and os.path.exists(sys_path) and wav_peak(sys_path) > 0:
        set_progress(job_id, 50, "Transcribing the other side of the call…")
        segments += _channel_segments(job_id, sys_path, model_name, diarize, device, OTHER_LABEL)
    segments.sort(key=lambda s: (s["start"] is None, s["start"] or 0.0))
    text = "\n".join(f"[{s['speaker']}] [{gigaam.format_time(s['start'] or 0)} - "
                     f"{gigaam.format_time(s['end'] or 0)}] {s['text']}" for s in segments)
    return {"text": text, "segments": segments, "diarized": True, "channels": True}


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
    """The multi-screen app (frontend/, built into static/app)."""
    if os.path.exists(os.path.join(app.static_folder, "app", "index.html")):
        return send_from_directory(os.path.join(app.static_folder, "app"), "index.html")
    return send_from_directory(app.static_folder, "index.html")


@app.route("/classic")
def classic():
    """The previous single-page UI, kept as a fallback while the new one settles."""
    return send_from_directory(app.static_folder, "index.html")


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


MIC_NO_AUDIO = ("the microphone delivers no audio. Check that it's connected and, on macOS, allowed in "
                "System Settings → Privacy & Security → Microphone")
SYS_SILENT = ("system audio was silent the whole time. If the call's audio was playing, allow "
              "Requirements Workbench in System Settings → Privacy & Security → Screen & System Audio Recording")


def _mic_source(device_index):
    def source(stop):
        import sounddevice as sd
        with sd.InputStream(device=device_index, samplerate=REC_SAMPLE_RATE, channels=1, dtype="int16") as s:
            while not stop.is_set():
                chunk, _ = s.read(1024)
                yield chunk[:, 0].copy()
    # Never block the recorder; fail with a reason if the mic stays silent (e.g. no permission).
    return realtime(source, REC_SAMPLE_RATE, no_audio_error=MIC_NO_AUDIO)


def system_audio_support():
    """(supported, reason) for desktop-mode system-audio capture, without opening anything."""
    if sys.platform == "darwin":
        return macos_audio.support()
    return True, None


def _system_source():
    """A recorder source for system audio, or a string saying why it's unavailable.

    macOS: Core Audio process tap (spec FR-PLAT-02), opened here, before the mic
    stream starts, because it makes PortAudio re-scan devices. Windows/Linux:
    soundcard loopback (WASAPI / PulseAudio).
    """
    if sys.platform == "darwin":
        ok, reason = macos_audio.support()
        if not ok:
            return reason
        try:
            tap = macos_audio.SystemAudioTap().open()
        except Exception as e:
            return f"system audio unavailable: {e}"
        # The tap delivers nothing while nothing plays: fill that with silence so the
        # system channel stays in step with the mic, and Stop never waits on it.
        wrapped = realtime(tap, REC_SAMPLE_RATE, fill_silence=True)
        wrapped.close = tap.close
        return wrapped

    def source(stop):
        import numpy as np
        import soundcard as sc
        spk = sc.default_speaker()
        lb = sc.get_microphone(id=str(spk.name), include_loopback=True)
        with lb.recorder(samplerate=REC_SAMPLE_RATE, channels=1, blocksize=1024) as rec:
            while not stop.is_set():
                chunk = rec.record(numframes=1024)[:, 0]
                yield (np.clip(chunk, -1.0, 1.0) * 32767).astype("int16")
    return realtime(source, REC_SAMPLE_RATE, fill_silence=True)


def _close_active_tap():
    global _active_tap
    if _active_tap is not None:
        try:
            _active_tap.close()
        finally:
            _active_tap = None


@app.route("/desktop-record/start", methods=["POST"])
def desktop_record_start():
    """Start recording mic + system audio as separate channels (desktop app mode)."""
    global _recorder, _active_tap
    data = request.get_json(silent=True) or {}
    mic_index = data.get("mic_device")  # sounddevice index or None for default
    if _recorder is not None and _recorder.recording:
        return jsonify({"error": "A recording is already in progress"}), 409

    # macOS: ask for the microphone first (shows the system prompt once), outside the
    # lock because the user may take a while to answer.
    mic_ok, mic_reason = microphone_access()
    mic = _mic_source(mic_index) if mic_ok else mic_reason

    with _recorder_lock:
        if _recorder is not None and _recorder.recording:
            return jsonify({"error": "A recording is already in progress"}), 409
        sys_source = _system_source()
        _active_tap = sys_source if hasattr(sys_source, "close") else None
        _recorder = DualChannelRecorder(recordings_dir(), {"mic": mic, "sys": sys_source})
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
        _close_active_tap()

    if result.get("sys") and "sys" not in result["errors"] and wav_peak(result["sys"]) == 0:
        result["errors"]["sys"] = SYS_SILENT
    captured = [result[c] for c in ("sys", "mic") if result.get(c)]
    if not captured:
        details = "; ".join(f"{c}: {e}" for c, e in result["errors"].items())
        return jsonify({"error": "No audio captured" + (f" ({details})" if details else ""),
                        "errors": result["errors"]}), 400

    playback_path = captured[0] if len(captured) == 1 else mix_wavs(
        captured, os.path.join(result["folder"], "mixed.wav"))

    # Keep the recording as a source in the current project (files move into its folder).
    title = ((request.get_json(silent=True) or {}).get("title") or "").strip()  # localised by the UI
    source = library.create_source(library.current_project()["id"], "recording",
                                   title or "Recording " + time.strftime("%d.%m.%Y %H:%M"), status="recorded")
    for name in os.listdir(result["folder"]):
        library.attach_file(source, os.path.join(result["folder"], name), name, move=True)
    shutil.rmtree(result["folder"], ignore_errors=True)
    playback_path = os.path.join(library.source_dir(source), os.path.basename(playback_path))
    library.update_source(source["id"], audit=False, audio_file=os.path.basename(playback_path))

    response = send_file(playback_path, mimetype="audio/wav", as_attachment=False,
                         download_name="recording.wav")
    response.headers["X-Recording-Id"] = result["recording_id"]
    response.headers["X-Source-Id"] = source["id"]
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
        "system_audio_capture": system_audio_support()[0],
    })


def _settings_payload():
    prefs = settings.load_settings()
    return {
        "hf_token_set": bool(hf_token),
        "anthropic_key_set": bool(settings.secret("ANTHROPIC_API_KEY")),
        "llm_provider": prefs["llm_provider"],
        "claude_model": prefs["claude_model"],
        "ollama_model": prefs["ollama_model"],
        "claude_models": [{"id": m, "label": label} for m, label in settings.CLAUDE_MODELS],
    }


@app.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(_settings_payload())


@app.route("/settings", methods=["POST"])
def save_settings():
    """Update only the fields present: hf_token, anthropic_api_key, llm_provider, claude_model, ollama_model."""
    global hf_token, _diarization_pipeline
    data = request.get_json(silent=True) or {}
    prefs = {k: data[k] for k in ("llm_provider", "claude_model", "ollama_model") if k in data}
    try:
        if prefs:
            settings.save_settings(prefs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if "hf_token" in data:
        settings.set_secret("HF_TOKEN", data.get("hf_token"))
        hf_token = settings.secret("HF_TOKEN")
        # Reset pipeline so it reloads with the new token next time
        with _diarization_lock:
            _diarization_pipeline = None
    if "anthropic_api_key" in data:
        settings.set_secret("ANTHROPIC_API_KEY", data.get("anthropic_api_key"))

    return jsonify({"ok": True, **_settings_payload()})


@app.route("/ollama/status")
def ollama_status():
    return jsonify({"reachable": ollama_reachable()})


def _run_summary(job_id, text, title, prefs, api_key, source_id=None):
    try:
        result = summarize(text, prefs, api_key, OLLAMA_URL,
                           on_delta=lambda piece: jobs.append_partial(job_id, piece), title=title)
    except SummaryError as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"Summary failed: {e}")
    else:
        model = prefs["ollama_model"] if prefs["llm_provider"] == "ollama" else prefs["claude_model"]
        if source_id:
            library.add_summary(source_id, prefs["llm_provider"], model, result)
        jobs.finish(job_id, {"summary": result, "provider": prefs["llm_provider"], "model": model,
                             "source_id": source_id})


@app.route("/summarize", methods=["POST"])
def summarize_route():
    """Summarise transcript text with the provider chosen in Settings (streams into the job)."""
    data = request.get_json(silent=True) or {}
    source_id, title = data.get("source_id"), data.get("title")
    project = None
    if source_id:
        try:
            source = library.get_source(source_id)
        except StoreError as e:
            return jsonify({"error": str(e)}), 404
        project = library.get_project(source["project_id"])
        title = title or source["title"]
        kind_label = {"email": "Email", "document": "Document"}.get(source["kind"], "Call or meeting")
        title = f"{kind_label} — {title}"
        text = library.transcript_text(source_id)   # renamed speakers included
    else:
        text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "There is no transcript text to summarise."}), 400
    prefs = settings.load_settings()
    if project and project["local_only"]:
        # "Local only" project: nothing may go to a cloud model (spec FR-PRJ-05, D-02).
        prefs = {**prefs, "llm_provider": "ollama"}
    api_key = settings.secret("ANTHROPIC_API_KEY")
    if prefs["llm_provider"] == "claude" and not api_key:
        return jsonify({"error": "Add your Anthropic API key in Settings, or choose a local model.",
                        "needs_setup": True}), 400
    job_id = jobs.create()
    jobs.set_progress(job_id, 0, "Writing summary…")
    threading.Thread(target=_run_summary, args=(job_id, text, title, prefs, api_key, source_id),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


def _request_project():
    """Project named in the request (form or JSON), else the current one."""
    data = request.get_json(silent=True) if request.is_json else None
    pid = (data or {}).get("project_id") or request.form.get("project_id")
    return library.get_project(pid) if pid else library.current_project()


def _transcription_options(values):
    """Validate model / device / flags from a form or JSON body; returns (options, error)."""
    model_name = values.get("model", "v3_e2e_rnnt")
    if model_name not in AVAILABLE_MODELS:
        return None, f"Unknown model: {model_name}"
    device = values.get("device", "cpu")
    if device == "cuda" and not CUDA_AVAILABLE:
        return None, "GPU requested but CUDA is not available. Install PyTorch with CUDA support — see README."
    if device == "mps" and not MPS_AVAILABLE:
        return None, "MPS requested but Apple Silicon GPU is not available."
    flag = lambda k: str(values.get(k, "false")).lower() == "true"  # noqa: E731
    return dict(model_name=model_name, diarize=flag("diarize"), word_timestamps=flag("word_timestamps"),
                device=device), None


def _recorded_channels(source):
    """(mic.wav, sys.wav) when a desktop recording kept both channels, else None."""
    if source.get("kind") != "recording":
        return None
    folder = library.source_dir(source)
    mic, sys_ = os.path.join(folder, "mic.wav"), os.path.join(folder, "sys.wav")
    return (mic, sys_) if os.path.exists(mic) and os.path.exists(sys_) else None


def _start_transcription(source, audio_path, opts):
    job_id = jobs.create()
    threading.Thread(target=run_job, daemon=True, args=(
        job_id, audio_path, audio_path, opts["model_name"], opts["diarize"], opts["word_timestamps"],
        opts["device"], source["id"], _recorded_channels(source))).start()
    return job_id


@app.route("/transcribe", methods=["POST"])
def transcribe():
    """Upload audio/video to transcribe, or a transcript to import. Always saved as a source."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    try:
        project = _request_project()
    except StoreError as e:
        return jsonify({"error": str(e)}), 400

    upload = request.files["audio"]
    filename = os.path.basename(upload.filename or "upload")
    title = os.path.splitext(filename)[0] or filename
    is_email = os.path.splitext(filename)[1].lower() in EMAIL_EXTENSIONS
    if is_email or is_transcript_file(filename):
        # Text sources skip speech recognition (spec FR-SRC-03 AC2): a ready-made
        # transcript (Teams/Zoom .vtt, .srt, .docx, .pdf, .txt…), an email (.eml/.msg),
        # or a document such as an earlier specification.
        data = upload.read(MAX_TRANSCRIPT_BYTES + 1)
        try:
            result = parse_email_file(filename, data) if is_email else parse_transcript(filename, data)
        except TranscriptError as e:
            return jsonify({"error": f"Could not read this file: {e}"}), 400
        if is_email:
            kind, title = "email", result.get("title") or title
        else:
            # Speakers or timestamps make it a transcript; plain prose is a document.
            timed = any(s.get("speaker") or s.get("start") is not None for s in result.get("segments", []))
            kind = "transcript" if timed else "document"
        source = library.create_source(project["id"], kind, title, original_filename=filename)
        with open(os.path.join(library.source_dir(source), filename), "wb") as f:
            f.write(data)
        library.save_transcript(source["id"], result)
        job_id = jobs.create()
        jobs.finish(job_id, {**result, "source_id": source["id"]})
        return jsonify({"job_id": job_id, "source_id": source["id"]})

    opts, error = _transcription_options(request.form)
    if error:
        return jsonify({"error": error}), 400
    suffix = os.path.splitext(filename)[1].lower() or ".wav"
    if suffix not in AUDIO_VIDEO_EXTENSIONS:
        return jsonify({"error": f"{filename}: unsupported file type. Use audio or video "
                        "(WAV, MP3, M4A, WebM, MP4…) or a transcript (.vtt, .srt, .docx, .pdf, .txt)."}), 400

    kind = "recording" if request.form.get("kind") == "recording" else "audio"
    source = library.create_source(project["id"], kind, title, original_filename=filename,
                                   asr_model=opts["model_name"])
    original = os.path.join(library.source_dir(source), "original" + suffix)
    upload.save(original)
    if suffix in NEEDS_CONVERSION:
        try:
            converted = convert_to_wav(original)
            audio_path = os.path.join(library.source_dir(source), "audio.wav")
            os.replace(converted, audio_path)
        except Exception as e:
            library.fail_source(source["id"], e)
            return jsonify({"error": str(e), "source_id": source["id"]}), 500
    else:
        audio_path = original
    library.update_source(source["id"], audit=False, audio_file=os.path.basename(audio_path))
    job_id = _start_transcription(source, audio_path, opts)
    return jsonify({"job_id": job_id, "source_id": source["id"]})


@app.route("/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ── Library API (projects, sources) ──────────────────────────────────────────

def _store_call(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs)), 200
    except StoreError as e:
        status = 404 if "not found" in str(e) else 400
        return jsonify({"error": str(e)}), status


@app.route("/api/projects", methods=["GET"])
def api_projects():
    include_archived = request.args.get("archived") == "1"
    current = library.current_project()
    return jsonify({"projects": library.list_projects(include_archived), "current_project_id": current["id"]})


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    data = request.get_json(silent=True) or {}
    return _store_call(library.create_project, data.get("name"), bool(data.get("local_only")))


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def api_update_project(project_id):
    data = request.get_json(silent=True) or {}
    return _store_call(library.update_project, project_id,
                       **{k: data[k] for k in ("name", "local_only", "archived") if k in data})


@app.route("/api/projects/<project_id>/current", methods=["POST"])
def api_switch_project(project_id):
    return _store_call(library.set_current_project, project_id)


@app.route("/api/projects/<project_id>/sources", methods=["GET"])
def api_sources(project_id):
    try:
        library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"sources": library.list_sources(project_id)})


@app.route("/api/sources/<source_id>", methods=["GET"])
def api_source(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    segments, speaker_names = library.transcript(source_id)
    return jsonify({**source, "segments": segments, "speaker_names": speaker_names,
                    "text": library.transcript_text(source_id) if segments else "",
                    "summary": library.latest_summary(source_id),
                    "audio_url": f"/api/sources/{source_id}/audio" if source.get("audio_file") else None})


@app.route("/api/sources/<source_id>", methods=["PATCH"])
def api_update_source(source_id):
    data = request.get_json(silent=True) or {}
    if set(data) - {"title"}:
        return jsonify({"error": "only the title can be changed here"}), 400
    return _store_call(library.update_source, source_id, **data)


@app.route("/api/sources/<source_id>", methods=["DELETE"])
def api_delete_source(source_id):
    return _store_call(lambda: (library.delete_source(source_id), {"ok": True})[1])


@app.route("/api/sources/<source_id>/restore", methods=["POST"])
def api_restore_source(source_id):
    return _store_call(lambda: (library.restore_source(source_id), {"ok": True})[1])


@app.route("/api/sources/<source_id>/speakers/<path:label>", methods=["PUT"])
def api_rename_speaker(source_id, label):
    data = request.get_json(silent=True) or {}
    return _store_call(lambda: (library.rename_speaker(source_id, label, data.get("name")),
                                {"ok": True, "speaker_names": library.transcript(source_id)[1]})[1])


@app.route("/api/sources/<source_id>/audio")
def api_source_audio(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if not source.get("audio_file"):
        return jsonify({"error": "this source has no audio"}), 404
    # conditional=True answers Range requests, so the player can seek.
    return send_file(os.path.join(library.source_dir(source), source["audio_file"]), conditional=True)


@app.route("/api/sources/<source_id>/transcribe", methods=["POST"])
def api_transcribe_source(source_id):
    """(Re)transcribe a saved source's audio, e.g. a recording after Stop."""
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if not source.get("audio_file"):
        return jsonify({"error": "this source has no audio to transcribe"}), 400
    opts, error = _transcription_options(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    library.update_source(source_id, status="processing", asr_model=opts["model_name"], error=None)
    job_id = _start_transcription(source, os.path.join(library.source_dir(source), source["audio_file"]), opts)
    return jsonify({"job_id": job_id, "source_id": source_id})


@app.route("/api/audit")
def api_audit():
    return jsonify({"entries": library.audit(request.args.get("entity"), request.args.get("entity_id"),
                                             min(int(request.args.get("limit", 200)), 1000))})


if __name__ == "__main__":
    # Dev entry point; the installed app starts through launcher.py.
    import launcher
    sys.exit(launcher.main(app_module=sys.modules[__name__]))
