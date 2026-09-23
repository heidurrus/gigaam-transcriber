"""Build the installable app with a bundled Python (spec FR-PLAT-04/06, D-16/D-17).

    python packaging/build.py --target macos-arm64    # on a Mac  → dist/*.dmg
    python packaging/build.py --target windows-x64    # on Windows → dist/*-Setup.exe

Steps: download the pinned standalone CPython (checksum-verified), install the
base layer into it, copy the app, then
- macOS: assemble the .app (native launcher stub, Info.plist), ad-hoc sign it
  (or sign with $MACOS_SIGN_IDENTITY), wrap it in a .dmg;
- Windows: stage the files and compile installer/RequirementsWorkbench.iss with
  Inno Setup.

Stdlib only; runs on the build machine's Python 3.9+.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "packaging")
CACHE = os.path.join(PKG, ".cache")
DIST = os.path.join(ROOT, "dist")
# Assemble outside the repo on macOS: synced folders (iCloud "Documents") keep
# adding file-provider attributes that codesign refuses. Override with BUILD_DIR.
BUILD = os.getenv("BUILD_DIR") or (
    os.path.expanduser("~/Library/Caches/RequirementsWorkbenchBuild") if sys.platform == "darwin"
    else os.path.join(ROOT, "build"))

APP_NAME = "Requirements Workbench"
BUNDLE_ID = "com.heidurrus.requirements-workbench"
ARTIFACT = "RequirementsWorkbench"
APP_FILES = ["app.py", "launcher.py", "boot.py", "requirements.txt", "core", "static"]


def log(msg):
    print(f"==> {msg}", flush=True)


def run(cmd, **kw):
    print("    $ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_runtime(target):
    spec = json.load(open(os.path.join(PKG, "runtime.json")))["targets"][target]
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, os.path.basename(spec["url"]).replace("%2B", "+"))
    if not os.path.exists(path) or sha256(path) != spec["sha256"]:
        log(f"Downloading Python runtime for {target}")
        tmp = path + ".part"
        urllib.request.urlretrieve(spec["url"], tmp)
        got = sha256(tmp)
        if got != spec["sha256"]:
            os.remove(tmp)
            sys.exit(f"checksum mismatch for {spec['url']}: {got}")
        os.replace(tmp, path)
    return path


def extract_runtime(archive, dest):
    log("Extracting Python runtime")
    shutil.rmtree(dest, ignore_errors=True)
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    with tarfile.open(archive) as tar:
        kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
        tar.extractall(parent, **kwargs)  # archive root is "python/"
    extracted = os.path.join(parent, "python")
    if extracted != dest:
        os.replace(extracted, dest)


def runtime_python(runtime_dir, target):
    if target.startswith("windows"):
        return os.path.join(runtime_dir, "python.exe")
    return os.path.join(runtime_dir, "bin", "python3")


def install_base_layer(python):
    log("Installing base layer into the bundled Python")
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
         "--no-compile", "-r", os.path.join(ROOT, "requirements.txt")])


def trim_runtime(runtime_dir):
    """Drop parts of the runtime the app never uses (keeps the installer small)."""
    for base, dirs, _ in os.walk(runtime_dir):
        for d in list(dirs):
            if d in ("PyObjCTest", "tests") and "site-packages" in base or d.endswith(".dSYM"):
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)
    for pattern in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip"):
        for base, dirs, _ in os.walk(runtime_dir):
            for d in list(dirs):
                if d == pattern and (os.path.basename(base).startswith("python3") or os.path.basename(base) == "Lib"):
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                    dirs.remove(d)
    for base, dirs, _ in os.walk(runtime_dir):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)


def copy_app(dest):
    log("Copying app files")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    for name in APP_FILES:
        src = os.path.join(ROOT, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, name), ignore=ignore)
        else:
            shutil.copy2(src, dest)


# ── macOS ────────────────────────────────────────────────────────────────────

def build_macos(skip_dmg=False):
    ver = version()
    app = os.path.join(BUILD, "macos", f"{APP_NAME}.app")
    contents = os.path.join(app, "Contents")
    shutil.rmtree(app, ignore_errors=True)
    os.makedirs(os.path.join(contents, "MacOS"))
    resources = os.path.join(contents, "Resources")

    runtime = os.path.join(resources, "python")
    extract_runtime(fetch_runtime("macos-arm64"), runtime)
    install_base_layer(runtime_python(runtime, "macos"))
    trim_runtime(runtime)
    copy_app(os.path.join(resources, "app"))

    log("Compiling native launcher")
    run(["clang", "-O2", "-Wall", "-arch", "arm64", "-mmacosx-version-min=13.0",
         "-o", os.path.join(contents, "MacOS", APP_NAME), os.path.join(PKG, "macos", "launcher_stub.c")])

    with open(os.path.join(PKG, "macos", "Info.plist.in"), encoding="utf-8") as f:
        plist = (f.read().replace("@NAME@", APP_NAME).replace("@BUNDLE_ID@", BUNDLE_ID)
                 .replace("@VERSION@", ver))
    with open(os.path.join(contents, "Info.plist"), "w", encoding="utf-8") as f:
        f.write(plist)
    with open(os.path.join(contents, "Info.plist"), "rb") as f:
        plistlib.load(f)  # fail the build on a malformed plist

    run(["xattr", "-cr", app])  # codesign rejects Finder info / provenance attributes
    # Unset CI secrets arrive as empty strings, so treat empty as "not configured".
    identity = os.getenv("MACOS_SIGN_IDENTITY") or "-"
    log("Signing " + ("ad-hoc (local use)" if identity == "-" else f"with {identity}"))
    sign = ["codesign", "--force", "--deep", "--sign", identity, "--timestamp=none" if identity == "-" else "--timestamp"]
    if identity != "-":
        sign += ["--options", "runtime"]
    run(sign + [app])
    run(["codesign", "--verify", "--deep", "--strict", app])

    if skip_dmg:
        return app
    log("Creating .dmg")
    os.makedirs(DIST, exist_ok=True)
    stage = os.path.join(BUILD, "macos", "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run(["ditto", app, os.path.join(stage, f"{APP_NAME}.app")])
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    dmg = os.path.join(DIST, f"{ARTIFACT}-{ver}-macos-arm64.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    return dmg


# ── Windows ──────────────────────────────────────────────────────────────────

def find_iscc():
    for candidate in (shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                      r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def build_windows(skip_installer=False):
    ver = version()
    stage = os.path.join(BUILD, "windows", "stage")
    shutil.rmtree(stage, ignore_errors=True)
    runtime = os.path.join(stage, "python")
    extract_runtime(fetch_runtime("windows-x64"), runtime)
    if sys.platform == "win32":
        install_base_layer(runtime_python(runtime, "windows"))
    else:
        log("Not on Windows: installing Windows wheels with uv cross-install")
        import importlib.util
        uv = [sys.executable, "-m", "uv"] if importlib.util.find_spec("uv") else [shutil.which("uv") or "uv"]
        run(uv + ["pip", "install", "--python-platform", "x86_64-pc-windows-msvc",
             "--python-version", "3.12", "--target", os.path.join(runtime, "Lib", "site-packages"),
             "-r", os.path.join(ROOT, "requirements.txt")])
    trim_runtime(runtime)
    copy_app(os.path.join(stage, "app"))
    if skip_installer:
        return stage
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found; install it or pass --skip-installer")
    log("Compiling installer with Inno Setup")
    os.makedirs(DIST, exist_ok=True)
    run([iscc, f"/DStageDir={stage}", f"/DAppVersion={ver}", f"/O{DIST}",
         os.path.join(ROOT, "installer", "RequirementsWorkbench.iss")])
    return os.path.join(DIST, f"{ARTIFACT}-{ver}-Setup.exe")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", required=True, choices=["macos-arm64", "windows-x64"])
    p.add_argument("--skip-package", action="store_true", help="stop after the .app / staged folder")
    args = p.parse_args()
    if args.target == "macos-arm64":
        out = build_macos(skip_dmg=args.skip_package)
    else:
        out = build_windows(skip_installer=args.skip_package)
    log(f"Built {out}")


if __name__ == "__main__":
    main()
