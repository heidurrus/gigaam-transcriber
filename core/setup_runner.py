"""Runs a setup plan step by step with retries, exposing progress for the Setup screen.

Spec FR-PLAT-04 AC3: failed steps retry automatically with backoff, then wait
for the user to press Retry; steps already done are never repeated.
"""
import importlib
import threading
import time
from collections import deque

LOG_LINES_KEPT = 12


class SetupRunner:
    def __init__(self, steps, retries=3, backoff=2.0, sleep=time.sleep):
        self.steps = steps
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._lock = threading.Lock()
        self._thread = None
        self._state = "idle"
        self._info = {s.id: {"status": "pending", "message": "", "log": deque(maxlen=LOG_LINES_KEPT)}
                      for s in steps}

    # ── queries ──────────────────────────────────────────────────────────────
    def missing_required(self):
        return [s for s in self.steps if s.required and not s.manual and not _safe_check(s)]

    def status(self):
        with self._lock:
            return {
                "state": self._state,
                "steps": [{
                    "id": s.id, "title": s.title, "detail": s.detail,
                    "required": s.required, "manual": s.manual, "help_urls": s.help_urls,
                    "status": self._info[s.id]["status"], "message": self._info[s.id]["message"],
                    "log": list(self._info[s.id]["log"]),
                } for s in self.steps],
            }

    @property
    def state(self):
        with self._lock:
            return self._state

    # ── control ──────────────────────────────────────────────────────────────
    def start(self):
        with self._lock:
            if self._state == "running":
                return False
            self._state = "running"
            for info in self._info.values():
                if info["status"] == "failed":
                    info["status"], info["message"] = "pending", ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    retry = start

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
        return self.state

    # ── internals ────────────────────────────────────────────────────────────
    def _set(self, step, status, message=""):
        with self._lock:
            self._info[step.id]["status"] = status
            self._info[step.id]["message"] = message

    def _log(self, step, line):
        with self._lock:
            self._info[step.id]["log"].append(line[-300:])

    def _run(self):
        for step in self.steps:
            with self._lock:
                if self._info[step.id]["status"] == "done":
                    continue
            self._set(step, "checking")
            if _safe_check(step):
                self._set(step, "done", "Already installed")
                continue
            if step.manual or step.install is None:
                self._set(step, "manual", "Action needed" if step.required else "Optional: can be done later")
                if step.required:
                    return self._finish("failed")
                continue
            if not self._install_with_retries(step):
                return self._finish("failed")
        self._finish("done")

    def _install_with_retries(self, step):
        for attempt in range(1, self._retries + 1):
            self._set(step, "running", "Installing…" if attempt == 1 else f"Retrying ({attempt}/{self._retries})…")
            try:
                step.install(lambda line, s=step: self._log(s, line))
                importlib.invalidate_caches()  # let this process see freshly installed packages
                if not _safe_check(step):
                    raise RuntimeError("installed, but the check still fails")
                self._set(step, "done", "Installed")
                return True
            except Exception as e:
                self._log(step, f"error: {e}")
                if attempt < self._retries:
                    self._sleep(self._backoff * 2 ** (attempt - 1))
                else:
                    self._set(step, "failed", str(e))
        return False

    def _finish(self, state):
        with self._lock:
            self._state = state


def _safe_check(step):
    try:
        return bool(step.check())
    except Exception:
        return False
