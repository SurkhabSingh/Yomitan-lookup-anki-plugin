const assert = require("node:assert/strict");
const core = require("../../src/anki_lookup/web/scanner-core.js");

function test(name, callback) {
    callback();
    console.log(`PASS ${name}`);
}

test("segments a Latin word at the pointer offset", () => {
    const result = core.segmentAt("hello world", 7, "en");
    assert.equal(result.term, "world");
});

test("segments non-Latin text", () => {
    const result = core.segmentAt("日本語 学習", 1, "ja");
    assert.ok(result);
    assert.ok(result.term.length > 0);
});

test("expands Japanese kana into longest-first lookup candidates", () => {
    assert.deepEqual(core.japaneseCandidates("くるまです", 0, 4), [
        "くるまで",
        "くるま",
        "くる",
        "く",
    ]);
    assert.deepEqual(core.japaneseCandidates("車です", 0, 3), ["車です", "車で", "車"]);
});

test("builds longest-first multiword lookup candidates for spaced languages", () => {
    assert.deepEqual(
        core.lookupCandidates("take off quickly.", 0, "take", 80, "en"),
        ["take off quickly", "take off", "take"],
    );
});

test("normalizes whitespace and enforces the limit", () => {
    assert.equal(core.normalizeTerm("  hello   world  ", 8), "hello wo");
});

test("extracts the sentence around the lookup offset", () => {
    assert.equal(
        core.sentenceAt("First sentence. Target word is here! Last sentence.", 22, "en"),
        "Target word is here!",
    );
});

test("removes unmatched template braces from captured sentence edges", () => {
    assert.equal(core.sentenceAt("{ 漢字を勉強します。", 3, "ja"), "漢字を勉強します。");
    assert.equal(core.sanitizeSentence("Translate {this} sentence."), "Translate {this} sentence.");
});

test("clamps popup dimensions to usable viewport bounds", () => {
    assert.deepEqual(core.clampPopupSize(900, 100, 800, 600, 12), {
        width: 776,
        height: 220,
    });
});

test("computes a leading lookup throttle delay", () => {
    assert.equal(core.lookupDelay(100, 0, 20), 0);
    assert.equal(core.lookupDelay(110, 100, 20), 10);
});

test("bounds nested popup depth and respects the feature toggle", () => {
    assert.equal(core.canOpenNestedPopup(1, true, 4), true);
    assert.equal(core.canOpenNestedPopup(3, true, 4), false);
    assert.equal(core.canOpenNestedPopup(0, false, 4), false);
});

test("groups small kana into Japanese morae", () => {
    assert.deepEqual(core.japaneseMorae("きょう"), ["きょ", "う"]);
    assert.deepEqual(core.japaneseMorae("キャット"), ["キャ", "ッ", "ト"]);
});

test("builds pitch levels from downstep positions and explicit patterns", () => {
    assert.deepEqual(core.pitchLevels(3, 0), [false, true, true, true]);
    assert.deepEqual(core.pitchLevels(3, 1), [true, false, false, false]);
    assert.deepEqual(core.pitchLevels(3, 2), [false, true, false, false]);
    assert.deepEqual(core.pitchLevels(3, "LHHL"), [false, true, true, false]);
});

test("identifies every popup descendant regardless of pin state", () => {
    const root = { parent: null, pinned: true };
    const child = { parent: root, pinned: false };
    const pinnedGrandchild = { parent: child, pinned: true };
    const otherRoot = { parent: null, pinned: false };

    assert.equal(core.isPopupDescendant(child, root), true);
    assert.equal(core.isPopupDescendant(pinnedGrandchild, root), true);
    assert.equal(core.isPopupDescendant(pinnedGrandchild, child), true);
    assert.equal(core.isPopupDescendant(root, root), false);
    assert.equal(core.isPopupDescendant(otherRoot, root), false);
});

test("keeps a popup below its scanned text", () => {
    assert.deepEqual(
        core.popupPosition(
            { left: 700, top: 200, bottom: 220 },
            { width: 300, height: 240 },
            800,
            700,
            12,
            10,
        ),
        { left: 488, top: 230, height: 240, placement: "below" },
    );
});

test("places a popup above text near the viewport bottom", () => {
    assert.deepEqual(
        core.popupPosition(
            { left: 700, top: 500, bottom: 520 },
            { width: 300, height: 240 },
            800,
            600,
            12,
            10,
        ),
        { left: 488, top: 250, height: 240, placement: "above" },
    );
});

