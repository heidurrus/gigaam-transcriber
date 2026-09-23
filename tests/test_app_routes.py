import io
import json
import os
import time

import numpy as np

from tests.test_recorder import read_wav, tone_source, wait_for


def test_health_reports_environment(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "ollama_reachable", lambda timeout=0.5: False)
    body = client.get("/health").get_json()
    assert set(body) >= {"ffmpeg", "gpu", "hf_token", "ollama", "platform", "system_audio_capture"}
    assert body["ollama"] is False
    assert body["gpu"] == {"cuda": False, "gpu_name": None, "mps": False}


def test_macos_system_audio_is_reported_unavailable(app_module, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    reason = app_module._system_source()
    assert isinstance(reason, str) and "macOS" in reason


def _use_fake_sources(app_module, monkeypatch, mic, sys_):
    monkeypatch.setattr(app_module, "_mic_source", lambda idx: mic)
    monkeypatch.setattr(app_module, "_system_source", lambda: sys_)
    monkeypatch.setattr(app_module, "_recorder", None)


def test_desktop_recording_roundtrip_keeps_separate_channels(client, app_module, monkeypatch):
    _use_fake_sources(app_module, monkeypatch, tone_source(1000, 3), tone_source(2000, 3))
    res = client.post("/desktop-record/start", json={"mic_device": None})
    assert res.status_code == 200
    assert client.post("/desktop-record/start", json={}).status_code == 409

    assert wait_for(lambda: all(c["frames"] == 3072 for c in
                                client.get("/desktop-record/status").get_json()["channels"].values()))
    res = client.post("/desktop-record/stop")
    assert res.status_code == 200 and res.mimetype == "audio/wav"
    assert json.loads(res.headers["X-Recording-Errors"]) == {}

    folder = os.path.join(os.environ["WORKBENCH_DATA_DIR"], "recordings", res.headers["X-Recording-Id"])
    assert set(read_wav(os.path.join(folder, "mic.wav"))) == {1000}
    assert set(read_wav(os.path.join(folder, "sys.wav"))) == {2000}
    mixed = np.frombuffer(res.data[44:], dtype="<i2")
    assert set(mixed) == {3000}


def test_stop_without_any_audio_returns_400_with_reasons(client, app_module, monkeypatch):
    def broken(stop):
        raise OSError("no input device")
        yield  # pragma: no cover
    _use_fake_sources(app_module, monkeypatch, broken, "unsupported here")
    client.post("/desktop-record/start", json={})
    time.sleep(0.05)
    res = client.post("/desktop-record/stop")
    assert res.status_code == 400
    body = res.get_json()
    assert body["errors"] == {"mic": "no input device", "sys": "unsupported here"}
    assert "no input device" in body["error"]


def test_stop_when_not_recording_is_409(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_recorder", None)
    assert client.post("/desktop-record/stop").status_code == 409


def test_transcribe_cleans_up_upload_and_converted_file(client, app_module, monkeypatch, tmp_path):
    seen = {}

    def fake_convert(path):
        wav = path + ".wav"
        open(wav, "wb").write(b"RIFF")
        seen["upload"], seen["wav"] = path, wav
        return wav

    monkeypatch.setattr(app_module, "convert_to_wav", fake_convert)
    monkeypatch.setattr(app_module, "_transcribe", lambda *a: {"text": "привет"})

    res = client.post("/transcribe", data={"audio": (io.BytesIO(b"webm"), "call.webm")},
                      content_type="multipart/form-data")
    job_id = res.get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job_id}").get_json()["status"] == "done")
    assert client.get(f"/job/{job_id}").get_json()["result"] == {"text": "привет"}
    assert not os.path.exists(seen["upload"]), "original upload must be deleted (baseline leaked it)"
    assert not os.path.exists(seen["wav"])


def test_transcribe_error_is_reported(client, app_module, monkeypatch):
    def boom(*a):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(app_module, "_transcribe", boom)
    res = client.post("/transcribe", data={"audio": (io.BytesIO(b"RIFF"), "a.wav")},
                      content_type="multipart/form-data")
    job_id = res.get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job_id}").get_json()["status"] == "error")
    assert client.get(f"/job/{job_id}").get_json()["error"] == "model exploded"
