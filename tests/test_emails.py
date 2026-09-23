import io
import sqlite3
import sys
import types

import pytest

from core import emails
from core.emails import html_to_text, parse_eml, parse_email_file
from core.store import Store
from core.transcripts import TranscriptError

EML = """From: =?utf-8?b?0JjQstCw0L0g0J/QtdGC0YDQvtCy?= <ivan@client.ru>
To: Анна <anna@us.example>, Олег <oleg@us.example>
Subject: =?utf-8?b?0KLRgNC10LHQvtCy0LDQvdC40Y8g0Log0LrQsNGA0YLQvtGH0LrQtQ==?=
Date: Thu, 12 Mar 2026 10:15:00 +0300
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 8bit

Коллеги, добрый день.

Карточка клиента должна открываться до ответа
оператора, не дольше двух секунд.

Спасибо,
Иван
""".encode()

HTML_EML = b"""From: Anna <anna@x.ru>
Subject: HTML only
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

<html><head><style>p{color:red}</style></head><body><p>First &amp; important</p><div>Second<br>line</div></body></html>
"""


def test_eml_headers_body_and_paragraphs():
    r = parse_eml("letter.eml", EML)
    assert r["email"] == {"subject": "Требования к карточке", "from": "Иван Петров",
                          "to": "Анна, Олег", "date": "Thu, 12 Mar 2026 10:15:00 +0300"}
    assert r["title"] == "Требования к карточке"
    assert [s["text"] for s in r["segments"]] == [
        "Коллеги, добрый день.", "Карточка клиента должна открываться до ответа оператора, не дольше двух секунд.",
        "Спасибо, Иван"]
    assert all(s["speaker"] == "Иван Петров" for s in r["segments"])
    assert r["text"].startswith("Subject: Требования к карточке\nFrom: Иван Петров · To: Анна, Олег")


def test_html_only_email_becomes_readable_text():
    r = parse_eml("h.eml", HTML_EML)
    assert [s["text"] for s in r["segments"]] == ["First & important", "Second line"]
    assert "color" not in r["text"]


def test_html_to_text_skips_scripts():
    assert html_to_text("<script>alert(1)</script><p>ok</p>").strip() == "ok"


class FakeOle:
    def __init__(self, streams):
        self.streams = streams

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        return io.BytesIO(self.streams[name])

    def close(self):
        pass


def test_msg_reads_unicode_and_8bit_properties(monkeypatch):
    streams = {
        "__substg1.0_0037001F": "Сроки по SLA".encode("utf-16-le"),
        "__substg1.0_0C1A001E": "Олег".encode("cp1251"),                 # old ANSI Cyrillic
        "__substg1.0_0E04001F": "Анна".encode("utf-16-le"),
        "__substg1.0_1000001F": "Пять секунд допустимо.\r\n\r\nОлег".encode("utf-16-le") + b"\x00\x00",
    }
    fake = types.SimpleNamespace(isOleFile=lambda f: True, OleFileIO=lambda f: FakeOle(streams))
    monkeypatch.setitem(sys.modules, "olefile", fake)
    r = emails.parse_msg("sla.msg", b"\xd0\xcf\x11\xe0")
    assert r["email"]["subject"] == "Сроки по SLA" and r["email"]["from"] == "Олег" and r["email"]["to"] == "Анна"
    assert [s["text"] for s in r["segments"]] == ["Пять секунд допустимо.", "Олег"]


def test_msg_html_body_fallback(monkeypatch):
    streams = {"__substg1.0_0037001F": "S".encode("utf-16-le"),
               "__substg1.0_10130102": "<p>Только HTML</p>".encode()}
    monkeypatch.setitem(sys.modules, "olefile",
                        types.SimpleNamespace(isOleFile=lambda f: True, OleFileIO=lambda f: FakeOle(streams)))
    assert emails.parse_msg("x.msg", b"x")["segments"][0]["text"] == "Только HTML"


def test_not_an_msg_file():
    with pytest.raises(TranscriptError, match="Outlook"):
        parse_email_file("fake.msg", b"plain text, not OLE")


def test_empty_email_is_rejected():
    with pytest.raises(TranscriptError):
        parse_eml("e.eml", b"Subject: x\nContent-Type: text/plain\n\n   \n")


def test_old_library_is_migrated(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    db = sqlite3.connect(root / "workbench.db")           # a v1 database without meta_json
    db.executescript("""
      CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, local_only INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, created_by TEXT NOT NULL,
        updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
      CREATE TABLE sources (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
        original_filename TEXT, status TEXT NOT NULL, error TEXT, duration REAL, speakers INTEGER, asr_model TEXT,
        diarized INTEGER NOT NULL DEFAULT 0, import_format TEXT, audio_file TEXT, text TEXT, words_json TEXT,
        deleted_at REAL, created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
      INSERT INTO projects VALUES ('p1', 'Old', 0, 0, 1, 'ba', 1, 'ba');
      INSERT INTO sources (id, project_id, kind, title, status, created_at, created_by, updated_at, updated_by)
        VALUES ('s1', 'p1', 'audio', 'Old call', 'ready', 1, 'ba', 1, 'ba');""")
    db.commit()
    db.close()
    store = Store(root=str(root), user="ba")
    assert store.get_source("s1")["meta"] is None and store.get_source("s1")["title"] == "Old call"
    s = store.create_source("p1", "email", "New mail")
    store.save_transcript(s["id"], parse_eml("m.eml", EML))
    assert store.get_source(s["id"])["meta"]["email"]["from"] == "Иван Петров"
