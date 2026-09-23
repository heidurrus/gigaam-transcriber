import io
import os
import json
import zipfile

import pytest

from core.transcripts import (MAX_BYTES, TranscriptError, decode_text, is_transcript_file, parse_timestamp,
                              parse_transcript)

TEAMS_VTT = """WEBVTT

0f1a2b3c-1/12-0
00:00:03.140 --> 00:00:05.520
<v Иван Петров>Добрый день, коллеги.</v>

0f1a2b3c-1/13-0
00:00:05.900 --> 00:00:08.000
<v Иван Петров>Начнём с карточки клиента.</v>

0f1a2b3c-1/14-0
00:00:09.000 --> 00:00:12.250
<v Anna Smirnova>Оператор должен видеть историю &amp; статус.</v>
"""

ZOOM_VTT = """WEBVTT

1
00:00:01.500 --> 00:00:04.200
Ivan Petrov: Hello everyone

2
00:00:04.900 --> 00:00:07.000
Anna Smirnova: Hi Ivan
"""

SRT = """1
00:00:01,000 --> 00:00:03,500
Первая строка
с переносом

2
00:01:02,250 --> 00:01:05,000
Вторая
"""

TEAMS_DOCX_PARAGRAPHS = [
    "Созвон с заказчиком",
    "12 марта 2026 г., 10:00",
    "",
    "Иван Петров   0:03",
    "Смотрите, основная боль сейчас в том, что оператор не понимает, кто звонит.",
    "",
    "Анна Смирнова   0:41",
    "Да, карточка должна уже висеть до поднятия трубки.",
    "И это критично.",
]


def make_docx(paragraphs):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_teams_vtt_keeps_names_and_merges_turns():
    r = parse_transcript("meeting.vtt", TEAMS_VTT.encode())
    assert r["diarized"] and r["imported"]["format"] == "vtt"
    assert r["segments"] == [
        {"speaker": "Иван Петров", "start": 3.14, "end": 8.0,
         "text": "Добрый день, коллеги. Начнём с карточки клиента."},
        {"speaker": "Anna Smirnova", "start": 9.0, "end": 12.25,
         "text": "Оператор должен видеть историю & статус."},
    ]
    assert r["text"].splitlines()[0] == "[Иван Петров] [00:03 - 00:08] Добрый день, коллеги. Начнём с карточки клиента."


def test_zoom_vtt_speaker_prefix():
    segs = parse_transcript("zoom.vtt", ZOOM_VTT.encode())["segments"]
    assert [(s["speaker"], s["text"]) for s in segs] == [("Ivan Petrov", "Hello everyone"), ("Anna Smirnova", "Hi Ivan")]


def test_srt_multiline_cues_without_speakers():
    r = parse_transcript("subs.srt", SRT.encode())
    assert not r["diarized"]
    assert r["segments"] == [
        {"start": 1.0, "end": 3.5, "text": "Первая строка с переносом"},
        {"start": 62.25, "end": 65.0, "text": "Вторая"},
    ]


def test_teams_docx_headers():
    r = parse_transcript("Транскрипт.docx", make_docx(TEAMS_DOCX_PARAGRAPHS))
    turns = [s for s in r["segments"] if s.get("speaker")]
    assert turns == [
        {"speaker": "Иван Петров", "start": 3.0, "end": 41.0,
         "text": "Смотрите, основная боль сейчас в том, что оператор не понимает, кто звонит."},
        {"speaker": "Анна Смирнова", "start": 41.0,
         "text": "Да, карточка должна уже висеть до поднятия трубки. И это критично."},
    ]
    assert r["segments"][0]["text"].startswith("Созвон с заказчиком")  # title kept as untimed text


def test_app_copy_format_roundtrip():
    text = ("[SPEAKER_00] [00:01.50 - 00:03.20] Привет\n"
            "[SPEAKER_01] [00:03.50 - 00:05.00] Здравствуйте\n")
    segs = parse_transcript("copy.txt", text.encode())["segments"]
    assert segs == [{"speaker": "SPEAKER_00", "start": 1.5, "end": 3.2, "text": "Привет"},
                    {"speaker": "SPEAKER_01", "start": 3.5, "end": 5.0, "text": "Здравствуйте"}]


