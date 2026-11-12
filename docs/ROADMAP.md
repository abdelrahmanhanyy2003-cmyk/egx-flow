# Implementation roadmap & status

| Phase | Scope | Status (v0.1) |
|---|---|---|
| 1 — Discovery | SDK inspection, capability matrix, architecture, data flow | ✅ `docs/EFG_API_CAPABILITIES.md`, `docs/ARCHITECTURE.md` |
| 2 — Foundation | FastAPI backend, Next.js frontend, DB + migrations, Redis (optional), Docker Compose, provider abstraction, demo provider | ✅ |
| 3 — Visualization | heatmap, bubbles, volume bars, order book, volume profile (session/visible, POC/VA), CVD, imbalance, depth | ✅ canvas engine |
| 4 — Younit integration | auth via SDK, L1 quotes, trade tape, market/index stats, portfolio, positions, orders, normalization, connection monitoring, rate limiting, entitlement-aware quality labels | ✅ code + mocked tests; ⏳ needs a live run with real credentials |
| 5 — Quant intelligence | Whale Radar, LLT, walls, icebergs (heuristic), absorption, accumulation/distribution, explainable whale score, alerts | ✅ |
| 6 — Portfolio | overview, positions, P&L, risk, equity curve (local snapshots), journal with FIFO, reconciliation | ✅ |
| 7 — Replay & QA | recorder, replay (same engine), 95 backend tests (+2 opt-in live checks) + frontend tests, security review | ✅ |

## Next steps (prioritised)
1. **Live validation with your EFG account** — run `DATA_MODE=live`, then the authorized
   live checks (`EGXFLOW_LIVE_TESTS=1 pytest app/tests/test_live_efg.py`). Confirm the
   `last_updated` formats and the `transaction_type` semantics with EFG Hermes, then set
   `EFG_TRANSACTION_TYPE_MAP` if it is the aggressor side.
2. **Licensed Level 2 feed** — implement `MarketDataProvider` for an EGX depth vendor
   emitting `BookDelta`; the heatmap, walls and iceberg confidence upgrade automatically.
3. Multi-provider composition (L1/trades from Younit + depth from vendor) via a
   `CompositeProvider` that merges event streams per symbol.
4. WebGL heatmap backend for 4K multi-chart layouts (the texture model already maps 1:1
   to a GPU texture).
5. Recorded-session export (Parquet) and backtesting of signal thresholds.
6. Per-user auth (OIDC) if the app is ever exposed beyond localhost.
