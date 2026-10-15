# Product scope

Flow Dictation turns English speech into editable text using models that run
on the user's device. The Android app is named **Flow Preview**.

## Android 1.5.0

The Kotlin app supports Android 8 and later. Speech models run through
sherpa-onnx and download separately: recommended Parakeet TDT 0.6B v2 int8,
Moonshine Tiny English int8, Whisper Tiny.en, and Whisper Base.en. A small
Silero VAD detects pauses. Model loading is lazy, with pre-warming and a
configurable idle unload interval.

The app provides recording, pause/finish/discard, editable transcripts,
copy/share/export, searchable and editable history, and privacy settings. The
optional floating talk button supports saved sizing, pinch resizing,
configurable gestures, a microphone-level waveform, and processing feedback.
Light is the default theme; Dark and System are available.

Optional Accessibility integration detects supported text fields and attempts
insertion. Failed or unconfirmed insertion preserves the result in Flow and
attempts a clipboard copy. Password and protected fields are excluded. This
does not promise compatibility with every app or keyboard.

Android vocabulary applies **Heard as** replacements after recognition. A
term-only entry and its saved Boost value currently do not influence the
recognizer. Suggestions from saved edits require confirmation. The Wispr Flow
helper transfers personal words and corrections, not snippets, history, or
team dictionaries. See [the vocabulary guide](android/docs/vocabulary.md).

Optional concise-prompt cleanup uses local text rules. It is off by default.
Update checks and APK downloads use GitHub Releases; Android asks the user to
approve installation. Recognition does not upload audio or transcripts.

## Desktop source

Linux and Windows share a Python/PySide6 app with Dictate, History, Notes,
Dictionary, and Settings; recording controls, a meter, shortcuts, a tray/pill,
and transcript copy/insertion. Adapters target Parakeet v2 int8 and Moonshine
Base English int8. Desktop dictionary behavior depends on the model adapter
and is separate from Android's replacement rules.

Linux X11 has a shortcut backend; Wayland global shortcuts are not implemented.
Windows has a per-user installer and input backend, but live Windows
integration remains unverified. See [Linux](docs/linux.md) and
[Windows](docs/windows.md) for prerequisites and limits.

## Product principles

- Make listening, paused, processing, and failure states clear.
- Preserve the transcript when insertion, saving, or processing fails.
- Explain permissions at the point a feature needs them.
- Keep recognition local and explain downloads, sharing, and clipboard use.
- Keep controls usable with enlarged text and accessible touch targets.
- Use measured results for performance and accuracy claims.
- Preserve package identity, signing compatibility, and user data on updates.

Physical-phone recognition accuracy, microphone behavior, and app compatibility
depend on the phone and target app. See [testing](docs/testing.md) for a checklist
that separates device testing from automated checks.
