# Deployment

EGX Flow is designed as a **single-user, read-only workstation** for the account owner.
Run it on your own machine or a private server you control.

## Docker Compose (TimescaleDB + Redis + API + UI)
```
cp .env.example .env        # fill TRADING_ID / API_KEY for live mode, set DATA_MODE
docker compose up --build
```
* UI: <http://localhost:3000>, API: <http://localhost:8000>.
* The backend image installs the official Younit SDK from GitHub (`YOUNIT_REF` build arg).
* Credentials are injected at runtime through `env_file`; they are never baked into images.
* TimescaleDB hypertables are created by migration `0001_initial` when the extension is available.

## Bare metal / VM
1. Backend: Python venv, `pip install -r requirements.txt` + SDK, then
   `uvicorn app.main:app --host 127.0.0.1 --port 8000` behind a reverse proxy (TLS).
2. Frontend: `npm ci && npm run build && npm start` (set `NEXT_PUBLIC_API_BASE` at build time).
3. Use PostgreSQL+TimescaleDB via `DATABASE_URL=postgresql+psycopg://...`.

## Hosting a public demo (simulated data only)

Use this to let other people try EGX Flow in their browser without installing anything.

```
DATA_MODE=demo
PUBLIC_DEMO=true                       # refuses to start unless DATA_MODE=demo
CORS_ORIGINS=https://demo.example.com  # the UI's public origin
ALLOWED_HOSTS=api.demo.example.com     # the API's public host name
API_RATE_LIMIT_PER_MINUTE=300
RECORD_RETENTION_DAYS=1
```

* Leave `TRADING_ID` / `API_KEY` empty on that server.
* Build the UI with `NEXT_PUBLIC_API_BASE=https://api.demo.example.com`.
* Put both behind HTTPS (the WebSocket then uses `wss://` automatically) and run uvicorn with
  `--proxy-headers --forwarded-allow-ips=<proxy address>` so rate limits see real client IPs.
* In this mode all write endpoints return 403, `/docs` is disabled and the UI shows a
  **PUBLIC DEMO · READ-ONLY** badge. Visitors keep their own layout in their browser.
* One process serves everyone (the simulator plus WebSocket fan-out). Load-test before
  sharing the link widely, and cap connections with `WS_MAX_CLIENTS` / `WS_MAX_PER_IP`.

## Security checklist
* Keep the API on `127.0.0.1` or behind a VPN. If reachable by others, set
  `APP_ACCESS_TOKEN` (required by all `/api/*` routes and `/ws`) **and** terminate TLS.
* Restrict `CORS_ORIGINS` to the UI origin.
* `.env` is git-ignored; never commit it. Rotate the API key from EFG Hermes ONE if leaked.
* Logs are JSON with redaction of tokens, keys, account identifiers.
* The platform is read-only: order-placement SDK methods are unreachable by design and by test.

## Backups & integrity
* PostgreSQL: `pg_dump -Fc egxflow > egxflow_$(date +%F).dump` daily; enable TimescaleDB
  compression for chunks older than 7 days.
* SQLite: copy `backend/data/egxflow.db` while the app is stopped (WAL mode), or use
  `sqlite3 egxflow.db ".backup egxflow.bak"`.
* Inserts are idempotent (natural keys), so replaying a recorder batch never duplicates data.
* The Status page shows sequence gaps, duplicates, late events and buffer overflow per stream.

## Operations
* `/api/health` for liveness, `/api/system/status` for detailed health (provider state,
  reconnects, 429 count, loop lag, DB row counts).
* Live connectivity check: Status page → "Run authorized live check" (read-only calls).
