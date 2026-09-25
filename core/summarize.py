"""Summarise a transcript with Claude (Anthropic API) or a local model (Ollama).

First AI stage of the app (spec increment 2 foundations: FR-SET-02 model per
stage, FR-SET-03 keys, D-02 transcript text may go to the cloud, local option).
The summary cites speakers and timestamps so every point can be traced back to
what was said (spec G2).
"""
import json
import re
import urllib.error
import urllib.request

import anthropic

from core.llm import LLMError, claude_errors, claude_params

SYSTEM_PROMPT = """You summarise sources for a business analyst who gathers requirements from clients: call and meeting transcripts, emails, and documents such as earlier specifications. The first line tells you which kind it is.

Write the whole summary, including the section headings, in the same language as the transcript (for a Russian transcript, translate the headings below into Russian). Use Markdown with these sections, leaving out any section that would be empty:

## Summary
A short paragraph: who met, what it was about, the outcome.

## Key points
The substance of the discussion.

## Requirements mentioned
What the client needs the system to do, and qualities such as speed, security or availability. Keep numbers and limits exactly as stated.

## Decisions

## Open questions
Anything left unresolved, contradictory, or "to discuss later".

## Action items
Who does what, and by when if it was said.

Refer to the source of each point with the speaker and timestamp in square brackets, e.g. [Anna, 12:30], when the transcript has them; for an email, name the sender when it matters. Only state what the transcript supports; if something is unclear, say so rather than guessing."""

# The same user-facing error for summaries and extraction.
SummaryError = LLMError


def _user_content(transcript, title=None):
    header = f"Transcript of: {title}\n\n" if title else "Transcript:\n\n"
    return header + transcript.strip()


# ── Claude ───────────────────────────────────────────────────────────────────

def summarize_with_claude(transcript, model, api_key, on_delta, title=None, client=None):
    if not api_key:
        raise SummaryError("Add your Anthropic API key in Settings to create summaries with Claude.")
    client = client or anthropic.Anthropic(api_key=api_key)
    params = claude_params(model, SYSTEM_PROMPT, [{"role": "user", "content": _user_content(transcript, title)}])
    with claude_errors(model):
        with client.beta.messages.stream(**params) as stream:
            for text in stream.text_stream:
                on_delta(text)
            message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise SummaryError("Claude declined to summarise this transcript.")
    text = "".join(b.text for b in message.content if b.type == "text")
    if message.stop_reason == "max_tokens":
        text += "\n\n*(The summary was cut off because it reached the length limit.)*"
    return text


# ── Ollama (local) ───────────────────────────────────────────────────────────

class _ThinkFilter:
    """Drops <think>…</think> sections that some local reasoning models stream inline."""

    def __init__(self):
        self.inside = False
        self.pending = ""

    def feed(self, chunk):
        self.pending += chunk
        out = []
        while self.pending:
            tag = "</think>" if self.inside else "<think>"
            idx = self.pending.find(tag)
            if idx == -1:
                # Keep a possible partial tag at the end for the next chunk.
                keep = max((i for i in range(1, len(tag)) if self.pending.endswith(tag[:i])), default=0)
                if not self.inside:
                    out.append(self.pending[:len(self.pending) - keep])
                self.pending = self.pending[len(self.pending) - keep:] if keep else ""
                break
            if not self.inside:
                out.append(self.pending[:idx])
            self.pending = self.pending[idx + len(tag):]
            self.inside = not self.inside
        return "".join(out)


def summarize_with_ollama(transcript, model, on_delta, url, title=None, opener=urllib.request.urlopen):
    body = json.dumps({
        "model": model,
        "stream": True,
        "think": False,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _user_content(transcript, title)}],
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    parts, think = [], _ThinkFilter()
    try:
        with opener(req, timeout=600) as resp:
            for line in resp:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("error"):
                    raise SummaryError(f"Local model error: {event['error']}")
                piece = think.feed(event.get("message", {}).get("content", ""))
                if piece:
                    parts.append(piece)
                    on_delta(piece)
                if event.get("done"):
                    break
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 404 or "not found" in detail.lower():
            raise SummaryError(f"The local model {model} isn't installed. In a terminal run: ollama pull {model}")
        raise SummaryError(f"Ollama error ({e.code}): {detail[:200]}")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raise SummaryError("Ollama isn't running. Start the Ollama app, or choose Claude in Settings.")
    return re.sub(r"^\s+", "", "".join(parts))


# ── entry point ──────────────────────────────────────────────────────────────

def summarize(transcript, settings, api_key, ollama_url, on_delta, title=None):
    if not transcript or not transcript.strip():
        raise SummaryError("There is no transcript text to summarise.")
    if settings["llm_provider"] == "ollama":
        return summarize_with_ollama(transcript, settings["ollama_model"], on_delta, ollama_url, title)
    return summarize_with_claude(transcript, settings["claude_model"], api_key, on_delta, title)
