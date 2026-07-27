# Atlas Live — Voice

Voice is a **read-only** interface over the grounded chat system. See ADR-002 for
the decision record.

## How it works

- **Speech-to-text:** the browser's `SpeechRecognition` (Web Speech API),
  `lang = en-ZA`. Tap the mic to start, tap to stop. The interim transcript fills
  the chat input.
- **You review before sending.** The transcript is never auto-submitted — you
  read/edit it, then press Send. This is the safety gate against misrecognition.
- **Text-to-speech:** the browser's `speechSynthesis`. Toggle "speak replies" in
  the chat dock, or press "read it to me" on the Morning Brief.
- The spoken question goes to the same `/api/chat` (or an agent's `query`) as
  typed text, so answers are equally grounded and cited.

## Privacy (read this)

Chrome's speech recognition **sends your audio to the browser vendor's servers**
for transcription. If that's unacceptable, don't use the mic — type instead — or
wait for the private-STT upgrade (local Whisper behind `POST
/api/voice/transcript`, planned; no UI change). `en-ZA` recognition is decent but
imperfect; always check the transcript.

## What voice cannot do

Voice is conversational only. It cannot promote strategies, change governance or
risk settings, delete/retire records, or touch the execution bot. Those remain
human-gated and, when eventually exposed, will require explicit typed
confirmation — never voice alone.

## Browser support

Works in Chromium-based browsers and Safari. If `SpeechRecognition` is
unavailable the mic button is disabled and text chat works unchanged;
`speechSynthesis` is broadly supported.
