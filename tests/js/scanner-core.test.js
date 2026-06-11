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

test("normalizes whitespace and enforces the limit", () => {
    assert.equal(core.normalizeTerm("  hello   world  ", 8), "hello wo");
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
