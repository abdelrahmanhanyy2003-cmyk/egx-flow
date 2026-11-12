# EFG Hermes Younit — API capability matrix

**Source of truth:** the official SDK at <https://github.com/efg-hermes-younit/younit-python>
(branch `master`, package version `0.1.1`, inspected 2026-11-09). Everything below was read
from the SDK's source (`src/younit/client.py`, `endpoints/*`, `models/*`,
`streaming/client.py`, `streaming/parsers.py`) and verified by installing the SDK into the
backend virtualenv and introspecting `younit.Client` / `younit.streaming.StreamingClient`.
**No endpoint, method or field in this document is assumed.** Where the SDK itself states
that something is unconfirmed, that is repeated here.

EGX Flow is **read-only**. The SDK also exposes order placement (`buy`, `sell`,
`place_order`, `amend_order`, `cancel_order`, fund equivalents). Those are unreachable in
EGX Flow: the integration wraps the SDK client in `ReadOnlyYounitClient`
(`backend/app/integrations/efg_hermes/client.py`), which only exposes a whitelist of read
methods and raises `PermissionError` for anything else. This is covered by
`test_read_only_wrapper_blocks_every_trading_method`.

## Installation

```
# PyPI package is "coming soon"; install from source (Python >= 3.11)
pip install "git+https://github.com/efg-hermes-younit/younit-python@master"
# or, without git:
pip install https://github.com/efg-hermes-younit/younit-python/archive/refs/heads/master.zip
```

The SDK depends on `mcp>=1.0,<2`, which pulls `sse-starlette` → `starlette>=0.49.1`.
EGX Flow therefore pins `fastapi==0.159.1` / `starlette==1.10.0` (see
`backend/requirements.txt`). Streaming requires `lightstreamer-client-lib>=2.0` (an SDK
dependency).

## Summary matrix

| Capability | Available | SDK method / stream | Model | Update frequency | Used by EGX Flow |
|---|---|---|---|---|---|
| Authentication | ✅ | `Client(trading_id=, api_key=)` | — (token internal) | Token refreshed 5 min before expiry; 1 re-auth on 401 | ✅ `authentication.py` |
| Stock quote (REST snapshot) | ✅ (no bid/ask) | `Client.quote(symbol)` / `stock_info` | `Quote` | On demand | ✅ price limits only |
| Market status | ✅ (empirical mapping) | `Client.market_status()`; `streaming.subscribe_market()` | `MarketUpdate.status` | Push on change | ✅ |
| Real-time L1 market data | ✅ | `streaming.subscribe_quote(symbol)` (SymbolStatistics, MERGE) | `SymbolUpdate` | Push on change | ✅ |
| Historical market data | ✅ OHLCV only | `Client.historical_prices(symbol, period, date_from, date_to)` | `HistoricalCandle` | On demand | ✅ candles, ADV, daily indicators |
| Streaming subscriptions | ✅ 5 streams | `client.streaming.*` (Lightstreamer) | see below | Push | ✅ 4 of 5 (orders stream not needed) |
| Level 1 quotes | ✅ | SymbolStatistics `bid`, `bid_volume`, `ask`, `ask_volume` | `SymbolUpdate` | Push | ✅ |
| **Level 2 order-book depth** | ❌ | — none in SDK | — | — | Heatmap falls back to **L1 only** (labelled) |
| **Historical order-book updates** | ❌ | — | — | — | Replay uses locally recorded snapshots only |
| Trade executions (tape) | ✅ real-time | `streaming.subscribe_trades(symbol)` (SecurityTrades, COMMAND) | `TradeUpdate` | Push per trade | ✅ |
| Historical trades (past sessions) | ❌ | — | — | — | Recorded locally from the live tape |
| Trade-side classification | ⚠️ undocumented semantics | `TradeUpdate.transaction_type` ("Buy/sell side indicator") | `str` | with each trade | ⚠️ ignored unless mapped; quote/tick rule **estimated** |
| Index values (EGX30) | ✅ | `streaming.subscribe_index(index_id)` (IndexStatistics, MERGE) | `IndexUpdate` | Push | ✅ |
| Market statistics (turnover, A/D) | ✅ | `streaming.subscribe_market(market_id)` | `MarketUpdate` | Push | ✅ |
| Portfolio positions | ✅ | `Client.positions(market_id)` / `position(symbol)` / `positions_split()` | `Position` | On demand | ✅ polled every 30 s |
| Available cash | ✅ | `Client.portfolio(market_id)` → `total_cash` | `PortfolioSummary` | On demand | ✅ |
| Open orders | ✅ | `Client.list_orders()`; `streaming.subscribe_orders()` | raw `dict` rows; `OrderUpdate` | On demand / push | ✅ REST (display only) |
| Executed orders | ✅ | `Client.order_history()` | `OrderHistoryEntry` | On demand | ✅ journal reconciliation |
| Transaction / cash-ledger history | ❌ | — | — | — | Not available; executed orders are the closest data |
| Historical portfolio performance | ❌ (stocks) | only `fund_performance(fund_id)` for mutual funds | — | — | EGX Flow records its own snapshots (labelled local) |
| Investor-type / participant statistics | ❌ | — | — | — | Panel shows "not available" |
| Tick size | ❌ | not in any model | — | — | Inferred from observed prices (labelled `inferred`) |
| Data entitlement flag | ✅ | `Client.account_info()` → `is_live_datafeed`, `can_setup_datafeed` | `AccountInfo` | On demand | ✅ `is_live_datafeed=False` ⇒ data labelled **DELAYED** |

