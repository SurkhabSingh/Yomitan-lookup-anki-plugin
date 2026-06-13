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

console.log("JavaScript scanner tests completed.");
