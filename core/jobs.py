"""In-memory job store plus a single-slot queue for transcription work.

Spec D-12 / NFR-REL-04: one transcription runs at a time (it holds the GPU and
the shared model objects); the rest wait and report their queue position.
Finished jobs are pruned after a TTL so the store doesn't grow forever.
"""
import threading
import time
import uuid

FINISHED_TTL_SECONDS = 3600


class JobStore:
    def __init__(self, ttl=FINISHED_TTL_SECONDS, clock=time.monotonic):
        self._jobs = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._clock = clock

    def create(self):
        self.prune()
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {"status": "processing", "progress": 0, "progress_msg": "Starting…"}
        return job_id

    def set_progress(self, job_id, pct, msg):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["progress"] = pct
                job["progress_msg"] = msg

    def append_partial(self, job_id, text):
        """Streamed output so far (e.g. a summary being written), shown while the job runs."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["partial"] = job.get("partial", "") + text

    def finish(self, job_id, result):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(status="done", progress=100, progress_msg="Done.", result=result,
                           finished_at=self._clock())

    def fail(self, job_id, error):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(status="error", error=str(error), finished_at=self._clock())

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {k: v for k, v in job.items() if k != "finished_at"}

    def prune(self):
        now = self._clock()
        with self._lock:
            expired = [jid for jid, job in self._jobs.items()
                       if "finished_at" in job and now - job["finished_at"] > self._ttl]
            for jid in expired:
                del self._jobs[jid]
        return len(expired)

    def __len__(self):
        with self._lock:
            return len(self._jobs)


class SerialQueue:
    """Lets one job run at a time; waiting jobs learn their position."""

    def __init__(self):
        self._cond = threading.Condition()
        self._waiting = []
        self._running = False

    def run(self, job_id, fn, on_wait=None):
        with self._cond:
            self._waiting.append(job_id)
            while self._running or self._waiting[0] != job_id:
                if on_wait:
                    on_wait(self._waiting.index(job_id) + (1 if self._running else 0))
                self._cond.wait()
            self._waiting.pop(0)
            self._running = True
        try:
            return fn()
        finally:
            with self._cond:
                self._running = False
                self._cond.notify_all()

    @property
    def depth(self):
        with self._cond:
            return len(self._waiting) + (1 if self._running else 0)
