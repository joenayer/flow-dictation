# Security reporting

Found a security problem in Pellin (Flow)? Please report it privately, so we
can fix it before the details are public.

## Report a vulnerability

Use GitHub's private vulnerability reporting for this repository:
[Report a vulnerability](https://github.com/joenayer/flow-dictation/security/advisories/new)

Please do not put credentials, private dictation, personal dictionaries, or
details of an exploitable vulnerability in a public issue or pull request.

A useful report includes:

- the affected version and platform,
- what you found,
- the smallest steps to reproduce it, using invented data,
- the impact — what an attacker could do with it.

Do not attach real signing keys, tokens, account databases, or other people's
recordings.

Every report is read. We aim to send a first reply within 7 days. Please give
us a reasonable window to fix the problem before disclosing it publicly.

## Scope

Pellin runs on-device: recognition happens locally, and there is no Pellin
server holding your dictation. Still report anything that looks like a
security problem — in the app, its update checks, the model downloads, or
these documents. If in doubt, report it.

## Supported builds

This is preview software. Security fixes target current development and the
latest preview where practical; there is no long-term support commitment for
older previews. Installation files and checksums are published in the
[official release repository](https://github.com/joenayer/flow-releases/releases).

Android update compatibility depends on package ID and signing certificate.
Do not uninstall Flow or clear its data to work around an unexplained update
failure. Report the message first, with private details removed.
