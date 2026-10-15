# Preview updates and signing

Android allows an update to install over an existing app when the package ID
and signing certificate match and the new version is acceptable. Flow Preview
uses package ID `com.flowdictation.android.preview`. Keep the app installed if
an update reports a signature conflict; uninstalling can remove its local data.

Official Preview APKs are published in the
[Flow Releases repository](https://github.com/joenayer/flow-releases/releases).
The public source repository's CI builds are development builds signed with a
temporary key. They cannot update an official Preview installation.

The official 1.5.0 release certificate SHA-256 fingerprint is:

```text
55d12445242c1cdcc248f6bc5026aba624e73de2f47496f328d8affb7222126b
```

The fingerprint is public and can help identify the signing certificate. It
does not replace the APK checksum published with each release. See
[Android build instructions](building.md) for development builds.
