"""What the app needs installed, how to check it, and how to install it.

Spec FR-PLAT-04 (first-run setup) and FR-PLAT-05 (check on every start). Every
check is cheap and idempotent, so the same plan serves both: on a healthy
machine all checks pass in well under a second and setup is skipped.

Stdlib only: this runs before torch / gigaam exist.
"""
import importlib.metadata as md
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.ffmpeg import find_ffmpeg
from core.hardware import torch_variant
from core.paths import app_data_dir, models_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS_FILE = os.path.join(ROOT, "requirements.txt")

GIGAAM_COMMIT = "7447938d791c4f3e643386ee22c33777004293a5"
GIGAAM_SPEC = (f"gigaam[longform] @ https://github.com/salute-developers/GigaAM/archive/"
               f"{GIGAAM_COMMIT}.zip")
DEFAULT_ASR_MODEL = "v3_e2e_rnnt"
HF_TERMS_URLS = [
    "https://huggingface.co/pyannote/segmentation-3.0",
    "https://huggingface.co/pyannote/speaker-diarization-3.1",
    "https://huggingface.co/pyannote/speaker-diarization-community-1",
]


@dataclass
class Step:
    id: str
    title: str
    detail: str
    check: Callable[[], bool]
    install: Optional[Callable[[Callable[[str], None]], None]] = None
    required: bool = True
    manual: bool = False          # needs the user (e.g. accepting model licences)
    help_urls: list = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────

def dist_version(name):
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


def _version_tuple(v):
    return tuple(int(p) for p in re.findall(r"\d+", v.split("+")[0])[:4])


_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:(>=|==)\s*([\w.]+))?")


_MARKER_RE = re.compile(r"""^\s*sys_platform\s*(==|!=)\s*["']([^"']+)["']\s*$""")


def marker_applies(marker, platform=None):
    """Evaluate the simple `sys_platform == "darwin"` markers used in requirements.txt."""
    platform = platform or sys.platform
    m = _MARKER_RE.match(marker)
    if not m:
        raise ValueError(f"unsupported requirement marker: {marker!r}")
    return (platform == m.group(2)) == (m.group(1) == "==")


def parse_requirements(path, platform=None):
    reqs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            line, _, marker = line.partition(";")
            line = line.strip()
            if marker.strip() and not marker_applies(marker.strip(), platform):
                continue
            m = _REQ_RE.match(line)
            if m:
                reqs.append((line, m.group(1), m.group(2), m.group(3)))
    return reqs


def requirement_satisfied(name, op, wanted, version_of=dist_version):
    have = version_of(name)
    if have is None:
        return False
    if op is None:
        return True
    if op == "==":
        return _version_tuple(have) == _version_tuple(wanted)
    return _version_tuple(have) >= _version_tuple(wanted)


def gigaam_pinned(expected_commit=GIGAAM_COMMIT):
    try:
        direct = md.distribution("gigaam").read_text("direct_url.json")
    except md.PackageNotFoundError:
        return False
    return bool(direct) and expected_commit in json.loads(direct).get("url", "")


def torch_matches(variant, version_of=dist_version):
    have = version_of("torch")
    if have is None or version_of("torchaudio") is None:
        return False
    if variant.local_tag:
        return have.endswith("+" + variant.local_tag)
    # CPU/MPS builds must not be a CUDA build (e.g. GPU removed or driver too old).
    return "+cu" not in have


class StateFile:
    """Remembers completed steps that can't be checked cheaply (model downloads)."""

    def __init__(self, path=None):
        self.path = path or os.path.join(app_data_dir(), "setup-state.json")

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def get(self, key):
        return self._load().get(key, False)

    def set(self, key, value=True):
        data = self._load()
        data[key] = value
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)


def default_python():
    """Interpreter to install into and run helpers with: the per-user venv when the
    app runs embedded (macOS), else the running interpreter."""
    return os.environ.get("WORKBENCH_VENV_PYTHON") or sys.executable


class PipInstaller:
    """Installs into the running interpreter's environment; prefers uv, falls back to pip."""

    def __init__(self, python=None):
        self.python = python or default_python()

    def base_cmd(self):
        if importlib.util.find_spec("uv") is not None:
            return [self.python, "-m", "uv", "pip", "install", "--python", self.python]
        return [self.python, "-m", "pip", "install", "--disable-pip-version-check"]

    def install(self, args, log):
        run_streaming(self.base_cmd() + list(args), log)


def run_streaming(cmd, log):
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    if proc.wait() != 0:
        raise RuntimeError(f"command failed with exit code {proc.returncode}")


# ── the plan ─────────────────────────────────────────────────────────────────

def build_plan(hw, installer=None, state=None, hf_token_set=lambda: bool(os.getenv("HF_TOKEN")),
               requirements_file=REQUIREMENTS_FILE, python=None):
    python = python or default_python()
    installer = installer or PipInstaller(python)
    state = state or StateFile()
    variant = torch_variant(hw)
    reqs = parse_requirements(requirements_file)

    def install_app_packages(log):
        installer.install(["-r", requirements_file], log)

    def install_torch(log):
        args = ["torch", "torchaudio"]
        if variant.index_url:
            args += ["--index-url", variant.index_url]
        if dist_version("torch") and not torch_matches(variant):
            args.append("--reinstall" if "uv" in installer.base_cmd() else "--force-reinstall")
        installer.install(args, log)

    def install_gigaam(log):
        installer.install([GIGAAM_SPEC], log)

    def install_ffmpeg(log):
        installer.install(["imageio-ffmpeg>=0.5"], log)

    def download_model(log):
        log(f"Downloading speech model {DEFAULT_ASR_MODEL} (~500 MB, once)…")
        root = models_dir("gigaam")
        run_streaming([python, "-c", f"import gigaam; gigaam.load_model({DEFAULT_ASR_MODEL!r}, "
                                     f"download_root={root!r}); print('model ready')"], log)
        state.set(f"model:{DEFAULT_ASR_MODEL}")

    return [
        Step("app", "App components", "Core libraries of the app (a few MB)",
             lambda: all(requirement_satisfied(n, op, v) for _, n, op, v in reqs), install_app_packages),
        Step("torch", "PyTorch", f"Machine-learning runtime · {variant.note} "
             f"({'~2.5 GB' if variant.name == 'cuda' else '~300 MB'})",
             lambda: torch_matches(variant), install_torch),
        Step("gigaam", "GigaAM speech recognition", f"Pinned version {GIGAAM_COMMIT[:7]} (~50 MB)",
             gigaam_pinned, install_gigaam),
        Step("ffmpeg", "ffmpeg", "Audio conversion (~30 MB)",
             lambda: find_ffmpeg() is not None, install_ffmpeg),
        Step("model", "Speech model", f"{DEFAULT_ASR_MODEL} (~500 MB, downloaded once)",
             lambda: bool(state.get(f"model:{DEFAULT_ASR_MODEL}")), download_model),
        Step("hf", "Speaker separation & long files", "Needs a free Hugging Face token and accepting "
             "the pyannote model terms. Optional: you can do this later in Settings.",
             hf_token_set, required=False, manual=True, help_urls=HF_TERMS_URLS),
    ]
