# Atlas Live — Deployment

## Local (recommended)

```
py -m pip install fastapi "uvicorn[standard]"
py -m atlas live                 # http://127.0.0.1:8800
```

Runs against the current working directory's Atlas root (SQLite + vault). Use
`--port` to change the port. Ctrl+C to stop. The engine, CLI, and nightly script
are unaffected and can run alongside it (each opens its own SQLite connection).

## Watching live activity

Atlas is idle between runs. To see the Chamber/Console come alive:
- trigger a run from the Chamber (enter a hypothesis name), or
- run the CLI/nightly script; those runs persist events that the web app streams
  and replays (they also show up in history on next connect).

> Note: CLI/nightly runs currently persist events **if invoked with a bus**. The
> web app's own run trigger always streams live. Wiring the standalone CLI
> commands and the nightly script to emit events is a follow-up (they populate
> experiments/records regardless, which the web app reads).

## LAN access (trusted networks only)

```
py -m atlas live --lan --port 8800     # binds 0.0.0.0, NO authentication
```

Reachable at `http://<your-ip>:8800` from other devices. **There is no auth** —
only do this on a network you trust. Add authentication before any wider
exposure.

## Read-only instance

```
py -m atlas live --no-run
```

Disables the research-run trigger; the app becomes a pure viewer.

## Fallback dashboard

The pre-existing dashboard remains available and hardened:
```
py -m atlas dashboard --serve          # auto-refresh HTML, disconnect-safe
py -m atlas dashboard                   # write a static atlas_dashboard.html
```

## Stopping safely

Ctrl+C stops the server; in-flight research runs are daemon threads and end with
the process. No capital or external action is ever taken, so stopping is always
safe.

## Requirements

`fastapi`, `uvicorn[standard]` (optional — only for `atlas live`). Core lab needs
only pandas/numpy/pyyaml. `ANTHROPIC_API_KEY` (optional) enables LLM phrasing in
chat; without it, chat returns record-only answers.
