#!/usr/bin/env bash
# EGX Flow launcher (macOS / Linux). Sets everything up on first run, then runs the
# API and the UI on this computer only (127.0.0.1). Press Ctrl+C to stop both.
#
#   ./scripts/start.sh                      # demo data unless .env says otherwise
#   API_PORT=8001 UI_PORT=3200 ./scripts/start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-3100}"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUN="$ROOT/.run"
mkdir -p "$RUN"

say() { printf '\033[36m[EGX Flow]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[EGX Flow]\033[0m %s\n' "$*" >&2; exit 1; }

PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || [ -x "$BACKEND/.venv/bin/python" ] || fail "Python 3.11+ was not found."
command -v node >/dev/null 2>&1 || fail "Node.js 20+ was not found."
[ "$(node -p 'parseInt(process.versions.node)')" -ge 20 ] || fail "Node.js 20+ is required."

[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; say "Created .env (demo mode, simulated data)."; }

if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  say "First run: creating the Python environment..."
  "$PY" -m venv "$BACKEND/.venv"
fi
VPY="$BACKEND/.venv/bin/python"
if ! "$VPY" -c 'import fastapi, uvicorn, sqlalchemy, alembic, pydantic_settings' 2>/dev/null; then
  say "Installing backend packages..."
  "$VPY" -m pip install --disable-pip-version-check -q -r "$BACKEND/requirements.txt"
fi

cd "$FRONTEND"
if [ ! -d node_modules/next ]; then
  say "First run: installing UI packages..."
  if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
fi
export NEXT_DIST_DIR=".next-prod" NEXT_PUBLIC_API_BASE="http://localhost:$API_PORT" NEXT_TELEMETRY_DISABLED=1
STAMP="$RUN/ui-build.txt"
if [ ! -f .next-prod/BUILD_ID ] || [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$NEXT_PUBLIC_API_BASE" ] ||
   [ -n "$(find src package.json next.config.ts -newer .next-prod/BUILD_ID -type f -print -quit)" ]; then
  say "Building the UI (about a minute, only when it changed)..."
  node node_modules/next/dist/bin/next build >/dev/null
  printf '%s' "$NEXT_PUBLIC_API_BASE" > "$STAMP"
fi

cleanup() { say "Stopping..."; kill "${API_PID:-}" "${UI_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$BACKEND"
CORS_ORIGINS="http://localhost:$UI_PORT,http://127.0.0.1:$UI_PORT" \
  "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$RUN/api.log" 2>&1 &
API_PID=$!
cd "$FRONTEND"
node node_modules/next/dist/bin/next start -p "$UI_PORT" -H 127.0.0.1 >"$RUN/ui.log" 2>&1 &
UI_PID=$!

say "Preparing market data (demo mode pre-generates 20 minutes of history; up to a minute)..."
for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null | grep -q '"ok":true' &&
     curl -fsS -o /dev/null "http://127.0.0.1:$UI_PORT" 2>/dev/null; then
    say "Running at http://localhost:$UI_PORT  (Ctrl+C to stop). Only this computer can reach it."
    (command -v xdg-open >/dev/null && xdg-open "http://localhost:$UI_PORT") ||
      (command -v open >/dev/null && open "http://localhost:$UI_PORT") || true
    wait
    exit 0
  fi
  kill -0 "$API_PID" 2>/dev/null || { tail -n 20 "$RUN/api.log" >&2; fail "The engine stopped during startup."; }
  sleep 1
done
fail "EGX Flow did not come up in time. See $RUN/api.log"
