# Development guide

## Prerequisites
* Python 3.11+ (tested 3.13), Node.js 20+ (tested 26), npm.
* Optional: Docker (PostgreSQL/TimescaleDB + Redis), git (for installing the SDK).

## Backend
```
cd backend
py -3.13 -m venv .venv            # Windows   (python3 -m venv .venv on macOS/Linux)
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip install "git+https://github.com/efg-hermes-younit/younit-python@master"   # only for live mode
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
* API docs: <http://localhost:8000/docs>. Health: `/api/health`.
* Migrations run automatically at startup (`alembic upgrade head`). Manual:
  `.venv\Scripts\alembic upgrade head` (from `backend/`).
* Tests: `.venv\Scripts\python -m pytest` (no credentials, no network needed).

### Adding a market-data provider
1. Implement `MarketDataProvider` (`app/providers/base.py`): `capabilities`, `status`,
   `start(sink)`, `stop`, `list_instruments`, `subscribe`, `unsubscribe`,
   optionally `historical_candles`.
2. Push normalized events (`Quote`, `Trade`, `BookSnapshot`, `BookDelta`, `MarketStats`,
   `IndexValue`, `ProviderStatusEvent`) into `sink` from any thread.
3. Declare honest capabilities (`book_resolution`, `trade_side`, `quality`).
4. Wire it in `app/services/container.py`.

### Adding an analytic
Put pure logic in `app/analytics/`, unit-test it, then call it from `SymbolState`
(`on_trade`, `sample`, or `analytics_tick`). Emit events via `SymbolState._emit` to get
recording, alerts and WebSocket delivery for free.

## Frontend
```
cd frontend
npm install
npm run dev             # http://localhost:3000   (npm run dev -- -p 3100 for another port)
npm run build           # production build (the launcher builds into .next-prod instead)
npm run typecheck
npm test
```
* Backend URL: `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`) in `frontend/.env.local`.
* The heatmap engine is plain TypeScript (`components/terminal/engine`). Keep React out of
  per-frame paths.

## Demo data
`DATA_MODE=demo` starts a deterministic simulator (`DEMO_SEED`) for 16 EGX tickers with
regimes, walls, icebergs and block prints. All demo data is labelled **DEMO / simulated** in
the API (`quality: "simulated"`) and the UI. 20 minutes of history are pre-generated at
startup (`DEMO_PREWARM_MINUTES`) and recorded so Replay works immediately.

## Code conventions
* Internal timestamps: UTC epoch **milliseconds**; display in `Africa/Cairo`.
* Money: EGP. Never invent a trade side; estimated sides are labelled.
* No secrets in logs (redaction filter), no credentials in API responses or the frontend.
