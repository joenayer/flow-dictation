# Get help or report a problem

Start with the [Android phone guide](android/INSTALL.md),
[vocabulary guide](android/docs/vocabulary.md), [Linux guide](docs/linux.md), or
[Windows guide](docs/windows.md). Android **Settings** shows version, selected
model, and timing information useful for troubleshooting.

For a bug report, include:

1. Flow version, device, and operating-system version.
2. The selected model and whether cleanup or vocabulary corrections were enabled.
3. Short steps, what you expected, and what happened instead.
4. Any exact error message, with private details removed.

## A name or phrase is wrong

Check **Show original** first. This separates what the recognizer heard from
later corrections. Use an invented example and include original and finished
wording, plus any **Heard as** entry that should apply. The
[dictionary test](android/docs/vocabulary.md#try-a-simple-check) explains the
expected behavior. Adding a word alone does not train the Android recognizer.

## Finishing or pasting seems slow

Include recording length and the last Stop-to-text timing breakdown from
Android Settings. Note whether Flow was loading the model, transcribing, or
inserting text. Name the target app and keyboard without private text. Check
the field before manually pasting an unconfirmed insertion.

## Where to report

Open a [GitHub issue](https://github.com/joenayer/flow-dictation/issues) using the
appropriate template. Bug reports are welcome; outside code contributions and
pull requests are not accepted. Support is provided as time permits, without
a guaranteed response. For security issues, do not use public issues — report privately, as described in [SECURITY.md](SECURITY.md).
