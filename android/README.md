# Flow Dictation for Android

Flow Dictation is an English speech-to-text app for Android. Recognition runs
on the phone after you install a speech model. Audio and transcripts stay on
the device. Android 1.5.0 is version code 8 and installs as **Flow Preview**.

## Install on a phone

Download and install the public APK by following [the phone setup guide](INSTALL.md).
The guide covers the current ARM64 and universal APKs, first-run speech setup,
and how to preserve your saved data when updating.

## What it does

- Record in Flow or use the optional floating microphone over other apps.
- Review, edit, copy, share, and save transcripts in history.
- Optionally use Android Accessibility to put text in a supported focused
  field. If insertion fails, Flow keeps the transcript available to copy.
- Download Parakeet, Moonshine Tiny, Whisper Tiny.en, or Whisper Base.en from
  Settings. Speech recognition works offline after a model is installed.
- Add words and “Heard as” aliases under **Settings > Custom vocabulary**.
  Aliases replace matching words after recognition; they do not change what the
  speech model recognizes. A word without an alias and the saved **Boost** value
  do not improve recognition. See [the vocabulary guide](docs/vocabulary.md)
  for details.
- Transfer personal words and corrections from Wispr Flow with the
  [Windows export helper](../scripts/EXPORT-WISPR-DICTIONARY.md).

The APK contains a small Silero voice-activity detector (VAD) for pause
detection. It is not a speech-recognition model. The recommended Parakeet model
and other speech models download separately; no speech model is bundled in the
APK. Model setup uses about 483 MB of internet data and up to 1.8 GB of free
phone storage while installing, as shown in the app.

The [phone setup guide](INSTALL.md) explains first-run model downloads and
updates. Phone-specific microphone behavior and recognition accuracy vary.

## Build and contribute

Developer setup, dependency fetching, local build commands, packaging, and
signing information are in [Building Android](docs/building.md).
