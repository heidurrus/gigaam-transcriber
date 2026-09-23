"""Which local port the app runs on, and whether a copy is already running.

Port 5000 (used up to 1.1.0) is taken on every recent Mac by the AirPlay
Receiver, which answers 403 to everything. So the app never assumes a busy
port is itself. It uses a dedicated default port, falls back to any free port
when that one is taken, records the port it got, and recognises a running copy
only when the other server says who it is.
"""
import json
import os
import socket
import urllib.request

from core.paths import app_data_dir
from core.security import BIND_HOST

APP_ID = "requirements-workbench"
# WORKBENCH_PORT lets a second copy run side by side (development, testing).
DEFAULT_PORT = int(os.environ.get("WORKBENCH_PORT") or 47823)
IDENTITY_PATH = "/__workbench/instance"


def url_for(port):
    return f"http://{BIND_HOST}:{port}"


def register_identity_route(flask_app):
    @flask_app.route(IDENTITY_PATH)
    def _workbench_identity():
        return {"app": APP_ID, "pid": os.getpid()}


def port_accepts_connections(port, host=BIND_HOST, timeout=0.5):
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def free_port(host=BIND_HOST):
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def choose_port(preferred=DEFAULT_PORT):
    """The preferred port if nothing answers on it, else any free port.

    Probing first (instead of just binding) matters on Windows, where binding can
    succeed on a port another program already listens on.
    """
    return free_port() if port_accepts_connections(preferred) else preferred


def is_workbench(port, timeout=1.0):
    try:
        with urllib.request.urlopen(url_for(port) + IDENTITY_PATH, timeout=timeout) as r:
            return json.load(r).get("app") == APP_ID
    except Exception:
        return False


def _instance_file():
    return os.path.join(app_data_dir(), "instance.json")


def record_instance(port):
    with open(_instance_file(), "w", encoding="utf-8") as f:
        json.dump({"port": port, "pid": os.getpid()}, f)


def clear_instance():
    try:
        with open(_instance_file(), encoding="utf-8") as f:
            if json.load(f).get("pid") != os.getpid():
                return  # another copy owns it
        os.remove(_instance_file())
    except (OSError, ValueError):
        pass


def find_running_instance(probe=is_workbench):
    """Port of a running copy of this app, or None. Foreign servers and stale records are ignored."""
    candidates = []
    try:
        with open(_instance_file(), encoding="utf-8") as f:
            candidates.append(int(json.load(f)["port"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if DEFAULT_PORT not in candidates:
        candidates.append(DEFAULT_PORT)
    for port in candidates:
        if probe(port):
            return port
    return None
