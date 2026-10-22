# Moving from Pellin Preview to the Play Store version

The Play Store version of Pellin is a separate app from the Preview.
Android treats them as two different apps, so nothing carries over on its
own — no history, no settings, no downloaded model. (Pellin also keeps
everything on your phone by design and never backs it up, which is why
there is nothing in the cloud to restore from.)

The good news: your vocabulary moves with a file, and your history and
voice notes can be saved out as copies before you switch. This guide
takes about ten minutes. Steps checked against Preview 2.3.10.

**Do the saving first, while Preview is still installed.** Uninstalling
Preview deletes everything stored in it.

## 1. Save your history

1. Open Preview and tap the **History** icon on the main screen.
2. Tap **Export all**.
3. Save the file (`Pellin-history.txt`) somewhere you can find again —
   your Downloads folder or Google Drive, for example.

The file holds every saved dictation with its date, in plain text you can
open anywhere. It is a reading copy: the Play version cannot load it back
into its History screen, so keep the file as your record.

## 2. Save any voice notes you want to keep

Voice notes live inside the app, so each one has to be shared out by
hand:

1. Tap the **Voice notes** icon on the main screen.
2. Open a note.
3. Tap **Share document** to send yourself the text, or **Share audio**
   to send the recording itself — save to Files, Drive, or your email.
4. Repeat for each note you want to keep.

If a note is still transcribing, let it finish first — its document
cannot be shared until then, although the audio can. Shared copies are
ordinary files; the Play version cannot load them back in as notes.

## 3. Move your vocabulary

This one fully transfers — words, "heard as" spellings, and all.

In Preview:

1. Open **Settings → Vocabulary**.
2. Tap **Export vocabulary** and save `Pellin-vocabulary.txt` next to
   your history file.

In the Play version (after step 4):

1. Open **Settings → Vocabulary**.
2. Tap **Import from a file** and pick `Pellin-vocabulary.txt`.
3. Tap **Import**. Your words are in.

## 4. Install the Play version and set it up

1. Install Pellin from the Play Store. It sits alongside Preview — that
   is expected.
2. Open it and let it download the speech model again (about 483 MB for
   the recommended one). The Preview copy of the model cannot be reused.
3. Give the microphone permission when asked, and turn on the
   accessibility service if you use automatic typing — the Play version
   asks for these fresh, and explains why.
4. Import your vocabulary (step 3).

## 5. Redo these by hand

These live only in Preview's settings and cannot be exported:

- Apps you excluded from the floating microphone
- Per-app styles
- Formatting choices and phrase-splitting settings
- Theme and bubble appearance
- How long history is kept
- Your voice profile, if you recorded one — record it again in the
  Play version

## 6. Check, then remove Preview

Dictate a few lines in the apps you use most. Check your vocabulary
landed (Settings → Vocabulary) and the right model is in place. When
everything feels right, uninstall Preview — and remember that uninstall
deletes its stored history, notes, and model, so finish steps 1–3 first
if you have not already.