def test_plain_speaker_lines_and_timestamped_lines():
    text = "Иван: первое\nИван: второе\nАнна: ответ\n\n00:12 Иван: с таймкодом\n[00:20] Анна: ещё\n"
    segs = parse_transcript("notes.txt", text.encode())["segments"]
    assert segs[0] == {"speaker": "Иван", "text": "первое второе"}
    assert segs[1] == {"speaker": "Анна", "text": "ответ"}
    assert segs[2] == {"speaker": "Иван", "start": 12.0, "end": 20.0, "text": "с таймкодом"}
    assert segs[3] == {"speaker": "Анна", "start": 20.0, "text": "ещё"}


def test_plain_prose_is_kept_as_paragraphs():
    text = "Требования заказчика.\nСистема должна работать быстро.\n\nВторой абзац: без спикера, но с двоеточием в тексте длинной фразы.\n"
    r = parse_transcript("email.txt", text.encode())
    assert not r["diarized"]
    assert [s["text"] for s in r["segments"]][0] == "Требования заказчика. Система должна работать быстро."


def test_urls_and_times_are_not_speakers():
    segs = parse_transcript("x.txt", "https://example.com: link\nNote: remember\n".encode())["segments"]
    assert not any(s.get("speaker") for s in segs)


def test_app_json_result():
    data = {"text": "x", "segments": [{"speaker": "SPEAKER_00", "start": 1, "end": 2, "text": "Привет"}], "diarized": True}
    r = parse_transcript("result.json", json.dumps(data, ensure_ascii=False).encode())
    assert r["segments"] == [{"speaker": "SPEAKER_00", "start": 1, "end": 2, "text": "Привет"}]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1251"])
def test_encodings(encoding):
    text = "Иван: Добрый день, это проверка кодировки."
    assert decode_text(text.encode(encoding)) == text


def test_errors():
    with pytest.raises(TranscriptError):
        parse_transcript("empty.txt", b"   \n\n")
    with pytest.raises(TranscriptError):
        parse_transcript("broken.docx", b"not a zip")
    with pytest.raises(TranscriptError):
        parse_transcript("big.txt", b"a" * (MAX_BYTES + 1))


def test_timestamps():
    assert parse_timestamp("1:02:03.5") == 3723.5
    assert parse_timestamp("00:00:03,140") == 3.14
    assert parse_timestamp("0:41") == 41


def test_extension_detection():
    assert is_transcript_file("Meeting Transcript.VTT") and is_transcript_file("a.docx")
    assert not is_transcript_file("call.webm") and not is_transcript_file("noext")


# ── PDF ──────────────────────────────────────────────────────────────────────
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def test_pdf_teams_style_russian():
    r = parse_transcript("Транскрипт.pdf", fixture("teams_ru.pdf"))
    assert r["imported"]["format"] == "pdf"
    turns = [s for s in r["segments"] if s.get("speaker")]
    assert turns == [
        {"speaker": "Иван Петров", "start": 3.0, "end": 41.0,
         "text": "Смотрите, основная боль сейчас в том, что оператор не понимает, кто звонит."},
        {"speaker": "Анна Смирнова", "start": 41.0, "text": "Да, карточка должна уже висеть до поднятия трубки."},
    ]


def test_pdf_page_footers_are_dropped_and_wrapped_lines_joined():
    r = parse_transcript("export.pdf", fixture("two_pages_footer.pdf"))
    assert [s.get("speaker") for s in r["segments"]] == ["Ivan Petrov", "Anna Smirnova"]
    assert r["segments"][0]["text"] == "The caller card must open before the operator answers the call."
    assert "Страница" not in r["text"]


def _pdf_bytes(writer):
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_scanned_pdf_without_text_layer_is_explained():
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    with pytest.raises(TranscriptError, match="no text layer"):
        parse_transcript("scan.pdf", _pdf_bytes(w))


def test_password_protected_pdf_is_explained():
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(fixture("teams_ru.pdf"))))
    w.encrypt("secret")
    with pytest.raises(TranscriptError, match="password"):
        parse_transcript("locked.pdf", _pdf_bytes(w))


def test_broken_pdf_is_explained():
    with pytest.raises(TranscriptError, match="PDF"):
        parse_transcript("broken.pdf", b"%PDF-1.4 garbage")
