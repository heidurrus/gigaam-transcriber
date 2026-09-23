"""App entry point: check dependencies, run first-run setup if needed, then start the app.

Spec FR-PLAT-01 (desktop window by default on Windows and macOS), FR-PLAT-03
(browser mode as an option: --browser), FR-PLAT-04/05 (automatic dependency
installation on first run and a check on every start).

Only needs the base layer (Flask, pywebview); torch and GigaAM are imported
after setup has made sure they exist.
"""
import atexit
import importlib
import signal
import sys
import threading
import time
import urllib.request
import webbrowser

from werkzeug.serving import make_server

from core import instance
from core.hardware import detect
from core.security import BIND_HOST
from core.setup_plan import build_plan
from core.setup_runner import SetupRunner
from core.setup_server import create_setup_app

APP_TITLE = "Requirements Workbench"


class ServerSlot:
    """Serves one WSGI app at a time on the fixed port, so setup can hand over to the app."""

    def __init__(self, host=BIND_HOST, port=instance.DEFAULT_PORT):
        self.host, self.port = host, port
        self._server = None
        self._thread = None
        self._bound_once = False
        self._closed = threading.Event()  # set only when the app shuts down, not during handoff

    def serve(self, wsgi_app):
        first_bind = not self._bound_once
        self.stop()
        if first_bind and self.port and instance.port_accepts_connections(self.port):
            # Binding can "succeed" on a port another server listens on (SO_REUSEADDR),
            # leaving both answering; never share a port with someone else.
            self.port = 0
        try:
            self._server = make_server(self.host, self.port, wsgi_app, threaded=True)
        except OSError:
            if not first_bind:
                raise  # the handoff must reuse the port the window already points at
            self._server = make_server(self.host, 0, wsgi_app, threaded=True)
        self._bound_once = True
        self.port = self._server.server_port  # keep the same port for the handoff
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(5)
            self._server = None

    def close(self):
        """Final shutdown (window closed / Ctrl+C)."""
        self.stop()
        self._closed.set()

    def join(self):
        """Block until close(). Waiting on server threads would return during the
        setup → app handoff, when neither server is running for a moment."""
        while not self._closed.wait(0.5):
            pass


def load_main_app(app_module=None):
    return app_module or importlib.import_module("app")


def print_summary(app_module):
    gpu = app_module.GPU_NAME or ("Apple Silicon (MPS)" if app_module.MPS_AVAILABLE else "not available (CPU only)")
    print()
    print(f"  {APP_TITLE}")
    print("  " + "-" * 40)
    print(f"  ffmpeg   : {'found' if app_module.FFMPEG_AVAILABLE else 'NOT FOUND — run Check & repair'}")
    print(f"  GPU      : {gpu}")
    print(f"  HF token : {'set' if app_module.hf_token else 'not set — diarization and longform disabled'}")
    print("  " + "-" * 40)


def start(slot, browser_mode, app_module=None, detect_hw=detect, plan_factory=build_plan,
          runner_factory=SetupRunner, log=print):
    """Start the setup screen or the app on `slot`. Returns the SetupRunner (or None)."""
    runner = runner_factory(plan_factory(detect_hw()))
    missing = runner.missing_required()

    def launch_app():
        module = load_main_app(app_module)
        module.IS_DESKTOP = not browser_mode
        print_summary(module)
        if instance.IDENTITY_PATH not in {r.rule for r in module.app.url_map.iter_rules()}:
            instance.register_identity_route(module.app)
        slot.serve(module.app)

    if not missing:
        launch_app()
        return None

    log("  Setup needed: " + ", ".join(s.title for s in missing))

    def handoff():
        # Import before stopping the setup screen, so an import error can still be shown there.
        try:
            launch_app()
        except Exception as e:
            log(f"  Could not start the app after setup: {e}")
            raise

    setup_app = create_setup_app(runner, on_done=lambda: threading.Thread(target=handoff, daemon=True).start())
    instance.register_identity_route(setup_app)
    slot.serve(setup_app)
    runner.start()
    return runner


def open_window_or_browser(browser_mode, url):
    if not browser_mode:
        try:
            import webview
        except ImportError:
            print("  pywebview is not available — opening in the browser instead.")
            browser_mode = True
    if browser_mode:
        print(f"  Open {url} in Chrome or Edge")
        webbrowser.open(url)
        return False

    class _Api:
        def open_in_browser(self):
            webbrowser.open(url)

    from core.paths import app_data_dir
    import os
    storage = os.path.join(app_data_dir(), "webview")
    os.makedirs(storage, exist_ok=True)
    try:
        webview.create_window(APP_TITLE, url, width=1200, height=820, min_size=(800, 600), js_api=_Api())
        webview.start(private_mode=False, storage_path=storage)  # blocks until the window closes
    except Exception as e:
        # e.g. WebView2 runtime missing on an older Windows 10: fall back to the browser
        # rather than exiting without showing anything (FR-PLAT-01 AC5).
        print(f"  Desktop window unavailable ({e}); opening in the browser instead.")
        webbrowser.open(url)
        return False
    return True


def wait_until_up(url, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main(argv=None, app_module=None):
    argv = sys.argv[1:] if argv is None else argv
    browser_mode = "--browser" in argv

    running = instance.find_running_instance()
    if running:
        # Single instance (FR-PLAT-01 AC4): a copy of this app is already running; show it.
        print(f"  {APP_TITLE} is already running at {instance.url_for(running)}")
        webbrowser.open(instance.url_for(running))
        return 0

    slot = ServerSlot(port=instance.choose_port())
    start(slot, browser_mode, app_module=app_module)
    instance.record_instance(slot.port)
    atexit.register(instance.clear_instance)
    # Make a plain kill (SIGTERM, e.g. logout) run the atexit cleanup too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    url = instance.url_for(slot.port)
    wait_until_up(url)
    if open_window_or_browser(browser_mode, url):
        slot.close()  # window closed → stop the local server
    else:
        try:
            slot.join()  # browser mode: run until Ctrl+C
        except KeyboardInterrupt:
            slot.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
