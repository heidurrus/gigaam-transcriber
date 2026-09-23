"""End-to-end: setup screen → install → hand over to the main app on the same port."""
import json
import types
import urllib.error
import urllib.request

from flask import Flask

import launcher
from core.hardware import Hardware
from core.setup_plan import Step
from core.setup_runner import SetupRunner
from tests.test_recorder import wait_for


def fake_app_module():
    app = Flask("fake-main")

    @app.route("/health")
    def health():
        return {"main": True}

    return types.SimpleNamespace(app=app, IS_DESKTOP=None, GPU_NAME=None, MPS_AVAILABLE=False,
                                 FFMPEG_AVAILABLE=True, hf_token=None)


def get(slot, path, method="GET"):
    url = f"http://127.0.0.1:{slot._server.server_port}{path}"
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_healthy_machine_starts_app_directly():
    slot = launcher.ServerSlot(port=0)
    module = fake_app_module()
    runner = launcher.start(slot, browser_mode=False, app_module=module,
                            detect_hw=lambda: Hardware("darwin", "arm64"),
                            plan_factory=lambda hw: [Step("a", "A", "", lambda: True)], log=lambda m: None)
    try:
        assert runner is None
        assert module.IS_DESKTOP is True
        assert get(slot, "/health")[0] == 200
    finally:
        slot.stop()


def test_missing_dependency_shows_setup_then_hands_over_to_app():
    installed = {"x": False}

    def install(log):
        installed["x"] = True

    slot = launcher.ServerSlot(port=0)
    module = fake_app_module()
    runner = launcher.start(slot, browser_mode=True, app_module=module,
                            detect_hw=lambda: Hardware("win32", "x86_64"),
                            plan_factory=lambda hw: [Step("x", "Thing", "", lambda: installed["x"], install)],
                            log=lambda m: None)
    try:
        assert runner is not None
        status, body = get(slot, "/")
        assert status == 200 and b"Setting up" in body          # setup screen, not the app
        assert get(slot, "/health")[0] == 404                   # main app not loaded yet
        assert runner.wait(5) == "done"
        st = json.loads(get(slot, "/setup/status")[1])
        assert st["state"] == "done" and st["steps"][0]["status"] == "done"

        port = slot.port
        assert get(slot, "/setup/continue", "POST")[0] == 200
        assert wait_for(lambda: slot._server is not None and _up(port), timeout=5)
        status, body = get(slot, "/health")
        assert status == 200 and json.loads(body) == {"main": True}
        assert module.IS_DESKTOP is False
    finally:
        slot.stop()


def _up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def test_continue_is_refused_before_setup_finishes():
    slot = launcher.ServerSlot(port=0)
    runner = launcher.start(slot, browser_mode=True, app_module=fake_app_module(),
                            detect_hw=lambda: Hardware("win32", "x86_64"),
                            plan_factory=lambda hw: [Step("x", "X", "", lambda: False,
                                                          lambda log: (_ for _ in ()).throw(OSError("offline")))],
                            runner_factory=lambda steps: SetupRunner(steps, sleep=lambda s: None),
                            log=lambda m: None)
    try:
        runner.wait(5)
        assert runner.state == "failed"
        assert get(slot, "/setup/continue", "POST")[0] == 409
    finally:
        slot.stop()
