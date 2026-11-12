# Performance notes

## Frontend heatmap engine
* **No React in the hot path.** WebSocket messages mutate `Series` objects directly
  (`lib/series.ts`). The canvas engine polls `series.version` inside `requestAnimationFrame`
  and only redraws when data changed or the user interacted (idle = ~0 CPU).
* **Incremental texture.** Liquidity history lives in a 7200×900 offscreen canvas
  (1 px per sample × 1 px per tick). A new sample paints one pixel column into an
  `ImageData` buffer and flushes a dirty-rect `putImageData`. A frame is one scaled
  `drawImage` of the visible window plus vector overlays. Full rebuilds happen only on
  settings change, price-range overflow (re-centres) or capacity overflow.
* **Log intensity scaling** relative to the median resting size keeps typical liquidity in
  the blue/cyan range; the top ~0.5% saturates (walls) — computed once per rebuild.
* **Bubbles** are aggregated per time bucket (configurable) and cached per viewport/version;
  capped at 8 000 drawn per frame. Trades are stored struct-of-arrays with binary search
  on time for the visible window.
* React panels (order book, tape, stats) re-render through `useSeriesTick` throttled to
  200–1000 ms.
* Memory caps: 20 000 columns, 60 000 trades per open symbol on the client.

### Measured (dev build, Chromium, DPR 1.25, ~1 300 heat columns × 60 levels, ~1 600 trades)
`window.__egxEngine.benchmark(frames, width, height)` (dev only) pans, zooms and hovers
while rendering synchronously:

| Canvas | avg / frame | p95 | max | full texture rebuild |
|---|---|---|---|---|
| 1400×700 | 0.45 ms | 0.9 ms | 8.1 ms | 41 ms |
| 2400×1100 | 0.62 ms | 1.0 ms | 9.5 ms | 44 ms |

These are CPU-side submission times; GPU compositing is not included. They leave a large
margin under the 16.7 ms budget for 60 FPS. Rebuilds happen only on settings changes,
re-centering or capacity overflow.

## Backend
* Asyncio single-writer design, no locks on hot state. Sampler (1 s), broadcaster
  (250 ms), analytics (2 s), recorder flush (2 s) run as separate tasks.
* Measured on the dev machine (Windows, Python 3.13, 16 simulated symbols at 4 Hz,
  ~600 events/s): event-loop lag ≈ 10 ms, zero buffer overflow; 20-minute demo prewarm
  (≈ 80 k events) ≈ 15–20 s at startup.
* Hot spots fixed during profiling: wall-threshold sampling over heatmap history was
  O(history) per second → replaced by an incremental EMA of the median level size
  (5× faster prewarm).
* DB writes are batched (2 000 rows per statement) and idempotent (`INSERT … ON CONFLICT DO NOTHING`).
* Book snapshots are recorded at `BOOK_SNAPSHOT_RECORD_S` (default 1 s, top 30 levels).
  Recorded data older than `RECORD_RETENTION_DAYS` (default 3) is pruned hourly in
  one-hour slices so the recorder is never blocked; use TimescaleDB compression in production.

## Tuning knobs
`HEATMAP_RESOLUTION_MS`, `HEATMAP_HISTORY_COLUMNS`, `HEATMAP_DEPTH_LEVELS`,
`BROADCAST_INTERVAL_MS`, `EVENT_QUEUE_SIZE`, `TRADE_HISTORY_LIMIT`,
`BOOK_SNAPSHOT_RECORD_S`, `RECORD_RETENTION_DAYS`, `REPLAY_MAX_WINDOW_HOURS`, `DEMO_PREWARM_MINUTES`.

## Profiling
```
cd backend
.venv\Scripts\python -m cProfile -o prof.out -m uvicorn app.main:app --port 8000
```
Browser: Performance panel → record while panning the heatmap; frames should be dominated
by `drawImage` and bubble arcs.
