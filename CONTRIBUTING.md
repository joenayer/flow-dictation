# Contribution policy

Flow is maintained by the project maintainer. **Outside pull requests and code
contributions are not accepted**, including patches submitted through issues.
Please use [Issues](https://github.com/joenayer/flow-dictation/issues) for bug
reports rather than proposed code changes. A report does not guarantee a fix
or response.

The [MIT License](LICENSE) permits you to use, modify, and redistribute Flow's
original source code, including in your own fork. This contribution policy
governs what is accepted into this repository; it does not restrict those
license permissions. Dependencies and models keep their own upstream terms.

The development instructions below are for the maintainer and people building
their own copy.

## Set up

1. Clone the repository and create a working branch.
2. Follow [Android builds](android/docs/building.md), [Linux setup](docs/linux.md),
   or [Windows setup](docs/windows.md).
3. Run the checks for your change. Keep models, recordings, signing keys,
   personal dictionaries, and generated APKs out of source control.

Enable the local publication check with `git config core.hooksPath .githooks`.
Before pushing, run `python scripts/check_public_source.py`. It checks staged
files and reachable history for common accidental disclosures. It does not
replace a human privacy review. Use the project maintainer identity and a
GitHub noreply email in commits; keep personal contact details out of metadata.

## Checks

| Change | Expected checks |
| --- | --- |
| Android app or rules | `cd android` then `./gradlew testDebugUnitTest lintDebug assembleDebug`; native coverage when the changed behavior needs Android itself |
| Wispr export helper | `python -m unittest discover -s scripts/tests -p 'test_export_wispr_dictionary.py'` |
| Linux setup | Follow the isolated tooling-test commands in the [Linux guide](docs/linux.md); never run the installer against your active session as a test |
| Desktop Python | Follow the platform guide, then `python -m pytest -q`; keep hardware-dependent checks separate |
| Documentation | `python scripts/check_docs.py`, review commands and versions, then `git diff --check` |

See [testing and evidence](docs/testing.md) for device checks and automated-suite
limits. Installers change startup configuration and may start Flow.

## Maintainer changes

- Explain the problem and resulting behavior in plain language.
- Keep changes focused. Cover meaningful behavior fixes with regression tests
  and update the relevant user guide.
- List checks actually run, their results, and anything still unverified.
  Name the device, OS, and model for speech or performance results.
- Include native screenshots for visible UI changes, including enlarged text
  when layout or controls change. Avoid private dictation in evidence.
- Preserve model IDs, saved settings, history compatibility, Android package
  identity, and signing rules unless the agreed change requires it.
- Keep changes focused and review them before release.

Review behavior and evidence respectfully. Do not post other people's private
data, recordings, or credentials. For sensitive issues, follow
[SECURITY.md](SECURITY.md).

## Dependencies and releases

Document the source, version, integrity checks, and upstream terms when adding
a model or runtime dependency. Arbitrary ONNX files are not assumed compatible.
Keep inference local and make network use explicit.

Release packaging is described in [Android builds](android/docs/building.md).
Development builds use temporary debug signing and cannot automatically update
the official Preview. Signing material stays outside the repository.
