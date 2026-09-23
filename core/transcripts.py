"""Import ready-made transcripts (spec FR-SRC-03 AC2: text sources skip transcription).

Supported: WebVTT (Teams, Zoom, Google Meet), SRT, DOCX (Teams export or any
document), PDF with a text layer (via pypdf), plain text in common layouts, and
this app's own JSON result. Output
has the same shape as a transcription result, so the UI (and later the atom
extraction) treat imported and transcribed sources alike:

    {"text": str, "segments": [{"speaker"?, "start"?, "end"?, "text"}], "diarized": bool,
     "imported": {"format": str, "filename": str}}

Stdlib only, except pypdf for PDF (imported lazily).
"""
import html
import io
import json
import os
import re
import zipfile
from xml.etree import ElementTree

TRANSCRIPT_EXTENSIONS = {".vtt", ".srt", ".txt", ".docx", ".pdf", ".json", ".md"}
MAX_BYTES = 50 * 1024 * 1024
MERGE_GAP_SECONDS = 1.5  # consecutive cues of one speaker closer than this become one turn


class TranscriptError(ValueError):
    pass


def is_transcript_file(filename):
    return os.path.splitext(filename or "")[1].lower() in TRANSCRIPT_EXTENSIONS


# ── helpers ──────────────────────────────────────────────────────────────────