## Details per capability

### Authentication
* **Method:** `younit.Client(trading_id=..., api_key=..., lazy_auth=False, lazy_symbols=False)`
  (constructor params: `trading_id, api_key, simulation, company_code, accept_language,
  timeout_seconds, token_store, lazy_auth, lazy_symbols`). `simulation=True` is currently
  disabled by the SDK (raises `ConfigError`).
* **Flow (SDK internal):** `POST https://tradingapis.efghermesone.com/api/public-keys/token`
  with `{tradingId, secret}`; response `accessToken`, `expiresIn`, `tokenType` (nested under
  `data` in production). Bearer token for REST; the same token is the Lightstreamer password
  with `TRADING_ID` as username. Refresh 5 minutes before expiry; one re-authentication and
  retry on HTTP 401. Refreshed tokens are pushed into the streaming connection
  (`StreamingClient.update_token`).
* **Entitlement:** an EFG Hermes ONE account with API access (`TRADING_ID` + `API_KEY`).
* **EGX Flow:** credentials are read from the backend `.env` into `SecretStr`, passed only to
  the SDK constructor, never logged (log redaction filter), never returned by any API route.
* **Errors:** `InvalidCredentials`, `AuthError`, `ConfigError` (missing credentials).

### Stock quote (REST)
* `Client.quote(symbol)` → `GET /api/stocks/stock-trading-info/{marketId}/{id}`.
* `Quote`: `stock_id, symbol, name, last, min_price, max_price, is_intraday, is_tplus1, market_id`.
* **Limitation:** no bid/ask/volume. EGX Flow uses it only for the daily price limits
  (`min_price` / `max_price`).

### Market status
* `Client.market_status(market_id=None, timeout=8.0)` subscribes briefly to
  MarketStatistics and reads `m_MarketStatus`; returns `"open" | "closed" | "unknown" | "unreachable"`.
* **Limitation (from the SDK docstring):** the mapping `2=open, 3=closed` is *empirically
  derived, not officially confirmed*. No REST endpoint exists for market status.
* EGX Flow uses the streaming `MarketUpdate.status` to override its configurable session
  calendar and shows the source (`provider` vs `calendar`) in the UI.

