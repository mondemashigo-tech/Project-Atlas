# Atlas Live — Security

MVP posture: a personal, locally-hosted research tool. Security scales with reach.

## Boundaries enforced today

- **Local-only bind** by default (`127.0.0.1`). `--lan` binds `0.0.0.0` and prints
  a no-auth warning; only for trusted networks.
- **Read-mostly.** The only state-changing endpoint is `POST /api/research/run`,
  which runs the same research council the CLI does. It **cannot promote to
  capital** — capital-bearing transitions stay human-gated inside the registry
  (`registry.transition`), unreachable from the API.
- **No shell execution.** Nothing in the API or chat runs commands. Chat is
  read-only retrieval over SQLite + optional LLM phrasing.
- **Path confinement.** `Runner.resolve_hypothesis` rejects traversal; a
  hypothesis must resolve to a file **inside the run root**.
- **Input validation.** Pydantic bounds message/hypothesis length; ids validated;
  bad input → 400/404.
- **Single-flight runs.** Only one research run at a time.
- **No secrets exposed.** No endpoint returns API keys; keys live only in the
  environment (`ANTHROPIC_API_KEY`) and are used server-side for chat phrasing.
- **Voice is read-only** and never triggers sensitive actions.

## Sensitive actions (design for later milestones)

Registry promotion, live status, risk settings, execution bot, governance
overrides, deletion/retirement — **not exposed** in the MVP. When added they must
require: a clear summary of the proposed action → explicit typed confirmation →
optional second confirmation for live-capital → audit logging. **Voice alone must
never trigger these.**

## Configuration modes

- **local** (default): `127.0.0.1`, no auth needed.
- **LAN** (`--lan`): reachable by other devices; **add authentication before
  using beyond a trusted home network** (not yet implemented).
- **remote** (future): requires authentication + TLS; out of MVP scope.

## Known gaps (honest)

- No authentication yet — do not expose beyond localhost/trusted LAN.
- Browser speech recognition (voice) sends audio to the browser vendor's servers
  (see `voice.md`). Use private STT if that's unacceptable.
- LLM chat phrasing sends retrieved records to Anthropic; disable by unsetting
  `ANTHROPIC_API_KEY` (chat then returns record-only answers).
