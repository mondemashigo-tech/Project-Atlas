# Atlas Live — Frontend

Self-contained, no build step. Three files under `atlas/live/web/`, served by
FastAPI (`/` → `index.html`, `/static/*` → assets).

- `index.html` — shell: top bar (Atlas status dot, nav, connection state), the
  view container, the chat dock, the drawer.
- `styles.css` — the design system: tokens (background/surface/border/text,
  agent-group colours, status colours, spacing/typography/radius/motion), layout,
  components. Theme-aware and responsive; honours `prefers-reduced-motion`.
- `app.js` — vanilla JS: API helpers, SSE client, hash router, view renderers,
  chat, voice.

## Views

- **Council Chamber** (`#chamber`) — Atlas core + agent grid from `/api/agents`,
  colour-coded by group, state badges (idle vs active work-state), click → agent
  drawer. Run controls post to `/api/research/run`.
- **Live Console** (`#console`) — rows from the SSE stream: time, agent, type,
  summary, evidence refs. Filters (agent/type/severity/search), pause/resume;
  warning/error rows get a coloured left border. `EXP-`/`HYP-` refs are links.
- **Experiments** (`#experiments`) — research funnel (real counts; walk-forward
  marked *plan*) + table; row → detail drawer with verdict, metrics, decision
  ladder, event timeline, and honest "unavailable" for missing chart data.
- **Registry / Graveyard / Knowledge / Governance** — record tables.
- **Brief** (`#brief`) — morning brief cards + "read it to me" (TTS).
- **Ask Atlas** dock — grounded chat with citation chips; tag shows
  `grounded·records` / `grounded·phrased` / `no recorded evidence`.

## SSE client

`EventSource('/api/events/stream?after_seq=<lastSeq>')`. `onmessage` parses each
event (default message type — the server deliberately omits a named `event:`
field), appends to the console, and throttles a `/api/agents` refresh. On error
the browser auto-reconnects and sends `Last-Event-ID`, so the server replays
missed events — no lost history on refresh/disconnect.

## Motion

Subtle and state-driven: the Atlas dot pulses only while a run is active; the
active agent badge blinks; everything stops when work completes. All motion is
disabled under `prefers-reduced-motion`. No animation implies work that isn't
happening.

## Accessibility / responsive

Relative units, fl/grid layouts, `overflow-x` on wide tables, mobile breakpoints
(chat dock spans bottom, console collapses columns). Keyboard-usable forms.
