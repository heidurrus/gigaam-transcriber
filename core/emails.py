"""Read emails as sources (spec FR-SRC-03: "an email").

.eml uses the standard library; Outlook .msg is an OLE compound file read with
olefile (pure Python) without Outlook. The body becomes paragraphs attributed
to the sender, so summaries can say who asked for what.
"""
import email
import email.policy
import email.utils
import html
import io
import re
from html.parser import HTMLParser

from core.transcripts import TranscriptError

EMAIL_EXTENSIONS = {".eml", ".msg"}


class _TextFromHTML(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup):
    p = _TextFromHTML()
    p.feed(markup)
    return html.unescape("".join(p.parts))


def _paragraphs(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    paras = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if lines:
            paras.append(" ".join(lines))
    return paras


def _result(subject, sender, to, date, body, fmt, filename):
    paras = _paragraphs(body)
    if not paras:
        raise TranscriptError("this email has no text")
    who = sender or None
    segments = [{"speaker": who, "text": p} if who else {"text": p} for p in paras]
    header = " · ".join(x for x in (f"From: {sender}" if sender else "", f"To: {to}" if to else "",
                                    f"Date: {date}" if date else "") if x)
    return {
        "text": (f"Subject: {subject}\n{header}\n\n" if subject or header else "") + "\n\n".join(paras),
        "segments": segments,
        "diarized": bool(who),
        "imported": {"format": fmt, "filename": filename},
        "email": {"subject": subject, "from": sender, "to": to, "date": date},
        "title": subject or None,
    }


def _name(addr_header):
    name, addr = email.utils.parseaddr(addr_header or "")
    return name or addr or ""


def parse_eml(filename, data):
    try:
        msg = email.message_from_bytes(data, policy=email.policy.default)
    except Exception as e:
        raise TranscriptError(f"not a readable email ({e})")
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise TranscriptError("this email has no text body")
    body = part.get_content()
    if part.get_content_type() == "text/html":
        body = html_to_text(body)
    # One To: header can hold several addresses; parseaddr would give up on the comma.
    to = ", ".join(name or addr for name, addr in email.utils.getaddresses(
        [str(h) for h in (msg.get_all("to") or [])]) if name or addr)
    return _result(str(msg.get("subject") or "").strip(), _name(msg.get("from")), to,
                   str(msg.get("date") or "").strip(), body, "eml", filename)


def _msg_string(ole, prop):
    """Read a MAPI string property: Unicode (001F) or 8-bit (001E) stream."""
    for suffix, enc in (("001F", "utf-16-le"), ("001E", None)):
        name = f"__substg1.0_{prop}{suffix}"
        if ole.exists(name):
            raw = ole.openstream(name).read()
            if enc:
                return raw.decode(enc, errors="replace").rstrip("\x00")
            for cp in ("utf-8", "cp1251", "cp1252"):
                try:
                    return raw.decode(cp).rstrip("\x00")
                except UnicodeDecodeError:
                    continue
    return ""


def parse_msg(filename, data):
    try:
        import olefile
    except ImportError:
        raise TranscriptError("Outlook .msg support is missing: restart the app to let setup install it")
    if not olefile.isOleFile(io.BytesIO(data)):
        raise TranscriptError("not an Outlook .msg file")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        subject = _msg_string(ole, "0037")
        sender = _msg_string(ole, "0C1A") or _msg_string(ole, "0065")
        to = _msg_string(ole, "0E04")
        body = _msg_string(ole, "1000")
        if not body.strip() and ole.exists("__substg1.0_10130102"):   # HTML body as bytes
            body = html_to_text(ole.openstream("__substg1.0_10130102").read().decode("utf-8", errors="replace"))
    finally:
        ole.close()
    return _result(subject.strip(), sender.strip(), to.strip(), "", body, "msg", filename)


def parse_email_file(filename, data):
    return parse_msg(filename, data) if filename.lower().endswith(".msg") else parse_eml(filename, data)
