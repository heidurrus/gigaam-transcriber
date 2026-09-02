import os
import subprocess
import tempfile
import threading
import uuid
import torch
import gigaam
from gigaam.preprocess import load_audio, SAMPLE_RATE
from gigaam.utils import AudioDataset
from torch.utils.data import DataLoader
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory

load_dotenv()

hf_token = os.getenv("HF_TOKEN")
if hf_token:
    os.environ["HF_TOKEN"] = hf_token

app = Flask(__name__, static_folder="static")

CUDA_AVAILABLE = torch.cuda.is_available()
GPU_NAME = torch.cuda.get_device_name(0) if CUDA_AVAILABLE else None

_models = {}
_model_lock = threading.Lock()

_diarization_pipeline = None
_diarization_lock = threading.Lock()

_jobs = {}
_jobs_lock = threading.Lock()

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

# Formats soundfile can't read — need ffmpeg pre-conversion to WAV
NEEDS_CONVERSION = {".webm", ".ogg", ".opus", ".mp4", ".m4a", ".weba"}


def convert_to_wav(input_path):
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
            from pyannote.audio import Pipeline
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=hf_token,
            )
        return _diarization_pipeline.to(torch.device(device))


def set_progress(job_id, pct, msg):
    with _jobs_lock:
        _jobs[job_id]["progress"] = pct
        _jobs[job_id]["progress_msg"] = msg


def transcribe_with_diarization(job_id, model, audio_path, device):
    if not hf_token:
        return None, "HF_TOKEN not set in .env — required for diarization"

    set_progress(job_id, 15, "Loading diarization pipeline…")
    pipeline = get_diarization_pipeline(device)

    set_progress(job_id, 25, "Loading audio…")
    audio = load_audio(audio_path)  # (time,) at 16kHz

    # Pass as waveform dict — pyannote uses it directly, bypassing file I/O entirely.
    # This avoids the torchcodec/AudioDecoder dependency which is broken on Windows.
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
        return None, "Audio is too long. Add HF_TOKEN to .env to enable longform transcription."
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


def run_job(job_id, audio_path, wav_path, model_name, diarize, word_timestamps, device):
    try:
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

        set_progress(job_id, 100, "Done.")
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e)}
    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass
        if wav_path and wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/models")
def list_models():
    return jsonify(AVAILABLE_MODELS)


@app.route("/device-info")
def device_info():
    return jsonify({"cuda": CUDA_AVAILABLE, "gpu_name": GPU_NAME})


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
        return jsonify({"error": "GPU requested but CUDA is not available on this machine."}), 400

    audio_file = request.files["audio"]
    suffix = os.path.splitext(audio_file.filename)[1].lower() or ".wav"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        audio_file.save(tmp_path)

    wav_path = None
    if suffix in NEEDS_CONVERSION:
        try:
            wav_path = convert_to_wav(tmp_path)
            audio_path = wav_path
        except Exception as e:
            os.unlink(tmp_path)
            return jsonify({"error": f"Audio conversion failed: {e}"}), 500
    else:
        audio_path = tmp_path

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "processing", "progress": 0, "progress_msg": "Starting…"}

    t = threading.Thread(
        target=run_job,
        args=(job_id, audio_path, wav_path, model_name, diarize, word_timestamps, device),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/job/<job_id>")
def job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


if __name__ == "__main__":
    print("GigaAM transcription server running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
