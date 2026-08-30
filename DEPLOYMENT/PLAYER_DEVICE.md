# E&R — Player Device Deployment Guide

How to install the E&R PokerBet extension on a player device and point it at
the central E&R server.

## What you need before starting

| Item | Where to get it |
|------|-----------------|
| Central E&R server URL | e.g. `http://192.168.0.10:8090` (LAN) or `https://er.example.com` (remote) — ask the operator |
| API key | the `ER_API_KEY` value from the server's `.env` — ask the operator |
| Player ID | assigned by the operator, e.g. `PLAYER-001` |
| Browser instance ID | unique per device/browser, e.g. `PLAYER-001-CHROME-01` |

The device needs: Chrome (or Chromium), a PokerBet account that the operator
has registered (`scripts/er-players.py register`), and network reachability to
the central E&R server (ping it first).

## The extension — what it is

The entire extension is **3 files** in the repository:

```
extension/
├── manifest.json     (MV3 manifest — version 0.2.0)
├── w4p.js            (scraper + command executor, runs on poker-web.pokerbet.co.za)
└── options.html      (settings page: server URL, API key, player ID, browser ID)
```

No build step. No package manager. No service worker. Copy the whole
`extension/` directory to the device and load it unpacked.

## Install (every device, same steps)

1. Copy the `extension/` directory to the device (USB, network share, or
   download from the repo):  `https://github.com/abwarren/NEW_E-R` → `extension/`
2. In Chrome open `chrome://extensions`
3. Turn ON **Developer mode** (top right)
4. Click **Load unpacked**
5. Select the `extension/` directory you copied
6. The "E&R PokerBet" card appears — click its **Details** → **Extension options**
   (or click the puzzle-piece icon in the toolbar → E&R PokerBet)
7. Fill in the four fields:

```
API base           https://er.example.com      ← central E&R server
API key            ***************             ← server's ER_API_KEY
Player ID          PLAYER-001
Browser instance   PLAYER-001-CHROME-01
```

8. Click **Save**. Chrome asks: *"Read and change your data on
   https://er.example.com"* → click **Allow**. (This is the host permission
   that lets the scraper talk to your central server; without it snapshots
   are blocked. For a localhost dev server no prompt appears.)
9. Open `https://poker-web.pokerbet.co.za/18751019/`, log in, sit at a table.
10. Verify: press F12 → Console → you should see
    `[ER-W4P] config | player=PLAYER-001 browser=PLAYER-001-CHROME-01 api=https://er.example.com`
    and the operator's dashboard should show your player block 🟢 ONLINE.

That's it — the same 3 files, the same steps, on 10, 20 or 100 devices. The
only per-device difference is the four option values.

## Changing settings later

Open the options page again, edit, Save. The open PokerBet tab picks up the
new values within a second (no reload needed).

## Connectivity checklist (if no snapshots appear)

- [ ] Device can reach the server: `curl http://<server>:8090/api/health` from the device
- [ ] API base in options has no trailing path (just scheme + host [+ port])
- [ ] Host permission granted (Chrome → extension Details → permissions)
- [ ] API key matches the server's `ER_API_KEY`
- [ ] Player ID / Browser ID are non-empty and unique to this device
- [ ] Server firewall allows the port (see DEPLOYMENT.md → Remote deployment)
- [ ] Console shows `[ER-W4P] config …` — if the line is missing, the content
      script did not load on the poker-web domain

## Remote vs localhost

- Local dev: API base `http://127.0.0.1:8090` works when E&R runs on the same
  machine as Chrome.
- Real multi-device: API base is the central server's address. Prefer HTTPS
  (`https://er.example.com`) — see DEPLOYMENT.md. Keep the server behind a
  firewall/VPN; the API key is the only authentication on every request.
