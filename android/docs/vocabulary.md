# Custom vocabulary on Android

Flow's vocabulary helps fix spellings after speech recognition. It does not teach
the speech model how a word sounds, and it cannot reliably fix every
mispronunciation or mishearing on its own.

## Add a correction

1. Open **Settings** and tap **Custom vocabulary**.
2. Tap **Add word or phrase**.
3. Enter the spelling you want under **Word or phrase**.
4. Under **Heard as (separate with commas)**, enter the wording Flow actually
   shows when it gets that name wrong. Add more than one spelling with commas.
5. Tap **Save**.

For example, if you want **Northstar** but Flow writes **north star**, save:

| Field | Enter |
| --- | --- |
| Word or phrase | `Northstar` |
| Heard as (separate with commas) | `north star` |

Adding **Northstar** without a **Heard as** entry only saves the term. It does
not change a different recognized phrase into Northstar or normalize its
spelling or capitalization. To rewrite recognized wording, add that wording
under **Heard as**. **Boost (1.0 to 3.0)** is saved with the entry but is
currently unused by Android recognition, so its value does not affect
dictation. Aliases are applied after recognition with Parakeet, Whisper, and
Moonshine alike.

## Try a simple check

First, dictate “I saw the north star” and note what Flow wrote. Then add
**Northstar** with that exact wording in **Heard as**, and dictate the same
sentence again. If Flow's original transcript contains “north star,” the
finished text should show “Northstar.”

Use **Show original** on the result to compare the recognized wording with the
finished text. In History, open a saved dictation and choose **Show original**.
The original is the text from speech recognition before vocabulary replacement
and other text processing. If the original shows a different phrase, add that
phrase as another **Heard as** spelling. If recognition misses the words
completely, an alias cannot recover them; try speaking more clearly or review
the result yourself.

## Suggestions from edits

When **Offer vocabulary suggestions from my edits** is on in Settings, saving an
edit in the main transcript editor or in **History** may offer to save a
correction. Flow compares the saved wording with your edit and asks before
adding anything. Choose **Add** to save the earlier wording as **Heard as**, or
**Skip** to leave the vocabulary alone. Suggestions are limited and heuristic,
so not every edit will produce one. This does not train the speech model.

## Import and export

The **Import vocabulary** and **Export vocabulary** buttons on the Vocabulary
screen transfer Flow's plain-text list. The **Import from Wispr Flow** button
accepts the transfer file made by Flow's Windows helper. It can add Wispr words
and spelling corrections; corrections become **Heard as** aliases in Flow.
The import preview shows additions, duplicates, and conflicts before you
confirm. Wispr snippets are not included. Importing copies dictionary entries;
it does not train either app's speech model.

Saved entries stay inside Flow on this phone. Use **Export vocabulary** to make
a separate copy you can move or keep elsewhere.
