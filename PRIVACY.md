# Privacy and local data

Pellin performs speech recognition on your device, using models you install.
It has no accounts, no cloud transcription, and no telemetry or analytics:
nothing you dictate is sent to us or to anyone else. Recognition works fully
offline once a model is installed.

This policy describes the current Pellin builds. The Android app ships in two
channels that differ in how updates arrive, so the network facts are stated
per channel. Everything else — recognition, storage, the accessibility
integration — is the same in both.

## Network access

**Google Play build.** The app itself makes one kind of network request:
downloading a speech model you choose, from the public sherpa-onnx model
releases (hosted on GitHub). The host receives the normal connection
information needed to serve the file. Pellin attaches no audio, transcripts,
or vocabulary to any request, and there is no other Pellin server to send
them to. App updates are delivered by Google Play, under Google's own
privacy terms; the Play build contains no updater of its own.

**GitHub preview build.** As above for model downloads. In addition, the
preview build can check GitHub for a newer preview release and, when you
approve it, download the update package from GitHub. Those requests carry
the same normal connection information and nothing about your dictation.

**Desktop.** The install scripts download runtimes and models once; after
installation the desktop app is fully offline. Sharing or exporting text,
opening a link, or moving a dictionary file uses the app or service you
choose; that destination has its own privacy rules.

## What the accessibility integration sees (Android)

Automatic typing is off until you turn it on, and turning it on first shows a
prominent disclosure you must accept. While it is on, the accessibility
service looks only at the focused text field of the app you are using:

- It checks whether the field can accept text, so the floating microphone
  can be offered. Password fields and fields Android marks data-sensitive
  are always excluded.
- To format inserted text, it reads up to 120 characters on either side of
  the cursor in that field, on the device, at insertion time only.
- In a browser, it may read the address bar's host (for example
  `example.com`) to pick a writing style. The host is reduced from the
  address on the device and the address itself is not kept.
- It remembers the package names of apps you dictate into (names only —
  never field contents), so the App styles page can list them.

None of this is stored beyond what is described, transmitted anywhere, or
used for anything else. A developer diagnostics switch in Settings can
record why the floating microphone did or did not appear (app package name
and which check failed — never field text). It is off by default, the
record stays in memory on the phone, and turning the switch off clears it.

## Storage and permissions (Android)

- Microphone access is used for recording. The floating control uses an
  Android foreground service and notification.
- Appearing over other apps is optional and needs overlay permission.
- History, custom vocabulary, and settings live in Pellin's private app
  storage. History is on by default and retains both the original
  recognized text and the saved text. You can turn history off or clear it
  in Settings; turning it off keeps entries already saved.
- Audio is held in memory during a take. There is no saved-audio library.
- Downloaded models are stored in private app storage and can be deleted
  in Settings (Settings → Delete a downloaded model), which frees the
  space they use.
- "Only my voice" is off by default. If you enrol a voice profile, the
  profile (a mathematical voice print, never audio) stays on the device.
- The app opts out of Android cloud backup and device-transfer backup.
  Export anything you want to keep before uninstalling; uninstalling or
  clearing app storage removes saved data.

## Clipboard and insertion

When a field accepts text, insertion writes directly to the field and the
clipboard is left unchanged. Only when there is positive evidence that no
text field is active does Pellin copy the transcript to the clipboard for
you to paste; a failed, protected, or changed field never triggers a copy —
your words stay in the app for review instead.

Pellin marks its Android clipboard copies as sensitive and schedules their
removal after 60 seconds if the same copy is still current. This cannot
erase copies already read or retained by another app, keyboard, or
clipboard manager. Desktop clipboard behaviour is controlled by the
operating system and other clipboard tools.

## Desktop files

| Platform | Default locations |
| --- | --- |
| Linux | `~/.local/share/pellin/` (settings, history, models, logs) |
| Windows | `%LOCALAPPDATA%\Pellin\` |

Installs from before the Pellin rename keep their data under the legacy
`flow-linux` folders; the desktop app reads those and migrates copies
non-destructively. The desktop dictionary is `hotwords.txt` inside the
models directory. These are local files, not encrypted application storage:
your account, device security, backup software, and filesystem permissions
affect who can read them.

## Wispr dictionary transfer

The Windows helper opens Wispr Flow's database read-only and reads personal
words and corrections, excluding snippets and team entries. It does not
import dictation history. The exported JSON contains private words; keep it
safe and remove copies you no longer need. Android previews the transfer
before you confirm changes to Pellin's vocabulary.

## Reporting problems

Use a short invented example instead of real private dictation. Redact
account names, recordings, vocabulary, paths, and text in screenshots or
logs before sharing them. See [support](SUPPORT.md) and
[security reporting](SECURITY.md).
