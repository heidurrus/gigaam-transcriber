"""Tiny Flask app for the first-run Setup screen (spec FR-PLAT-04).

Needs only the base layer (Flask); the main app can't be imported until setup
has installed torch and GigaAM.
"""
import os

from flask import Flask, jsonify, send_from_directory

from core.security import install_local_only_guard

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def create_setup_app(runner, on_done=None):
    app = Flask(__name__, static_folder=None)
    install_local_only_guard(app)

    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "setup.html")

    @app.route("/setup/status")
    def status():
        return jsonify(runner.status())

    @app.route("/setup/retry", methods=["POST"])
    def retry():
        started = runner.retry()
        return jsonify({"ok": True, "started": started})

    @app.route("/setup/continue", methods=["POST"])
    def continue_to_app():
        # Called by the page once every required step is done.
        if runner.state != "done":
            return jsonify({"error": "Setup is not finished"}), 409
        if on_done:
            on_done()
        return jsonify({"ok": True})

    return app
