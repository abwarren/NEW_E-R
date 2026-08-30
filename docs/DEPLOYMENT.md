# E&R PokerBet — Deployment

Bare-metal single service (this box has no Docker daemon). One uvicorn process
+ SQLite state (PG-ready via `ER_DB_URL`) + Chrome extension loaded unpacked.

## 1. Backend

```bash
cd /home/gdi/NEW_E-R
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env            # edit ER_API_KEY
```

## 2. Run (systemd)

```ini
# /etc/systemd/system/er-pokerbet.service
[Unit]
Description=E&R PokerBet backend
After=network.target

[Service]
WorkingDirectory=/home/gdi/NEW_E-R
EnvironmentFile=/home/gdi/NEW_E-R/.env
ExecStart=/home/gdi/NEW_E-R/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8090
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now er-pokerbet
curl -H "X-API-Key: $ER_API_KEY" http://127.0.0.1:8090/api/health
```

## 3. Player accounts (credentials → OS keyring, never on disk/git)

```bash
.venv/bin/python scripts/er-players.py register --username <PokerBet user> --display-name "<name>"
.venv/bin/python scripts/er-players.py list
.venv/bin/python scripts/er-players.py add-browser <player_id> --label "kasm-01"
```

## 4. Extension

1. chrome://extensions → Developer mode → Load unpacked → `extension/`
2. Options → API base `http://127.0.0.1:8090`, API key, Player ID, Browser ID
3. Open `https://poker-web.pokerbet.co.za/18751019/` → snapshots flow

## 5. PostgreSQL (production state store)

```bash
# provision (postgres superuser)
sudo -u postgres psql -c "CREATE ROLE er_user LOGIN PASSWORD '<strong>';"
sudo -u postgres psql -c "CREATE DATABASE new_er OWNER er_user;"
# apply schema
psql -U er_user -d new_er -f backend/migrations/001_postgres.sql
# point E&R at it
echo 'ER_DB_URL=postgresql+psycopg2://er_user:<strong>@localhost:5432/new_er' >> .env
sudo systemctl restart er-pokerbet
```

SQLAlchemy `create_all` + the DDL are identical across SQLite/PG; switching is
one env change. `pool_pre_ping` handles PG connection drops.

### Schema migrations (dev SQLite)

`create_all` creates missing tables but does NOT alter existing ones. If a
model changed since a previous run (e.g. equity_results gained per-perspective
columns), the old table must be dropped once so it is recreated:

```bash
sqlite3 data/er_state.db "DROP TABLE equity_results;"   # only if schema drifted
# restart uvicorn → create_all recreates it with the new schema
```

Production uses the explicit DDL in `backend/migrations/001_postgres.sql`
(apply via psql; no create_all drift).

## 6. Dashboard

Open `http://127.0.0.1:8090/` — tables grid + directional equity cards, SSE live.

## Rollback

Previous commit is a working state. `git revert` + restart the service.
State DB (`data/er_state.db`) is versioned by snapshot_version — no migration
risk; delete the file to start fresh (players DB untouched).
