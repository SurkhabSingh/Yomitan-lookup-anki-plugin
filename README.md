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
- Google Translate and DeepL translation actions.
- A configurable popup with themes, fonts, sizing, and layout controls.
- Direct creation of new Anki notes from lookup results.

> **Development status:** Pre-alpha. Hold-to-scan, local Yomitan term and kanji
> dictionary imports, exact and reverse-definition results, and dictionary tabs are
> available.
> Translation provider connections and direct note creation are still being
> implemented.

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
Results are shown in a separate tab for each dictionary. Google Translate and DeepL
tabs are visible as placeholders, but do not send text or translate it yet. Pitch
metadata-only archives are not searchable yet.

Open **Tools > Anki Lookup: Settings...** to select a system, light, dark, or
high-contrast theme, choose the popup font and font size, change the pin shortcut, or
choose between dictionary buttons in Sources and continuous dictionary results.
Appearance and layout changes apply immediately to the active reviewer.

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
