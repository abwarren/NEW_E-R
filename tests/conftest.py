"""Test isolation: one fresh temp DB per session (overrides per-module env).

All test modules set ER_DB_URL/ER_PLAYERS_DB at import with setdefault; the
first import wins in a single process, so modules would share whatever the
first one set. This conftest forces a single clean temp DB for the whole
session so ordering never matters, and the per-module setdefaults become
no-ops. Tests that need a clean slate between cases wipe tables via their
own autouse fixtures.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="er-test-")
os.environ["ER_DB_URL"] = f"sqlite:///{_TMP}/state.db"
os.environ["ER_PLAYERS_DB"] = f"{_TMP}/players.db"
# All test modules must authenticate with this shared key.
os.environ["ER_API_KEY"] = "test-key-123"
