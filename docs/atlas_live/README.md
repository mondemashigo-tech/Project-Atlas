# Atlas Live

An interactive web application over the Atlas research engine: watch the council,
read the live event console, inspect experiments, and ask Atlas questions by text
or voice — all driven by **real** persisted records and events. It never
fabricates activity and never touches capital.

## Quick start

```
py -m pip install fastapi "uvicorn[standard]"
py -m atlas live                 # http://127.0.0.1:8800
```

Options:
- `--port N` (default 8800)
- `--lan` bind `0.0.0.0` for other devices on your network — **no auth; trusted
  networks only.**
- `--no-run` disable the research-run trigger (fully read-only instance).

The existing dashboard remains available as a fallback: `py -m atlas dashboard --serve`.

## What you can do

- **Council Chamber** — the real 10-agent council + Backtester around the Atlas
  core. State comes from live events; idle means idle. Click an agent for its
  recent activity and to ask it about its work. Trigger a research run.
- **Live Console** — structured system events streaming over SSE: operational
  status, actions, decisions, evidence refs. Filter by agent/type/severity,
  search, pause. Survives refresh/reconnect (replays missed events).
- **Experiments** — a research funnel (real counts) and a detail drawer per
  experiment: verdict, metrics, the decision ladder, event timeline. Charts show
  an honest "unavailable" state when raw data isn't stored.
- **Registry / Graveyard / Knowledge / Governance** — the records, as they are.
- **Morning Brief** — what happened overnight, from real activity (or an honest
  "nothing ran").
- **Ask Atlas** — grounded chat. Answers are built from records and cite them;
  with an `ANTHROPIC_API_KEY` the LLM only *phrases* retrieved records, never
  invents. Voice is a read-only layer over the same grounded system.

## Non-negotiables honoured

- SQLite stays the source of truth; migrations are additive only.
- Research logic is untouched; the API calls existing services.
- Nothing reaches capital without explicit human approval — voice and UI are
  read-only except a research-only run trigger.
- The console shows operational events, never private chain-of-thought.
- Every conclusion links back to an experiment/hypothesis/memo/record id.

## Docs

`architecture.md`, `event_model.md`, `api.md`, `frontend.md`, `voice.md`,
`security.md`, `testing.md`, `deployment.md`, `jarvis_integration.md`,
`current_system_baseline.md`, `ADR-001-web-application-architecture.md`,
`ADR-002-voice-architecture.md`.