test("uses the larger side and constrains height when neither side fits", () => {
    assert.deepEqual(
        core.popupPosition(
            { left: 300, top: 260, bottom: 280 },
            { width: 300, height: 400 },
            800,
            600,
            12,
            10,
        ),
        { left: 300, top: 290, height: 298, placement: "below" },
    );
});

test("places a nested popup beside its parent when space is available", () => {
    assert.deepEqual(
        core.nestedPopupPosition(
            { left: 100, right: 500 },
            { left: 200, top: 120, bottom: 140 },
            { width: 280, height: 300 },
            1000,
            700,
            12,
            10,
        ),
        { left: 510, top: 150, height: 300, placement: "below" },
    );
});

test("places a nested popup above a bottom-edge scan target", () => {
    assert.deepEqual(
        core.nestedPopupPosition(
            { left: 100, right: 500 },
            { left: 200, top: 560, bottom: 580 },
            { width: 280, height: 300 },
            1000,
            700,
            12,
            10,
        ),
        { left: 510, top: 250, height: 300, placement: "above" },
    );
});

test("places a source rail outside the preferred popup edge", () => {
    assert.deepEqual(
        core.sourceRailPlacement(200, 360, 1000, 12, 144, 8, false),
        { popupLeft: 200, side: "left" },
    );
    assert.deepEqual(
        core.sourceRailPlacement(20, 360, 1000, 12, 144, 8, false),
        { popupLeft: 20, side: "right" },
    );
});

test("moves the popup to reserve its external source rail", () => {
    assert.deepEqual(
        core.sourceRailPlacement(150, 700, 1000, 12, 144, 8, false),
        { popupLeft: 164, side: "left" },
    );
});

test("keeps a dragged pinned popup and its source rail inside the viewport", () => {
    assert.deepEqual(
        core.clampDraggedPopupPosition(
            -100,
            900,
            { width: 360, height: 420 },
            1000,
            700,
            12,
            "left",
            144,
            8,
        ),
        { left: 164, top: 268 },
    );
    assert.deepEqual(
        core.clampDraggedPopupPosition(
            900,
            20,
            { width: 360, height: 420 },
            1000,
            700,
            12,
            "right",
            144,
            8,
        ),
        { left: 476, top: 20 },
    );
});

test("matches the configured selection shortcut exactly", () => {
    const event = {
        key: "L",
        ctrlKey: true,
        shiftKey: true,
        altKey: false,
        metaKey: false,
    };
    assert.equal(core.matchesShortcut(event, "Ctrl+Shift+L"), true);
    assert.equal(core.matchesShortcut({ ...event, altKey: true }, "Ctrl+Shift+L"), false);
});

/* Translation ----------------------------------------------------------------
   The fixture below is shared with tests/test_translation_external.py. Python's
   urlencode/quote and JavaScript's URLSearchParams/encodeURIComponent are separate
   implementations of the same rule, and they disagree on enough characters that
   only a shared contract keeps them honest. */

const externalUrlFixture = require("../fixtures/external_urls.json");

test("builds external translator URLs matching the shared fixture", () => {
    assert.ok(externalUrlFixture.cases.length > 0);
    for (const testCase of externalUrlFixture.cases) {
        assert.equal(
            core.externalTranslateUrl(
                testCase.provider,
                testCase.text,
                testCase.source,
                testCase.target,
            ),
            testCase.expected,
            testCase.name,
        );
    }
});

test("falls back to Google for an unknown external provider", () => {
    const url = core.externalTranslateUrl("wonder-of-u", "hi", "auto", "en");
    assert.ok(url.startsWith("https://translate.google.com/"));
});

test("falls back to auto and en for empty external language codes", () => {
    const url = core.externalTranslateUrl("google-translate", "hi", "", "");
    assert.ok(url.includes("sl=auto"));
    assert.ok(url.includes("tl=en"));
});

test("truncates long external translator text", () => {
    const text = "あ".repeat(2500);
    assert.equal(core.truncateForExternalUrl(text).length, 1800);
});

test("labels providers for display", () => {
    assert.equal(core.providerLabel("google-translate"), "Google Translate");
    assert.equal(core.providerLabel("deepl"), "DeepL");
    assert.equal(core.providerLabel("unknown"), "unknown");
});

