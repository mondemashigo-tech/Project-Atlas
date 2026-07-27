# Atlas Live — Event Model (M1)

The typed event spine is the real-time nervous system for Atlas Live. Events are
**emitted by the engine as it actually works**, persisted to SQLite, streamed to
connected clients, and replayable after a reconnect. Nothing here fabricates
activity — every event corresponds to a real call site.

## Core principle

> With **no bus attached**, the engine behaves exactly as before and emits
> nothing. Events are pure side-effects. A test (`test_untouched_engine_emits_no_events`)
> enforces this.

## `Event` (atlas/events/model.py)

A dataclass. Key fields (only meaningful ones are populated per event):

| field | meaning |
|---|---|
| `seq` | monotonic stream cursor, assigned by the store on write. **The reconnect cursor.** |
| `event_id` | stable unique id (`EV-…`) for referencing one event |
| `event_type` | one of `EVENT_TYPES` (validated) |
| `timestamp_utc`, `created_at` | ISO timestamps |
| `agent_id`, `agent_name` | which actor (e.g. `Skeptic`) |
| `task_id` | correlates events of one run (= hypothesis id for a council run) |
| `cycle_id` | correlates events of a loop cycle (future) |
| `hypothesis_id`, `experiment_id`, `strategy_id` | record links |
| `severity` | `info` \| `warning` \| `error` |
| `status` | `started` \| `completed` \| `blocked` |
| `title`, `summary` | short human text |
| `evidence_refs` | list of ids/paths backing the event (memo path, exp id, snapshot id…) |
| `progress_current`, `progress_total` | **None ⇒ indeterminate** (never fake a %) |
| `metadata` | typed extras (verdict, counts…) |
| `source_module` | emitting module |
| `is_historical` | true if backfilled, false if live |

Validation: `__post_init__` rejects an unknown `event_type` or `severity`, so a
new type must be added to `EVENT_TYPES` **beside the real call site** that emits
it — never speculatively.

## Event types emitted today (M1)

M1 instruments exactly one path: **hypothesis → council → backtest → verdict →
report** (`atlas/kernel/orchestrator.py`). Emitted, in order:

1. `experiment_started` — run kickoff (window, hyp path)
2. `agent_started` (Backtester) → `backtest_completed` — deterministic engine; carries experiment id, verdict, trade count, engine version
3. `agent_started`/`agent_completed` (Historian) — novelty check
4. `agent_started`/`agent_completed` (Statistician) — statistical review
5. `agent_started` (Skeptic) → `skeptic_rejected` **or** `agent_completed` (Skeptic)
6. `governance_checked` — OOS look budget (warning if burned)
7. *(only if it advances)* `agent_*` (RiskManager, Portfolio), `hypothesis_registered` (non-capital candidate; promotion stays human-gated)
8. `agent_started` (Reporter) → `report_completed` — memo path in `evidence_refs`
9. `experiment_completed` — verdict, reached layer, advanced, candidate id
10. `system_error` — only if the run raises (severity `error`)

Types are defined in `EVENT_TYPES`; more will be added as other paths (loop,
scout, discover, invent, nightly) are instrumented in later milestones.

### Progress honesty

The backtester runs a frame in one shot with no callback, so backtest events
carry **no percentage** — `progress_*` stay `None`, which the UI must render as an
indeterminate running state. Real percentages will only appear if/when the
backtest loop is instrumented.

## Persistence (atlas/memory/store.py)

Additive migration — `CREATE TABLE IF NOT EXISTS events (…)` plus indexes on
`task_id` and `event_type`. **No existing table or data is altered.** Columns
mirror `Event`; `seq INTEGER PRIMARY KEY AUTOINCREMENT` is the cursor.

Store methods:
- `write_event(event)` → persists, assigns `event.seq`
- `list_events(after_seq=0, task_id=…, event_type=…, agent_id=…, severity=…, limit=500)` → seq-ordered
- `latest_event_seq()`

## Event bus (atlas/events/bus.py)

Small, synchronous, matches the brief:

1. **persist** to SQLite, 2. **stream** to subscribers, 3. **catch up** on reconnect.

- `publish(event)` — write (assigns seq) then fan out; subscriber errors are isolated so one bad handler can't break emission or the research run
- `emit(event_type, **kwargs)` — build + publish
- `subscribe(handler) -> unsubscribe`
- `get_events(after_seq=0, **filters)` — durable catch-up
- `replay(task_id=… | cycle_id=…)` — all events for one run, in order
- `latest_seq()`

`NullBus` is the default in the engine: `publish` is a no-op, so instrumented
code can call the bus unconditionally with zero behavior change.

## How the UI will use it (later milestones)

- **Initial load:** `get_events(after_seq=0)` (or a recent window) to render history.
- **Live:** subscribe over SSE; server pushes each new event.
- **Reconnect:** client remembers the last `seq` it saw; on reconnect it calls
  `get_events(after_seq=<last>)` to fill the gap, then resumes the live stream.
  This is why events are persisted first, then streamed — the exact requirement
  behind the M4 "survives refresh/reconnect" proof.

## Tests (`tests/test_events.py`)

Schema validation, row round-trip, bus persist/stream/catch-up, `NullBus` silence,
a **real council run emitting ordered events** with replay, and the untouched-engine
guarantee. 6 tests; full suite 116 passing.
