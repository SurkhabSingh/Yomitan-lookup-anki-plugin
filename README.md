# Anki Lookup

Anki Lookup is a desktop Anki add-on for looking up text directly while reviewing
cards.

It is designed to provide:

- Hold-to-scan word lookup with a configurable modifier key.
- Local Yomitan-compatible dictionaries for multiple languages.
- Indexed English-definition lookup for corresponding Japanese expressions and
  readings in bilingual dictionaries.
- Japanese conjugation and common English inflection lookup, including forms such as
  `はがし` to `剥がす` and `running` to `run`.
- Google Translate and DeepL translation of the captured sentence.
- A configurable popup with themes, fonts, sizing, and layout controls.
- Direct creation of new Anki notes from lookup results, including the sentence the
  word appeared in.

> **Development status:** Pre-alpha. Hold-to-scan, local Yomitan term and kanji
> dictionary imports, exact and reverse-definition results, dictionary tabs,
> sentence translation, and note creation are available.

## Current Preview

While reviewing a card, hold **Shift** and move the pointer across text. Anki Lookup
will highlight the word under the pointer and open the lookup popup. Drag the popup's
bottom-right corner to resize it. Click outside the popup or press **Escape** to close
it. Press **Ctrl+Shift+K** to pin or unpin the latest popup. Pinned popups are preserved
during later scans and can be dragged by their header. You can also select text and
press **Ctrl+Shift+L**.

Continue holding **Shift** while moving over a headword, definition, or captured
sentence inside the popup to open a nested lookup beside it. Nested lookup is enabled
by default and can be disabled through the add-on configuration. Clicking inside a
parent popup closes its child popups. Dictionaries and translation providers appear in
a compact source rail outside the popup, so switching sources does not consume result
space or require horizontal scrolling.

Japanese kana words are resolved using longest exact dictionary matching, so words
such as `くるま` are not limited by the browser's shorter segmentation boundary.
The scanner also tests bounded longest-to-shortest word and phrase candidates from the
cursor and merges valid matches from more than one source length. For example, scanning
`自分の` can show an installed exact `自分の` entry followed by results for `自分`.
This progressive exact matching is language-neutral. Japanese and English use
dedicated morphology profiles; other languages use Unicode-aware exact word and phrase
matching until a dedicated profile is available.

Import one or more dictionaries from **Tools > Anki Lookup: Manage Dictionaries...**.
The current version supports Yomitan format-3 term and kanji-only dictionaries. Use
Ctrl or Shift selection in the manager to remove multiple dictionaries together.
Results are shown in a separate tab for each dictionary. Pitch metadata-only archives
are not searchable yet.

Move between source tabs with the arrow keys, or jump to the first and last with Home
and End.

Open **Tools > Anki Lookup: Settings...** to select a system, light, dark, or
high-contrast theme, choose the popup font and font size, change the pin shortcut, or
choose between dictionary buttons in Sources and continuous dictionary results.
Appearance and layout changes apply immediately to the active reviewer.

## Translation

The translation tab translates the sentence captured around the scanned word, using
Google Translate or DeepL. Choose the provider and the target language in
**Tools > Anki Lookup: Settings...**.

By default the tab opens the provider's website with the sentence prefilled. That
needs nothing else installed and always works.

For translations shown **inside** Anki, turn on *Translate inside Anki using the
browser extension*. This requires the Wonder of U browser extension in App Support
mode, which performs the translation and hands the result back over a local
loopback connection.

> **Anki and the Wonder of U desktop app cannot do this at the same time.** Both
> listen on the same local port, the browser extension only ever contacts that one
> port, and whichever program starts first gets it. This is why the setting is off by
> default: turning it on while the desktop app is running changes nothing, and turning
> it on before the desktop app starts means the desktop app loses its own translation.
> **Tools > Anki Lookup: Diagnostics...** always reports which program currently holds
> the port. Anki picks the port up on its own within a minute of the other program
> quitting; no restart is needed.

Successful translations are cached, so re-scanning the same sentence is instant and
works even when the port is unavailable. The cache lifetime is configurable, and zero
turns caching off.

No translation is ever sent anywhere until you open a translation tab.

## Creating Notes

Configure a preset in **Tools > Anki Lookup: Note Preset...**: choose the deck and
note type, then map each field to a lookup value. Field names such as `Front`,
`Reading`, `Back`, and `Sentence` are matched to sensible defaults automatically.

Press the **+** button on a lookup result to create the note. The captured sentence is
available as a field source, so a saved word keeps the context it appeared in.

Notes are created with Anki's normal undo support, so **Ctrl+Z** removes one. The card
you are reviewing is never modified. If a note with the same key field already exists,
Anki Lookup offers to open it instead of silently creating a duplicate.

## Installation

1. Download the latest `.ankiaddon` file from the GitHub Releases page.
2. Open Anki Desktop.
3. Select **Tools > Add-ons**.
4. Choose **Install from file** and select the downloaded `.ankiaddon` file.
5. Restart Anki.

Anki Lookup supports Anki Desktop. AnkiMobile and AnkiDroid do not load desktop
add-ons.

## Dictionary Files

Dictionary files are not bundled. Users must provide dictionaries they are permitted
to use and import them through the add-on's dictionary manager. Imported dictionaries
are stored in the add-on's preserved `user_files` directory and survive normal restarts
and add-on upgrades.

## Security & privacy

- **No telemetry, no background network access.** Anki Lookup contacts the network only
  when you explicitly open a translation tab, and only then it opens Google Translate or
  DeepL with the sentence you selected. Nothing is sent anywhere otherwise.
- **Dictionary content is treated as untrusted.** Definitions from imported dictionaries
  are rendered as plain text in the popup and HTML-escaped before landing in a note
  field, so a malicious dictionary cannot run scripts in the reviewer or on a card.
  Dictionary archives are validated on import against path-traversal and decompression
  ("zip bomb") attacks.
- **The translation bridge is off by default and local-only.** The optional *Translate
  inside Anki* feature listens on the loopback interface (`127.0.0.1`) only — never on a
  network interface — so no other machine can reach it. It is a same-machine channel
  shared with the Wonder of U desktop app and browser extension; treat it, like anything
  else on your own computer, as trusted only against other software already running as
  you. Leave it off unless you use that integration.
- **Everything stays in the add-on's folder.** All data the add-on writes — dictionaries
  and the translation cache — lives under its own `user_files` directory. It does not
  read or write anywhere else on your system.
