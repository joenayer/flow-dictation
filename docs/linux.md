# Linux desktop setup

Flow has a Python desktop app for Linux. Global shortcuts are implemented for
X11. On Wayland, the global-shortcut backend is a stub, so use the controls in
the app window. Text insertion depends on the session and installed typing
tools; the app can copy the result to the clipboard when typing is unavailable.

The app uses Parakeet v2 int8 or Moonshine Base English int8 speech models. You
download the models before the first transcription. Speech recognition runs on
the computer after that. The Linux model fetch script currently does not verify
download checksums, so treat its downloaded files as unverified.

## Requirements

- Linux with Python 3.10 or newer and `venv`/`pip` support.
- An X11 or Wayland desktop session and a working microphone.
- Network access for the first model download. The model packs total about 1 GB.
- For audio, a working PortAudio setup for `sounddevice`, or PipeWire's
  `pw-record` command as a fallback.
- For typing into other apps, the app selects from available X11/Wayland tools.
  X11 can use `xdotool` or Xlib; Wayland can use `wtype`. Clipboard copy is also
  available. These tools depend on your session and distribution.

The repository does not maintain a tested list of Linux distribution package
names. Install the Python, audio, and desktop packages provided by your
distribution when the matching Python wheel or system library is missing.

## Install from a checkout

Run these commands from the repository root. The development extra includes
pytest; `fetch_models.sh` also checks that its Python has `numpy` and
`soundfile` before it creates files or downloads anything.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
PYTHON="$PWD/.venv/bin/python" ./scripts/fetch_models.sh
```

To start the app from the checkout:

```sh
.venv/bin/python -m flow.flowd
```

To install the user systemd service and start Flow at login:

```sh
./packaging/install.sh
```

The installer creates `.venv` and installs the project if needed, then enables
and starts the user service immediately, with paths for this checkout. It does
not download speech models. Fetch the models before installing if you want the
first service start to have them available. The installer requires a working
`systemctl --user` session.

The optional `packaging/flow-linux.desktop` launcher is for installations that
make the `flowd` command available on the desktop session's `PATH`. The service
installer does not install that launcher; it uses the checkout's own environment.

## Development checks

The isolated setup tests use temporary files and command stubs, without model
downloads, dependency installation, or changes to a real user service:

```sh
.venv/bin/python -m unittest scripts.tests.test_linux_setup -v
.venv/bin/python -m pytest -q
```

The broader pytest suite includes checks that need models, a display, audio,
or a user systemd session. Review skips; a passing headless run does not verify
your microphone, global shortcuts, or typing in another app.

Optionally, after fetching models, run the desktop benchmark with
`.venv/bin/python bench/bench.py --gate`. Its timing threshold is a benchmark
criterion, not an installation requirement or a promise for every computer.

## Session limits

On X11, Flow registers global shortcuts. On Wayland, the current backend raises
an error when global shortcuts are requested; start, stop, and cancel from the
app window instead. The `wtype` typing backend may work in supported Wayland
compositors, but this project does not claim it works in every compositor or
target app.

Linux device behavior has not been verified by this setup guide. Test the
microphone, shortcut behavior, and text insertion in the desktop session where
you plan to use Flow.
