# Privacy and local data

Flow performs speech recognition on the device using installed models. It has
no cloud-transcription or telemetry service. This describes the current source
and Android 1.5.0 preview, not a guarantee about other apps on the device.

## Network access

Android uses internet access for selected model downloads, GitHub update checks,
and APK downloads. GitHub and model hosts receive normal connection information
needed to serve those requests. Flow does not attach dictated audio, transcripts,
or vocabulary. Once a model is installed, dictation works offline.

Desktop setup scripts download runtimes, models, and optional test audio files
when needed. Sharing/exporting text, opening a link, or moving a dictionary
file uses the app or service you choose; that destination has its own privacy
rules.

## Android storage and permissions

- Microphone access is used for recording. The floating control uses an Android
  foreground service and notification.
- Appearing over other apps is optional and needs overlay permission.
- Optional Accessibility integration detects supported focused text fields and
  attempts insertion. Password and protected fields are excluded.
- History, custom vocabulary, and settings are in Flow's private app storage.
  History retains both original recognized text and saved text. Turn history
  off or clear existing history in Settings; turning it off keeps older entries.
- Audio is held in memory during the take. There is no saved-audio library.
  The latest transcript can remain available in the running app with history off.
- The app opts out of Android cloud backup and device-transfer backup in its
  manifest and backup rules. Export data you want to retain yourself.

Models and downloaded update files also use local storage. Uninstalling or
clearing app storage can remove saved data. Export important text and vocabulary
before deliberately removing the app.

## Clipboard and insertion

Copying makes text available through the system clipboard. Failed or unconfirmed
Android insertion attempts a clipboard copy; check the field before pasting
after an unconfirmed insertion to avoid duplicates. If Android refuses the
copy, retrieve the text in Flow.

Flow marks its Android clipboard copies as sensitive and schedules removal
after 60 seconds if the same copy is still current. This cannot erase copies
already read or retained by another app, keyboard, or clipboard manager.
Confirmed insertion leaves the existing clipboard unchanged.

Desktop copy/insertion uses the selected platform backend. Desktop clipboard
retention is controlled by the operating system and other clipboard tools;
the Android timeout does not apply to desktop.

## Desktop files

| Platform | Default locations |
| --- | --- |
| Linux settings | `~/.config/flow-linux/` |
| Linux history and notes | `~/.local/share/flow-linux/` |
| Windows settings | `%APPDATA%\flow-linux\` |
| Windows history and notes | `%LOCALAPPDATA%\flow-linux\` |

The desktop dictionary is `hotwords.txt` inside the configured models directory
(`models/` in the checkout by default), on both platforms.

These are local files, not encrypted application storage. Your account, device
security, backup software, and filesystem permissions affect who can read them.

## Wispr dictionary transfer

The Windows helper opens Wispr Flow's database read-only and reads personal
words and corrections, excluding snippets and team entries. It does not import
dictation history. The exported JSON contains private words; keep it safe and
remove copies you no longer need. Android previews the transfer before you
confirm changes to Flow's vocabulary.

## Reporting problems

Use a short invented example instead of real private dictation. Redact account
names, recordings, vocabulary, paths, and text in screenshots or logs before
sharing them. See [support](SUPPORT.md) and [security reporting](SECURITY.md).
