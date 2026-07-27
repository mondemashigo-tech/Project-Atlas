# ADR-002 — Voice architecture

**Status:** accepted (MVP) · **Date:** 2026-07 · **Milestone:** M7

## Context

Voice is an interface layer over the already-grounded chat system, not a new
brain. MVP requirement: read-only conversation, transcript preview before send,
no sensitive actions. Constraints weighed: cost, latency, privacy, browser
support, South African English, offline, future Jarvis integration.

## Options

**STT:** (a) browser `SpeechRecognition` (Web Speech API), (b) server-side
provider, (c) local model (e.g. Whisper), (d) hybrid.
**TTS:** (a) browser `speechSynthesis`, (b) external provider, (c) local.

## Decision (MVP)

**Browser `SpeechRecognition` + `speechSynthesis`.** Zero setup, zero cost, no
server audio handling, works offline for TTS. `lang` set to `en-ZA` for South
African English. Chosen because it makes voice available immediately with the
least new infrastructure, and voice is read-only so accuracy risk is bounded by
the mandatory transcript preview.

### Trade-off explicitly accepted

Chrome's `SpeechRecognition` streams audio to the browser vendor's servers, and
`en-ZA` accuracy is imperfect. This is disclosed (`voice.md`, `security.md`).
Because the user **reviews and edits the transcript before sending**, a
misrecognition cannot silently drive an action.

## UX rules implemented

- Tap mic to start, tap to stop; live "listening…" state.
- Interim transcript fills the input; the user reviews/edits, then Sends.
- Cancel = clear the input. "Speak replies" toggle for TTS.
- Voice targets the same `/api/chat` (or `/api/agents/{id}/query`) as text.

## Sensitive commands

Out of MVP scope for voice. Any future governance/registry/risk/execution action
must require an explicit typed confirmation flow (see `security.md`); **voice
alone can never trigger capital or governance changes.**

## Migration path

If privacy or `en-ZA` accuracy proves insufficient: add a server `POST
/api/voice/transcript` backed by a local Whisper model (private, offline) behind
the same UI — no frontend contract change. This is the natural Jarvis-era
upgrade.
