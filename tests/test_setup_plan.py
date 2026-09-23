from core import setup_plan
from core.hardware import Hardware, TorchVariant
from core.setup_plan import (GIGAAM_COMMIT, GIGAAM_SPEC, StateFile, build_plan, parse_requirements,
                             requirement_satisfied, torch_matches)

CUDA = TorchVariant("cuda", "https://download.pytorch.org/whl/cu126", "cu126")
CPU = TorchVariant("cpu", "https://download.pytorch.org/whl/cpu", None)


def versions(**kw):
    return lambda name: kw.get(name)


def test_torch_check_matches_variant():
    assert torch_matches(CUDA, versions(torch="2.7.1+cu126", torchaudio="2.7.1+cu126"))
    assert not torch_matches(CUDA, versions(torch="2.7.1+cpu", torchaudio="2.7.1"))
    assert not torch_matches(CUDA, versions(torch="2.7.1", torchaudio="2.7.1"))
    assert torch_matches(CPU, versions(torch="2.7.1+cpu", torchaudio="2.7.1+cpu"))
    assert torch_matches(CPU, versions(torch="2.7.1", torchaudio="2.7.1"))  # macOS wheels
    # GPU removed or driver downgraded → the CUDA build must be replaced
    assert not torch_matches(CPU, versions(torch="2.7.1+cu126", torchaudio="2.7.1+cu126"))
    assert not torch_matches(CPU, versions(torch="2.7.1"))  # torchaudio missing


def test_requirement_satisfied():
    v = versions(flask="3.1.2", numpy="1.26.4")
    assert requirement_satisfied("flask", ">=", "3.1", v)
    assert not requirement_satisfied("flask", ">=", "3.2", v)
    assert requirement_satisfied("numpy", "==", "1.26.4", v)
    assert requirement_satisfied("numpy", None, None, v)
    assert not requirement_satisfied("uv", ">=", "0.4", v)


def test_parse_requirements_skips_comments_and_options(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("# comment\n-r other.txt\nflask>=3.1  # web\npywebview[qt]>=5.0\nsoundcard\n\n")
    assert [(n, op, v) for _, n, op, v in parse_requirements(str(f))] == [
        ("flask", ">=", "3.1"), ("pywebview", ">=", "5.0"), ("soundcard", None, None)]


def test_repo_requirements_are_parseable():
    names = {n for _, n, _, _ in parse_requirements(setup_plan.REQUIREMENTS_FILE)}
    assert {"flask", "pywebview", "numpy", "uv"} <= names
    assert "torch" not in names, "torch is installed by setup, per hardware"


def test_gigaam_is_pinned_to_an_archive_not_git():
    assert GIGAAM_SPEC.endswith(f"/archive/{GIGAAM_COMMIT}.zip")
    assert "git+" not in GIGAAM_SPEC


def test_state_file_roundtrip(tmp_path):
    s = StateFile(str(tmp_path / "state.json"))
    assert s.get("model:x") is False
    s.set("model:x")
    assert StateFile(str(tmp_path / "state.json")).get("model:x") is True


class RecordingInstaller:
    def __init__(self):
        self.calls = []

    def base_cmd(self):
        return ["python", "-m", "uv", "pip", "install"]

    def install(self, args, log):
        self.calls.append(list(args))
        log("ok")


def _plan(tmp_path, hw, monkeypatch, torch_version=None):
    monkeypatch.setattr(setup_plan, "dist_version",
                        lambda n: torch_version if n in ("torch", "torchaudio") else None)
    inst = RecordingInstaller()
    plan = build_plan(hw, installer=inst, state=StateFile(str(tmp_path / "s.json")),
                      hf_token_set=lambda: False)
    return {s.id: s for s in plan}, inst


def test_plan_order_and_optional_hf_step(tmp_path, monkeypatch):
    steps, _ = _plan(tmp_path, Hardware("darwin", "arm64"), monkeypatch)
    assert list(steps) == ["app", "torch", "gigaam", "ffmpeg", "model", "hf"]
    assert steps["hf"].manual and not steps["hf"].required
    assert all(s.required for k, s in steps.items() if k != "hf")


def test_torch_install_uses_cuda_index_on_nvidia(tmp_path, monkeypatch):
    steps, inst = _plan(tmp_path, Hardware("win32", "x86_64", "RTX 4070 Ti", "560.94"), monkeypatch)
    steps["torch"].install(lambda line: None)
    assert inst.calls == [["torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu126"]]
    assert "2.5 GB" in steps["torch"].detail


def test_torch_install_on_mac_uses_default_index(tmp_path, monkeypatch):
    steps, inst = _plan(tmp_path, Hardware("darwin", "arm64"), monkeypatch)
    steps["torch"].install(lambda line: None)
    assert inst.calls == [["torch", "torchaudio"]]


def test_wrong_torch_build_is_reinstalled(tmp_path, monkeypatch):
    steps, inst = _plan(tmp_path, Hardware("win32", "x86_64"), monkeypatch, torch_version="2.7.1+cu126")
    assert not steps["torch"].check()
    steps["torch"].install(lambda line: None)
    assert inst.calls[0][-1] == "--reinstall"


def test_gigaam_and_ffmpeg_install_commands(tmp_path, monkeypatch):
    steps, inst = _plan(tmp_path, Hardware("darwin", "arm64"), monkeypatch)
    steps["gigaam"].install(lambda line: None)
    steps["ffmpeg"].install(lambda line: None)
    assert inst.calls == [[GIGAAM_SPEC], ["imageio-ffmpeg>=0.5"]]


def test_model_step_records_completion(tmp_path, monkeypatch):
    steps, _ = _plan(tmp_path, Hardware("darwin", "arm64"), monkeypatch)
    ran = []
    monkeypatch.setattr(setup_plan, "run_streaming", lambda cmd, log: ran.append(cmd))
    assert not steps["model"].check()
    steps["model"].install(lambda line: None)
    assert "gigaam.load_model('v3_e2e_rnnt', download_root=" in ran[0][-1]
    assert steps["model"].check()
