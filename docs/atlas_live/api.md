# Atlas Live — API

FastAPI app (`atlas/live/app.py`), created by `create_app(root, allow_run=True)`.
Local-only by default (`127.0.0.1`). All read endpoints open a short-lived store
per request; routes call services, never research logic.

## Read

| Method / path | Returns |
|---|---|
| `GET /api/overview` | counts, decision tally, recent experiments, graveyard count, latest event seq |
| `GET /api/system/health` | status, db path, counts, latest seq |
| `GET /api/agents` | roster with live state (idle unless a recent event) + runner status |
| `GET /api/agents/{id}` | agent meta + state + recent activity |
| `GET /api/agents/{id}/activity` | recent events for the agent |
| `GET /api/experiments?limit=` | experiment summaries |
| `GET /api/experiments/{id}` | experiment + hypothesis + decision ladder + event timeline |
| `GET /api/hypotheses/{id}` | hypothesis record |
| `GET /api/graveyard` · `GET /api/registry` · `GET /api/knowledge` · `GET /api/governance` | records |
| `GET /api/reports/morning-brief?hours=24` | brief (or honest no-activity) |
| `GET /api/events?after_seq=&task_id=&event_type=&agent_id=&severity=&limit=` | filtered events (seq order) |
| `GET /api/events/stream?after_seq=` | **SSE**: replay from cursor, then live. Honours `Last-Event-ID` on reconnect. |

## Write (read-mostly)

| Method / path | Notes |
|---|---|
| `POST /api/chat` `{message, agent_id?, transcript_source?}` | grounded answer + citations |
| `POST /api/agents/{id}/query` `{message}` | ask a specific agent |
| `POST /api/research/run` `{hypothesis, window?, data_utc_offset?}` | **research-only** council run; single-flight; path-confined to root; never capital |
| `GET /api/research/status` | `{running, current}` |

Disable the run trigger entirely with `create_app(root, allow_run=False)` or
`atlas live --no-run`.

## SSE frame format

```
id: <seq>
data: {<event JSON, includes event_type>}
```

No custom `event:` field (that would bypass `EventSource.onmessage`); the type
rides in the JSON. `id` feeds `Last-Event-ID` so a reconnecting browser resumes
at its last `seq`. `: keepalive` comments hold the connection open.

## Errors & validation

Pydantic models bound message/hypothesis length; unknown ids → 404; unsafe or
missing hypothesis path → 400; run trigger disabled → 403. No endpoint executes
shell commands or returns secrets.
