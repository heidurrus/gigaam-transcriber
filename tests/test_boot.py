import os
import subprocess
import sys

import pytest

import boot


def write_cfg(root, home, version=None, system_site="true"):
    os.makedirs(root, exist_ok=True)
    version = version or "{}.{}.{}".format(*sys.version_info[:3])
    with open(os.path.join(root, "pyvenv.cfg"), "w") as f:
        f.write(f"home = {home}\ninclude-system-site-packages = {system_site}\nversion = {version}\n")
    exe = boot.venv_python(root)
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    open(exe, "w").close()


def base_home():
    return os.path.dirname(os.path.realpath(boot._base_python()))


def test_current_venv_is_reused(tmp_path):
    root = str(tmp_path / "rt")
    write_cfg(root, base_home())
    assert boot.venv_is_current(root)
    calls = []
    assert boot.ensure_venv(root, run=lambda *a, **k: calls.append(a)) == root
    assert calls == []


def test_venv_from_another_python_is_rebuilt(tmp_path):
    root = str(tmp_path / "rt")
    write_cfg(root, "/Volumes/Old Disk Image/GigaAM Transcriber.app/Contents/Resources/python/bin")
    assert not boot.venv_is_current(root)
    calls = []
    boot.ensure_venv(root, run=lambda cmd, **k: calls.append(cmd))
    assert calls and calls[0][1:5] == ["-m", "venv", "--system-site-packages", "--without-pip"]
    assert not os.path.exists(os.path.join(root, "pyvenv.cfg")), "stale venv must be removed first"


def test_venv_after_python_upgrade_is_rebuilt(tmp_path):
    root = str(tmp_path / "rt")
    write_cfg(root, base_home(), version="3.12.0" if sys.version_info[:3] != (3, 12, 0) else "3.12.1")
    assert not boot.venv_is_current(root)


def test_venv_without_system_site_packages_is_rebuilt(tmp_path):
    root = str(tmp_path / "rt")
    write_cfg(root, base_home(), system_site="false")
    assert not boot.venv_is_current(root)


def test_missing_venv_is_not_current(tmp_path):
    assert not boot.venv_is_current(str(tmp_path / "nothing"))


@pytest.mark.skipif(sys.prefix != sys.base_prefix,
                    reason="needs the base layer in the base interpreter, like the bundled Python (CI)")
def test_real_venv_sees_base_packages(tmp_path):
    """Creates a real venv like the installed app does and imports a base-layer package from it."""
    root = boot.ensure_venv(str(tmp_path / "rt"))
    assert boot.venv_is_current(root)
    out = subprocess.run([boot.venv_python(root), "-c", "import flask, sys; print(sys.prefix)"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert os.path.realpath(out.stdout.strip()) == os.path.realpath(root)
