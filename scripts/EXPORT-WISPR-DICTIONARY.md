# Move a Wispr Flow dictionary to Flow Dictation

Use the included Windows helper to make a transfer file from Wispr Flow, then move that file to your Android phone.

1. On the Windows computer with Wispr Flow, extract the dictionary helper ZIP from the release page. Open its folder and double-click `Export-Wispr-Dictionary.cmd`. In a repository checkout, the helper is in `scripts`.
2. The helper creates a new `Wispr-Flow-Dictionary.json` file in your Downloads folder. If that name is already there, it makes a numbered copy instead of replacing it.
3. Move the file to your phone, open Flow Dictation → Custom vocabulary → **Import from Wispr Flow**, and select the transfer file.
4. Review the new words and skipped duplicates, then confirm the import.

The helper uses Python 3, which must already be available on the Windows computer. It reads only the active personal, non-snippet dictionary words and corrections from `%APPDATA%\Wispr Flow\flow.sqlite`. It opens the database read-only, does not read dictation history, and does not change Wispr Flow data. The transfer file contains private words; keep it somewhere safe and delete it yourself when you no longer need it.

Wispr corrections are stored as the spelling to correct and the spelling to use. Flow Dictation keeps the desired spelling as the word and the original spelling as its “Heard as” alias. New words and corrections are added. If a word already exists, new non-conflicting “Heard as” aliases are added while its existing aliases and boost are kept. Exact duplicates are skipped; alias conflicts are reported and skipped. Wispr snippets and team dictionary entries are not included.

For details about Wispr’s dictionary import columns and shared dictionary, see [Wispr’s bulk-import guide](https://docs.wisprflow.ai/articles/8955301725-How-Do-I-Bulk-Import-Dictionary-Items-and-Snippets) and [dictionary guide](https://docs.wisprflow.ai/articles/9639977157-view-shared-dictionary-words-and-snippets-in-the-admin-portal).
