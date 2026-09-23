"""Locate ffmpeg: a system install wins, otherwise the binary shipped in the
imageio-ffmpeg wheel that setup installs automatically (spec FR-PLAT-04, D-17).

GigaAM's own ``load_audio`` runs a bare ``ffmpeg`` from PATH, and the wheel's
binary has a versioned name inside site-packages, so ``ensure_ffmpeg_on_path``
exposes it as ``ffmpeg`` in a per-user bin folder that is put on PATH.
"""
import os
import shutil
import stat
import sys

from core.paths import app_data_dir


def _bundled_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffmpeg():
    return shutil.which("ffmpeg") or _bundled_ffmpeg()


def _link_or_copy(src, dst):
    try:
        if sys.platform == "win32":
            os.link(src, dst)        # hard links need no admin rights on NTFS
        else:
            os.symlink(src, dst)
    except OSError:
        shutil.copy2(src, dst)       # different volume, or links not allowed
    if sys.platform != "win32":
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_ffmpeg_on_path(bundled=_bundled_ffmpeg):
    """Make ``ffmpeg`` resolvable on PATH for this process and its children.

    Returns the ffmpeg path to use, or None when neither a system nor a bundled
    build exists.
    """
    bin_dir = os.path.join(app_data_dir(), "bin")
    # Look for a real system ffmpeg, ignoring the shim folder we manage ourselves.
    other_dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep)
                  if d and os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.abspath(bin_dir))]
    system = shutil.which("ffmpeg", path=os.pathsep.join(other_dirs))
    if system:
        return system
    src = bundled()
    if not src:
        return None
    os.makedirs(bin_dir, exist_ok=True)
    dst = os.path.join(bin_dir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if os.path.lexists(dst):
        # Replace a leftover from an older imageio-ffmpeg version (broken/retargeted
        # symlink, or a copy/hard link whose size no longer matches).
        if os.path.islink(dst):
            stale = os.path.realpath(dst) != os.path.realpath(src)
        else:
            stale = os.path.getsize(dst) != os.path.getsize(src)
        if stale:
            os.remove(dst)
    if not os.path.exists(dst):
        _link_or_copy(src, dst)
    os.environ["PATH"] = os.pathsep.join([bin_dir] + other_dirs)
    return dst
