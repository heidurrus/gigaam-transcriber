"""Port selection and single-instance detection (regression: macOS AirPlay on port 5000)."""
import http.server
import threading
import types

import pytest
from flask import Flask

import launcher
from core import instance
from core.hardware import Hardware
from core.setup_plan import Step


class Forbidden(http.server.BaseHTTPRequestHandler):
    """Behaves like the macOS AirPlay Receiver: empty 403 for every request."""

    def do_GET(self):
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture()
def foreign_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Forbidden)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()
    srv.server_close()


def test_busy_preferred_port_is_skipped(foreign_server):
    port = instance.choose_port(preferred=foreign_server)
    assert port != foreign_server and port > 0


def test_free_preferred_port_is_used():
    free = instance.free_port()
    assert instance.choose_port(preferred=free) == free


def test_foreign_server_is_not_mistaken_for_the_app(foreign_server):
    assert not instance.is_workbench(foreign_server)


def test_stale_or_foreign_instance_record_is_ignored(foreign_server, monkeypatch):
    monkeypatch.setattr(instance, "DEFAULT_PORT", instance.free_port())
    instance.record_instance(foreign_server)          # e.g. port reused by another program after a crash
    assert instance.find_running_instance() is None
    instance.clear_instance()


def test_running_copy_is_found_by_identity(monkeypatch):
    slot = launcher.ServerSlot(port=0)
    app = Flask("wb")
    instance.register_identity_route(app)
    slot.serve(app)
    try:
        monkeypatch.setattr(instance, "DEFAULT_PORT", instance.free_port())
        instance.record_instance(slot.port)
        assert instance.find_running_instance() == slot.port
    finally:
        instance.clear_instance()
        slot.stop()


def test_clear_instance_leaves_another_copys_record(tmp_path, monkeypatch):
    instance.record_instance(12345)
    monkeypatch.setattr(instance.os, "getpid", lambda: -1)  # pretend we're a different process
    instance.clear_instance()
    monkeypatch.undo()
    assert instance.find_running_instance(probe=lambda p: p == 12345) == 12345
    instance.clear_instance()


def test_slot_falls_back_to_free_port_when_bind_fails(foreign_server):
    slot = launcher.ServerSlot(port=foreign_server)   # already bound by the foreign server
    slot.serve(Flask("x"))
    try:
        assert slot.port not in (foreign_server, 0)
    finally:
        slot.stop()


def test_setup_screen_and_app_both_identify_themselves():
    module = types.SimpleNamespace(app=Flask("main"), IS_DESKTOP=None, GPU_NAME=None, MPS_AVAILABLE=False,
                                   FFMPEG_AVAILABLE=True, hf_token=None)
    done = {"x": False}
    slot = launcher.ServerSlot(port=0)
    runner = launcher.start(slot, browser_mode=True, app_module=module,
                            detect_hw=lambda: Hardware("darwin", "arm64"),
                            plan_factory=lambda hw: [Step("x", "X", "", lambda: done["x"],
                                                          lambda log: done.update(x=True))],
                            log=lambda m: None)
    try:
        assert instance.is_workbench(slot.port), "setup screen must identify as the app"
        runner.wait(5)
    finally:
        slot.stop()
    slot2 = launcher.ServerSlot(port=0)
    launcher.start(slot2, browser_mode=True, app_module=module,
                   detect_hw=lambda: Hardware("darwin", "arm64"),
                   plan_factory=lambda hw: [Step("x", "X", "", lambda: True)], log=lambda m: None)
    try:
        assert instance.is_workbench(slot2.port), "main app must identify as the app"
    finally:
        slot2.stop()
