-- E&R PokerBet — PostgreSQL schema (production state store)
-- Run against the `new_er` database once provisioned:
--   psql -U er_user -d new_er -f backend/migrations/001_postgres.sql
-- The SQLite dev store uses the same table/column names via SQLAlchemy
-- create_all; this file is the explicit production DDL.

CREATE TABLE IF NOT EXISTS table_state (
    id                  BIGSERIAL PRIMARY KEY,
    scope_key           TEXT NOT NULL UNIQUE,
    player_id           TEXT NOT NULL,
    browser_instance_id TEXT NOT NULL,
    table_id            TEXT NOT NULL,
    hand_id             TEXT NOT NULL DEFAULT '',
    snapshot_version    INTEGER NOT NULL DEFAULT 0,
    street              TEXT NOT NULL DEFAULT '',
    pot                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    board               JSONB NOT NULL DEFAULT '[]',
    seats               JSONB NOT NULL DEFAULT '[]',
    hero_seat           INTEGER NOT NULL DEFAULT -1,
    hero_name           TEXT NOT NULL DEFAULT '',
    available_actions   JSONB NOT NULL DEFAULT '[]',
    action_amounts      JSONB NOT NULL DEFAULT '{}',
    button_state        TEXT NOT NULL DEFAULT '',
    table_state         TEXT NOT NULL DEFAULT '',
    variant             TEXT NOT NULL DEFAULT 'plo',
    is_stale            BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_table_state_scope ON table_state (player_id, browser_instance_id, table_id);

CREATE TABLE IF NOT EXISTS commands (
    id                  BIGSERIAL PRIMARY KEY,
    command_id          TEXT NOT NULL UNIQUE,
    player_id           TEXT NOT NULL,
    browser_instance_id TEXT NOT NULL,
    table_id            TEXT NOT NULL,
    hand_id             TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL,
    amount              DOUBLE PRECISION,
    status              TEXT NOT NULL DEFAULT 'QUEUED',
    attempts            INTEGER NOT NULL DEFAULT 0,
    error               TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_commands_claim ON commands (player_id, browser_instance_id, status);
CREATE INDEX IF NOT EXISTS idx_commands_id ON commands (command_id);

CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    type        TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT '',
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);

CREATE TABLE IF NOT EXISTS equity_results (
    id                  BIGSERIAL PRIMARY KEY,
    table_id            TEXT NOT NULL DEFAULT '',
    hand_id             TEXT NOT NULL DEFAULT '',
    hero_player_id      TEXT NOT NULL DEFAULT '',
    villain_player_id   TEXT NOT NULL DEFAULT '',
    raw_equity          DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_equity     DOUBLE PRECISION NOT NULL DEFAULT 0,
    disparity           DOUBLE PRECISION NOT NULL DEFAULT 0,
    calculation_version TEXT NOT NULL DEFAULT '1',
    variant             TEXT NOT NULL DEFAULT 'plo',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_equity_scope ON equity_results (table_id, hand_id, hero_player_id);

-- seat_snapshots (per-seat history, used for replay/audit)
CREATE TABLE IF NOT EXISTS seat_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    scope_key   TEXT NOT NULL,
    hand_id     TEXT NOT NULL DEFAULT '',
    seat_no     INTEGER NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    stack       DOUBLE PRECISION NOT NULL DEFAULT 0,
    hole_cards  JSONB NOT NULL DEFAULT '[]',
    is_hero     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_seats_scope ON seat_snapshots (scope_key, hand_id);
