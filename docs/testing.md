# Testing and evidence

Automated rules, native UI checks, speech decoding, and physical-device use
answer different questions. When reporting a result, say what you tested and
which build you used rather than calling the whole app verified.

## Automated checks

[CONTRIBUTING.md](../CONTRIBUTING.md#checks) lists local commands. Public source
CI runs development checks and, after they pass, makes a debug-signed APK and
checksum available as build artifacts. Such APKs cannot update the official
Preview. Automated Android checks do not establish real microphone accuracy in
a noisy room.

Desktop tests include mocked platform behavior. Checks needing a display,
microphone, models, or a live platform can skip or require separate setup.
Report skips. Live input tests can register shortcuts or interact with apps;
do not run them casually against an active session.

## Phone checklist

Use harmless sample text. Record phone, Android version, Flow version, model,
target app, and keyboard.

1. **Normal dictation:** speak a short sentence, finish, and compare words.
   Repeat with a longer take. Confirm listening changes to processing and then
   a visible result. Note the timing breakdown in Settings.
2. **Custom names:** follow the [dictionary check](../android/docs/vocabulary.md#try-a-simple-check).
   Compare **Show original** with finished text. A matching **Heard as** alias
   should change the result; adding a word alone should not.
3. **Suggestions:** edit a mistaken phrase, save with suggestions enabled, and
   accept a suitable correction. Check that its earlier wording appears under
   **Heard as**. Not every edit generates a suggestion.
4. **Typing and recovery:** try an ordinary supported text field, then change
   the target before finishing. A failed or uncertain insertion must leave the
   result recoverable. Check the field before pasting again.
5. **Bubble and accessibility:** start/finish, pause/resume, cancel, resize,
   restart Flow, and confirm saved size. Repeat with large system text and
   each appearance setting; controls and status must stay reachable.
6. **Microphone conditions:** compare quiet speech, normal speech, silence, and
   background noise. The waveform should follow loudness; hints are estimates
   and do not rate recognition accuracy.
7. **Offline and updates:** after installing a model, try airplane-mode dictation.
   Check a compatible update without uninstalling; retain history and settings.

Record original and final wording for failed samples. An alias not matching
the original differs from a matching alias being ignored. A recognizer omitting
a word entirely cannot be repaired by replacing an existing phrase.

## Performance and accuracy reports

Use the same sample for model comparisons. Separate cold model load, speech
processing after Stop, cleanup, delivery, and history-saving time. Include
recording length and device details. Desktop `bench/bench.py --gate` needs
models and fixtures; its latency target is a benchmark criterion, not a promise
for every phone or recording length.

Do not publish private recordings or imported vocabulary in test artifacts.
