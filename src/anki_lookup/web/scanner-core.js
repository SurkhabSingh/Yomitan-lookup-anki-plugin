(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.AnkiLookupScannerCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    const WORD_PATTERN = /[\p{L}\p{N}\p{M}_'’\-]/u;

    function normalizeTerm(value, maximumLength) {
        return String(value || "")
            .replace(/\s+/gu, " ")
            .trim()
            .slice(0, maximumLength);
    }

    function segmentAt(text, offset, locale) {
        if (!text || offset < 0 || offset > text.length) {
            return null;
        }

        if (typeof Intl !== "undefined" && typeof Intl.Segmenter === "function") {
            const segmenter = new Intl.Segmenter(locale || undefined, {
                granularity: "word",
            });
            for (const part of segmenter.segment(text)) {
                const end = part.index + part.segment.length;
                if (
                    part.isWordLike &&
                    offset >= part.index &&
                    offset <= end
                ) {
                    return {
                        term: part.segment,
                        start: part.index,
                        end,
                    };
                }
            }
        }

        let probe = Math.min(offset, text.length - 1);
        if (probe >= 0 && !WORD_PATTERN.test(text[probe]) && probe > 0) {
            probe -= 1;
        }
        if (probe < 0 || !WORD_PATTERN.test(text[probe])) {
            return null;
        }

        let start = probe;
        let end = probe + 1;
        while (start > 0 && WORD_PATTERN.test(text[start - 1])) {
            start -= 1;
        }
        while (end < text.length && WORD_PATTERN.test(text[end])) {
            end += 1;
        }

        return { term: text.slice(start, end), start, end };
    }

    function matchesShortcut(event, shortcut) {
        const parts = String(shortcut || "")
            .split("+")
            .map((part) => part.trim().toLowerCase())
            .filter(Boolean);
        if (!parts.length) {
            return false;
        }

        const key = parts[parts.length - 1];
        return (
            event.key.toLowerCase() === key &&
            event.ctrlKey === parts.includes("ctrl") &&
            event.shiftKey === parts.includes("shift") &&
            event.altKey === parts.includes("alt") &&
            event.metaKey === parts.includes("meta")
        );
    }

    return { matchesShortcut, normalizeTerm, segmentAt };
});

