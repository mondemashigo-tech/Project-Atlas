# ADR-001 — Atlas Live web application architecture

**Status:** accepted · **Date:** 2026-07 · **Milestone:** M2

## Context (current architecture, from the audit)

- No web framework existed; the dashboard was a single-threaded stdlib
  `http.server` re-rendering one HTML string per request, refreshed by a
  `<meta refresh>` tag (source of the benign `WinError 10053` traceback).
- Clean service layer already present (`atlas/service.py`,
  `atlas/kernel/orchestrator.py`); SQLite is the source of truth.
- Execution is synchronous; the system is idle except during a run.

## Options considered

1. **FastAPI + SSE + React/Vite frontend.** Richest DX for complex UI, but adds a
   Node toolchain, `node_modules`, and a build step to maintain on a solo laptop.
2. **FastAPI + SSE + self-contained vanilla-JS frontend (chosen).** No build step;
   Python is the only runtime. Slightly more manual DOM code; the cinematic look
   is CSS (identical either way).
3. **Keep stdlib http.server, add polling.** Lowest complexity, but no real live
   streaming, and the refresh-churn/stability issues remain.

## Decision

**Option 2.** FastAPI (`atlas/live/app.py`) wrapping existing services;
**Server-Sent Events** for the event stream (one-way server→client fits the
console/chamber; `EventSource` gives auto-reconnect + `Last-Event-ID` replay for
free); a **self-contained vanilla-JS/CSS frontend** served by FastAPI from
`atlas/live/web/` (no build step). SQLite retained; **additive migrations only**.

### Why SSE over WebSocket

The UI only needs server→client push. SSE is simpler, rides plain HTTP, and its
built-in reconnect + `Last-Event-ID` maps exactly onto our persisted-event
`seq` cursor — satisfying the "survive refresh/reconnect without losing history"
requirement with almost no client code. WebSockets would add bidirectional
complexity we don't need.

## Migration approach

Purely additive. New package `atlas/live/`, new `events`/`conversations` tables
(`CREATE TABLE IF NOT EXISTS`), a `bus=None` parameter on `Orchestrator.run`. The
old dashboard is untouched and remains the fallback. No research behaviour
changes; a test asserts the engine emits nothing without a bus.

## Risks & rollback

- **Risk:** FastAPI/uvicorn as new deps → kept **optional** (core CLI runs
  without them); `atlas live` prints an install hint if missing.
- **Risk:** SQLite cross-thread use → each request/thread opens its own
  connection; the live hub is SQLite-free.
- **Rollback:** delete `atlas/live/`, drop the two optional deps, and the CLI +
  hardened dashboard remain fully functional. The additive tables are inert if
  unused.
