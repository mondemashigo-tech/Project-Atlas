# Atlas Live — Jarvis integration boundary

Atlas Live will eventually be **a module inside a broader Jarvis system**. This
document defines the boundary. **Jarvis is not built here** — Atlas stays
independent; Jarvis orchestrates it later, not embedded inside it.

## The integration surface Atlas already exposes

Everything Jarvis needs is (or will be) available at the HTTP + event boundary,
so Jarvis integrates as a **client**, not by importing Atlas internals:

| Capability | Surface today |
|---|---|
| Typed events | `GET /api/events`, `GET /api/events/stream` (SSE, `seq` cursor) |
| Conversation | `POST /api/chat`, `POST /api/agents/{id}/query` |
| Morning brief | `GET /api/reports/morning-brief` |
| Agent status | `GET /api/agents` |
| Research records | experiments / hypotheses / registry / graveyard / knowledge / governance |
| Obsidian-compatible markdown | the vault mirror under `<root>/vault/` |
| Notifications | derivable from `system_error` / `system_warning` events + brief |
| Governance requests | registry candidates awaiting review (surfaced in the brief) |

## Design rules for staying Jarvis-ready

1. **Stable typed contracts.** Events and API responses are JSON with explicit
   fields; new fields are additive. Jarvis binds to these, never to Python
   internals.
2. **Atlas owns its gates.** Capital promotion, governance, and risk stay
   human-gated *inside Atlas*. Jarvis may *request* or *surface* them but cannot
   bypass the confirmation flow (see `security.md`).
3. **One-way by default.** Jarvis reads Atlas's event stream and records, and
   sends conversational/queued requests. It does not reach into the engine.
4. **Independent lifecycle.** Atlas runs and is useful with no Jarvis present;
   removing Jarvis changes nothing about Atlas.

## Not in scope now

The Jarvis platform itself, cross-module orchestration, a unified assistant shell,
multi-tool routing, and any embedding of Jarvis logic inside `atlas/`. When built,
Jarvis consumes the surface above.
