import io
import json
import os
import time

import numpy as np
import pytest

from tests.test_recorder import read_wav, tone_source, wait_for


def test_health_reports_environment(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "ollama_reachable", lambda timeout=0.5: False)
    body = client.get("/health").get_json()
    assert set(body) >= {"ffmpeg", "gpu", "hf_token", "ollama", "platform", "system_audio_capture"}
    assert body["ollama"] is False
    assert body["gpu"] == {"cuda": False, "gpu_name": None, "mps": False}


def test_old_macos_explains_why_system_audio_is_unavailable(app_module, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.macos_audio, "support", lambda: (False, "needs macOS 14.2 or newer"))
    assert app_module._system_source() == "needs macOS 14.2 or newer"
    assert app_module.system_audio_support() == (False, "needs macOS 14.2 or newer")


def test_macos_uses_core_audio_tap_and_closes_it_after_recording(client, app_module, monkeypatch):
    events = []

    class FakeTap:
        def open(self):
            events.append("open")
            return self

        def __call__(self, stop):
            yield from tone_source(500, 2)(stop)

        def close(self):
            events.append("close")

    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.macos_audio, "support", lambda: (True, None))
    monkeypatch.setattr(app_module.macos_audio, "SystemAudioTap", FakeTap)
    monkeypatch.setattr(app_module, "_mic_source", lambda idx: tone_source(1, 2))
    monkeypatch.setattr(app_module, "_recorder", None)

    assert client.post("/desktop-record/start", json={}).status_code == 200
    assert events == ["open"], "tap must be opened before recording starts"
    assert wait_for(lambda: client.get("/desktop-record/status").get_json()["channels"]["sys"]["frames"] == 2048)
    res = client.post("/desktop-record/stop")
    assert res.status_code == 200 and json.loads(res.headers["X-Recording-Errors"]) == {}
    assert events == ["open", "close"]


def test_macos_tap_failure_is_reported_not_fatal(client, app_module, monkeypatch):
    class BrokenTap:
        def open(self):
            raise OSError("permission denied")

    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.macos_audio, "support", lambda: (True, None))
    monkeypatch.setattr(app_module.macos_audio, "SystemAudioTap", BrokenTap)
    monkeypatch.setattr(app_module, "_mic_source", lambda idx: tone_source(1, 2))
    monkeypatch.setattr(app_module, "_recorder", None)
    assert client.post("/desktop-record/start", json={}).status_code == 200
    status = client.get("/desktop-record/status").get_json()
    assert "permission denied" in status["channels"]["sys"]["error"]
    time.sleep(0.05)
    assert client.post("/desktop-record/stop").status_code == 200  # mic-only recording still saved


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


def test_transcript_upload_skips_speech_recognition(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_transcribe", lambda *a: pytest.fail("must not run ASR for a transcript"))
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n<v Иван Петров>Добрый день</v>\n".encode()
    res = client.post("/transcribe", data={"audio": (io.BytesIO(vtt), "Meeting.vtt")},
                      content_type="multipart/form-data")
    assert res.status_code == 200
    job = client.get(f"/job/{res.get_json()['job_id']}").get_json()
    assert job["status"] == "done"                      # immediately, no queue
    assert job["result"]["segments"] == [{"speaker": "Иван Петров", "start": 1.0, "end": 2.5, "text": "Добрый день"}]
    assert job["result"]["imported"] == {"format": "vtt", "filename": "Meeting.vtt"}


def test_unreadable_transcript_is_a_clear_400(client):
    res = client.post("/transcribe", data={"audio": (io.BytesIO(b"not a zip"), "notes.docx")},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert "Could not read this transcript" in res.get_json()["error"]


def test_pdf_transcript_upload(client):
    import os
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "teams_ru.pdf"), "rb") as f:
        pdf = f.read()
    res = client.post("/transcribe", data={"audio": (io.BytesIO(pdf), "Встреча.pdf")},
                      content_type="multipart/form-data")
    job = client.get(f"/job/{res.get_json()['job_id']}").get_json()
    assert job["status"] == "done" and job["result"]["imported"]["format"] == "pdf"
    assert {s.get("speaker") for s in job["result"]["segments"]} >= {"Иван Петров", "Анна Смирнова"}


def test_unsupported_file_type_gets_a_clear_message(client):
    res = client.post("/transcribe", data={"audio": (io.BytesIO(b"PK"), "budget.xlsx")},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert "unsupported file type" in res.get_json()["error"] and ".pdf" in res.get_json()["error"]


def test_settings_roundtrip_keeps_key_secret(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = client.get("/settings").get_json()
    assert body["anthropic_key_set"] is False and body["llm_provider"] == "claude"
    assert {"id": "claude-opus-5", "label": "Claude Opus 5 (best quality)"} in body["claude_models"]
    body = client.post("/settings", json={"anthropic_api_key": "sk-ant-secret", "claude_model": "claude-sonnet-5"}).get_json()
    assert body["anthropic_key_set"] is True and body["claude_model"] == "claude-sonnet-5"
    assert "sk-ant-secret" not in json.dumps(client.get("/settings").get_json())   # never sent back
    assert client.post("/settings", json={"llm_provider": "gpt"}).status_code == 400


def test_summarize_without_key_asks_for_setup(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/summarize", json={"text": "Иван: привет"})
    assert res.status_code == 400 and res.get_json()["needs_setup"] is True
    assert client.post("/summarize", json={"text": "  "}).status_code == 400


def test_summarize_streams_partial_text_into_the_job(client, app_module, monkeypatch, tmp_path):
    import threading
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    release = threading.Event()

    def fake_summarize(text, prefs, api_key, url, on_delta, title=None):
        assert api_key == "sk-ant-x" and title == "call.vtt"
        on_delta("## Итоги\n")
        release.wait(2)
        on_delta("Готово")
        return "## Итоги\nГотово"
    monkeypatch.setattr(app_module, "summarize", fake_summarize)

    job_id = client.post("/summarize", json={"text": "Иван: привет", "title": "call.vtt"}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job_id}").get_json().get("partial") == "## Итоги\n")
    assert client.get(f"/job/{job_id}").get_json()["status"] == "processing"
    release.set()
    assert wait_for(lambda: client.get(f"/job/{job_id}").get_json()["status"] == "done")
    assert client.get(f"/job/{job_id}").get_json()["result"] == {
        "summary": "## Итоги\nГотово", "provider": "claude", "model": "claude-opus-5"}


def test_summary_errors_are_reported(client, app_module, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    def failing(*a, **k):
        raise app_module.SummaryError("Anthropic rejected the API key. Check it in Settings.")
    monkeypatch.setattr(app_module, "summarize", failing)
    job_id = client.post("/summarize", json={"text": "t"}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job_id}").get_json()["status"] == "error")
    assert "rejected the API key" in client.get(f"/job/{job_id}").get_json()["error"]
