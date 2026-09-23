import os
import shutil
import subprocess
import sys

import pytest

from core import ffmpeg


@pytest.fixture()
def fake_binary(tmp_path):
    src = tmp_path / "site-packages" / "ffmpeg-macos-aarch64-v7.1"
    src.parent.mkdir()
    src.write_text("#!/bin/sh\necho fake ffmpeg $@\n")
    src.chmod(0o755)
    return str(src)


@pytest.fixture()
def no_system_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "data"))


def test_system_ffmpeg_wins(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name, path=None: "/usr/bin/ffmpeg")
    assert ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: pytest.fail("must not use bundled")) == "/usr/bin/ffmpeg"


def test_nothing_available(no_system_ffmpeg):
    assert ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: None) is None


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in for ffmpeg")
def test_bundled_binary_is_exposed_as_plain_ffmpeg_for_child_processes(no_system_ffmpeg, fake_binary):
    path = ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: fake_binary)
    assert os.path.basename(path) == "ffmpeg"
    assert shutil.which("ffmpeg") == path
    # What GigaAM's load_audio does: run a bare "ffmpeg".
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, env=os.environ.copy())
    assert out.stdout.strip() == "fake ffmpeg -version"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics")
def test_stale_link_after_upgrade_is_replaced(no_system_ffmpeg, fake_binary, tmp_path):
    ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: fake_binary)
    newer = tmp_path / "site-packages" / "ffmpeg-macos-aarch64-v7.2"
    newer.write_text("#!/bin/sh\necho newer\n")
    newer.chmod(0o755)
    path = ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: str(newer))
    assert os.path.realpath(path) == os.path.realpath(str(newer))


def test_falls_back_to_copy_when_links_fail(no_system_ffmpeg, fake_binary, monkeypatch):
    def refuse(*a):
        raise OSError("links not allowed")
    monkeypatch.setattr(ffmpeg.os, "symlink", refuse)
    monkeypatch.setattr(ffmpeg.os, "link", refuse)
    path = ffmpeg.ensure_ffmpeg_on_path(bundled=lambda: fake_binary)
    assert not os.path.islink(path)
    assert open(path).read() == open(fake_binary).read()