test("an untouched translation tab shows nothing", () => {
    const model = core.translationState(null);
    assert.equal(model.state, "idle");
    assert.deepEqual(model.actions, []);
});

test("a pending translation names the provider and offers cancel", () => {
    const model = core.translationState({ status: "pending", provider: "deepl" });
    assert.equal(model.state, "pending");
    assert.ok(model.message.includes("DeepL"));
    assert.deepEqual(model.actions, ["cancel"]);
});

test("a ready translation shows text and offers copy and retry", () => {
    const model = core.translationState({
        status: "ready",
        text: "Hello",
        provider: "google-translate",
    });
    assert.equal(model.state, "ready");
    assert.equal(model.text, "Hello");
    assert.equal(model.cached, false);
    assert.deepEqual(model.actions, ["copy", "retry"]);
});

test("a cached translation is marked as cached", () => {
    const model = core.translationState({ status: "ready", text: "Hello", cached: true });
    assert.equal(model.cached, true);
});

test("an unavailable translation explains why and offers the website", () => {
    const model = core.translationState({
        status: "unavailable",
        message: "Wonder of U desktop is handling translation on port 8791.",
        external_url: "https://translate.google.com/?sl=auto",
    });
    assert.equal(model.state, "unavailable");
    assert.ok(model.message.includes("Wonder of U"));
    assert.deepEqual(model.actions, ["open_external"]);
});

test("an unavailable translation without a fallback offers no action", () => {
    const model = core.translationState({ status: "unavailable", message: "Nope" });
    assert.deepEqual(model.actions, []);
});

test("a failed translation offers retry and the website", () => {
    const model = core.translationState({
        status: "error",
        message: "The translation timed out.",
        external_url: "https://translate.google.com/?sl=auto",
    });
    assert.equal(model.state, "error");
    assert.deepEqual(model.actions, ["retry", "open_external"]);
});

test("an unknown status is treated as an error rather than rendering blank", () => {
    const model = core.translationState({ status: "banana" });
    assert.equal(model.state, "error");
    assert.ok(model.message);
});

test("translation is requested lazily and only once per lookup", () => {
    // Every hold-to-scan pointer move re-renders the tabs. Requesting on render
    // would queue a job per mouse move against a serial extension.
    assert.equal(core.shouldRequestTranslation({ sentence: "hi", requested: false }), true);
    assert.equal(core.shouldRequestTranslation({ sentence: "hi", requested: true }), false);
    assert.equal(core.shouldRequestTranslation({ sentence: "", requested: false }), false);
    assert.equal(core.shouldRequestTranslation(null), false);
});

test("a pushed result is matched to its popup and request", () => {
    const payload = { kind: "translation", popup_token: "popup-2", request_id: 7 };
    assert.equal(core.isCurrentTranslation(payload, "popup-2", 7), true);
});

test("a pushed result for a replaced popup or stale request is ignored", () => {
    const payload = { kind: "translation", popup_token: "popup-2", request_id: 7 };
    // Nested popups reuse depth, so the token is the only stable key.
    assert.equal(core.isCurrentTranslation(payload, "popup-3", 7), false);
    assert.equal(core.isCurrentTranslation(payload, "popup-2", 8), false);
    assert.equal(core.isCurrentTranslation({ kind: "lookup" }, "popup-2", 7), false);
    assert.equal(core.isCurrentTranslation(null, "popup-2", 7), false);
});

/* Sentence context ------------------------------------------------------------- */

test("locates the scanned word inside the sentence it sends", () => {
    const text = "毎朝パンを食べました。それから出かけた。";
    const context = core.sentenceContextAt(text, 5, "ja", "食べました");
    assert.equal(context.term, "食べました");
    assert.equal(context.text.slice(context.offset, context.offset + context.term.length), "食べました");
});

test("the offset partitions the sentence without losing anything", () => {
    // The invariant the Python side depends on: prefix + body + suffix === sentence.
    const text = "I ate bread today.";
    const context = core.sentenceContextAt(text, 2, "en", "ate");
    const prefix = context.text.slice(0, context.offset);
    const body = context.text.slice(context.offset, context.offset + context.term.length);
    const suffix = context.text.slice(context.offset + context.term.length);
    assert.equal(body, "ate");
    assert.equal(prefix + body + suffix, context.text);
});

