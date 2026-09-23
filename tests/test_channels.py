import os

import numpy as np
import pytest

from core.store import Store
from tests.test_recorder import StreamingWavWriter, wait_for


def write_wav(path, seconds, value=500):
    w = StreamingWavWriter(path)
    w.write(np.full(int(16000 * seconds), value, np.int16))
    w.close()


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


def fake_transcribe(results):
    """_transcribe stub returning a canned result per file name, recording the calls."""
    calls = []

    def fake(job_id, path, model, diarize, words, device):
        calls.append((os.path.basename(path), diarize))
        return results[os.path.basename(path)]
    fake.calls = calls
    return fake


def test_mic_is_the_ba_remote_side_is_diarized_and_merged_in_time_order(app_module, monkeypatch, tmp_path):
    mic, sys_ = str(tmp_path / "mic.wav"), str(tmp_path / "sys.wav")
    write_wav(mic, 1)
    write_wav(sys_, 1)
    fake = fake_transcribe({
        "mic.wav": {"segments": [{"start": 0.5, "end": 3.0, "text": "Расскажите про карточку"},
                                 {"start": 9.0, "end": 11.0, "text": "Понял"}]},
        "sys.wav": {"diarized": True, "segments": [
            {"speaker": "SPEAKER_00", "start": 3.2, "end": 6.0, "text": "Оператор должен видеть историю"},
            {"speaker": "SPEAKER_01", "start": 6.1, "end": 8.8, "text": "До поднятия трубки"}]},
    })
    monkeypatch.setattr(app_module, "_transcribe", fake)
    r = app_module._transcribe_channels("job", mic, sys_, "v3_e2e_rnnt", True, "cpu")
    assert [(s["speaker"], s["text"]) for s in r["segments"]] == [
        ("BA", "Расскажите про карточку"), ("SPEAKER_00", "Оператор должен видеть историю"),
        ("SPEAKER_01", "До поднятия трубки"), ("BA", "Понял")]
    assert fake.calls == [("mic.wav", False), ("sys.wav", True)], "the BA channel is never diarized"
    assert r["diarized"] is True and r["text"].splitlines()[0].startswith("[BA] [00:00")


def test_without_speaker_separation_remote_side_is_other(app_module, monkeypatch, tmp_path):
    mic, sys_ = str(tmp_path / "mic.wav"), str(tmp_path / "sys.wav")
    write_wav(mic, 2)
    write_wav(sys_, 2)
    monkeypatch.setattr(app_module, "_transcribe", fake_transcribe({
        "mic.wav": {"text": "короткая фраза"},                      # short audio: text only
        "sys.wav": {"text": "ответ собеседника"}}))
    r = app_module._transcribe_channels("job", mic, sys_, "v3_e2e_rnnt", False, "cpu")
    assert [(s["speaker"], s["start"], s["end"]) for s in r["segments"]] == [("BA", 0.0, 2.0), ("OTHER", 0.0, 2.0)]


def test_short_clip_segment_starts_where_the_speech_starts(app_module, monkeypatch, tmp_path):
    mic, sys_ = str(tmp_path / "mic.wav"), str(tmp_path / "sys.wav")
    write_wav(mic, 1.0)
    w = StreamingWavWriter(sys_)                                    # 3 s silence, 2 s speech, 1 s silence
    w.write(np.concatenate([np.zeros(48000, np.int16), np.full(32000, 900, np.int16), np.zeros(16000, np.int16)]))
    w.close()
    monkeypatch.setattr(app_module, "_transcribe", fake_transcribe({"mic.wav": {"text": "вопрос"}, "sys.wav": {"text": "ответ"}}))
    r = app_module._transcribe_channels("job", mic, sys_, "v3_e2e_rnnt", False, "cpu")
    other = [s for s in r["segments"] if s["speaker"] == "OTHER"][0]
    assert (other["start"], other["end"]) == (3.0, 5.0)


def test_silent_channel_is_skipped(app_module, monkeypatch, tmp_path):
    mic, sys_ = str(tmp_path / "mic.wav"), str(tmp_path / "sys.wav")
    write_wav(mic, 1)
    write_wav(sys_, 1, value=0)                                     # nothing played
    fake = fake_transcribe({"mic.wav": {"text": "только я"}})
    monkeypatch.setattr(app_module, "_transcribe", fake)
    r = app_module._transcribe_channels("job", mic, sys_, "v3_e2e_rnnt", True, "cpu")
    assert [s["speaker"] for s in r["segments"]] == ["BA"] and fake.calls == [("mic.wav", False)]


def test_saved_recording_with_both_channels_uses_channel_mode(client, app_module, lib, monkeypatch):
    src = lib.create_source(lib.current_project()["id"], "recording", "Звонок", status="recorded")
    folder = lib.source_dir(src)
    write_wav(os.path.join(folder, "mic.wav"), 1)
    write_wav(os.path.join(folder, "sys.wav"), 1)
    write_wav(os.path.join(folder, "mixed.wav"), 1)
    lib.update_source(src["id"], audio_file="mixed.wav")
    monkeypatch.setattr(app_module, "_transcribe", fake_transcribe({
        "mic.wav": {"text": "вопрос"}, "sys.wav": {"text": "ответ"}}))
    job = client.post(f"/api/sources/{src['id']}/transcribe", json={}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    body = client.get(f"/api/sources/{src['id']}").get_json()
    assert [s["speaker"] for s in body["segments"]] == ["BA", "OTHER"]
    assert body["speakers"] == 2 and body["status"] == "ready"


def test_uploaded_audio_is_not_treated_as_channels(client, app_module, lib, monkeypatch):
    src = lib.create_source(lib.current_project()["id"], "audio", "file")
    assert app_module._recorded_channels(src) is None
