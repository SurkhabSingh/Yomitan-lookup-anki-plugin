# Anki Lookup

Anki Lookup is a desktop Anki add-on for looking up text directly while reviewing
cards.

It is designed to provide:

- Hold-to-scan word lookup with a configurable modifier key.
- Local Yomitan-compatible dictionaries for multiple languages.
- Google Translate and DeepL translation actions.
- A configurable popup with themes, fonts, sizing, and layout controls.
- Direct creation of new Anki notes from lookup results.

> **Development status:** Pre-alpha. Hold-to-scan and the lookup popup are available
> with placeholder results. Dictionary definitions and translation providers are still
> being implemented.

## Current Preview

While reviewing a card, hold **Shift** and move the pointer across text. Anki Lookup
will detect the word under the pointer and open the lookup popup. Press **Escape** to
close it. You can also select text and press **Ctrl+Shift+L**.

## Installation

1. Download the latest `.ankiaddon` file from the GitHub Releases page.
2. Open Anki Desktop.
3. Select **Tools > Add-ons**.
4. Choose **Install from file** and select the downloaded `.ankiaddon` file.
5. Restart Anki.

Anki Lookup supports Anki Desktop. AnkiMobile and AnkiDroid do not load desktop
add-ons.

## Dictionary Files

Dictionary files are not bundled. Users will import their own compatible dictionaries
through the add-on's dictionary manager when that feature is released.
