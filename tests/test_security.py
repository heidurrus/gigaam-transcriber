import pytest

from core.security import BIND_HOST, is_local_host, is_local_origin


def test_server_binds_to_loopback_only():
    assert BIND_HOST == "127.0.0.1"


@pytest.mark.parametrize("host", ["127.0.0.1:5000", "localhost:5000", "localhost", "[::1]:5000", "LOCALHOST:5000"])
def test_local_hosts_allowed(host):
    assert is_local_host(host)


@pytest.mark.parametrize("host", ["192.168.1.20:5000", "evil.example:5000", "127.0.0.1.evil.example", "", None])
def test_foreign_hosts_rejected(host):
    assert not is_local_host(host)


@pytest.mark.parametrize("origin,ok", [
    (None, True),
    ("", True),
    ("http://127.0.0.1:5000", True),
    ("http://localhost:5000", True),
    ("http://[::1]:5000", True),
    ("null", False),
    ("https://evil.example", False),
    ("http://127.0.0.1.evil.example", False),
])
def test_origin_check(origin, ok):
    assert is_local_origin(origin) is ok


def test_request_with_local_host_is_served(client):
    assert client.get("/models").status_code == 200


def test_dns_rebinding_host_is_rejected(client):
    res = client.get("/models", headers={"Host": "attacker.example:5000"})
    assert res.status_code == 403


def test_cross_origin_settings_write_is_rejected(client, app_module, monkeypatch):
    written = []
    monkeypatch.setattr(app_module, "_update_env_file", lambda k, v: written.append((k, v)))
    res = client.post("/settings", json={"hf_token": "hf_x"}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert written == []
