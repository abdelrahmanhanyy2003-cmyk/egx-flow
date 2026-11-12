# Security

EGX Flow can connect to a brokerage account, so it is built to be safe by default and to
fail closed. This page describes what it protects against, how to run it safely, and how
to report a problem.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
reporting instead: **Security → Report a vulnerability** on the repository page. Include
steps to reproduce. Never include real credentials, account numbers or tokens in a report.

## Safe by default

| Area | What EGX Flow does |
|---|---|
| **Trading** | Read-only. The broker SDK's order methods (`buy`, `sell`, `place_order`, `amend_order`, `cancel_order`, fund equivalents) are unreachable: the SDK client is wrapped in `ReadOnlyYounitClient`, which exposes only a whitelist of read methods. A test proves every trading method raises `PermissionError`. |
| **Default mode** | `DATA_MODE=demo`: simulated data, no credentials, no calls to any broker. |
| **Credentials** | Read only from the backend `.env` (git-ignored) into `SecretStr`. Never returned by any API route, never sent to the browser, never bundled into the frontend, redacted from logs. |
| **Network exposure** | The launchers bind the API and the UI to `127.0.0.1`: other devices on your network cannot reach them. |
| **Cross-site attacks** | REST: CORS allow-list (`CORS_ORIGINS`). WebSocket: the `Origin` header is checked against the same list (CORS does not cover WebSockets, so without this any open website could read your data). `Host` header allow-list (`ALLOWED_HOSTS`) blocks DNS-rebinding. |
| **Abuse limits** | Per-IP request budget (`API_RATE_LIMIT_PER_MINUTE`), WebSocket connection caps (`WS_MAX_CLIENTS`, `WS_MAX_PER_IP`), topic cap per socket, 4 KB message limit, bounded per-client queues, bounded replay window. |
| **Browser hardening** | Production UI ships a Content-Security-Policy that only allows itself and the configured backend; `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`. |
| **Input validation** | Every request body and query parameter is validated (Pydantic); symbols are restricted to short alphanumerics; SQL is parameterised (SQLAlchemy). |
| **Storage** | Recorded market data is pruned after `RECORD_RETENTION_DAYS`. Your journal and portfolio history are never pruned. |

## If you connect a real account (`DATA_MODE=live`)

* Keep it on your own computer. Do not expose a live instance to the internet or a shared network.
* If the API must be reachable from another device, set `APP_ACCESS_TOKEN` (required by every
  `/api/*` route and by `/ws`), put it behind TLS, and restrict `CORS_ORIGINS` / `ALLOWED_HOSTS`.
* Rotate your API key at the broker if you ever suspect it leaked.
* `.env` must never be committed. `.gitignore` already excludes it; check `git status` before your first push.

## Hosting a public demo

Set `PUBLIC_DEMO=true`. In this mode:

* the app **refuses to start** unless `DATA_MODE=demo`, so a real account can never be served publicly;
* every write endpoint returns `403` (journal, alert rules, layouts, watchlists, refresh, live check).
  Only replay controls are allowed, and they touch short-lived in-memory state only;
* interactive API docs (`/docs`, `/openapi.json`) are disabled;
* the UI shows a **PUBLIC DEMO · READ-ONLY** badge.

Also set `CORS_ORIGINS` and `ALLOWED_HOSTS` to your public hostnames, serve over HTTPS, and
run uvicorn with `--proxy-headers --forwarded-allow-ips=<your proxy>` so rate limits see the
real client address. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Out of scope

EGX Flow is a single-user workstation. It has no user accounts or per-user permissions; a
non-demo instance must not be shared between people.
