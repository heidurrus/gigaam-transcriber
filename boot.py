"""First stage of the installed app. Runs on the Python bundled in the installer.

The installer ships a standalone Python with the small base layer (Flask,
pywebview, uv…). Heavy components (PyTorch, GigaAM, ffmpeg) are installed by
the Setup screen into a per-user virtual environment instead, which:
- keeps the signed macOS .app bundle unmodified (installing into it would
  break its code signature), and
- lets app updates replace the bundled runtime without touching user data.

The venv sees the bundled base layer through --system-site-packages. It is
rebuilt automatically when the bundled Python changes (e.g. after an update);
setup then reinstalls the heavy layer. Spec FR-PLAT-04/06, D-17.

Stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from core.paths import app_data_dir  # noqa: E402  (stdlib-only module)

RUNTIME_TAG = f"py{sys.version_info.major}{sys.version_info.minor}"


def venv_dir():
    return os.path.join(app_data_dir(), "runtime", RUNTIME_TAG)


def venv_python(root, windowed=False):
    if sys.platform == "win32":
        return os.path.join(root, "Scripts", "pythonw.exe" if windowed else "python.exe")
    return os.path.join(root, "bin", "python3")


def _base_python():
    # Inside a venv sys._base_executable points at the bundled interpreter.
    return getattr(sys, "_base_executable", None) or sys.executable


def venv_is_current(root, base_python=None):
    """True when the venv exists and was created from this exact bundled Python."""
    cfg = os.path.join(root, "pyvenv.cfg")
    if not os.path.isfile(cfg) or not os.path.exists(venv_python(root)):
        return False
    values = {}
    with open(cfg, encoding="utf-8") as f:
        for line in f:
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip()
    home = os.path.dirname(os.path.realpath(base_python or _base_python()))
    same_home = os.path.normcase(os.path.realpath(values.get("home", ""))) == os.path.normcase(home)
    version = values.get("version") or values.get("version_info", "")
    same_version = version.startswith(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return same_home and same_version and values.get("include-system-site-packages") == "true"


def ensure_venv(root=None, run=subprocess.run):
    root = root or venv_dir()
    if venv_is_current(root):
        return root
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.dirname(root), exist_ok=True)
    run([_base_python(), "-m", "venv", "--system-site-packages", "--without-pip", root], check=True)
    return root


def self_test():
    """`boot.py --self-test`: verify the bundled runtime without opening a window."""
    root = ensure_venv()
    code = ("import json, sys, importlib.util as u; print(json.dumps({'python': sys.version.split()[0], "
            "'prefix': sys.prefix, 'base': {m: bool(u.find_spec(m)) for m in "
            "['flask', 'webview', 'numpy', 'uv', 'sounddevice', 'soundcard', 'dotenv']}}))")
    out = subprocess.run([venv_python(root), "-c", code], capture_output=True, text=True)
    report = json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr}
    report["venv"] = root
    print(json.dumps(report, indent=2))
    return 0 if out.returncode == 0 and all(report.get("base", {}).values()) else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = ensure_venv()
    windowed = sys.platform == "win32" and os.path.basename(sys.executable).lower() == "pythonw.exe"
    cmd = [venv_python(root, windowed), os.path.join(APP_DIR, "launcher.py"), *argv]
    if sys.platform == "win32":
        return subprocess.call(cmd)
    # exec keeps the same process, so macOS keeps attributing permissions to the .app
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
