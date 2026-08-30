"""OS-keyring credential store for PokerBet player accounts.

The SQLite database stores only a *reference* to the credential
(service + key name). The actual password lives in the operating system
keyring (GNOME Keyring via Secret Service) and is never printed, logged,
serialized into API responses, or committed to Git.

Backend injection: ``set_backend`` exists so tests can use an in-memory
dict; production always uses the OS keyring.
"""
from __future__ import annotations

from typing import Callable, Protocol

KEYRING_SERVICE = "er-pokerbet"

CredentialBackend = Callable[[str, str, str | None], str | None]

# Value conventions for the backend function:
#   value is None  → get
#   value == ""    → delete
#   otherwise      → set (returns value)


def _keyring_backend(service: str, key: str, value: str | None = None) -> str | None:
    import keyring  # deferred import: only needed when keyring backend in use

    if value is None:
        return keyring.get_password(service, key)
    if value == "":
        try:
            keyring.delete_password(service, key)
        except Exception:
            pass  # absent entry is fine on delete
        return None
    keyring.set_password(service, key, value)
    return value


def _null_get(service: str, key: str, _value: str | None = None) -> str | None:
    """Backend used when the OS keyring is unavailable (never stores anything)."""
    return None


_backend: CredentialBackend = _keyring_backend
_available: bool = True


def set_backend(fn: CredentialBackend) -> None:
    """Test seam: swap in an in-memory backend (never used in production)."""
    global _backend
    _backend = fn


def get_backend_name() -> str:
    return _backend.__name__


def keyring_available() -> bool:
    return _available


def store_password(player_id: str, password: str) -> None:
    """Store a player's PokerBet password in the OS keyring."""
    if not password:
        raise ValueError("password must not be empty")
    _backend(KEYRING_SERVICE, player_id, password)


def fetch_password(player_id: str) -> str | None:
    """Fetch a player's PokerBet password from the OS keyring.

    Returns None if absent. Callers MUST NOT log or display the result.
    """
    return _backend(KEYRING_SERVICE, player_id)


def delete_password(player_id: str) -> None:
    _backend(KEYRING_SERVICE, player_id, "")


def has_password(player_id: str) -> bool:
    return fetch_password(player_id) is not None
