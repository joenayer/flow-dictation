# Third-party components

The root [MIT License](LICENSE) covers Flow's original code. It does not replace
licenses or notices belonging to dependencies, models, or data. Preserve their
required notices and check the terms of the exact version you distribute.

## Included word-list data

The Android common-word filter is derived from Ilya Semenov's Wikipedia word
frequency list. Its source revision, derivation, copyright, and MIT notice are
preserved in [common-english-LICENSE.txt](android/app/src/main/assets/common-english-LICENSE.txt),
alongside the word list. This is a text-processing heuristic, not a pronunciation
dictionary.

## Runtimes and libraries

Android builds fetch the pinned sherpa-onnx runtime and Silero VAD through
[fetch-deps.sh](android/scripts/fetch-deps.sh) and its
[checksum file](android/scripts/checksums.sha256). Runtime dependencies are
declared in [Android's build file](android/app/build.gradle.kts).

Desktop Python dependencies are declared in [pyproject.toml](pyproject.toml),
with the Windows install list in
[requirements-windows.txt](packaging/windows/requirements-windows.txt).
Their upstream license files remain authoritative. Installing Flow does not
relicense those packages under Flow's MIT license.

## Downloadable speech models

Speech models are downloaded separately from the APK. The Android
[model catalog](android/app/src/main/java/com/flowdictation/android/ModelCatalog.kt)
records model names, source download URLs, checksums, and license labels.
Model weights and accompanying files retain the upstream terms; the code
license does not grant additional rights to them.

Distributors should retain the notices supplied with the exact runtime/model
artifacts and check their redistribution requirements before repackaging.
This document identifies source locations; it is not a complete license bundle
for every possible desktop environment or downloaded model.
