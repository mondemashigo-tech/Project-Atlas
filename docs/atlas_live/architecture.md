# Atlas Live — Architecture

```
 Browser (vanilla JS SPA)                      atlas/live/
 ┌───────────────────────────┐        ┌──────────────────────────────┐
 │ Chamber · Console · Exp    │  HTTP  │ app.py     FastAPI routes     │
 │ Chat · Voice · Brief       │◀──────▶│ services.py read helpers      │
 │ EventSource (SSE)          │  SSE   │ chat.py    grounded answers   │
 └───────────────────────────┘        │ brief.py   morning brief      │
                                       │ roster.py  agent state        │
                                       │ runner.py  bg research run    │
                                       │ hub.py     live fan-out       │
                                       └───────┬──────────────┬────────┘
                                               │ calls        │ subscribes
                                     ┌─────────▼───────┐  ┌───▼──────────┐
                                     │ atlas engine    │  │ EventBus     │
                                     │ orchestrator,   │─▶│ (persist +   │
                                     │ service, agents │  │  stream)     │
                                     └─────────┬───────┘  └───┬──────────┘
                                               │ writes       │ writes
                                          ┌────▼──────────────▼────┐
                                          │ SQLite (source of truth)│
                                          │ + Obsidian vault mirror │
                                          └─────────────────────────┘
```

## Principles

- **Read-mostly surface.** The API reads the source of truth and the event spine;
  research logic stays in the engine. The one write path is a research-only run.
- **Events, not scraping.** The UI is powered by the typed event spine (M1), not
  by parsing terminal text.
- **Idle is honest.** Agent state derives from real events; no recent event → idle.
- **Persist then stream.** Events are written to SQLite (monotonic `seq`) then
  fanned out; reconnecting clients replay from their last `seq`.

## Threading & SQLite

The engine runs on its own thread (the `Runner`) with its own store connection;
the live `Hub` is SQLite-free and only fans event dicts to SSE clients; each API
request opens its own short-lived store. This avoids cross-thread SQLite sharing
entirely.

## Data flow for a live run

1. `POST /api/research/run` → `Runner` spawns a thread, builds an `EventBus`
   bound to a thread-local store, subscribes a hub-broadcast handler.
2. `Orchestrator.run(..., bus=bus)` emits typed events; each is persisted (seq)
   and broadcast to the hub.
3. Every connected SSE client receives the event; the Chamber lights up the real
   agent, the Console appends the row. On completion, agents return to idle.
4. A browser that refreshes reconnects with `Last-Event-ID = last seq` and
   replays exactly what it missed from SQLite.

## Modules

See `api.md` (endpoints), `event_model.md` (events), `frontend.md` (SPA),
`voice.md`, `security.md`.
