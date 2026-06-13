(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.AnkiLookupScannerCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    const WORD_PATTERN = /[\p{L}\p{N}\p{M}_'’\-]/u;

    const JAPANESE_CHARACTER_PATTERN =
        /[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}々〆ヶー]/u;
    const SMALL_KANA_PATTERN = /[ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ]/u;
    const segmenters = new Map();

    function getSegmenter(locale, granularity) {
        if (typeof Intl === "undefined" || typeof Intl.Segmenter !== "function") {
            return null;
        }
        const key = `${locale || ""}:${granularity}`;
        if (!segmenters.has(key)) {
            segmenters.set(
                key,
                new Intl.Segmenter(locale || undefined, { granularity }),
            );
        }
        return segmenters.get(key);
    }

    function normalizeTerm(value, maximumLength) {
        return String(value || "")
            .replace(/\s+/gu, " ")
            .trim()
            .slice(0, maximumLength);
    }

    function sanitizeSentence(value, maximumLength = 2000) {
        let sentence = normalizeTerm(value, maximumLength);
        const openingBraces = (sentence.match(/\{/gu) || []).length;
        const closingBraces = (sentence.match(/\}/gu) || []).length;
        if (openingBraces > closingBraces) {
            sentence = sentence.replace(/^\{+\s*/u, "");
        } else if (closingBraces > openingBraces) {
            sentence = sentence.replace(/^\}+\s*/u, "");
        }

        const remainingOpeningBraces = (sentence.match(/\{/gu) || []).length;
        const remainingClosingBraces = (sentence.match(/\}/gu) || []).length;
        if (remainingOpeningBraces > remainingClosingBraces) {
            sentence = sentence.replace(/\s*\{+$/u, "");
        } else if (remainingClosingBraces > remainingOpeningBraces) {
            sentence = sentence.replace(/\s*\}+$/u, "");
        }
        return sentence.trim();
    }

    function japaneseCandidates(text, start, maximumLength) {
        if (!text || start < 0 || start >= text.length) {
            return [];
        }
        const run = [];
        for (const character of Array.from(text.slice(start))) {
            if (!JAPANESE_CHARACTER_PATTERN.test(character)) {
                break;
            }
            run.push(character);
            if (run.length >= maximumLength) {
                break;
            }
        }
        const candidates = [];
        for (let length = run.length; length > 0; length -= 1) {
            candidates.push(run.slice(0, length).join(""));
        }
        return candidates;
    }

    function lookupCandidates(text, start, initialTerm, maximumLength, locale) {
        if (!text || start < 0 || start >= text.length) {
            return initialTerm ? [initialTerm] : [];
        }
        if (JAPANESE_CHARACTER_PATTERN.test(text[start])) {
            return japaneseCandidates(text, start, Math.min(maximumLength, 20));
        }

        const endLimit = Math.min(text.length, start + maximumLength);
        const source = text.slice(start, endLimit);
        const candidates = [];
        const segmenter = getSegmenter(locale, "word");
        if (segmenter) {
            let wordCount = 0;
            for (const part of segmenter.segment(source)) {
                if (/[\n.!?。！？]/u.test(part.segment)) {
                    break;
                }
                if (!part.isWordLike) {
                    continue;
                }
                wordCount += 1;
                candidates.push(normalizeTerm(source.slice(0, part.index + part.segment.length), maximumLength));
                if (wordCount >= 6) {
                    break;
                }
            }
        }
        if (!candidates.length && initialTerm) {
            candidates.push(normalizeTerm(initialTerm, maximumLength));
        }
        return [...new Set(candidates.filter(Boolean))].reverse();
    }

    function segmentAt(text, offset, locale) {
        if (!text || offset < 0 || offset > text.length) {
            return null;
        }

        const segmenter = getSegmenter(locale, "word");
        if (segmenter) {
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

    function clampPopupSize(width, height, viewportWidth, viewportHeight, margin) {
        const availableWidth = Math.max(240, viewportWidth - margin * 2);
        const availableHeight = Math.max(180, viewportHeight - margin * 2);
        return {
            width: Math.min(availableWidth, Math.max(280, width)),
            height: Math.min(availableHeight, Math.max(220, height)),
        };
    }

    function lookupDelay(now, previousStart, interval) {
        return Math.max(0, interval - (now - previousStart));
    }

    function canOpenNestedPopup(sourceDepth, enabled, maximumDepth) {
        return enabled && sourceDepth + 1 < maximumDepth;
    }

    function japaneseMorae(reading) {
        const morae = [];
        for (const character of Array.from(reading || "")) {
            if (SMALL_KANA_PATTERN.test(character) && morae.length) {
                morae[morae.length - 1] += character;
            } else {
                morae.push(character);
            }
        }
        return morae;
    }

    function pitchLevels(moraCount, position) {
        const count = Math.max(0, moraCount);
        if (typeof position === "string" && /^[HL]+$/u.test(position)) {
            const values = Array.from(position, (level) => level === "H");
            while (values.length < count + 1) {
                values.push(values[values.length - 1] || false);
            }
            return values.slice(0, count + 1);
        }
        const downstep =
            Number.isInteger(position) && position >= 0 ? position : 0;
        const levels = [];
        for (let index = 0; index <= count; index += 1) {
            if (downstep === 0) {
                levels.push(index > 0);
            } else if (downstep === 1) {
                levels.push(index === 0);
            } else {
                levels.push(index > 0 && index < downstep);
            }
        }
        return levels;
    }

    function isPopupDescendant(state, ancestor) {
        let parent = state.parent;
        while (parent) {
            if (parent === ancestor) {
                return true;
            }
            parent = parent.parent;
        }
        return false;
    }

    function anchoredVerticalPosition(
        anchor,
        requestedHeight,
        viewportHeight,
        margin,
        gap,
    ) {
        const viewportHeightAvailable = Math.max(0, viewportHeight - margin * 2);
        if (!anchor) {
            return {
                top: margin,
                height: Math.min(requestedHeight, viewportHeightAvailable),
                placement: "below",
            };
        }

        const belowTop = Math.max(
            margin,
            Math.min(anchor.bottom + gap, viewportHeight - margin),
        );
        const aboveBottom = Math.max(
            margin,
            Math.min(anchor.top - gap, viewportHeight - margin),
        );
        const availableBelow = Math.max(
            0,
            viewportHeight - margin - belowTop,
        );
        const availableAbove = Math.max(0, aboveBottom - margin);
        const placement =
            availableBelow >= requestedHeight || availableBelow >= availableAbove
                ? "below"
                : "above";
        const availableHeight =
            placement === "above" ? availableAbove : availableBelow;
        const height = Math.min(requestedHeight, availableHeight);

        return {
            top: placement === "above" ? aboveBottom - height : belowTop,
            height,
            placement,
        };
    }

    function popupPosition(
        anchor,
        size,
        viewportWidth,
        viewportHeight,
        margin,
        gap,
    ) {
        const preferredLeft = anchor ? anchor.left : (viewportWidth - size.width) / 2;
        const vertical = anchoredVerticalPosition(
            anchor,
            size.height,
            viewportHeight,
            margin,
            gap,
        );
        return {
            left: Math.max(
                margin,
                Math.min(preferredLeft, viewportWidth - size.width - margin),
            ),
            ...vertical,
        };
    }

    function nestedPopupPosition(
        parent,
        anchor,
        size,
        viewportWidth,
        viewportHeight,
        margin,
        gap,
    ) {
        const right = parent.right + gap;
        const left = parent.left - size.width - gap;
        const preferredLeft =
            right + size.width <= viewportWidth - margin
                ? right
                : left >= margin
                  ? left
                  : anchor.left;
        const vertical = anchoredVerticalPosition(
            anchor,
            size.height,
            viewportHeight,
            margin,
            gap,
        );
        return {
            left: Math.max(
                margin,
                Math.min(preferredLeft, viewportWidth - size.width - margin),
            ),
            ...vertical,
        };
    }

    function sourceRailPlacement(
        popupLeft,
        popupWidth,
        viewportWidth,
        margin,
        railWidth,
        gap,
        preferRight,
    ) {
        const assemblyWidth = popupWidth + railWidth + gap;
        if (assemblyWidth > viewportWidth - margin * 2) {
            return {
                popupLeft: Math.max(
                    margin,
                    Math.min(popupLeft, viewportWidth - popupWidth - margin),
                ),
                side: "inside",
            };
        }
        const canUseLeft = popupLeft - railWidth - gap >= margin;
        const canUseRight =
            popupLeft + popupWidth + railWidth + gap <= viewportWidth - margin;
        if (preferRight && canUseRight) {
            return { popupLeft, side: "right" };
        }
        if (!preferRight && canUseLeft) {
            return { popupLeft, side: "left" };
        }
        if (canUseLeft) {
            return { popupLeft, side: "left" };
        }
        if (canUseRight) {
            return { popupLeft, side: "right" };
        }
        return preferRight
            ? {
                  popupLeft: viewportWidth - margin - assemblyWidth,
                  side: "right",
              }
            : {
                  popupLeft: margin + railWidth + gap,
                  side: "left",
              };
    }

    function clampDraggedPopupPosition(
        left,
        top,
        size,
        viewportWidth,
        viewportHeight,
        margin,
        railSide,
        railWidth,
        gap,
    ) {
        const minimumLeft =
            railSide === "left" ? margin + railWidth + gap : margin;
        const maximumLeft =
            viewportWidth -
            margin -
            size.width -
            (railSide === "right" ? railWidth + gap : 0);
        return {
            left: Math.max(minimumLeft, Math.min(left, maximumLeft)),
            top: Math.max(
                margin,
                Math.min(top, viewportHeight - margin - size.height),
            ),
        };
    }

    function sentenceAt(text, offset, locale) {
        if (!text || offset < 0 || offset > text.length) {
            return "";
        }
        const segmenter = getSegmenter(locale, "sentence");
        if (segmenter) {
            for (const part of segmenter.segment(text)) {
                const end = part.index + part.segment.length;
                if (offset >= part.index && offset <= end) {
                    return sanitizeSentence(part.segment);
                }
            }
        }

        const boundary = /[.!?。！？\n]/u;
        let start = Math.min(offset, text.length);
        let end = start;
        while (start > 0 && !boundary.test(text[start - 1])) {
            start -= 1;
        }
        while (end < text.length && !boundary.test(text[end])) {
            end += 1;
        }
        if (end < text.length) {
            end += 1;
        }
        return sanitizeSentence(text.slice(start, end));
    }

    return {
        clampPopupSize,
        clampDraggedPopupPosition,
        canOpenNestedPopup,
        isPopupDescendant,
        japaneseMorae,
        japaneseCandidates,
        lookupCandidates,
        lookupDelay,
        matchesShortcut,
        nestedPopupPosition,
        normalizeTerm,
        pitchLevels,
        popupPosition,
        sanitizeSentence,
        segmentAt,
        sentenceAt,
        sourceRailPlacement,
    };
});
