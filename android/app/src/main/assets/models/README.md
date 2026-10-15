# Local model staging (gitignored)

Legacy developer dependency fetching can stage a subdirectory per model here,
for example:

    models/moonshine-tiny-en-int8/*.onnx, tokens.txt
    models/whisper-tiny.en/*.onnx, *tokens.txt

Current Preview release APKs must not bundle speech models. From `android/`,
use `./scripts/fetch-deps.sh runtime-only` to fetch the pinned runtime and small
Silero VAD without staging a speech model. Release packaging checks for model
exclusion. Do not commit generated model files.

The app downloads supported speech models through its catalog, verifies their
checksums, and stores them privately on the phone. Recognition then works
offline. Internet permission also supports update checks and APK downloads;
dictated audio and transcripts are not uploaded for recognition.