test("a repeated word resolves to the occurrence that was scanned", () => {
    // Why the original position is used as a hint rather than taking indexOf's first
    // answer: both occurrences match, and only one is the one under the pointer.
    const text = "パンを食べる前にパンを見た。";
    const near = core.sentenceContextAt(text, 0, "ja", "パン");
    const far = core.sentenceContextAt(text, 8, "ja", "パン");
    assert.equal(near.offset, 0);
    assert.ok(far.offset > near.offset, "the later occurrence should win when scanned later");
});

test("a word missing from the sentence yields an empty cloze rather than a wrong one", () => {
    // The segmenter and the scanner disagreed about a boundary. Better no cloze body
    // than one cut in the wrong place.
    const context = core.sentenceContextAt("完全に違う文です。", 0, "ja", "見つからない");
    assert.equal(context.term, "");
    assert.equal(context.offset, 0);
    assert.ok(context.text.length > 0, "the sentence itself should still be usable");
});

test("no text yields an empty context", () => {
    const context = core.sentenceContextAt("", 0, "ja", "食べる");
    assert.equal(context.text, "");
    assert.equal(context.term, "");
});

test("the sentence context still returns the same sentence as sentenceAt", () => {
    const text = "毎朝パンを食べました。";
    assert.equal(core.sentenceContextAt(text, 5, "ja", "食べました").text, core.sentenceAt(text, 5, "ja"));
});

/* Pitch ------------------------------------------------------------------------
   The same fixture tests/test_notes_markers.py reads. The popup renders pitch here
   in JavaScript; note fields render it in Python. Two implementations of one
   algorithm, and this fixture is the only thing holding them together — a case added
   there has to pass on both sides. (The fixture's `categories` section is Python-only:
   the popup does not render categories, so there is nothing here to keep in step.) */

const pitchFixture = require("../fixtures/pitch_accents.json");

test("morae match the shared fixture", () => {
    assert.ok(pitchFixture.morae.length > 0);
    for (const testCase of pitchFixture.morae) {
        assert.deepEqual(core.japaneseMorae(testCase.reading), testCase.expected, testCase.name);
    }
});

test("pitch levels match the shared fixture", () => {
    assert.ok(pitchFixture.levels.length > 0);
    for (const testCase of pitchFixture.levels) {
        assert.deepEqual(
            core.pitchLevels(testCase.moraCount, testCase.position),
            testCase.expected,
            testCase.name,
        );
    }
});

test("pitch levels always cover every mora plus the particle", () => {
    // The particle is where heiban and odaka actually differ, so it is not optional.
    for (const testCase of pitchFixture.levels) {
        assert.equal(
            core.pitchLevels(testCase.moraCount, testCase.position).length,
            testCase.moraCount + 1,
            testCase.name,
        );
    }
});

/* Resize ---------------------------------------------------------------------- */

const START_RECT = { left: 100, top: 100, right: 400, bottom: 300, width: 300, height: 200 };

test("each corner grows along its own diagonal", () => {
    assert.deepEqual(core.resizeDelta("bottom-right", START_RECT, 50, 40), {
        width: 350,
        height: 240,
    });
    // Dragging left/up from a left/top grip grows the box, so the deltas invert.
    assert.deepEqual(core.resizeDelta("top-left", START_RECT, -50, -40), {
        width: 350,
        height: 240,
    });
    assert.deepEqual(core.resizeDelta("bottom-left", START_RECT, -50, 40), {
        width: 350,
        height: 240,
    });
    assert.deepEqual(core.resizeDelta("top-right", START_RECT, 50, -40), {
        width: 350,
        height: 240,
    });
});

test("the corner opposite the grip stays put", () => {
    // bottom-right drag: the top-left corner must not move.
    let g = core.resizeGeometry("bottom-right", START_RECT, { width: 350, height: 240 });
    assert.equal(g.left, 100);
    assert.equal(g.top, 100);

    // top-left drag: the bottom-right corner must not move.
    g = core.resizeGeometry("top-left", START_RECT, { width: 350, height: 240 });
    assert.equal(g.left + g.width, START_RECT.right);
    assert.equal(g.top + g.height, START_RECT.bottom);

    g = core.resizeGeometry("bottom-left", START_RECT, { width: 350, height: 240 });
    assert.equal(g.left + g.width, START_RECT.right);
    assert.equal(g.top, START_RECT.top);

    g = core.resizeGeometry("top-right", START_RECT, { width: 350, height: 240 });
    assert.equal(g.left, START_RECT.left);
    assert.equal(g.top + g.height, START_RECT.bottom);
});

