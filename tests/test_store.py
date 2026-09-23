import os
import threading

import pytest

from core.store import Store, StoreError


@pytest.fixture()
def store(tmp_path):
    t = [1000.0]

    def clock():
        t[0] += 1
        return t[0]
    return Store(root=str(tmp_path / "lib"), user="ba", clock=clock)


def test_projects_create_rename_archive(store):
    p = store.create_project("CRM для контакт-центра")
    assert p["name"] == "CRM для контакт-центра" and p["created_by"] == "ba" and len(p["id"]) == 36
    with pytest.raises(StoreError, match="already exists"):
        store.create_project("crm для КОНТАКТ-центра")          # case-insensitive
    with pytest.raises(StoreError):
        store.create_project("  ")
    q = store.update_project(p["id"], name="CRM", local_only=True)
    assert q["name"] == "CRM" and q["local_only"] is True and q["updated_at"] > p["updated_at"]
    store.update_project(p["id"], archived=True)
    assert store.list_projects() == []
    assert [x["id"] for x in store.list_projects(include_archived=True)] == [p["id"]]
    with pytest.raises(StoreError):
        store.update_project(p["id"], id="hack")


def test_default_project_created_once(store):
    a = store.ensure_default_project()
    b = store.ensure_default_project()
    assert a["id"] == b["id"] and a["name"] == "My project"


def test_current_project(store):
    a, b = store.create_project("A"), store.create_project("B")
    assert store.current_project()["id"] == a["id"]            # first active project by default
    store.set_current_project(b["id"])
    assert store.current_project()["id"] == b["id"]
    store.update_project(b["id"], archived=True)
    assert store.current_project()["id"] == a["id"]            # archived falls back
    with pytest.raises(StoreError):
        store.set_current_project("nope")


def test_source_lifecycle_and_transcript(store):
    p = store.create_project("P")
    s = store.create_source(p["id"], "audio", "Созвон 12.03", original_filename="call.webm", asr_model="v3_e2e_rnnt")
    assert s["status"] == "processing" and os.path.isdir(store.source_dir(s))
    result = {"text": "…", "diarized": True, "segments": [
        {"speaker": "SPEAKER_00", "start": 0.5, "end": 4.0, "text": "Добрый день"},
        {"speaker": "SPEAKER_01", "start": 4.2, "end": 9.75, "text": "Здравствуйте"},
        {"speaker": "SPEAKER_00", "start": 10.0, "end": 12.0, "text": "Начнём"}]}
    s = store.save_transcript(s["id"], result)
    assert (s["status"], s["duration"], s["speakers"], s["diarized"]) == ("ready", 12.0, 2, True)
    segs, names = store.transcript(s["id"])
    assert [x["text"] for x in segs] == ["Добрый день", "Здравствуйте", "Начнём"] and names == {}

    store.rename_speaker(s["id"], "SPEAKER_00", "Иван Петров")
    segs, names = store.transcript(s["id"])
    assert names == {"SPEAKER_00": "Иван Петров"}
    assert [x["speaker_name"] for x in segs] == ["Иван Петров", "SPEAKER_01", "Иван Петров"]
    assert store.transcript_text(s["id"]).splitlines()[0] == "[Иван Петров] [00:00 - 00:04] Добрый день"
    store.rename_speaker(s["id"], "SPEAKER_00", "")            # empty resets to the label
    assert store.transcript(s["id"])[1] == {}
    with pytest.raises(StoreError):
        store.rename_speaker(s["id"], "SPEAKER_09", "X")


def test_import_without_timestamps_and_plain_text(store):
    p = store.create_project("P")
    s = store.create_source(p["id"], "transcript", "notes.txt")
    s = store.save_transcript(s["id"], {"text": "just text", "segments": [], "imported": {"format": "text"}})
    assert s["import_format"] == "text" and s["duration"] is None
    assert store.transcript(s["id"])[0][0]["text"] == "just text"


def test_list_newest_first_with_summary_flag_and_soft_delete(store):
    p = store.create_project("P")
    a = store.create_source(p["id"], "audio", "first")
    b = store.create_source(p["id"], "recording", "second", status="recorded")
    store.add_summary(a["id"], "claude", "claude-opus-5", "## Итоги")
    listed = store.list_sources(p["id"])
    assert [x["title"] for x in listed] == ["second", "first"]
    assert [x["has_summary"] for x in listed] == [False, True]
    assert store.latest_summary(a["id"])["text"] == "## Итоги"

    store.delete_source(b["id"])
    assert [x["id"] for x in store.list_sources(p["id"])] == [a["id"]]
    with pytest.raises(StoreError):
        store.get_source(b["id"])
    assert os.path.isdir(store.source_dir(b)), "files are kept on soft delete"
    store.restore_source(b["id"])
    assert len(store.list_sources(p["id"])) == 2


def test_validation(store):
    p = store.create_project("P")
    with pytest.raises(StoreError):
        store.create_source(p["id"], "video", "x")
    with pytest.raises(StoreError):
        store.create_source("missing", "audio", "x")
    s = store.create_source(p["id"], "audio", "x")
    with pytest.raises(StoreError):
        store.update_source(s["id"], status="done")
    with pytest.raises(StoreError):
        store.update_source(s["id"], title=" ")
    with pytest.raises(StoreError):
        store.update_source(s["id"], project_id="other")


def test_audit_trail_records_who_what_when(store):
    p = store.create_project("P")
    store.update_project(p["id"], name="P2")
    s = store.create_source(p["id"], "audio", "call")
    store.update_source(s["id"], title="Call with client")
    store.delete_source(s["id"])
    entries = store.audit()
    assert [(e["entity"], e["action"]) for e in entries] == [
        ("source", "delete"), ("source", "update"), ("source", "create"), ("project", "update"), ("project", "create")]
    rename = store.audit(entity="project", entity_id=p["id"])[0]
    assert rename["before"]["name"] == "P" and rename["after"]["name"] == "P2" and rename["by"] == "ba"


def test_persists_across_instances(tmp_path):
    a = Store(root=str(tmp_path / "lib"), user="ba")
    p = a.create_project("Keep me")
    b = Store(root=str(tmp_path / "lib"), user="ba")
    assert b.get_project(p["id"])["name"] == "Keep me"


def test_concurrent_writes(store):
    p = store.create_project("P")
    errors = []

    def worker(n):
        try:
            for i in range(10):
                store.create_source(p["id"], "audio", f"{n}-{i}")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(store.list_sources(p["id"])) == 60


def test_attach_file(store, tmp_path):
    p = store.create_project("P")
    s = store.create_source(p["id"], "audio", "x")
    f = tmp_path / "in.wav"
    f.write_bytes(b"RIFF")
    dest = store.attach_file(s, str(f), "original.wav")
    assert os.path.dirname(dest) == store.source_dir(s) and f.exists()
    dest2 = store.attach_file(s, str(f), "moved.wav", move=True)
    assert os.path.exists(dest2) and not f.exists()
