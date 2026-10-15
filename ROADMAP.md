# Roadmap

This is a direction for future work, not a release promise. See the
[changelog](CHANGELOG.md) for released features and
[product scope](PRODUCT.md) for current behavior.

## Next: validate everyday dictation

- Use the [phone checklist](docs/testing.md#phone-checklist) on real devices and
  representative target apps, including Samsung Keyboard.
- Compare speech models with the same consented recordings. Report device,
  model, errors, memory use, and Stop-to-text time together.
- Test custom names with the original transcript visible. Document consistent
  mishearings and the effect of explicit **Heard as** corrections.
- Decide whether to implement actual recognizer vocabulary bias. Android's
  current term-only entries and Boost values do not provide it.
- Check permission denial/retry, background restrictions, changed text targets,
  clipboard failure, and update compatibility on physical phones.

## Desktop improvements

- Add guided model installation and selection, with pinned checksums and safe
  activation. The Linux downloader still lacks the checksum enforcement used
  by the Android and Windows paths.
- Bring history editing/deletion/export, appearance settings, and draft
  preservation to parity with Android.
- Implement supported Wayland global shortcuts with a clear fallback.
- Verify X11 focus handling, Windows shortcut suppression and text insertion,
  audio-device recovery, multiple monitors, and enlarged text in native sessions.
- Offer easier end-user packages after clean install, update, uninstall, and
  data-preservation checks on each supported platform.

## Distribution and project readiness

- Keep Android updates compatible with the established package and signing
  identity, and publish checksums with official releases.
- Preserve dependency and model licensing and redistribution terms.
