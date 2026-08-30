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

Per-device install is fully documented in `DEPLOYMENT/PLAYER_DEVICE.md`. Short
version:

1. Copy `extension/` (3 files: manifest.json, w4p.js, options.html) to the device.
2. chrome://extensions → Developer mode → Load unpacked → that directory.
3. Options → API base, API key, Player ID, Browser ID → Save (grant the host
   permission prompt for remote servers).
4. Open `https://poker-web.pokerbet.co.za/18751019/` → snapshots flow.

Config is stored in `chrome.storage.local` per device — no JS editing.

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

Open `http://127.0.0.1:8090/` — fleet grid (per player: 🟢 ONLINE / 🔴 OFFLINE,
tables, hands, streets, last-seen), directional equity cards, SSE live.
A device that stops sending snapshots turns 🔴 OFFLINE after
`ER_STALE_SNAPSHOT_SECONDS` (default 30s).

## 7. Remote / multi-device deployment

Player devices run Chrome + the extension and connect to ONE central E&R
server. Required changes vs local dev:

### 7.1 Server bind + firewall

```bash
# .env — listen on all interfaces so remote devices can connect
ER_HOST=0.0.0.0
```

Open one port (8090) in the firewall for the E&R server. Prefer restricting
the source to the VPN / device subnet:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8090 proto tcp   # LAN
# or, remote: allow only from your VPN range, e.g. 10.8.0.0/24
```

Devices must reach `http://<server-ip>:8090/api/health`.

### 7.2 HTTPS (recommended for anything beyond a trusted LAN)

The extension works over plain HTTP, but API keys in cleartext travel the
network — use HTTPS for remote deployment. nginx reverse proxy example:

```nginx
server {
    listen 443 ssl;
    server_name er.example.com;
    ssl_certificate     /etc/letsencrypt/live/er.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/er.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;                 # SSE must not be buffered
    }
}
```

API base on devices: `https://er.example.com` (no port, no path).

### 7.3 CORS

The extension's content-script fetch bypasses CORS via its manifest host
permission (granted on the options page). Non-extension callers (a dashboard
opened from another host, dev tools) need the server's explicit allow-list:

```bash
# .env — comma-separated origins
ER_ALLOWED_ORIGINS=https://dash.example.com,http://192.168.0.10:8090
```

Default (empty) = fully locked down; preflight from foreign origins is
rejected. API-key auth still gates every request.

### 7.4 VPN / private network

For N devices in the field, prefer a VPN (WireGuard/Tailscale) with the E&R
server on the private range — the extension then talks `https://er:8090` or
`http://10.x.x.x:8090` and the server never needs public exposure.

### 7.5 Reconnect / offline behavior

- The extension polls every 800 ms; a failed request is silently retried —
  no backoff logic needed, snapshots resume automatically when the network
  returns.
- The dashboard marks a device 🔴 OFFLINE when no snapshot arrived for
  `ER_STALE_SNAPSHOT_SECONDS` (default 30s) and back to 🟢 ONLINE on the next
  snapshot.
- Commands claimed but never ACKed are returned to the queue as TIMEOUT
  after `ER_COMMAND_TIMEOUT_SECONDS` (default 20s); the extension's
  command-id memo prevents double execution.

## Rollback

Previous commit is a working state. `git revert` + restart the service.
State DB (`data/er_state.db`) is versioned by snapshot_version — no migration
risk; delete the file to start fresh (players DB untouched).
