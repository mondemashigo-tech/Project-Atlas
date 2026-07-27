# Atlas Live — Testing

Run everything: `python -m pytest -q` (135+ tests).

## Event spine (`tests/test_events.py`)

Schema validation, row round-trip, bus persist/stream/catch-up, `NullBus`
silence, a **real council run emitting ordered events** with replay-after-
reconnect, and the untouched-engine-emits-nothing guarantee.

## Backend API (`tests/test_live_api.py`)

A real council experiment populates the store; the API is exercised with FastAPI
`TestClient`:
- overview, health, agents (real roster; **all idle after a run** — no fabricated
  activity), agent detail + 404, experiments list + detail (decision ladder +
  event timeline), graveyard/registry/knowledge/governance.
- events by `after_seq` cursor; **SSE generator** replays persisted events then
  emits the connected marker (tested at generator level — TestClient can't
  iterate an infinite stream).
- **grounded chat**: "why was EXP-… rejected" is grounded and cites the
  experiment/hypothesis; `llm_used` is false with no key; an unknown query stays
  honest.
- morning brief with activity, and the **no-activity** path on an empty root.
- research trigger safety: path-traversal rejected, single-flight enforced, bad
  hypothesis → 400, and a **real end-to-end run** that completes and emits new
  events.
- frontend assets served.

## Hardened dashboard (`tests/test_dashboard_server.py`)

Serves HTML, **survives a mid-request client disconnect**, `handle_error`
swallows the benign connection-reset family.

## Manual / visual checks

The SPA was verified under real `uvicorn` + headless Chromium: the Console
streams real event rows (`skeptic_rejected`, `governance_checked`, …), the
Chamber shows the real roster idle, layout is full-width (`.view` = 1200px), and
the SSE fix (default `message` frames) populates the console live. Reduced-motion
and mobile breakpoints are CSS-driven.

## Known testing gaps (honest)

- No JS unit-test runner; frontend logic is covered by the API contract + manual
  browser/Playwright checks rather than headless JS assertions.
- SSE live-streaming under load and multi-client fan-out are covered structurally
  (hub unit behaviour + generator replay), not with many concurrent real clients.
