"""Detect the machine so setup can pick the right PyTorch build (spec FR-PLAT-04 AC1, AC4).

Only stdlib: this runs before torch is installed.
"""
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

PYTORCH_INDEX = "https://download.pytorch.org/whl"
CUDA_TAG = "cu126"
# CUDA 12.x wheels run on drivers >= these (CUDA minor-version compatibility).
MIN_DRIVER_FOR_CUDA = {"win32": 528, "linux": 525}


@dataclass(frozen=True)
class Hardware:
    os: str                      # "win32" | "darwin" | "linux"
    arch: str                    # "x86_64" | "arm64" | …
    nvidia_gpu: Optional[str] = None
    nvidia_driver: Optional[str] = None

    @property
    def apple_silicon(self):
        return self.os == "darwin" and self.arch in ("arm64", "aarch64")


@dataclass(frozen=True)
class TorchVariant:
    name: str                    # "cuda" | "mps" | "cpu"
    index_url: Optional[str]     # None = default PyPI wheels
    local_tag: Optional[str]     # expected "+cu126"-style suffix of the installed version
    note: str = ""


def _query_nvidia(run):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None
    try:
        out = run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                  capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0 or not out.stdout.strip():
        return None, None
    name, _, driver = out.stdout.strip().splitlines()[0].partition(",")
    return name.strip() or None, driver.strip() or None


def detect(run=subprocess.run):
    os_name = "linux" if sys.platform.startswith("linux") else sys.platform
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    gpu, driver = (None, None) if os_name == "darwin" else _query_nvidia(run)
    return Hardware(os=os_name, arch=arch, nvidia_gpu=gpu, nvidia_driver=driver)


def _driver_major(driver):
    m = re.match(r"(\d+)", driver or "")
    return int(m.group(1)) if m else 0


def torch_variant(hw):
    if hw.os == "darwin":
        if hw.apple_silicon:
            return TorchVariant("mps", None, None, "Apple Silicon GPU (MPS)")
        return TorchVariant("cpu", None, None, "Intel Mac: CPU only")
    if hw.nvidia_gpu:
        min_driver = MIN_DRIVER_FOR_CUDA.get(hw.os, 10**6)
        if _driver_major(hw.nvidia_driver) >= min_driver:
            return TorchVariant("cuda", f"{PYTORCH_INDEX}/{CUDA_TAG}", CUDA_TAG, f"NVIDIA {hw.nvidia_gpu}")
        return TorchVariant(
            "cpu", f"{PYTORCH_INDEX}/cpu", None,
            f"NVIDIA driver {hw.nvidia_driver} is older than {min_driver}; using CPU. "
            "Update the GPU driver and run Check & repair to enable the GPU.")
    return TorchVariant("cpu", f"{PYTORCH_INDEX}/cpu", None, "No NVIDIA GPU: CPU only")
