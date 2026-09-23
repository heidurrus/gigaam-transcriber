"""App entry point: check dependencies, run first-run setup if needed, then start the app.

Spec FR-PLAT-01 (desktop window by default on Windows and macOS), FR-PLAT-03
(browser mode as an option: --browser), FR-PLAT-04/05 (automatic dependency
installation on first run and a check on every start).

Only needs the base layer (Flask, pywebview); torch and GigaAM are imported
after setup has made sure they exist.
"""
import importlib
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from werkzeug.serving import make_server

from core.hardware import detect
from core.security import BIND_HOST
from core.setup_plan import build_plan
from core.setup_runner import SetupRunner
from core.setup_server import create_setup_app

PORT = 5000
APP_TITLE = "GigaAM Transcriber"
URL = f"http://{BIND_HOST}:{PORT}"


class ServerSlot:
    """Serves one WSGI app at a time on the fixed port, so setup can hand over to the app."""

    def __init__(self, host=BIND_HOST, port=PORT):
        self.host, self.port = host, port
        self._server = None
        self._thread = None

    def serve(self, wsgi_app):
        self.stop()
        self._server = make_server(self.host, self.port, wsgi_app, threaded=True)
        self.port = self._server.server_port  # keep the same port for the handoff
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(5)
            self._server = None

    def join(self):
        while self._thread is not None and self._thread.is_alive():
            self._thread.join(0.5)


def port_in_use(host=BIND_HOST, port=PORT):
    with socket.socket() as s:
        return s.connect_ex((host, port)) == 0


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

    slot.serve(create_setup_app(runner, on_done=lambda: threading.Thread(target=handoff, daemon=True).start()))
    runner.start()
    return runner


def open_window_or_browser(browser_mode):
    if not browser_mode:
        try:
            import webview
        except ImportError:
            print("  pywebview is not available — opening in the browser instead.")
            browser_mode = True
    if browser_mode:
        print(f"  Open {URL} in Chrome or Edge")
        webbrowser.open(URL)
        return False

    class _Api:
        def open_in_browser(self):
            webbrowser.open(URL)

    from core.paths import app_data_dir
    import os
    storage = os.path.join(app_data_dir(), "webview")
    os.makedirs(storage, exist_ok=True)
    try:
        webview.create_window(APP_TITLE, URL, width=1200, height=820, min_size=(800, 600), js_api=_Api())
        webview.start(private_mode=False, storage_path=storage)  # blocks until the window closes
    except Exception as e:
        # e.g. WebView2 runtime missing on an older Windows 10: fall back to the browser
        # rather than exiting without showing anything (FR-PLAT-01 AC5).
        print(f"  Desktop window unavailable ({e}); opening in the browser instead.")
        webbrowser.open(URL)
        return False
    return True


def wait_until_up(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL + "/", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main(argv=None, app_module=None):
    argv = sys.argv[1:] if argv is None else argv
    browser_mode = "--browser" in argv

    if port_in_use():
        # Single instance (FR-PLAT-01 AC4): the app is already running; just show it.
        print(f"  {APP_TITLE} is already running at {URL}")
        webbrowser.open(URL)
        return 0

    slot = ServerSlot()
    start(slot, browser_mode, app_module=app_module)
    wait_until_up()
    if open_window_or_browser(browser_mode):
        slot.stop()  # window closed → stop the local server
    else:
        slot.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