test("a clamped size does not drag the anchored corner out of place", () => {
    // The size is derived from the opposite edge rather than the pointer delta, so
    // when clampPopupSize refuses to shrink further the far corner stays exactly
    // where it was instead of creeping.
    const clamped = { width: 280, height: 220 };
    const g = core.resizeGeometry("top-left", START_RECT, clamped);
    assert.equal(g.left + g.width, START_RECT.right);
    assert.equal(g.top + g.height, START_RECT.bottom);
});

test("only real corners are accepted", () => {
    for (const corner of ["top-left", "top-right", "bottom-left", "bottom-right"]) {
        assert.equal(core.isResizeCorner(corner), true);
    }
    assert.equal(core.isResizeCorner("middle"), false);
    assert.equal(core.isResizeCorner(undefined), false);
    assert.equal(core.isResizeCorner(""), false);
});

// A word near the bottom of the viewport: little room below, plenty above.
const LOW_ANCHOR = { top: 400, bottom: 420, left: 50, right: 120 };
const TALL = { width: 360, height: 600 };

test("an automatically placed popup is capped to the room beside the word", () => {
    const auto = core.popupPosition(LOW_ANCHOR, TALL, 800, 480, 12, 10, false);
    assert.equal(auto.placement, "above");
    assert.ok(auto.height < TALL.height, "height should be capped when auto-placed");
    assert.ok(auto.top >= 12);
});

test("a user-sized popup keeps its height instead of being capped", () => {
    // The bug: dragging a grip grew state.size while the rendered box refused to
    // change, because the anchor slot overrode it. Pinning was the only way out.
    const auto = core.popupPosition(LOW_ANCHOR, TALL, 800, 480, 12, 10, false);
    const sized = core.popupPosition(LOW_ANCHOR, TALL, 800, 480, 12, 10, true);

    assert.ok(sized.height > auto.height, "user size must beat the anchor cap");
    assert.equal(sized.height, 480 - 24, "capped only by the viewport");
});

test("a user-sized popup still fits inside the viewport", () => {
    const huge = { width: 360, height: 10000 };
    const sized = core.popupPosition(LOW_ANCHOR, huge, 800, 480, 12, 10, true);
    assert.ok(sized.top >= 12);
    assert.ok(sized.top + sized.height <= 480 - 12);
});

test("a user-sized popup still prefers the side with room", () => {
    const size = { width: 360, height: 300 };
    const nearTop = { top: 20, bottom: 40, left: 50, right: 120 };
    assert.equal(core.popupPosition(nearTop, size, 800, 480, 12, 10, true).placement, "below");
    assert.equal(core.popupPosition(LOW_ANCHOR, size, 800, 480, 12, 10, true).placement, "above");
});

test("a nested popup honours a user size too", () => {
    const parent = { left: 100, right: 400, top: 50, bottom: 250 };
    const auto = core.nestedPopupPosition(parent, LOW_ANCHOR, TALL, 800, 480, 12, 10, false);
    const sized = core.nestedPopupPosition(parent, LOW_ANCHOR, TALL, 800, 480, 12, 10, true);
    assert.ok(sized.height > auto.height);
});

test("automatic placement is unchanged when the user has not resized", () => {
    // The default must stay exactly as it was: userSized defaults to false, and the
    // opening position is still chosen to avoid covering the scanned word.
    const withFlag = core.popupPosition(LOW_ANCHOR, TALL, 800, 480, 12, 10, false);
    const withoutFlag = core.popupPosition(LOW_ANCHOR, TALL, 800, 480, 12, 10);
    assert.deepEqual(withoutFlag, withFlag);
});

/* Source rail keyboard navigation -------------------------------------------- */

test("arrow keys move between source tabs", () => {
    assert.equal(core.nextTabIndex(0, 3, "ArrowRight"), 1);
    assert.equal(core.nextTabIndex(1, 3, "ArrowLeft"), 0);
    // The rail renders vertically, so Up/Down have to work too.
    assert.equal(core.nextTabIndex(0, 3, "ArrowDown"), 1);
    assert.equal(core.nextTabIndex(1, 3, "ArrowUp"), 0);
});

