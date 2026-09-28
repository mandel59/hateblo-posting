import json

import pytest

from hateblo import auth
from hateblo.errors import HatebloError


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for name in ("HATENA_USER", "HATENA_BLOG", "HATENA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(auth, "config_path", lambda: tmp_path / "config.json")


class Vault:
    def __init__(self):
        self.items = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[service, username] = password

    def delete_password(self, service, username):
        del self.items[service, username]


def test_round_trip_never_writes_key_to_config(monkeypatch):
    vault = Vault()
    monkeypatch.setattr(auth, "secure_backend", lambda: vault)
    auth.login("alice", "alice.hatenablog.com", "secret-key")
    assert auth.account(None, None) == ("alice", "alice.hatenablog.com")
    assert auth.api_key("alice", "alice.hatenablog.com") == "secret-key"
    config = auth.config_path().read_text()
    assert "secret-key" not in config
    assert set(json.loads(config)) == {"user", "blog"}
    auth.logout("alice", "alice.hatenablog.com")
    auth.logout("alice", "alice.hatenablog.com")
    with pytest.raises(HatebloError, match="未設定"):
        auth.api_key("alice", "alice.hatenablog.com")


def test_environment_overrides_store(monkeypatch):
    monkeypatch.setenv("HATENA_API_KEY", "environment-secret")
    monkeypatch.setattr(auth, "secure_backend", lambda: pytest.fail("must not open store"))
    assert auth.api_key("alice", "alice.hatenablog.com") == "environment-secret"
    monkeypatch.setenv("HATENA_USER", "alice")
    monkeypatch.setenv("HATENA_BLOG", "alice.hatenablog.com")
    assert auth.account(None, None) == ("alice", "alice.hatenablog.com")
    assert auth.account("bob", "bob.hatenablog.com") == ("bob", "bob.hatenablog.com")


def test_accounts_isolated(monkeypatch):
    monkeypatch.setattr(auth, "secure_backend", lambda: vault)
    vault = Vault()
    auth.login("alice", "a.hatenablog.com", "one")
    auth.login("alice", "b.hatenablog.com", "two")
    assert auth.api_key("alice", "a.hatenablog.com") == "one"
    assert auth.api_key("alice", "b.hatenablog.com") == "two"


def test_untrusted_plaintext_backend_rejected(monkeypatch):
    class Plaintext:
        priority = 100

    monkeypatch.setattr(auth.keyring, "get_keyring", Plaintext)
    with pytest.raises(HatebloError, match="安全なOS"):
        auth.secure_backend()


def test_invalid_settings():
    auth.config_path().write_text("[]")
    with pytest.raises(HatebloError):
        auth.account(None, None)


@pytest.mark.parametrize(
    "user,blog",
    [("alice:secret", "a.com"), ("alice", "https://a.com"), ("", "a.com"), ("alice", "../a")],
)
def test_invalid_accounts(user, blog):
    with pytest.raises(HatebloError):
        auth.validate_account(user, blog)
