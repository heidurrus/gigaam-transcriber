"""Shared LLM plumbing for summaries and requirement extraction.

Claude goes through the official anthropic SDK (streaming, server-side refusal
fallback on Claude Opus 5, prompt caching, typed errors → clear messages);
local models through Ollama's HTTP API. Spec FR-SET-02, D-02.
"""
import json
import re
import urllib.error
import urllib.request
from contextlib import contextmanager

import anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_DEFAULT_FALLBACKS = {"claude-opus-5"}
CLAUDE_MAX_TOKENS = 32000


class LLMError(Exception):
    """A user-facing problem (bad key, no internet, model missing…)."""


def claude_params(model, system, messages, max_tokens=CLAUDE_MAX_TOKENS, **extra):
    params = dict(model=model, max_tokens=max_tokens, system=system, messages=messages,
                  # Caches the prompt prefix, so re-running on the same source is cheap.
                  cache_control={"type": "ephemeral"}, **extra)
    if model in MODELS_WITH_DEFAULT_FALLBACKS:
        # If a safety classifier declines, the API re-runs the request on Anthropic's
        # recommended fallback model instead of returning a refusal.
        params.update(betas=[FALLBACK_BETA], fallbacks="default")
    return params


@contextmanager
def claude_errors(model):
    """Translate SDK errors into messages a BA can act on."""
    try:
        yield
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected the API key. Check it in Settings.")
    except anthropic.PermissionDeniedError:
        raise LLMError(f"This API key isn't allowed to use {model}. Check your Anthropic account or pick another model in Settings.")
    except anthropic.NotFoundError:
        raise LLMError(f"The model {model} isn't available to this API key. Pick another model in Settings.")
    except anthropic.RequestTooLargeError:
        raise LLMError("This text is too large to send in one request.")
    except anthropic.RateLimitError as e:
        wait = e.response.headers.get("retry-after") if e.response is not None else None
        raise LLMError("Anthropic rate limit reached. " + (f"Try again in {wait} s." if wait else "Try again shortly."))
    except anthropic.OverloadedError:
        raise LLMError("Anthropic is overloaded right now. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}")
    except (anthropic.APIConnectionError, anthropic.APITimeoutError):
        raise LLMError("Could not reach Anthropic. Check your internet connection.")


def model_name(prefs):
    return prefs["ollama_model"] if prefs["llm_provider"] == "ollama" else prefs["claude_model"]


# ── structured JSON ──────────────────────────────────────────────────────────

def _claude_json(system, user, schema, model, api_key, client=None, max_tokens=CLAUDE_MAX_TOKENS):
    if not api_key:
        raise LLMError("Add your Anthropic API key in Settings, or choose a local model.")
    client = client or anthropic.Anthropic(api_key=api_key)
    params = claude_params(model, system, [{"role": "user", "content": user}], max_tokens=max_tokens,
                           output_config={"format": {"type": "json_schema", "schema": schema}})
    with claude_errors(model):
        # Streaming: extraction output can be long, and streaming avoids request timeouts.
        with client.beta.messages.stream(**params) as stream:
            message = stream.get_final_message()
    if message.stop_reason == "refusal":
        raise LLMError("Claude declined to process this text.")
    if message.stop_reason == "max_tokens":
        raise LLMError("The answer was cut off at the length limit; try a shorter source.")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise LLMError("Claude returned malformed JSON.")


def _ollama_json(system, user, schema, model, url, opener=urllib.request.urlopen):
    body = json.dumps({
        "model": model, "stream": False, "think": False, "format": schema,
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with opener(req, timeout=900) as resp:
            reply = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 404 or "not found" in detail.lower():
            raise LLMError(f"The local model {model} isn't installed. In a terminal run: ollama pull {model}")
        raise LLMError(f"Ollama error ({e.code}): {detail[:200]}")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raise LLMError("Ollama isn't running. Start the Ollama app, or choose Claude in Settings.")
    content = re.sub(r"<think>.*?</think>", "", (reply.get("message") or {}).get("content", ""), flags=re.S)
    try:
        return json.loads(content)
    except ValueError:
        raise LLMError("The local model returned malformed JSON; try again or use a larger model.")


def complete_json(system, user, schema, prefs, api_key, ollama_url, claude_client=None, opener=None):
    """One structured call with the provider chosen in Settings; returns the parsed JSON."""
    if prefs["llm_provider"] == "ollama":
        kwargs = {"opener": opener} if opener else {}
        return _ollama_json(system, user, schema, prefs["ollama_model"], ollama_url, **kwargs)
    return _claude_json(system, user, schema, prefs["claude_model"], api_key, client=claude_client)
