from core.setup_plan import Step
from core.setup_runner import SetupRunner


class Flag:
    def __init__(self, value=False):
        self.value = value

    def __call__(self):
        return self.value


def installer(flag, fail_times=0, log_line="working"):
    calls = {"n": 0}

    def install(log):
        calls["n"] += 1
        log(log_line)
        if calls["n"] <= fail_times:
            raise RuntimeError(f"network down (attempt {calls['n']})")
        flag.value = True
    install.calls = calls
    return install


def run(steps, **kw):
    kw.setdefault("sleep", lambda s: None)
    r = SetupRunner(steps, **kw)
    r.start()
    r.wait(5)
    return r


def by_id(runner):
    return {s["id"]: s for s in runner.status()["steps"]}


def test_healthy_machine_needs_nothing():
    r = SetupRunner([Step("a", "A", "", Flag(True))])
    assert r.missing_required() == []


def test_installs_missing_steps_in_order_and_skips_present_ones():
    order = []
    a, b = Flag(True), Flag(False)

    def install_b(log):
        order.append("b")
        b.value = True
    r = run([Step("a", "A", "", a, lambda log: order.append("a")), Step("b", "B", "", b, install_b)])
    assert r.state == "done" and order == ["b"]
    st = by_id(r)
    assert st["a"]["message"] == "Already installed" and st["b"]["message"] == "Installed"


def test_retries_with_backoff_then_succeeds():
    flag, sleeps = Flag(), []
    inst = installer(flag, fail_times=2)
    r = run([Step("x", "X", "", flag, inst)], sleep=sleeps.append, backoff=2.0)
    assert r.state == "done" and inst.calls["n"] == 3
    assert sleeps == [2.0, 4.0]


def test_failure_stops_setup_and_keeps_log():
    flag, later = Flag(), Flag()
    r = run([Step("x", "X", "", flag, installer(flag, fail_times=99)),
             Step("y", "Y", "", later, installer(later))], retries=3)
    st = by_id(r)
    assert r.state == "failed"
    assert st["x"]["status"] == "failed" and "attempt 3" in st["x"]["message"]
    assert "working" in st["x"]["log"] and any("network down" in line for line in st["x"]["log"])
    assert st["y"]["status"] == "pending", "later steps don't run after a failure"


def test_retry_resumes_without_repeating_finished_steps():
    a, b = Flag(), Flag()
    inst_a = installer(a)
    inst_b = installer(b, fail_times=3)
    r = run([Step("a", "A", "", a, inst_a), Step("b", "B", "", b, inst_b)], retries=3)
    assert r.state == "failed"
    r.retry()
    r.wait(5)
    assert r.state == "done"
    assert inst_a.calls["n"] == 1, "finished step must not be repeated"
    assert inst_b.calls["n"] == 4


def test_install_that_does_not_fix_the_check_counts_as_failure():
    r = run([Step("x", "X", "", Flag(False), lambda log: None)], retries=1)
    assert r.state == "failed"
    assert "check still fails" in by_id(r)["x"]["message"]


def test_optional_manual_step_does_not_block():
    r = run([Step("hf", "HF", "", Flag(False), required=False, manual=True, help_urls=["u"])])
    assert r.state == "done"
    assert by_id(r)["hf"]["status"] == "manual"
    assert r.missing_required() == []


def test_check_that_raises_is_treated_as_missing():
    def boom():
        raise ImportError("broken install")
    r = SetupRunner([Step("x", "X", "", boom)])
    assert [s.id for s in r.missing_required()] == ["x"]


def test_log_is_bounded():
    flag = Flag()

    def noisy(log):
        for i in range(500):
            log(f"line {i}")
        flag.value = True
    r = run([Step("x", "X", "", flag, noisy)])
    assert len(by_id(r)["x"]["log"]) <= 12