test("source tab navigation wraps at both ends", () => {
    assert.equal(core.nextTabIndex(2, 3, "ArrowRight"), 0);
    assert.equal(core.nextTabIndex(0, 3, "ArrowLeft"), 2);
});

test("Home and End jump to the first and last source", () => {
    assert.equal(core.nextTabIndex(2, 3, "Home"), 0);
    assert.equal(core.nextTabIndex(0, 3, "End"), 2);
});

test("a non-navigation key leaves the source tab alone", () => {
    // Returning the current index unchanged is how the caller knows not to
    // preventDefault and swallow the key.
    assert.equal(core.nextTabIndex(1, 3, "a"), 1);
    assert.equal(core.nextTabIndex(1, 3, "Enter"), 1);
    assert.equal(core.isTabNavigationKey("a"), false);
    assert.equal(core.isTabNavigationKey("ArrowRight"), true);
    assert.equal(core.isTabNavigationKey("Home"), true);
});

test("source tab navigation survives a missing or out-of-range index", () => {
    // findIndex returns -1 when nothing is active yet.
    assert.equal(core.nextTabIndex(-1, 3, "ArrowRight"), 1);
    assert.equal(core.nextTabIndex(99, 3, "ArrowRight"), 0);
    assert.equal(core.nextTabIndex(0, 0, "ArrowRight"), 0);
});

/* Note creation -------------------------------------------------------------- */

test("an unconfigured preset disables Add and says why", () => {
    // Disabled up front rather than failing after the user commits to it mid-review.
    const model = core.noteState(null, false);
    assert.equal(model.state, "not_configured");
    assert.equal(model.enabled, false);
    assert.ok(model.message.includes("preset"));
});

test("a configured preset offers Add", () => {
    const model = core.noteState(null, true);
    assert.equal(model.state, "idle");
    assert.equal(model.enabled, true);
    assert.equal(model.message, "");
});

test("a queued note disables the button while it runs", () => {
    const model = core.noteState({ status: "queued" }, true);
    assert.equal(model.state, "queued");
    assert.equal(model.enabled, false);
});

test("an added note confirms and offers to open it", () => {
    const model = core.noteState({ status: "added", note_id: 12 }, true);
    assert.equal(model.state, "added");
    assert.equal(model.enabled, false);
    assert.deepEqual(model.actions, ["open_note"]);
});

test("a duplicate offers to open the existing note or add anyway", () => {
    // The roadmap's rule: offer to open the existing note rather than silently
    // creating another.
    const model = core.noteState(
        { status: "duplicate", note_id: 9, message: "A note with this expression already exists." },
        true,
    );
    assert.equal(model.state, "duplicate");
    assert.deepEqual(model.actions, ["open_note", "add_anyway"]);
    assert.equal(model.enabled, true);
});

test("a failed note reports the error and stays retryable", () => {
    const model = core.noteState({ status: "error", message: "The deck no longer exists." }, true);
    assert.equal(model.state, "error");
    assert.equal(model.message, "The deck no longer exists.");
    assert.equal(model.enabled, true);
});

test("an unknown note status is treated as an error rather than rendering blank", () => {
    const model = core.noteState({ status: "banana" }, true);
    assert.equal(model.state, "error");
    assert.ok(model.message);
});

test("a pushed note result is matched to its popup and request", () => {
    const payload = { kind: "note", popup_token: "popup-1", request_id: 4 };
    assert.equal(core.isCurrentNote(payload, "popup-1", 4), true);
    assert.equal(core.isCurrentNote(payload, "popup-9", 4), false);
    assert.equal(core.isCurrentNote(payload, "popup-1", 5), false);
    assert.equal(core.isCurrentNote({ kind: "translation" }, "popup-1", 4), false);
});

test("note and translation pushes do not cross-dispatch", () => {
    // Both arrive on the same channel and carry the same routing keys.
    const notePayload = { kind: "note", popup_token: "p", request_id: 1 };
    const translationPayload = { kind: "translation", popup_token: "p", request_id: 1 };
    assert.equal(core.isCurrentTranslation(notePayload, "p", 1), false);
    assert.equal(core.isCurrentNote(translationPayload, "p", 1), false);
});

console.log("JavaScript scanner tests completed.");
