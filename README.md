# Flow Dictation

English voice dictation with speech recognition on your own device. Record,
review the text, then copy it or insert it into a supported app.

**[Download Flow Preview 1.5.0 for Android](https://github.com/joenayer/flow-releases/releases/tag/android-v1.5.0)**

[Phone setup](android/INSTALL.md) | [Custom words](android/docs/vocabulary.md) |
[Release notes](CHANGELOG.md)

## Choose your platform

| Platform | Current state | Start here |
| --- | --- | --- |
| Android 8+ | Installable 1.5.0 preview. Speech models download separately. | [Phone setup](android/INSTALL.md) |
| Linux X11 | Python/Qt desktop app, model setup, and user-service installer. | [Linux setup](docs/linux.md) |
| Linux Wayland | Desktop controls are available; global shortcuts are not implemented. Insertion depends on the compositor and installed tools. | [Linux limits](docs/linux.md) |
| Windows 10/11 | Python/Qt app and per-user installer are implemented. Live Windows integration still needs verification. | [Windows setup](docs/windows.md) |

Recognition accuracy and microphone behavior vary by phone. Desktop features
and limitations are listed in the platform guides.

## Android preview

- Record in the app or through a floating talk button, with a microphone-level
  waveform and a visible processing state after you finish.
- Resize the button with a pinch gesture or the Settings slider. Choose what
  long presses, double taps, and triple taps do.
- Review and edit transcripts, search history, or copy, share, and export text.
- Optionally insert text into a supported focused field through Android
  Accessibility. Failed or unconfirmed insertion attempts a clipboard copy;
  the transcript remains available in Flow.
- Download recommended Parakeet or choose Moonshine Tiny or Whisper. Recognition
  works offline after setup. No speech model is bundled in the APK.
- Add spelling corrections, or transfer personal words and corrections from
  Wispr Flow with the [Windows helper](scripts/EXPORT-WISPR-DICTIONARY.md).

**Custom words need a correction rule to change the result.** On Android,
adding a word alone does not teach the model its pronunciation. Add the wrong
wording under **Heard as** to replace that wording after recognition. The
[vocabulary guide](android/docs/vocabulary.md) includes a short test using
**Show original** so you can see exactly what changed.

Choose the **ARM64 APK** for most current Android phones, including recent
Samsung models. The larger **universal APK** includes native libraries for
more processor types. Both download their speech models separately.

Keep the installed app and its data if Android rejects an update. Installation
over an existing Preview requires a matching signing certificate; see
[update guidance](android/INSTALL.md#install-problems-and-updates).

## Documentation

- [All guides](docs/README.md): installation, development, and testing.
- [Privacy](PRIVACY.md): local data, permissions, downloads, and clipboard behavior.
- [Report a problem](SUPPORT.md): useful details without sharing private dictation.
- [Contribution policy](CONTRIBUTING.md): maintainer-only development and build guidance.
- [Security](SECURITY.md): how to report a sensitive issue.
- [Product scope](PRODUCT.md) and [roadmap](ROADMAP.md): implemented and future work.

## Repository layout

| Path | Contents |
| --- | --- |
| `android/` | Native Android app, JVM/native tests, build and release tooling |
| `flow/` | Shared Linux/Windows Python app and platform backends |
| `tests/` | Desktop Python tests |
| `bench/` | Desktop recognition and latency benchmarks; require models |
| `scripts/` | Model setup, Wispr transfer helper, and tooling tests |
| `packaging/` | Linux user-service and Windows per-user installers |
| `.github/` | CI and contribution templates |

## License and contribution policy

Flow's original source code is available under the [MIT License](LICENSE).
You may use, modify, and redistribute it under that license, including in
commercial products. Dependencies and model files keep their own upstream terms;
see [third-party components](THIRD_PARTY_NOTICES.md).

Development is maintained by the project maintainer. **Outside pull requests
and code contributions are not accepted.** Bug reports are welcome through
[Issues](https://github.com/joenayer/flow-dictation/issues); they do not guarantee
a fix or response. The contribution policy does not limit your MIT rights to
use the code or maintain your own fork. See [the full policy](CONTRIBUTING.md).
