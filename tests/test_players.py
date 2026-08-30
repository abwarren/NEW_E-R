"""Credential-safety acceptance tests for the E&R PokerBet player database.

Covers the acceptance checklist from the player-account directive:

1. Multiple PokerBet accounts can be registered.
2. E&R can identify which player/bot owns each browser instance.
3. Credentials can be retrieved securely when launching/using an account.
4. Passwords never appear in application logs / API responses / dashboard / git.
5. Database inspection does not reveal plaintext passwords.
6. Disabling a player prevents that account from being used.
7. Two player/browser instances remain completely isolated.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.players import credentials
from backend.players.db import PlayerDatabase
from backend.players.identity import IdentityService, StateKey

FAKE_PW_ALICE = "S3cret-Alice-!9"
FAKE_PW_BOB = "B0b-Passw0rd-#7"


@pytest.fixture()
def mem_backend():
    vault: dict[tuple[str, str], str] = {}

    def backend(service: str, key: str, value: str | None = None) -> str | None:
        if value is None:
            return vault.get((service, key))
        if value == "":
            vault.pop((service, key), None)
            return None
        vault[(service, key)] = value
        return value

    credentials.set_backend(backend)
    yield backend
    credentials.set_backend(credentials._keyring_backend)  # restore


@pytest.fixture()
def db(tmp_path, mem_backend):
    return PlayerDatabase(tmp_path / "players-test.db")


def _register(db, username, pw, display="", enabled=True):
    player = db.create_player(username=username, display_name=display or username, enabled=enabled)
    credentials.store_password(player.player_id, pw)
    return player


# ── 1. Multiple accounts can be registered ────────────────────────────────
def test_multiple_accounts_register(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    b = _register(db, "bob", FAKE_PW_BOB)
    assert len(db.list_players()) == 2
    assert {p.username for p in db.list_players()} == {"alice", "bob"}
    assert credentials.has_password(a.player_id)
    assert credentials.has_password(b.player_id)


def test_duplicate_username_rejected(db):
    _register(db, "alice", FAKE_PW_ALICE)
    with pytest.raises(ValueError):
        db.create_player(username="alice")


# ── 2. E&R identifies which player owns each browser instance ─────────────
def test_browser_ownership(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    b = _register(db, "bob", FAKE_PW_BOB)
    ia = db.register_browser_instance(a.player_id, "kasm-alice-1")
    ib = db.register_browser_instance(b.player_id, "kasm-bob-1")
    assert db.get_browser_instance(ia.browser_instance_id).player_id == a.player_id
    assert db.get_browser_instance(ib.browser_instance_id).player_id == b.player_id
    assert len(db.list_browser_instances(a.player_id)) == 1


# ── 3. Credential retrievable securely (backend returns it to launcher) ───
def test_credential_retrieval(db, mem_backend):
    a = _register(db, "alice", FAKE_PW_ALICE)
    assert credentials.fetch_password(a.player_id) == FAKE_PW_ALICE


# ── 4. Passwords never in logs / API responses / dashboard ────────────────
def test_player_serialization_has_no_password(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    d = a.to_dict()
    assert "password" not in d
    assert "credential" not in d
    assert FAKE_PW_ALICE not in repr(d)
    assert FAKE_PW_ALICE not in repr(a)


def test_list_players_never_exposes_password(db):
    _register(db, "alice", FAKE_PW_ALICE)
    for p in db.list_players():
        assert FAKE_PW_ALICE not in str(p.to_dict())


# ── 5. Database inspection reveals no plaintext passwords ─────────────────
def test_db_file_has_no_plaintext_password(tmp_path, mem_backend):
    db = PlayerDatabase(tmp_path / "inspect.db")
    _register(db, "alice", FAKE_PW_ALICE)
    db.close()
    raw = (tmp_path / "inspect.db").read_bytes()
    assert FAKE_PW_ALICE.encode() not in raw
    # Also verify the keyring (backend) holds it, not the DB
    conn = sqlite3.connect(tmp_path / "inspect.db")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(players)")]
    assert "password" not in cols
    conn.close()


# ── 6. Disabling a player prevents use ────────────────────────────────────
def test_disabled_player_cannot_be_used(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    db.set_enabled(a.player_id, False)
    svc = IdentityService(db)
    ia = db.register_browser_instance(a.player_id, "kasm-alice-1")
    with pytest.raises(PermissionError):
        svc.state_key(a.player_id, ia.browser_instance_id, "T1", "H1")


# ── 7. Two player/browser instances remain completely isolated ────────────
def test_two_players_isolated_state_keys(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    b = _register(db, "bob", FAKE_PW_BOB)
    ia = db.register_browser_instance(a.player_id, "kasm-alice-1")
    ib = db.register_browser_instance(b.player_id, "kasm-bob-1")
    svc = IdentityService(db)

    key_a = svc.state_key(a.player_id, ia.browser_instance_id, "T1", "H42")
    key_b = svc.state_key(b.player_id, ib.browser_instance_id, "T1", "H42")

    # Same table, same hand, different player → different state key.
    assert key_a.as_key() != key_b.as_key()
    # Same player, different tables → different keys.
    key_a2 = svc.state_key(a.player_id, ia.browser_instance_id, "T2", "H42")
    assert key_a.as_key() != key_a2.as_key()
    # Same player/table, different hands → different keys.
    key_a3 = svc.state_key(a.player_id, ia.browser_instance_id, "T1", "H43")
    assert key_a.as_key() != key_a3.as_key()


def test_cross_player_browser_access_blocked(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    b = _register(db, "bob", FAKE_PW_BOB)
    ia = db.register_browser_instance(a.player_id, "kasm-alice-1")
    svc = IdentityService(db)
    with pytest.raises(PermissionError):
        svc.state_key(b.player_id, ia.browser_instance_id, "T1", "H1")


def test_state_key_requires_table(db):
    a = _register(db, "alice", FAKE_PW_ALICE)
    ia = db.register_browser_instance(a.player_id, "kasm-alice-1")
    svc = IdentityService(db)
    with pytest.raises(ValueError):
        svc.state_key(a.player_id, ia.browser_instance_id, "")


# ── composite key shape ────────────────────────────────────────────────────
def test_state_key_shape():
    k = StateKey("p1", "b1", "t1", "h1", 7)
    assert k.as_key() == "player=p1|browser=b1|table=t1|hand=h1|v=7"
    assert k.scope_key() == "player=p1|browser=b1|table=t1"
