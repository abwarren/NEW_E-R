"""E&R PokerBet — environment-based configuration.

No hardcoded IPs, keys or ports (legacy failure mode #10 eliminated).
Everything overrides via environment variables; defaults are dev-safe.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    app_name: str = "E&R PokerBet"
    # :8000 is taken on this box (ConceptPokerMTTpro) → E&R owns :8080 (ADR-001)
    port: int = int(_env("ER_PORT", "8080"))
    host: str = _env("ER_HOST", "127.0.0.1")

    # State store. SQLite default (dev). PostgreSQL: switch URL once the DBA
    # (user) provisions the role/database — see docs/adr/ADR-002.md
    db_url: str = _env(
        "ER_DB_URL",
        f"sqlite:///{DATA_DIR / 'er_state.db'}",
    )

    # API key auth (single header X-API-Key). Dev key auto-generated unless set.
    api_key: str = _env("ER_API_KEY", "")
    players_db: str = _env("ER_PLAYERS_DB", str(DATA_DIR / "players.db"))

    allowed_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in _env("ER_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    )

    # Equity engine
    equity_default_variant: str = _env("ER_EQUITY_VARIANT", "plo")  # plo | holdem
    equity_samples: int = int(_env("ER_EQUITY_SAMPLES", "2000"))

    # Staleness
    stale_snapshot_seconds: int = int(_env("ER_STALE_SNAPSHOT_SECONDS", "30"))

    # Command delivery
    command_timeout_seconds: int = int(_env("ER_COMMAND_TIMEOUT_SECONDS", "20"))

    def effective_api_key(self) -> str:
        return self.api_key or "er-dev-" + secrets.token_hex(8)


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