### Real-time market data / Level 1 — SymbolStatistics
* `client.streaming.subscribe_quote(symbol, on_update, on_error)`; Lightstreamer item
  `sy{stockId}`, **MERGE** mode.
* `SymbolUpdate` fields: `stock_id, symbol, name, last, open, close, high, low, bid,
  bid_volume, ask, ask_volume, volume, value, trades_count, change, change_pct,
  reference_price, week52_high, week52_low, market_cap, status_id, status, last_updated, raw`.
* **MERGE semantics:** after the initial snapshot only changed fields are sent (others are
  `None`). EGX Flow's `QuoteMerger` keeps the last known value per field.
* Callbacks run on the Lightstreamer thread; EGX Flow only normalizes and enqueues them.

### Historical market data
* `Client.historical_prices(symbol, period="Month", date_from=None, date_to=None)` →
  `GET /api/charts/GetChartingHistoricalDataFeed` (params `SecurityID, Period, DateFrom, DateTo`).
* `period` ∈ `Day | Week | Month | Year` (`younit.enums.ChartPeriod`).
* `HistoricalCandle`: `timestamp, open, high, low, close, volume`.
* **Limitation (SDK docstring):** raw timestamps are naive; the SDK *assumes* Cairo local
  time — unconfirmed with the backend team.
* **Never used to reconstruct order-book history.**

### Streaming subscriptions
Five Lightstreamer streams are documented: `SymbolStatistics` (`sy{id}`, MERGE),
`IndexStatistics` (`ix{id}`, MERGE), `MarketStatistics` (`mk{id}`, MERGE),
`SecurityTrades` (`ts{id}`, COMMAND), `ActiveOrders` (`po{profileId}`, COMMAND, trading
adapter). There is also `subscribe_raw(mode, item, fields, ...)`, which EGX Flow does not
expose. `StreamingClient.connect()` blocks up to 30 s; `is_connected()`, `disconnect()`,
`unsubscribe(sub)` are available. Lost updates are only logged by the SDK
(`onLostUpdates`), so EGX Flow adds its own heartbeat/staleness monitor and automatic
reconnection with exponential back-off (`ConnectionMonitor`).

### Level 2 depth and historical order book — **not available**
The SDK has no depth stream, depth endpoint or order-level (MBO) data. Consequences in EGX Flow:
* The heatmap for live EFG data is built from best bid/ask sizes only, labelled **L1 ONLY**
  in the chart header, order book and status page.
* Iceberg heuristics run with a reduced confidence factor (`L1_ONLY = 0.55`).
* A licensed Level 2 vendor can be added by implementing `MarketDataProvider`
  (`backend/app/providers/base.py`) and emitting `BookSnapshot` / `BookDelta` events.

### Trade executions — SecurityTrades
* `client.streaming.subscribe_trades(symbol, on_update, on_error)`; COMMAND mode, each event
  has `command` `ADD | UPDATE | DELETE`.
* `TradeUpdate`: `command, key, stock_id, ticket_number, price, volume, last_updated,
  change_from_close, change_pct_from_close, transaction_type, raw`.
* EGX Flow uses `ticket_number` (fallback `key`) as trade id for de-duplication; `DELETE`
  events are counted, not applied (their exact meaning — e.g. trade busts — is undocumented).
* **Limitations:** how many trades the initial COMMAND snapshot contains is undocumented;
  there is no historical-trades endpoint.

### Trade-side classification
* `TradeUpdate.transaction_type` is documented only as *"Buy/sell side indicator"*. It is
  **not** documented as the aggressor side, and its value set is not documented.
* EGX Flow therefore **does not use it** for CVD by default. It stores the raw value
  (`provider_side_raw`) and classifies with the quote rule (vs prevailing L1 bid/ask) then
  the tick rule. Those trades are marked **estimated** everywhere (hollow bubbles, `EST`
  badges, CVD "% side-estimated").
* Once EFG Hermes confirms the semantics, set `EFG_TRANSACTION_TYPE_MAP` (e.g. `B:buy,S:sell`)
  and those trades become `method=provider`.

