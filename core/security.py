"""Keep the local server local (spec NFR-SEC-04).

The server only ever binds to loopback, and every request must name a loopback
host. That blocks LAN access and DNS-rebinding attacks from web pages the user
visits, which could otherwise read transcripts or overwrite .env via /settings.
"""
from urllib.parse import urlsplit

from flask import jsonify, request

BIND_HOST = "127.0.0.1"
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _hostname(host_header):
    if not host_header:
        return ""
    if host_header.startswith("["):  # IPv6 literal, e.g. [::1]:5000
        return host_header.split("]")[0] + "]"
    return host_header.rsplit(":", 1)[0] if ":" in host_header else host_header


def is_local_host(host_header):
    return _hostname(host_header).lower() in LOCAL_HOSTNAMES


def is_local_origin(origin):
    if not origin:
        return True  # same-origin GETs, pywebview, curl
    if origin == "null":
        return False  # file:// pages and sandboxed iframes
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and (parts.hostname or "").lower() in {
        h.strip("[]") for h in LOCAL_HOSTNAMES
    }


def install_local_only_guard(app):
    @app.before_request
    def _reject_non_local():
        if not is_local_host(request.host):
            return jsonify({"error": "Forbidden: this server only accepts local requests"}), 403
        if "Origin" in request.headers and not is_local_origin(request.headers.get("Origin")):
            return jsonify({"error": "Forbidden: cross-origin request"}), 403
        return None
