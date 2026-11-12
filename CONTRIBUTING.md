# Contributing

Thanks for helping. A few ground rules keep the project trustworthy:

1. **Read-only stays read-only.** No order placement, amendment or cancellation — in any provider.
2. **Never fabricate data.** Anything estimated or heuristic must be labelled as such in the
   API and the UI. Simulated data is always marked `simulated` / DEMO.
3. **Only documented broker capabilities.** Do not add endpoints, SDK methods or fields that
   are not in the official SDK. Update `docs/EFG_API_CAPABILITIES.md` when the SDK changes.
4. **No secrets.** Never commit `.env`, credentials, tokens or real account data — not in code,
   tests, issues or screenshots.

## Workflow

```bash
# backend
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest

# frontend
cd frontend && npm ci && npm run typecheck && npm test && npm run build
```

* Put calculations in `backend/app/analytics/` as pure functions with unit tests.
* Keep React out of the per-frame rendering path (`frontend/src/components/terminal/engine`).
* New data sources implement `MarketDataProvider` and declare honest capabilities.
* Run both test suites before opening a pull request; CI runs the same commands.

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