### Portfolio, cash, orders
* `Client.portfolio(market_id)` → `GET /api/portfolio/GetPortfolioSummary` →
  `PortfolioSummary`: `client_id, market_id, total_cash, total_stocks, total_balance,
  realized_profit, unrealized_profit, profit_or_loss, unrealized_profit_pct, currency`.
* `Client.positions(market_id)` → `GET /api/portfolio/GetStocksPortfolio` → `Position`:
  `stock_id, symbol, name, name_ar, quantity, unsettled_qty, qty_valid_for_sale, frozen_qty,
  average_price, market_price, market_value, total_value, unrealized_pnl,
  unrealized_pnl_pct, realized_pnl, profit_or_loss, currency, is_fund, is_suspended`.
  Fund holdings come from `fund_positions()` (`GET /api/portfolio/GetPortfolioSecurities`).
* `Client.list_orders(profile_id=None, market_id=None)` → `POST /core-services/Orders` (a
  query, no side effects) → raw rows `OrderId, StockId, ProfileId, Quantity, Price, Status`.
* `Client.order_history(profile_id=None, market_id=None)` →
  `GET /api/stocks/order-history/{MarketId}/{ProfileId}` → `OrderHistoryEntry`:
  `stock_id, order_id, order_type_id, quantity, price, average, order_amount, stock_name,
  short_name, order_type, transaction_type, placed_by, reuter_id, currency_short_name,
  status, status_color, reject_reason, order_date, is_rejected, is_market_price, show_price`.
* **Note:** `list_orders` / `order_history` need a `profile_id`; the SDK resolves it lazily
  by calling `GET /api/v1/trading/buying-power/normal/{stockId}` (a read-only GET).
* **Not available:** cash ledger / account statements, historical portfolio valuation for
  stocks. EGX Flow records its own portfolio snapshots every 60 s and labels the equity
  curve and drawdown as *locally calculated*.

### Instruments
* `Client.list_stocks(market_id)` → `GET /api/stocks/market/{marketId}` → `StockInfo`
  (`stock_id, symbol, name, short_name, reuters_code, market_id, currency, is_auction, last,
  is_intraday, is_tplus1, security_class_id, security_class_name, is_same_day_eligible`).
* `security_class_*` is enriched client-side by the SDK **from a point-in-time snapshot**
  (not live). EGX Flow keeps equities (`LocalSecurity_IN`, `LocalSecurity_OUT`, `OTC`) and
  shows the class as the sector field; there is no GICS-style sector in the SDK.
* Tick size is not exposed anywhere ⇒ inferred from observed prices and labelled.

### Rate limits and errors
* No published quota. The SDK raises `RateLimited` on HTTP 429 and retries idempotent GETs on
  5xx / connection errors (never order placement paths).
* EGX Flow adds a client-side token bucket (`EFG_MAX_REQUESTS_PER_MINUTE`, default 60) and
  exponential back-off on `RateLimited` (`rate_limit.py`); counts are on the Status page.
* Exception hierarchy: `EFGError` → `AuthError` (`InvalidCredentials`, `TokenExpired`),
  `APIError` (`BadRequest`, `Unauthorized`, `Forbidden`, `NotFound`, `RateLimited`,
  `ServerError`), `OrderError`, `InvalidSymbol`, `ConfigError`, `StreamingError`
  (`ConnectionFailed`, `SubscriptionFailed`).

## Open questions to confirm with EFG Hermes
1. Semantics and value set of `TradeUpdate.transaction_type` (aggressor side?).
2. Whether a Level 2 / market-depth feed exists or is planned for API clients.
3. Official `m_MarketStatus` code mapping (pre-open / auction states).
4. Timezone of `HistoricalCandle` timestamps and `TradeUpdate.last_updated` format.
5. Size of the SecurityTrades initial COMMAND snapshot; meaning of `DELETE` events.
6. Request quotas for REST endpoints.