def decode_text(data):
    """UTF-8 (with or without BOM), UTF-16 with BOM, else Windows Cyrillic, else Latin-1."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1251")
        if sum("а" <= c.lower() <= "я" or c in "ёЁ" for c in text) > len(text) * 0.05:
            return text
    except UnicodeDecodeError:
        pass
    return data.decode("latin-1")


_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"


def parse_timestamp(value):
    m = re.fullmatch(_TS, value.strip())
    if not m:
        raise TranscriptError(f"bad timestamp: {value!r}")
    h, mnt, sec, frac = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec) + (int(frac.ljust(3, "0")) / 1000 if frac else 0)


def format_time(seconds):
    seconds = max(0.0, float(seconds))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_SPEAKER_PREFIX = re.compile(r"^\s*([^:\n]{1,60}?)\s*:\s+(.+)$", re.S)
_NOT_A_NAME = re.compile(r"^(https?|note|примечание|внимание|важно)$|\d{2,}", re.I)


_GENERIC_SPEAKER = re.compile(r"^(speaker|спикер|участник|participant)[ _]?\d+$", re.I)


def looks_like_name(label):
    """'Иван Петров', 'Anna', 'SPEAKER_00', 'Спикер 2' yes; 'Второй абзац', 'https' no."""
    label = label.strip()
    words = label.split()
    if not words or len(words) > 5 or _NOT_A_NAME.search(label):
        return _GENERIC_SPEAKER.match(label) is not None
    return _GENERIC_SPEAKER.match(label) is not None or all(w[0].isupper() for w in words)


def split_speaker(text, allowed=None):
    """'Ivan Petrov: hello' → ('Ivan Petrov', 'hello'); leaves ordinary text alone.

    allowed: optional set of labels known to be speakers in this document.
    """
    m = _SPEAKER_PREFIX.match(text)
    if m and looks_like_name(m.group(1)) and (allowed is None or m.group(1).strip() in allowed):
        return m.group(1).strip(), m.group(2).strip()
    return None, text.strip()


def _speaker_labels(lines):
    """Labels used as 'Name: text' in a plain document. A label counts only if the
    document really uses speaker labels: it repeats, or there are 2+ distinct ones."""
    counts = {}
    for line in lines:
        m = _SPEAKER_PREFIX.match(line)
        if m and looks_like_name(m.group(1)):
            counts[m.group(1).strip()] = counts.get(m.group(1).strip(), 0) + 1
    if len(counts) >= 2:
        return set(counts)
    return {label for label, n in counts.items() if n >= 2}


def merge_turns(segments, gap=MERGE_GAP_SECONDS):
    """Join consecutive cues of the same speaker (subtitle files split every sentence)."""
    merged = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if (prev and seg.get("speaker") and prev.get("speaker") == seg.get("speaker")
                and "start" in seg and "end" in prev and seg["start"] - prev["end"] <= gap):
            prev["text"] = f"{prev['text']} {seg['text']}".strip()
            prev["end"] = seg["end"]
        else:
            merged.append(dict(seg))
    return merged


def _result(segments, fmt, filename):
    segments = [s for s in segments if s.get("text", "").strip()]
    if not segments:
        raise TranscriptError("no text found in this file")
    diarized = any(s.get("speaker") for s in segments)
    lines = []
    for s in segments:
        prefix = f"[{s['speaker']}] " if s.get("speaker") else ""
        if "start" in s:
            end = f" - {format_time(s['end'])}" if "end" in s else ""
            prefix += f"[{format_time(s['start'])}{end}] "
        lines.append(prefix + s["text"])
    return {"text": "\n".join(lines), "segments": segments, "diarized": diarized,
            "imported": {"format": fmt, "filename": filename}}


# ── formats ──────────────────────────────────────────────────────────────────

_CUE_TIME = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
_TAGS = re.compile(r"</?[^>]+>")


def _cue_text(raw):
    speaker = None
    m = _VOICE.search(raw)
    if m:                                   # Teams: <v Ivan Petrov>text</v>
        speaker, raw = m.group(1).strip(), m.group(2)
    text = html.unescape(_TAGS.sub("", raw)).replace("\n", " ").strip()
    if speaker is None:                     # Zoom / Meet: "Ivan Petrov: text"
        speaker, text = split_speaker(text)
    return speaker, re.sub(r"\s+", " ", text)


def parse_cues(text):
    """Shared by WebVTT and SRT: blocks with a 'start --> end' line."""
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            m = _CUE_TIME.match(line)
            if m:
                start = parse_timestamp(m.group(1))
                end = parse_timestamp(m.group(6))
                speaker, body = _cue_text("\n".join(lines[i + 1:]))
                seg = {"start": round(start, 3), "end": round(end, 3), "text": body}
                if speaker:
                    seg["speaker"] = speaker
                segments.append(seg)
                break
    return merge_turns(segments)


# "[SPEAKER_00] [00:01.50 - 00:03.20] text" (this app's copy format) or "[00:01 - 00:03] text"
_APP_LINE = re.compile(rf"^(?:\[([^\]]+)\]\s*)?\[({_TS})\s*-\s*({_TS})\]\s*(.*)$")
# "00:12 Ivan: text" / "[00:12] Ivan: text" / "(00:12) text"
_TS_LINE = re.compile(rf"^[\[(]?({_TS})[\])]?\s+(.+)$")
# Teams DOCX / Otter: "Ivan Petrov   0:03" (or "Ivan Petrov  00:00:03") on its own line
_HEADER_LINE = re.compile(rf"^(.{{1,60}}?)\s+({_TS})$")


def parse_plain(text):
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    speakers = _speaker_labels(lines)
    segments = []

    def add(speaker, start, end, body):
        seg = {"text": body.strip()}
        if speaker:
            seg["speaker"] = speaker
        if start is not None:
            seg["start"] = round(start, 3)
        if end is not None:
            seg["end"] = round(end, 3)
        segments.append(seg)

    pending_header = None      # (speaker, start) waiting for its text lines
    buffer = []

    def flush_header():
        nonlocal pending_header, buffer
        if pending_header:
            add(pending_header[0], pending_header[1], None, " ".join(buffer))
        elif buffer:
            add(None, None, None, " ".join(buffer))
        pending_header, buffer = None, []

    for line in lines:
        if not line:
            if not pending_header:
                flush_header()
            continue
        m = _APP_LINE.match(line)
        if m:
            flush_header()
            speaker = m.group(1)
            add(speaker, parse_timestamp(m.group(2)), parse_timestamp(m.group(7)), m.group(12))
            continue
        m = _HEADER_LINE.match(line)
        if m and not re.search(r"[.!?,;]$", m.group(1)) and len(m.group(1).split()) <= 5:
            flush_header()
            pending_header = (m.group(1).strip(), parse_timestamp(m.group(2)))
            continue
        m = _TS_LINE.match(line)
        if m and not pending_header:
            flush_header()
            speaker, body = split_speaker(m.group(6))
            add(speaker, parse_timestamp(m.group(1)), None, body)
            continue
        if not pending_header:
            speaker, body = split_speaker(line, allowed=speakers)
            if speaker:
                flush_header()
                add(speaker, None, None, body)
                continue
        buffer.append(line)
    flush_header()

    # Fill missing end times from the next segment's start, so timestamps read as ranges.
    for cur, nxt in zip(segments, segments[1:]):
        if "start" in cur and "end" not in cur and "start" in nxt:
            cur["end"] = nxt["start"]
    return _merge_untimed(segments)


def _merge_untimed(segments):
    """Consecutive untimed lines of the same speaker ("Name: a", "Name: b") become one turn."""
    out = []
    for seg in segments:
        prev = out[-1] if out else None
        if (prev and "start" not in seg and "start" not in prev
                and seg.get("speaker") and seg.get("speaker") == prev.get("speaker")):
            prev["text"] += " " + seg["text"]
        else:
            out.append(seg)
    return out


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise TranscriptError(f"not a readable .docx file ({e})")
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
            elif node.tag == f"{_W}tab":
                parts.append("  ")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


# "Page 2 of 5", "Страница 2 из 5", "стр. 2", "- 2 -", a bare page number
_PAGE_FURNITURE = re.compile(
    r"^(?:(?:page|p\.|страница|стр\.?)\s*\d+(?:\s*(?:of|из|/)\s*\d+)?|[-–—]?\s*\d{1,4}\s*[-–—]?|\d+\s*/\s*\d+)$",
    re.I)


def pdf_text(data):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise TranscriptError("PDF support is missing: restart the app to let setup install it")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise TranscriptError("this PDF is password-protected; save an unprotected copy and try again")
        pages = [page.extract_text() or "" for page in reader.pages]
    except TranscriptError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        raise TranscriptError(f"not a readable PDF file ({e})")
    lines = [ln for page in pages for ln in (page.split("\n") + [""])
             if not _PAGE_FURNITURE.match(ln.strip())]
    text = "\n".join(lines)
    if not text.strip():
        raise TranscriptError("this PDF has no text layer (probably a scan); OCR isn't supported yet")
    return text


def parse_app_json(text):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TranscriptError(f"not valid JSON ({e})")
    segments = data.get("segments") if isinstance(data, dict) else None
    if isinstance(segments, list) and segments:
        out = []
        for s in segments:
            seg = {"text": str(s.get("text", "")).strip()}
            for key in ("speaker", "start", "end"):
                if s.get(key) is not None:
                    seg[key] = s[key]
            out.append(seg)
        return out
    if isinstance(data, dict) and data.get("text"):
        return parse_plain(str(data["text"]))
    raise TranscriptError("JSON has no 'segments' or 'text'")


# ── entry point ──────────────────────────────────────────────────────────────

def parse_transcript(filename, data):
    if len(data) > MAX_BYTES:
        raise TranscriptError(f"transcript is larger than {MAX_BYTES // (1024 * 1024)} MB")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".docx":
        return _result(parse_plain(docx_text(data)), "docx", filename)
    if ext == ".pdf":
        return _result(parse_plain(pdf_text(data)), "pdf", filename)
    text = decode_text(data)
    if ext == ".json":
        return _result(parse_app_json(text), "json", filename)
    if ext == ".vtt" or text.lstrip().startswith("WEBVTT"):
        return _result(parse_cues(text), "vtt", filename)
    if ext == ".srt" or re.search(r"^\d+\s*\n\s*\d{1,2}:\d{2}:\d{2},\d{3}\s*-->", text, re.M):
        return _result(parse_cues(text), "srt", filename)
    return _result(parse_plain(text), "text", filename)
