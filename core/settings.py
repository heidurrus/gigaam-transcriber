"""User settings: secrets in a per-user .env, preferences in settings.json.

Both live in the app data folder, never next to the app code: inside an
installed app that folder is the signed macOS bundle or Program Files, where
writing would break the signature or be lost on update (spec FR-SET-03,
NFR-SEC-01/02). A .env next to the code (how 1.0 and source checkouts stored
it) is still read, so existing tokens keep working.
"""
import json
import os
import sys

from dotenv import load_dotenv

from core.paths import app_data_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_ENV_FILE = os.path.join(ROOT, ".env")

SECRET_KEYS = {"HF_TOKEN", "ANTHROPIC_API_KEY"}
DEFAULTS = {
    "llm_provider": "claude",          # "claude" | "ollama"
    "claude_model": "claude-opus-5",
    "ollama_model": "qwen3:8b",
}
CLAUDE_MODELS = [
    ("claude-opus-5", "Claude Opus 5 (best quality)"),
    ("claude-sonnet-5", "Claude Sonnet 5 (faster, cheaper)"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (fastest, cheapest)"),
]
PROVIDERS = {"claude", "ollama"}


def env_file():
    return os.path.join(app_data_dir(), ".env")


def settings_file():
    return os.path.join(app_data_dir(), "settings.json")


def load_env():
    """Legacy .env first, then the app-data one, which wins."""
    if os.path.exists(LEGACY_ENV_FILE):
        load_dotenv(LEGACY_ENV_FILE)
    if os.path.exists(env_file()):
        load_dotenv(env_file(), override=True)


def _write_private(path, text):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def set_secret(key, value):
    """Write or remove one key in the app-data .env and update this process."""
    if key not in SECRET_KEYS:
        raise ValueError(f"unknown secret {key}")
    value = (value or "").strip()
    lines, found = [], False
    if os.path.exists(env_file()):
        with open(env_file(), encoding="utf-8") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    found = True
                    if value:
                        lines.append(f"{key}={value}\n")
                else:
                    lines.append(line)
    if value and not found:
        lines.append(f"{key}={value}\n")
    _write_private(env_file(), "".join(lines))
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)


def secret(key):
    return os.getenv(key) or None


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(settings_file(), encoding="utf-8") as f:
            stored = json.load(f)
        data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save_settings(updates):
    """Validate and persist preference changes; returns the full settings."""
    data = load_settings()
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key}")
        value = str(value).strip()
        if key == "llm_provider" and value not in PROVIDERS:
            raise ValueError(f"llm_provider must be one of {sorted(PROVIDERS)}")
        if key == "claude_model" and value not in dict(CLAUDE_MODELS):
            raise ValueError(f"unsupported Claude model {value}")
        if key == "ollama_model" and not value:
            raise ValueError("ollama_model must not be empty")
        data[key] = value
    tmp = settings_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, settings_file())
    return data
