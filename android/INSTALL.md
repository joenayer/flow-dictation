# Install Flow Preview 1.5.0 on Android

Download Flow Preview from the [1.5.0 release page](https://github.com/joenayer/flow-releases/releases/tag/android-v1.5.0). No GitHub sign-in is required.

1. Choose **Flow-Dictation-1.5.0-arm64-v8a.apk** for a modern Samsung phone. Choose **Flow-Dictation-1.5.0-universal.apk** for another supported Android device.
2. Open the downloaded APK from Chrome or My Files. If Android asks, allow that app to install unknown apps, then tap **Install**.
3. Open **Flow Preview** and tap **Download recommended setup**. Flow downloads the Parakeet speech model and Silero pause detector. The app reports about 483 MB of download data and up to 1.8 GB of free storage needed while files are installed. Wi-Fi is recommended.
4. If setup is interrupted, reopen Flow and tap **Resume recommended setup**. Keep Flow open until setup finishes. Settings and history remain available while it runs.
5. When setup is complete, tap **Start recording** and allow microphone access when Android asks. Speak, then tap **Finish recording**. Review or edit the result, then copy, share, or save it.

The APK is a complete installer; there is no ZIP or separate split installer. Android 8 or newer is required. The ARM64 APK is smaller because it includes native libraries for one processor type; universal includes several. Neither APK bundles a speech model. You can add or change a model later in **Settings > Speech model > Download a model**. The available choices are Parakeet, Moonshine Tiny, Whisper Tiny.en, and Whisper Base.en. Recognition works offline once a model is installed.

## Install problems and updates

If Samsung names **Auto Blocker**, follow the phone's instructions for allowing an app you trust. Auto Blocker is a phone security setting. If Android reports a signature or update conflict, keep Flow installed and its storage intact, and note the exact message before seeking help.

The package ID is `com.flowdictation.android.preview`. An installed Preview
signed with a different temporary key cannot be updated in place by the
official release. A matching filename or checksum cannot resolve a signing-key
mismatch.

In **Settings**, tap **Check for updates** to check the public [releases page](https://github.com/joenayer/flow-releases/releases). When an update is available, tap **Download and install**, then approve Android's installation screen. The app checks the package, version, and signing certificate before installation. The release certificate SHA-256 is:

```text
55d12445242c1cdcc248f6bc5026aba624e73de2f47496f328d8affb7222126b
```

These are preview builds, not Play Store releases. Release APK checksums are listed on the release page.

## Optional features

The floating microphone asks separately for permission to **Appear on top**. Tap it to start or stop recording. By default, triple-tap while idle to resize, then pinch. **Settings > Floating button controls** lets you change its size and the long-press, double-tap, and triple-tap actions. A long press holds to pause and release to resume during a recording.

For automatic typing in other apps, go to **Settings > Automatic typing**, turn on **Show microphone with the keyboard**, and tap **Enable in phone settings**. In Android Accessibility settings, enable **Flow Preview**, then return to Flow. If Android blocks this setting, tap **Android blocked this setting?** in Flow for the device steps. Some apps and fields do not support insertion; Flow keeps the transcript available if insertion cannot be confirmed. Password and protected fields are excluded. You can always use **Copy** and paste manually.

New installs start in **Light** appearance. Choose **Light**, **Dark**, or **System** near the top of Settings.

To transfer personal custom words and corrections from Wispr Flow, run the Windows helper, move its JSON transfer file to the phone, and open **Settings > Custom vocabulary > Import from Wispr Flow**. Review the entries before adding them. The helper requirements and steps are in the [transfer instructions](../scripts/EXPORT-WISPR-DICTIONARY.md). Import does not include snippets, history, or team dictionaries.

For the behavior and limits of custom vocabulary, see [the vocabulary guide](docs/vocabulary.md). For build and developer information, see [Building Android](docs/building.md).
