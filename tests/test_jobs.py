import threading
import time

from core.jobs import JobStore, SerialQueue


def test_job_lifecycle():
    store = JobStore()
    jid = store.create()
    assert store.get(jid)["status"] == "processing"
    store.set_progress(jid, 40, "half")
    assert store.get(jid)["progress"] == 40
    store.finish(jid, {"text": "hi"})
    job = store.get(jid)
    assert job["status"] == "done" and job["result"] == {"text": "hi"} and job["progress"] == 100


def test_failed_job_keeps_progress_fields():
    store = JobStore()
    jid = store.create()
    store.set_progress(jid, 55, "Transcribing…")
    store.fail(jid, RuntimeError("boom"))
    job = store.get(jid)
    assert job["status"] == "error" and job["error"] == "boom" and job["progress"] == 55


def test_finished_jobs_are_pruned_after_ttl():
    now = [0.0]
    store = JobStore(ttl=10, clock=lambda: now[0])
    done, running = store.create(), store.create()
    store.finish(done, {})
    now[0] = 11
    assert store.prune() == 1
    assert store.get(done) is None
    assert store.get(running) is not None


def test_serial_queue_runs_one_job_at_a_time_and_reports_position():
    queue = SerialQueue()
    active, max_active = [0], [0]
    lock = threading.Lock()
    positions = {}
    release = threading.Event()

    def work(name):
        with lock:
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
        if name == "first":
            release.wait(2)
        with lock:
            active[0] -= 1
        return name

    results = []
    first = threading.Thread(target=lambda: results.append(queue.run("first", lambda: work("first"))))
    first.start()
    time.sleep(0.05)
    others = [threading.Thread(target=lambda n=n: results.append(
        queue.run(n, lambda: work(n), on_wait=lambda ahead, n=n: positions.setdefault(n, ahead))))
        for n in ("second", "third")]
    for t in others:
        t.start()
        time.sleep(0.05)
    assert queue.depth == 3
    release.set()
    for t in [first, *others]:
        t.join(2)

    assert max_active[0] == 1
    assert results == ["first", "second", "third"]
    assert positions == {"second": 1, "third": 2}
    assert queue.depth == 0


def test_serial_queue_releases_slot_when_job_raises():
    queue = SerialQueue()
    try:
        queue.run("bad", lambda: 1 / 0)
    except ZeroDivisionError:
        pass
    assert queue.run("next", lambda: "ok") == "ok"
