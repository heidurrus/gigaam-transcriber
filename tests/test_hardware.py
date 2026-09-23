import subprocess

import pytest

from core import hardware
from core.hardware import Hardware, torch_variant


@pytest.mark.parametrize("hw,name,tag,index", [
    (Hardware("darwin", "arm64"), "mps", None, None),
    (Hardware("darwin", "x86_64"), "cpu", None, None),
    (Hardware("win32", "x86_64", "NVIDIA GeForce RTX 4070 Ti", "560.94"), "cuda", "cu126",
     "https://download.pytorch.org/whl/cu126"),
    (Hardware("win32", "x86_64", "NVIDIA GeForce GTX 1060", "472.12"), "cpu", None,
     "https://download.pytorch.org/whl/cpu"),
    (Hardware("win32", "x86_64"), "cpu", None, "https://download.pytorch.org/whl/cpu"),
    (Hardware("linux", "x86_64", "NVIDIA A10", "535.104.05"), "cuda", "cu126",
     "https://download.pytorch.org/whl/cu126"),
])
def test_torch_variant(hw, name, tag, index):
    v = torch_variant(hw)
    assert (v.name, v.local_tag, v.index_url) == (name, tag, index)


def test_old_driver_explains_how_to_enable_gpu():
    note = torch_variant(Hardware("win32", "x86_64", "GTX 1060", "472.12")).note
    assert "472.12" in note and "Check & repair" in note


def test_detect_reads_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "win32")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(hardware.shutil, "which", lambda exe: "C:/nvidia-smi.exe")
    fake = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "NVIDIA GeForce RTX 4070 Ti, 560.94\n", "")
    hw = hardware.detect(run=fake)
    assert hw == Hardware("win32", "x86_64", "NVIDIA GeForce RTX 4070 Ti", "560.94")


def test_detect_without_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "win32")
    monkeypatch.setattr(hardware.shutil, "which", lambda exe: None)
    assert hardware.detect().nvidia_gpu is None


def test_detect_survives_broken_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "linux")
    monkeypatch.setattr(hardware.shutil, "which", lambda exe: "/usr/bin/nvidia-smi")

    def broken(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)
    assert hardware.detect(run=broken).nvidia_gpu is None


def test_mac_never_probes_nvidia(monkeypatch):
    monkeypatch.setattr(hardware.sys, "platform", "darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    hw = hardware.detect(run=lambda *a, **k: pytest.fail("nvidia-smi must not run on macOS"))
    assert hw.apple_silicon
