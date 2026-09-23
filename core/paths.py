import os
import sys

APP_DIR_NAME = "RequirementsWorkbench"


def app_data_dir():
    """Per-user folder for recordings and app state (spec FR-PLAT-06 AC3).

    Override with WORKBENCH_DATA_DIR (used by tests and portable installs).
    """
    override = os.getenv("WORKBENCH_DATA_DIR")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), APP_DIR_NAME)
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_DIR_NAME)
    else:
        base = os.path.join(os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP_DIR_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def recordings_dir():
    path = os.path.join(app_data_dir(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path
