(function () {
    "use strict";

    const core = window.AnkiLookupScannerCore;
    const initialConfig = window.AnkiLookupConfig || {};
    const lookupConfig = initialConfig.lookup || {};
    let appearance = initialConfig.appearance || {};
    let translationSettings = normalizeTranslationSettings(initialConfig.translation);
    let notesSettings = normalizeNotesSettings(initialConfig.notes);

    function normalizeNotesSettings(settings) {
        const source = settings || {};
        return {
            // Derived by config.py: the popup does not need to know what makes a
            // preset valid, only whether this one is.
            configured: source.configured === true,
        };
    }

    function normalizeTranslationSettings(settings) {
        const source = settings || {};
        return {
            provider: source.provider || "google-translate",
            target_language: source.target_language || "en",
            // Injected by config.py so the popup never needs the language tables.
            target_language_label: source.target_language_label || "English",
        };
    }
    const modifier = lookupConfig.modifier || "Shift";
    const releaseBehavior = lookupConfig.release_behavior || "remain_open";
    const debounceMs = Number.isFinite(lookupConfig.debounce_ms)
        ? lookupConfig.debounce_ms
        : 20;
    const maximumTermLength = lookupConfig.maximum_term_length || 200;
    const allowNestedPopups = lookupConfig.allow_nested_popups !== false;
    const allowKanjiClick = lookupConfig.allow_kanji_click !== false;
    const maximumPopupDepth = lookupConfig.maximum_popup_depth || 4;
    const shortcut = lookupConfig.selection_shortcut || "Ctrl+Shift+L";
    let pinShortcut = lookupConfig.pin_shortcut || "Ctrl+Shift+K";
    const sourceRailWidth = 144;
    const sourceRailGap = 8;
    const popupByElement = new WeakMap();
    const popups = [];
    const lookupCache = new Map();
    let popupTokenSequence = 0;

    function nextPopupToken() {
        popupTokenSequence += 1;
        return `popup-${popupTokenSequence}`;
    }

    let modifierHeld = false;
    let requestSequence = 0;
    let framePending = false;
    let latestPointer = null;
    let pendingLookupTimer = null;
    let lastLookupStartedAt = 0;
    let resizeState = null;
    let dragState = null;

    function loadRootPopupSize() {
        const fallback = {
            width: appearance.popup_width_px || 380,
            height: appearance.popup_max_height_px || 440,
        };
        try {
            const saved = JSON.parse(localStorage.getItem("anki_lookup_popup_size"));
            if (
                saved &&
                Number.isFinite(saved.width) &&
                Number.isFinite(saved.height)
            ) {
                return { width: saved.width, height: saved.height };
            }
        } catch (_error) {
            // Storage can be unavailable in restricted card contexts.
        }
        return fallback;
    }

    function saveRootPopupSize(state) {
        if (state.depth !== 0) {
            return;
        }
        try {
            localStorage.setItem("anki_lookup_popup_size", JSON.stringify(state.size));
        } catch (_error) {
            // Resizing still works for the current reviewer session.
        }
    }

    function createPopup(depth, parent) {
        const element = document.createElement("section");
        const state = {
            element,
            depth,
            parent,
            // Identifies this popup for results that arrive after it was created.
            // Depth is not usable for this: nested popups reuse it, and by the time a
            // translation lands the popup that asked may be gone or replaced.
            token: nextPopupToken(),
            pinned: false,
            lastTerm: "",
            latestRequest: 0,
            hasResult: false,
            lastResponse: null,
            activeTabId: "",
            translation: null,
            anchorRect: null,
            manualPosition: null,
            // Set once the user drags a grip. From then on their size wins over
            // automatic placement, until the popup is reused for a different word.
            userSized: false,
            placement: "below",
            renderedSize: null,
            size:
                depth === 0
                    ? loadRootPopupSize()
                    : {
                          width: Math.min(360, appearance.popup_width_px || 380),
                          height: Math.min(380, appearance.popup_max_height_px || 440),
                      },
        };
        element.className = "anki-lookup-popup";
        element.dataset.depth = String(depth);
        element.setAttribute("role", "dialog");
        element.setAttribute("aria-live", "polite");
        element.setAttribute("aria-label", "Anki Lookup result");
        element.innerHTML = [
            '<header class="anki-lookup__header">',
            '<button type="button" class="anki-lookup__header-control anki-lookup__pin" data-popup-action="pin" aria-label="Pin popup" aria-pressed="false">',
            '<span class="anki-lookup__pin-icon" aria-hidden="true"></span>',
            "</button>",
            '<button type="button" class="anki-lookup__header-control anki-lookup__close" data-popup-action="close" aria-label="Close popup and child popups" title="Close popup and child popups">',
            '<span class="anki-lookup__close-icon" aria-hidden="true"></span>',
            "</button>",
            "</header>",
            '<div class="anki-lookup__body"></div>',
            // One grip per corner. A single grip that relocated depending on placement
            // meant the popup could only be resized from whichever corner happened to
            // face the free space.
            '<div class="anki-lookup__resize anki-lookup__resize--top-left" data-resize-corner="top-left" role="separator" aria-label="Resize popup" title="Drag to resize"></div>',
            '<div class="anki-lookup__resize anki-lookup__resize--top-right" data-resize-corner="top-right" role="separator" aria-label="Resize popup" title="Drag to resize"></div>',
            '<div class="anki-lookup__resize anki-lookup__resize--bottom-left" data-resize-corner="bottom-left" role="separator" aria-label="Resize popup" title="Drag to resize"></div>',
            '<div class="anki-lookup__resize anki-lookup__resize--bottom-right" data-resize-corner="bottom-right" role="separator" aria-label="Resize popup" title="Drag to resize"></div>',
        ].join("");
        element.addEventListener("pointerdown", (event) => onPopupPointerDown(event, state));
        element.addEventListener("click", (event) => onPopupClick(event, state));
        element.addEventListener("keydown", (event) => onPopupKeyDown(event, state));
        document.body.appendChild(element);
        popupByElement.set(element, state);
        popups.push(state);
        applyAppearance(state);
        applyPopupSize(state);
        return state;
    }

    function onPopupPointerDown(event, state) {
        if (event.button === 0) {
            closeDescendants(state);
            promotePopup(state);
        }
        const handle = event.target.closest(".anki-lookup__resize");
        if (handle && event.button === 0) {
            const corner = handle.dataset.resizeCorner;
            if (!core.isResizeCorner(corner)) {
                return;
            }
            const rect = state.element.getBoundingClientRect();
            resizeState = {
                state,
                corner,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                rect: {
                    left: rect.left,
                    top: rect.top,
                    right: rect.right,
                    bottom: rect.bottom,
                    width: rect.width,
                    height: rect.height,
                },
            };
            // Touching a grip hands the popup to the user. From here its size and
            // position are theirs: automatic placement chose where it opened, and
            // that job is done. Reusing the manual branch of positionPopup means no
            // anchor clamp can shrink what they drag, and the box cannot flip sides
            // mid-gesture.
            state.userSized = true;
            state.manualPosition = { left: rect.left, top: rect.top };
            handle.setPointerCapture(event.pointerId);
            state.element.classList.add("anki-lookup--resizing");
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const header = event.target.closest(".anki-lookup__header");
        const headerControl = event.target.closest(".anki-lookup__header-control");
        if (header && !headerControl && state.pinned && event.button === 0) {
            const rect = state.element.getBoundingClientRect();
            dragState = {
                state,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                left: rect.left,
                top: rect.top,
            };
            header.setPointerCapture(event.pointerId);
            state.element.classList.add("anki-lookup--dragging");
            event.preventDefault();
            event.stopPropagation();
        }
    }

    function resizePopup(event) {
        if (!resizeState || event.pointerId !== resizeState.pointerId) {
            return;
        }
        const { state, corner, rect } = resizeState;
        const requested = core.resizeDelta(
            corner,
            rect,
            event.clientX - resizeState.startX,
            event.clientY - resizeState.startY,
        );
        state.size = core.clampPopupSize(
            requested.width,
            requested.height,
            window.innerWidth,
            window.innerHeight,
            12,
        );
        const geometry = core.resizeGeometry(corner, rect, state.size);
        state.manualPosition = { left: geometry.left, top: geometry.top };
        applyPopupSize(state);
        positionPopup(state, state.anchorRect);
    }

    function finishResize(event) {
        if (!resizeState || event.pointerId !== resizeState.pointerId) {
            return;
        }
        const { state } = resizeState;
        resizeState = null;
        state.element.classList.remove("anki-lookup--resizing");
        if (!state.pinned) {
            // Free positioning was for the gesture. Drop it so the next scan anchors
            // the popup to the new word again — still at the size the user chose,
            // because userSized stays set.
            state.manualPosition = null;
        }
        saveRootPopupSize(state);
    }

    function dragPopup(event) {
        if (!dragState || event.pointerId !== dragState.pointerId) {
            return;
        }
        const { state } = dragState;
        const position = core.clampDraggedPopupPosition(
            dragState.left + event.clientX - dragState.startX,
            dragState.top + event.clientY - dragState.startY,
            state.renderedSize || state.size,
            window.innerWidth,
            window.innerHeight,
            12,
            sourceRailSide(state),
            sourceRailWidth,
            sourceRailGap,
        );
        state.manualPosition = position;
        state.element.style.left = `${position.left}px`;
        state.element.style.top = `${position.top}px`;
    }

    function finishDrag(event) {
        if (!dragState || event.pointerId !== dragState.pointerId) {
            return;
        }
        const { state } = dragState;
        dragState = null;
        state.element.classList.remove("anki-lookup--dragging");
    }

    function onPopupClick(event, state) {
        const action = event.target.closest("button[data-popup-action]");
        if (action) {
            if (action.dataset.popupAction === "pin") {
                setPinned(state, !state.pinned);
            } else if (action.dataset.popupAction === "close") {
                closePopup(state);
            }
            return;
        }
        const kanji = event.target.closest("[data-kanji]");
        if (kanji) {
            openKanjiLookup(state, kanji.dataset.kanji, kanji.getBoundingClientRect());
            return;
        }
        const tab = event.target.closest("button[data-tab]");
        if (tab) {
            activateTab(state, tab.dataset.tab);
            return;
        }
        const translationAction = event.target.closest("button[data-translation-action]");
        if (translationAction) {
            onTranslationAction(state, translationAction.dataset.translationAction);
            return;
        }
        const addNote = event.target.closest("button[data-add-note]");
        if (addNote && addNote.__ankiLookupEntry) {
            requestAddNote(state, addNote.__ankiLookupEntry);
            return;
        }
        const noteAction = event.target.closest("button[data-note-action]");
        if (noteAction) {
            onNoteAction(state, noteAction.dataset.noteAction);
            return;
        }
    }

    function onTranslationAction(state, action) {
        if (action === "cancel") {
            cancelTranslation(state);
        } else if (action === "retry") {
            requestTranslation(state, state.translationSentence, { force: true });
        } else if (action === "copy") {
            copyTranslation(state);
        } else if (action === "open_external") {
            openExternalTranslation(state);
        }
    }

    function copyTranslation(state) {
        const text = state.translation && state.translation.text;
        if (!text) {
            return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).catch(() => {});
        }
    }

    function setPinned(state, value) {
        state.pinned = value;
        if (value) {
            const rect = state.element.getBoundingClientRect();
            state.manualPosition = { left: rect.left, top: rect.top };
            setPopupPlacement(state, "manual");
        } else {
            state.manualPosition = null;
            positionPopup(state, state.anchorRect);
        }
        state.element.setAttribute(
            "aria-label",
            value ? "Pinned Anki Lookup result" : "Anki Lookup result",
        );
        state.element.classList.toggle("anki-lookup--pinned", value);
        updatePinControl(state);
    }

    function updatePinControl(state) {
        const pin = state.element.querySelector(".anki-lookup__pin");
        const action = state.pinned ? "Unpin" : "Pin";
        pin.setAttribute("aria-label", `${action} popup`);
        pin.setAttribute("aria-pressed", String(state.pinned));
        pin.title = `${action} popup (${pinShortcut})`;
    }

    function containingText(node) {
        const element = node.parentElement;
        if (!element) {
            return { text: node.nodeValue || "", offset: 0 };
        }
        const container =
            element.closest("p, li, td, th, blockquote, .card, .anki-lookup__panel") ||
            element;
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        const parts = [];
        let offset = null;
        let textLength = 0;
        let current = walker.nextNode();
        while (current) {
            const parent = current.parentElement;
            const excluded = Boolean(
                parent &&
                    parent.closest(
                        "script, style, template, noscript, [hidden], " +
                            "[aria-hidden='true'], .anki-lookup-popup",
                    ),
            );
            if (!excluded) {
                if (current === node) {
                    offset = textLength;
                }
                const value = current.nodeValue || "";
                parts.push(value);
                textLength += value.length;
            }
            current = walker.nextNode();
        }
        if (offset === null) {
            return { text: node.nodeValue || "", offset: 0 };
        }
        return { text: parts.join(""), offset };
    }

    function isEditable(target) {
        return Boolean(
            target &&
                target.closest &&
                target.closest("input, textarea, select, [contenteditable='true']"),
        );
    }

    function isScannablePopupContent(target) {
        const popupElement = popupElementFor(target);
        if (!popupElement) {
            return true;
        }
        return Boolean(
            target.closest(
                ".anki-lookup__headword, .anki-lookup__definitions, .anki-lookup__sentence",
            ),
        );
    }

    function popupElementFor(target) {
        return target && target.closest
            ? target.closest(".anki-lookup-popup")
            : null;
    }

    function modifierPressed(event) {
        const keyMap = {
            Shift: event.shiftKey,
            Control: event.ctrlKey,
            Alt: event.altKey,
            Meta: event.metaKey,
        };
        return Boolean(keyMap[modifier]);
    }

    function caretFromPoint(x, y) {
        if (document.caretPositionFromPoint) {
            const position = document.caretPositionFromPoint(x, y);
            if (position) {
                const resolved = resolveTextPosition(
                    position.offsetNode,
                    position.offset,
                );
                if (resolved) {
                    return resolved;
                }
            }
        }
        if (document.caretRangeFromPoint) {
            const range = document.caretRangeFromPoint(x, y);
            if (range) {
                return resolveTextPosition(range.startContainer, range.startOffset);
            }
        }
        return null;
    }

    function resolveTextPosition(node, offset) {
        if (!node) {
            return null;
        }
        if (node.nodeType === Node.TEXT_NODE) {
            return {
                node,
                offset: Math.max(0, Math.min(offset, (node.nodeValue || "").length)),
            };
        }
        if (node.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }
        const children = node.childNodes;
        const start = Math.min(offset, Math.max(0, children.length - 1));
        for (let distance = 0; distance < children.length; distance += 1) {
            for (const index of [start + distance, start - distance]) {
                if (index < 0 || index >= children.length) {
                    continue;
                }
                const walker = document.createTreeWalker(
                    children[index],
                    NodeFilter.SHOW_TEXT,
                );
                const text = walker.nextNode();
                if (text && (text.nodeValue || "").trim()) {
                    return { node: text, offset: 0 };
                }
            }
        }
        return null;
    }

    function wordAtPoint(x, y, target) {
        if (!isScannablePopupContent(target)) {
            return null;
        }
        const caret = caretFromPoint(x, y);
        if (!caret || caret.node.nodeType !== Node.TEXT_NODE) {
            return null;
        }
        if (caret.node.parentElement && isEditable(caret.node.parentElement)) {
            return null;
        }
        const segment = core.segmentAt(
            caret.node.nodeValue || "",
            caret.offset,
            document.documentElement.lang,
        );
        if (!segment) {
            return null;
        }
        const range = document.createRange();
        range.setStart(caret.node, segment.start);
        range.setEnd(caret.node, segment.end);
        const rect = range.getBoundingClientRect();
        if (
            rect.width <= 0 ||
            rect.height <= 0 ||
            x < rect.left - 2 ||
            x > rect.right + 2 ||
            y < rect.top - 2 ||
            y > rect.bottom + 2
        ) {
            return null;
        }
        const context = containingText(caret.node);
        const contextStart = context.offset + segment.start;
        const candidates = core.lookupCandidates(
            context.text,
            contextStart,
            segment.term,
            Math.min(maximumTermLength, 80),
            document.documentElement.lang,
        );
        return {
            term: core.normalizeTerm(segment.term, maximumTermLength),
            rect,
            range,
            candidates,
            rangeNode: caret.node,
            rangeStart: segment.start,
            source: popupByElement.get(popupElementFor(target)) || null,
            sentenceContext: core.sentenceContextAt(
                context.text,
                contextStart,
                document.documentElement.lang,
                segment.term,
            ),
        };
    }

    function selectedText() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
            return null;
        }
        const range = selection.getRangeAt(0);
        const term = core.normalizeTerm(selection.toString(), maximumTermLength);
        if (!term) {
            return null;
        }
        const container =
            range.commonAncestorContainer.nodeType === Node.TEXT_NODE
                ? range.commonAncestorContainer.parentElement
                : range.commonAncestorContainer;
        const block =
            container && container.closest
                ? container.closest("p, li, td, th, blockquote, .card")
                : null;
        const context = block ? block.textContent || "" : selection.toString();
        let offset = 0;
        if (block) {
            const prefix = document.createRange();
            prefix.selectNodeContents(block);
            prefix.setEnd(range.startContainer, range.startOffset);
            offset = prefix.toString().length;
        }
        return {
            term,
            rect: range.getBoundingClientRect(),
            source: null,
            sentenceContext: core.sentenceContextAt(
                context,
                offset,
                document.documentElement.lang,
                term,
            ),
        };
    }

    function scheduleLookup(event) {
        if (
            !modifierHeld ||
            !modifierPressed(event) ||
            resizeState ||
            isEditable(event.target)
        ) {
            return;
        }
        latestPointer = {
            x: event.clientX,
            y: event.clientY,
            target: event.target,
        };
        if (!framePending) {
            framePending = true;
            requestAnimationFrame(processPointer);
        }
    }

    function processPointer() {
        framePending = false;
        if (!latestPointer || !modifierHeld) {
            return;
        }
        const candidate = wordAtPoint(
            latestPointer.x,
            latestPointer.y,
            latestPointer.target,
        );
        if (!candidate || !candidate.term) {
            return;
        }
        if (
            candidate.source &&
            !core.canOpenNestedPopup(
                candidate.source.depth,
                allowNestedPopups,
                maximumPopupDepth,
            )
        ) {
            return;
        }
        const targetState = targetPopupFor(candidate.source);
        const lookupKey = candidate.candidates.length
            ? candidate.candidates.join("\u0000")
            : candidate.term;
        if (lookupKey === targetState.lastTerm) {
            return;
        }
        setScanHighlight(candidate.range);
        const now = performance.now();
        const delay = core.lookupDelay(now, lastLookupStartedAt, debounceMs);
        window.clearTimeout(pendingLookupTimer);
        pendingLookupTimer = window.setTimeout(() => {
            lastLookupStartedAt = performance.now();
            requestLookup(
                targetState,
                candidate.term,
                candidate.rect,
                candidate.sentenceContext,
                candidate.candidates,
                candidate.rangeNode,
                candidate.rangeStart,
            );
        }, delay);
    }

    function targetPopupFor(source) {
        if (!source) {
            const root = popups.find((state) => state.depth === 0 && !state.pinned);
            if (root) {
                closeDescendants(root);
                return root;
            }
            return createPopup(0, null);
        }
        const existing = popups.find((state) => state.parent === source);
        if (existing) {
            closeDescendants(existing);
            return existing;
        }
        closeDescendants(source);
        return createPopup(source.depth + 1, source);
    }

    function requestLookup(
        state,
        term,
        rect,
        sentenceContext,
        candidates = [],
        rangeNode = null,
        rangeStart = 0,
    ) {
        const context = sentenceContext || { text: "", offset: 0, term: "" };
        const sentence = context.text || "";
        // Belongs to this scan, not to the cached dictionary result: the same word
        // in a different sentence must not inherit the cloze of the one before it.
        state.sentenceContext = context;

        const cacheKey = candidates.length ? candidates.join("\u0000") : term;
        state.lastTerm = cacheKey;
        const cached = lookupCache.get(cacheKey);
        if (cached) {
            showResult(state, { ...cached, sentence }, rect);
            highlightMatchedRange(rangeNode, rangeStart, cached.term);
            return;
        }
        const requestId = ++requestSequence;
        state.latestRequest = requestId;
        showPending(state, rect);
        const message = `anki_lookup:${JSON.stringify({
            action: "lookup",
            request_id: requestId,
            term,
            sentence,
            candidates,
        })}`;
        pycmd(message, (response) => {
            if (
                !response ||
                response.request_id !== state.latestRequest ||
                !state.element.isConnected
            ) {
                return;
            }
            if (response.status === "ready" || response.status === "empty") {
                const cachedResponse = {
                    status: response.status,
                    entries: response.entries || [],
                    term: response.term,
                };
                rememberLookup(cacheKey, cachedResponse);
                showResult(state, { ...cachedResponse, sentence }, rect);
                highlightMatchedRange(rangeNode, rangeStart, response.term);
            } else {
                showError(state, response.message || "Lookup failed.", rect);
            }
        });
    }

    function rememberLookup(cacheKey, response) {
        lookupCache.delete(cacheKey);
        lookupCache.set(cacheKey, response);
        if (lookupCache.size > 128) {
            lookupCache.delete(lookupCache.keys().next().value);
        }
    }

    function showPending(state, rect) {
        if (!state.hasResult) {
            state.element.querySelector(".anki-lookup__body").innerHTML = [
                '<div class="anki-lookup__loading">',
                '<span class="anki-lookup__spinner" aria-hidden="true"></span>',
                "<span>Searching dictionaries...</span>",
                "</div>",
            ].join("");
        }
        positionPopup(state, rect);
        state.element.classList.add("anki-lookup--visible");
    }

    function showResult(state, response, rect) {
        state.lastResponse = response;
        renderTabs(state, response);
        state.hasResult = true;
        positionPopup(state, rect);
        state.element.classList.add("anki-lookup--visible");
    }

    /* Note creation ----------------------------------------------------------- */

    function createAddNoteControl(entry) {
        const model = core.noteState(null, notesSettings.configured);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "anki-lookup__add-note";
        button.dataset.addNote = "";
        button.textContent = "+";
        button.setAttribute("aria-label", model.label);
        button.title = model.enabled ? "Add a note from this result" : model.message;
        button.disabled = !model.enabled;
        // The entry is carried on the element so the click handler sends exactly what
        // the user is looking at, rather than re-deriving it from a lookup that may
        // have moved on.
        button.__ankiLookupEntry = entry;
        return button;
    }

    function requestAddNote(state, entry, { allowDuplicate = false } = {}) {
        const requestId = ++requestSequence;
        state.noteRequest = requestId;
        state.noteEntry = entry;
        state.note = { status: "queued" };
        renderNoteStatus(state);

        const message = `anki_lookup:${JSON.stringify({
            action: "add_note",
            request_id: requestId,
            popup_token: state.token,
            expression: entry.expression || "",
            reading: entry.reading || "",
            definition: (entry.definitions || []).join("; "),
            // The sentence the scanner captured around the word. Without it a saved
            // card is a word with no context to recall it from.
            sentence: state.translationSentence || "",
            // Where the scanned word sits in that sentence, and the form it actually
            // took. Cloze quotes the sentence, and the sentence said 食べました even
            // though the dictionary matched the headword 食べる.
            sentence_offset: (state.sentenceContext && state.sentenceContext.offset) || 0,
            source_term: (state.sentenceContext && state.sentenceContext.term) || "",
            translation: (state.translation && state.translation.text) || "",
            selected_text: entry.expression || "",
            dictionary: entry.dictionary || "",
            allow_duplicate: allowDuplicate,
        })}`;
        pycmd(message, (response) => {
            if (
                !response ||
                !state.element.isConnected ||
                response.request_id !== state.noteRequest
            ) {
                return;
            }
            state.note = response;
            renderNoteStatus(state);
        });
    }

    function renderNoteStatus(state) {
        const model = core.noteState(state.note, notesSettings.configured);
        let banner = state.element.querySelector(".anki-lookup__note-status");

        if (!model.message) {
            if (banner) {
                banner.remove();
            }
            return;
        }

        if (!banner) {
            banner = document.createElement("div");
            banner.className = "anki-lookup__note-status";
            const body = state.element.querySelector(".anki-lookup__body");
            state.element.insertBefore(banner, body);
        }

        banner.replaceChildren();
        banner.classList.toggle("anki-lookup__note-status--error", model.state === "error");

        const text = document.createElement("span");
        text.textContent = model.message;
        banner.appendChild(text);

        for (const action of model.actions) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "anki-lookup__note-action";
            button.dataset.noteAction = action;
            button.textContent = action === "open_note" ? "Open note" : "Add anyway";
            banner.appendChild(button);
        }
    }

    function onNoteAction(state, action) {
        if (action === "open_note") {
            const noteId = state.note && state.note.note_id;
            if (noteId) {
                pycmd(
                    `anki_lookup:${JSON.stringify({ action: "open_note", note_id: noteId })}`,
                );
            }
        } else if (action === "add_anyway" && state.noteEntry) {
            requestAddNote(state, state.noteEntry, { allowDuplicate: true });
        }
    }

    function onPopupKeyDown(event, state) {
        // A kanji span is a role="button", so Enter and Space must activate it the way
        // a real button would.
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }
        const kanji = event.target.closest("[data-kanji]");
        if (kanji) {
            event.preventDefault();
            openKanjiLookup(state, kanji.dataset.kanji, kanji.getBoundingClientRect());
        }
    }

    function openKanjiLookup(state, character, rect) {
        // Reuses the nested-popup path hover-scan already uses: targetPopupFor gives a
        // child (reusing an existing one), and a plain lookup of a single kanji already
        // returns its kanji entry, so no dedicated request or Python change is needed.
        if (
            !allowKanjiClick ||
            !character ||
            !core.canOpenNestedPopup(state.depth, allowNestedPopups, maximumPopupDepth)
        ) {
            return;
        }
        const child = targetPopupFor(state);
        requestLookup(child, character, rect, null, [character]);
    }

    function appendHeadword(target, entry) {
        // Only a term's kanji become clickable spans: a kanji entry's own character is
        // not a link to itself, and kana has no entry to open. With the feature off
        // this is one plain text node — exactly the DOM the headword had before. The
        // depth limit is enforced on click, not here, to avoid threading popup state
        // through the render path for a case (max nesting) that is rarely reached.
        if (!allowKanjiClick || entry.entry_type === "kanji") {
            target.textContent = entry.expression;
            return;
        }

        for (const character of Array.from(entry.expression)) {
            if (core.isKanji(character)) {
                const span = document.createElement("span");
                span.className = "anki-lookup__kanji";
                span.dataset.kanji = character;
                span.textContent = character;
                span.setAttribute("role", "button");
                span.setAttribute("tabindex", "0");
                span.setAttribute("aria-label", `Look up the kanji ${character}`);
                span.title = `Look up ${character}`;
                target.appendChild(span);
            } else {
                target.appendChild(document.createTextNode(character));
            }
        }
    }

    function createDictionaryPanel(entries) {
        const panel = document.createElement("div");
        for (const entry of entries) {
            const entryElement = document.createElement("article");
            entryElement.className = "anki-lookup__entry";
            const heading = document.createElement("div");
            heading.className = "anki-lookup__entry-heading";
            const headingText = document.createElement("div");
            headingText.className = "anki-lookup__headword";
            const expression = document.createElement("strong");
            appendHeadword(expression, entry);
            headingText.appendChild(expression);
            if (entry.reading && entry.reading !== entry.expression) {
                const reading = document.createElement("span");
                reading.className = "anki-lookup__reading";
                reading.textContent = entry.reading;
                headingText.appendChild(reading);
            }
            heading.appendChild(headingText);
            const type = document.createElement("span");
            type.className = "anki-lookup__entry-type";
            type.textContent =
                entry.entry_type === "kanji"
                    ? "Kanji"
                    : entry.match_type === "definition"
                      ? "Reverse"
                      : "Term";
            heading.appendChild(type);
            const addControl = createAddNoteControl(entry);
            if (addControl) {
                heading.appendChild(addControl);
            }
            entryElement.appendChild(heading);
            const lexicalMetadata = createLexicalMetadata(entry);
            if (lexicalMetadata) {
                entryElement.appendChild(lexicalMetadata);
            }
            const tags = [...(entry.term_tags || []), ...(entry.definition_tags || [])];
            if (tags.length) {
                const tagList = document.createElement("div");
                tagList.className = "anki-lookup__tags";
                for (const tag of tags) {
                    const tagElement = document.createElement("span");
                    tagElement.textContent = tag;
                    tagList.appendChild(tagElement);
                }
                entryElement.appendChild(tagList);
            }
            if (entry.inflection_reasons && entry.inflection_reasons.length) {
                const inflection = document.createElement("div");
                inflection.className = "anki-lookup__inflection";
                inflection.setAttribute(
                    "aria-label",
                    `Conjugation breakdown: ${entry.inflection_reasons.join(", ")}`
                );
                const icon = document.createElement("span");
                icon.className = "anki-lookup__inflection-icon";
                icon.setAttribute("aria-hidden", "true");
                inflection.appendChild(icon);
                entry.inflection_reasons.forEach((reason, index) => {
                    if (index > 0) {
                        const separator = document.createElement("span");
                        separator.className = "anki-lookup__inflection-separator";
                        separator.textContent = "←";
                        separator.setAttribute("aria-hidden", "true");
                        inflection.appendChild(separator);
                    }
                    const step = document.createElement("span");
                    step.className = "anki-lookup__inflection-step";
                    step.textContent = reason;
                    inflection.appendChild(step);
                });
                entryElement.appendChild(inflection);
            }
            const list = document.createElement("ol");
            list.className = "anki-lookup__definitions";
            for (const definition of entry.definitions || []) {
                const item = document.createElement("li");
                item.textContent = definition;
                list.appendChild(item);
            }
            entryElement.appendChild(list);
            if (entry.metadata && Object.keys(entry.metadata).length) {
                const metadata = document.createElement("dl");
                metadata.className = "anki-lookup__metadata";
                for (const [name, value] of Object.entries(entry.metadata)) {
                    const key = document.createElement("dt");
                    key.textContent = name;
                    const detail = document.createElement("dd");
                    detail.textContent = value;
                    metadata.append(key, detail);
                }
                entryElement.appendChild(metadata);
            }
            panel.appendChild(entryElement);
        }
        return panel;
    }

    function createLexicalMetadata(entry) {
        const pronunciations = [
            ...(entry.pitch_accents || []).map((item) =>
                createPitchAccentItem(item, entry),
            ),
            ...(entry.ipa || []).map(createIpaItem),
        ];
        const frequencies = (entry.frequencies || []).map(createFrequencyItem);
        if (!pronunciations.length && !frequencies.length) {
            return null;
        }

        const container = document.createElement("div");
        container.className = "anki-lookup__lexical-metadata";
        if (pronunciations.length) {
            container.appendChild(
                createLexicalMetadataRow("Pronunciation", pronunciations),
            );
        }
        if (frequencies.length) {
            container.appendChild(
                createLexicalMetadataRow("Frequency", frequencies),
            );
        }
        return container;
    }

    function createLexicalMetadataRow(label, items) {
        const row = document.createElement("div");
        row.className = "anki-lookup__lexical-row";
        row.setAttribute("aria-label", label);
        for (const item of items) {
            row.appendChild(item);
        }
        return row;
    }

    function createPitchAccentItem(item, entry) {
        const element = createLexicalMetadataItem(
            item.dictionary,
            "anki-lookup__lexical-item--pitch",
        );
        const reading = item.reading || entry.reading || entry.expression;
        const morae = core.japaneseMorae(reading);
        const levels = core.pitchLevels(morae.length, item.position);
        const nasal = new Set(item.nasal_positions || []);
        const devoice = new Set(item.devoice_positions || []);
        const contour = document.createElement("span");
        contour.className = "anki-lookup__pitch";
        contour.lang = "ja";
        morae.forEach((mora, index) => {
            const moraElement = document.createElement("span");
            moraElement.className = "anki-lookup__pitch-mora";
            moraElement.dataset.pitch = levels[index] ? "high" : "low";
            if (levels[index] && !levels[index + 1]) {
                moraElement.dataset.downstep = "true";
            }
            if (nasal.has(index + 1)) {
                moraElement.dataset.nasal = "true";
            }
            if (devoice.has(index + 1)) {
                moraElement.dataset.devoice = "true";
            }
            moraElement.textContent = mora;
            contour.appendChild(moraElement);
        });
        const position = document.createElement("span");
        position.className = "anki-lookup__pitch-position";
        position.textContent = `[${item.position}]`;
        element.append(contour, position);
        element.title = [
            `${item.dictionary}: ${reading}, pitch ${item.position}`,
            ...(item.tags || []),
        ].join(" · ");
        return element;
    }

    function createIpaItem(item) {
        const element = createLexicalMetadataItem(
            item.dictionary,
            "anki-lookup__lexical-item--ipa",
        );
        const transcription = document.createElement("span");
        transcription.className = "anki-lookup__ipa";
        transcription.textContent = `/${item.transcription}/`;
        element.appendChild(transcription);
        element.title = [
            `${item.dictionary}: IPA ${item.transcription}`,
            ...(item.tags || []),
        ].join(" · ");
        return element;
    }

    function createFrequencyItem(item) {
        const element = createLexicalMetadataItem(
            item.dictionary,
            "anki-lookup__lexical-item--frequency",
        );
        const value = document.createElement("span");
        value.className = "anki-lookup__frequency-value";
        value.textContent = item.display_value;
        element.appendChild(value);
        const mode =
            item.frequency_mode === "rank-based"
                ? "rank; lower is more common"
                : item.frequency_mode === "occurrence-based"
                  ? "occurrence; higher is more common"
                  : "frequency";
        element.title = `${item.dictionary}: ${item.display_value} (${mode})`;
        return element;
    }

    function createLexicalMetadataItem(dictionary, className) {
        const element = document.createElement("span");
        element.className = `anki-lookup__lexical-item ${className}`;
        const source = document.createElement("span");
        source.className = "anki-lookup__lexical-source";
        source.textContent = dictionary;
        element.appendChild(source);
        return element;
    }

    function createContinuousDictionaryPanel(entries) {
        const panel = document.createElement("div");
        panel.className = "anki-lookup__continuous";
        const groups = new Map();
        for (const entry of entries) {
            if (!groups.has(entry.dictionary)) {
                groups.set(entry.dictionary, []);
            }
            groups.get(entry.dictionary).push(entry);
        }
        for (const [dictionary, dictionaryEntries] of groups) {
            const section = document.createElement("section");
            section.className = "anki-lookup__dictionary-section";
            const heading = document.createElement("h2");
            heading.className = "anki-lookup__dictionary-heading";
            heading.textContent = dictionary;
            section.append(heading, createDictionaryPanel(dictionaryEntries));
            panel.appendChild(section);
        }
        if (!groups.size) {
            const empty = document.createElement("div");
            empty.className = "anki-lookup__status";
            empty.textContent =
                "No dictionary result. Try the captured sentence in a translation tab.";
            panel.appendChild(empty);
        }
        return panel;
    }

    function createTranslationPanel(state, sentence) {
        const panel = document.createElement("div");
        panel.className = "anki-lookup__provider";

        const heading = document.createElement("h2");
        heading.textContent = `${core.providerLabel(translationSettings.provider)} translation`;

        const contextLabel = document.createElement("div");
        contextLabel.className = "anki-lookup__section-label";
        contextLabel.textContent = "Captured sentence";

        const context = document.createElement("p");
        context.className = "anki-lookup__sentence";
        context.textContent = sentence || "No surrounding sentence was detected.";

        const body = document.createElement("div");
        body.className = "anki-lookup__translation-body";

        panel.append(heading, contextLabel, context, body);
        renderTranslationState(state, body);
        return panel;
    }

    function renderTranslationState(state, body) {
        const model = core.translationState(state.translation);
        body.replaceChildren();

        if (model.state === "idle") {
            return;
        }

        if (model.state === "pending") {
            const loading = document.createElement("div");
            loading.className = "anki-lookup__loading";
            const spinner = document.createElement("span");
            spinner.className = "anki-lookup__spinner";
            spinner.setAttribute("aria-hidden", "true");
            const label = document.createElement("span");
            label.textContent = model.message;
            loading.append(spinner, label);
            body.appendChild(loading);
        } else if (model.state === "ready") {
            const label = document.createElement("div");
            label.className = "anki-lookup__section-label";
            label.textContent = `Translation into ${translationSettings.target_language_label}`;
            const text = document.createElement("p");
            text.className = "anki-lookup__translation-text";
            text.textContent = model.text;
            body.append(label, text);

            const attribution = document.createElement("p");
            attribution.className = "anki-lookup__attribution";
            attribution.textContent = model.cached
                ? `via ${core.providerLabel(state.translation.provider)} (cached)`
                : `via ${core.providerLabel(state.translation.provider)}`;
            body.appendChild(attribution);
        } else {
            const status = document.createElement("p");
            status.className = "anki-lookup__status";
            status.textContent = model.message;
            body.appendChild(status);
        }

        const actions = createTranslationActions(model.actions);
        if (actions) {
            body.appendChild(actions);
        }
    }

    const TRANSLATION_ACTION_LABELS = {
        cancel: "Cancel",
        copy: "Copy",
        retry: "Retry",
        open_external: "Open in browser",
    };

    function createTranslationActions(names) {
        if (!names || !names.length) {
            return null;
        }
        const row = document.createElement("div");
        row.className = "anki-lookup__translation-actions";
        for (const name of names) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "anki-lookup__translation-action";
            button.dataset.translationAction = name;
            button.textContent =
                name === "open_external"
                    ? `Open in ${core.providerLabel(translationSettings.provider)}`
                    : TRANSLATION_ACTION_LABELS[name];
            row.appendChild(button);
        }
        return row;
    }

    function requestTranslation(state, sentence, { force = false } = {}) {
        if (!sentence) {
            return;
        }
        const requestId = ++requestSequence;
        state.translationRequest = requestId;
        state.translationSentence = sentence;
        state.translation = { status: "pending", provider: translationSettings.provider };
        refreshTranslationPanel(state);

        const message = `anki_lookup:${JSON.stringify({
            action: "translate",
            request_id: requestId,
            popup_token: state.token,
            text: sentence,
        })}`;
        pycmd(message, (response) => {
            // Guard one: the popup went away. Guard two: a newer request replaced
            // this one. A pending answer is only a promise; the real result arrives
            // through AnkiLookupPushResult later.
            if (
                !response ||
                !state.element.isConnected ||
                response.request_id !== state.translationRequest
            ) {
                return;
            }
            state.translation = response;
            refreshTranslationPanel(state);
        });
        if (force) {
            state.translationRequested = true;
        }
    }

    function cancelTranslation(state) {
        if (!state.translationRequest) {
            return;
        }
        pycmd(
            `anki_lookup:${JSON.stringify({
                action: "translate_cancel",
                request_id: state.translationRequest,
                popup_token: state.token,
            })}`,
        );
        state.translationRequest = 0;
        state.translation = {
            status: "error",
            message: "Translation cancelled.",
            provider: translationSettings.provider,
        };
        refreshTranslationPanel(state);
    }

    function openExternalTranslation(state) {
        if (!state.translationSentence) {
            return;
        }
        pycmd(
            `anki_lookup:${JSON.stringify({
                action: "open_external",
                request_id: ++requestSequence,
                popup_token: state.token,
                text: state.translationSentence,
            })}`,
        );
    }

    function refreshTranslationPanel(state) {
        const body = state.element.querySelector(".anki-lookup__translation-body");
        if (body) {
            renderTranslationState(state, body);
        }
    }

    /* The channel Python pushes late results down. A translation waits on a browser
       and a note add runs as a background collection operation, so neither can be
       answered from the pycmd handler that started it. */
    window.AnkiLookupPushResult = (payload) => {
        if (!payload) {
            return;
        }
        const state = popups.find((candidate) => candidate.token === payload.popup_token);
        if (!state || !state.element.isConnected) {
            return;
        }
        if (core.isCurrentTranslation(payload, state.token, state.translationRequest)) {
            state.translation = payload;
            refreshTranslationPanel(state);
            return;
        }
        if (core.isCurrentNote(payload, state.token, state.noteRequest)) {
            state.note = payload;
            renderNoteStatus(state);
        }
    };

    function renderTabs(state, response) {
        const body = state.element.querySelector(".anki-lookup__body");
        for (const child of state.element.children) {
            if (child.classList.contains("anki-lookup__tabs")) {
                child.remove();
                break;
            }
        }
        body.replaceChildren();
        const tabs = document.createElement("div");
        tabs.className = "anki-lookup__tabs";
        tabs.setAttribute("role", "tablist");
        tabs.setAttribute("aria-label", "Lookup sources");
        const tabsLabel = document.createElement("div");
        tabsLabel.className = "anki-lookup__tabs-label";
        tabsLabel.textContent = "Sources";
        // Decorative: a tablist may only contain tabs, and the list already carries
        // aria-label="Lookup sources". Without this a screen reader announces a
        // stray "Sources" item among the tabs.
        tabsLabel.setAttribute("aria-hidden", "true");
        tabs.appendChild(tabsLabel);
        tabs.addEventListener("keydown", (event) => onTabsKeyDown(event, state));
        const panels = document.createElement("div");
        panels.className = "anki-lookup__panels";
        let index = 0;
        function addTab(label, panel) {
            const id = `anki-lookup-tab-${state.depth}-${requestSequence}-${index++}`;
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.tab = id;
            button.setAttribute("role", "tab");
            button.setAttribute("aria-controls", id);
            button.textContent = label;
            button.title = label;
            panel.id = id;
            panel.classList.add("anki-lookup__panel");
            panel.setAttribute("role", "tabpanel");
            panel.setAttribute("tabindex", "0");
            tabs.appendChild(button);
            panels.appendChild(panel);
            return id;
        }
        if (appearance.dictionary_layout === "continuous") {
            addTab(
                "Results",
                createContinuousDictionaryPanel(response.entries || []),
            );
        } else {
            const groups = new Map();
            for (const entry of response.entries || []) {
                if (!groups.has(entry.dictionary)) {
                    groups.set(entry.dictionary, []);
                }
                groups.get(entry.dictionary).push(entry);
            }
            for (const [dictionary, entries] of groups) {
                addTab(dictionary, createDictionaryPanel(entries));
            }
            if (!groups.size) {
                const empty = document.createElement("div");
                empty.className = "anki-lookup__status";
                empty.textContent =
                    "No dictionary result. Try the captured sentence in a translation tab.";
                addTab("Dictionary", empty);
            }
        }
        // One tab, for the configured provider. The old build showed both Google and
        // DeepL unconditionally, but only one of them is ever the one that would run:
        // the provider is a setting, not a per-lookup choice.
        const translationTab = addTab(
            core.providerLabel(translationSettings.provider),
            createTranslationPanel(state, response.sentence),
        );
        state.translationTabId = translationTab;
        state.translationRequested = false;
        state.translationSentence = response.sentence || "";
        state.translation = null;
        // A new lookup is a new subject. Carrying "Note added." across to a different
        // word would claim something untrue about it.
        state.note = null;
        state.noteEntry = null;
        state.noteRequest = 0;

        state.element.insertBefore(tabs, body);
        body.appendChild(panels);
        activateTab(state, tabs.querySelector("button").dataset.tab);
    }

    function activateTab(state, id) {
        if (!id) {
            return;
        }
        state.activeTabId = id;
        for (const tab of state.element.querySelectorAll("button[data-tab]")) {
            const active = tab.dataset.tab === id;
            tab.classList.toggle("anki-lookup__tab--active", active);
            tab.setAttribute("aria-selected", String(active));
            // Roving tabindex: one stop for the whole rail, then arrow keys within it.
            // Leaving every tab focusable would make Tab walk through all of them.
            tab.tabIndex = active ? 0 : -1;
        }
        for (const panel of state.element.querySelectorAll(".anki-lookup__panel")) {
            panel.hidden = panel.id !== id;
        }

        // Translate only when the user actually opens the tab, and only once. Every
        // hold-to-scan pointer move re-renders these tabs; translating on render
        // would queue a job per mouse move against a serial extension.
        if (id !== state.translationTabId) {
            return;
        }
        const shouldRequest = core.shouldRequestTranslation({
            sentence: state.translationSentence,
            requested: state.translationRequested,
        });
        if (shouldRequest) {
            state.translationRequested = true;
            requestTranslation(state, state.translationSentence);
        }
    }

    function onTabsKeyDown(event, state) {
        if (!core.isTabNavigationKey(event.key)) {
            return;
        }
        const tabs = [...state.element.querySelectorAll("button[data-tab]")];
        if (tabs.length < 2) {
            return;
        }
        const current = tabs.findIndex((tab) => tab.dataset.tab === state.activeTabId);
        const next = core.nextTabIndex(current, tabs.length, event.key);
        if (next === current) {
            return;
        }
        event.preventDefault();
        activateTab(state, tabs[next].dataset.tab);
        tabs[next].focus();
    }

    function showError(state, message, rect) {
        const tabs = state.element.querySelector(".anki-lookup__tabs");
        if (tabs) {
            tabs.remove();
        }
        state.element.querySelector(".anki-lookup__body").innerHTML = "";
        const error = document.createElement("div");
        error.className = "anki-lookup__status anki-lookup__status--error";
        error.textContent = message;
        state.element.querySelector(".anki-lookup__body").appendChild(error);
        positionPopup(state, rect);
        state.element.classList.add("anki-lookup--visible");
    }

    function positionPopup(state, rect) {
        const margin = 12;
        state.anchorRect = rect || state.anchorRect;
        state.size = core.clampPopupSize(
            state.size.width,
            state.size.height,
            window.innerWidth,
            window.innerHeight,
            margin,
        );
        // Pinned popups have always taken this path. A popup the user has resized now
        // takes it too: both mean "the user decided where and how big this is", and
        // this branch is the one that applies their size verbatim instead of clamping
        // it to whatever room is left beside the scanned word.
        if ((state.pinned || state.userSized) && state.manualPosition) {
            const renderedSize = { ...state.size };
            state.renderedSize = renderedSize;
            applyPopupSize(state, renderedSize);
            setPopupPlacement(state, "manual");
            const manualPosition = core.clampDraggedPopupPosition(
                state.manualPosition.left,
                state.manualPosition.top,
                renderedSize,
                window.innerWidth,
                window.innerHeight,
                margin,
                sourceRailSide(state),
                sourceRailWidth,
                sourceRailGap,
            );
            state.manualPosition = manualPosition;
            state.element.style.left = `${manualPosition.left}px`;
            state.element.style.top = `${manualPosition.top}px`;
            return;
        }
        const position = state.parent
            ? core.nestedPopupPosition(
                  state.parent.element.getBoundingClientRect(),
                  state.anchorRect,
                  state.size,
                  window.innerWidth,
                  window.innerHeight,
                  margin,
                  10,
                  state.userSized,
              )
            : core.popupPosition(
                  state.anchorRect,
                  state.size,
                  window.innerWidth,
                  window.innerHeight,
                  margin,
                  10,
                  state.userSized,
              );
        const renderedSize = {
            width: state.size.width,
            height: position.height,
        };
        state.renderedSize = renderedSize;
        applyPopupSize(state, renderedSize);
        setPopupPlacement(state, position.placement);
        const railPlacement = state.element.querySelector(".anki-lookup__tabs")
            ? core.sourceRailPlacement(
                  position.left,
                  renderedSize.width,
                  window.innerWidth,
                  margin,
                  sourceRailWidth,
                  sourceRailGap,
                  Boolean(state.parent),
              )
            : { popupLeft: position.left, side: "none" };
        state.element.classList.toggle(
            "anki-lookup--rail-left",
            railPlacement.side === "left",
        );
        state.element.classList.toggle(
            "anki-lookup--rail-right",
            railPlacement.side === "right",
        );
        state.element.classList.toggle(
            "anki-lookup--rail-inside",
            railPlacement.side === "inside",
        );
        state.element.style.left = `${railPlacement.popupLeft}px`;
        state.element.style.top = `${position.top}px`;
    }

    function setPopupPlacement(state, placement) {
        state.placement = placement;
        state.element.classList.toggle(
            "anki-lookup--above",
            placement === "above",
        );
    }

    function sourceRailSide(state) {
        if (state.element.classList.contains("anki-lookup--rail-left")) {
            return "left";
        }
        if (state.element.classList.contains("anki-lookup--rail-right")) {
            return "right";
        }
        return "inside";
    }

    function applyPopupSize(state, size = state.size) {
        state.element.style.width = `${size.width}px`;
        state.element.style.height = `${size.height}px`;
    }

    function applyAppearance(state) {
        state.element.dataset.theme = appearance.theme || "system";
        state.element.style.setProperty(
            "--anki-lookup-font-family",
            appearance.font_family || "inherit",
        );
        state.element.style.setProperty(
            "--anki-lookup-font-size",
            `${appearance.font_size_px || 14}px`,
        );
        updatePinControl(state);
    }

    window.AnkiLookupApplyConfig = (nextConfig) => {
        if (!nextConfig || typeof nextConfig !== "object") {
            return;
        }
        appearance = nextConfig.appearance || {};
        pinShortcut = (nextConfig.lookup || {}).pin_shortcut || "Ctrl+Shift+K";
        translationSettings = normalizeTranslationSettings(nextConfig.translation);
        notesSettings = normalizeNotesSettings(nextConfig.notes);
        for (const state of popups) {
            applyAppearance(state);
            if (state.lastResponse) {
                renderTabs(state, state.lastResponse);
                positionPopup(state, state.anchorRect);
            }
        }
    };

    function setScanHighlight(range) {
        if (!window.CSS || !CSS.highlights || typeof Highlight !== "function") {
            return;
        }
        CSS.highlights.delete("anki-lookup-scan");
        if (range) {
            CSS.highlights.set(
                "anki-lookup-scan",
                new Highlight(range.cloneRange()),
            );
        }
    }

    function clearScanHighlight() {
        if (window.CSS && CSS.highlights) {
            CSS.highlights.delete("anki-lookup-scan");
        }
    }

    function highlightMatchedRange(node, start, term) {
        if (!node || !term) {
            return;
        }
        const end = start + term.length;
        if (end > (node.nodeValue || "").length) {
            return;
        }
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, end);
        setScanHighlight(range);
    }

    function closeDescendants(state) {
        for (const popupState of [...popups].reverse()) {
            if (core.isPopupDescendant(popupState, state)) {
                removePopup(popupState);
            }
        }
    }

    function promotePopup(state) {
        const index = popups.indexOf(state);
        if (index < 0 || index === popups.length - 1) {
            return;
        }
        popups.splice(index, 1);
        popups.push(state);
        document.body.appendChild(state.element);
    }

    function closePopup(state) {
        closeDescendants(state);
        removePopup(state);
        if (!popups.length) {
            clearScanHighlight();
        }
    }

    function removePopup(state) {
        const index = popups.indexOf(state);
        if (index >= 0) {
            popups.splice(index, 1);
        }
        state.element.remove();
    }

    function closeUnpinnedPopups() {
        const protectedAncestors = new Set();
        for (const state of popups) {
            if (!state.pinned) {
                continue;
            }
            let ancestor = state.parent;
            while (ancestor) {
                protectedAncestors.add(ancestor);
                ancestor = ancestor.parent;
            }
        }
        for (const state of [...popups].reverse()) {
            if (
                !state.pinned &&
                !protectedAncestors.has(state) &&
                state.element.isConnected
            ) {
                closePopup(state);
            }
        }
    }

    document.addEventListener(
        "keydown",
        (event) => {
            if (event.key === modifier && !isEditable(event.target)) {
                modifierHeld = true;
            }
            if (core.matchesShortcut(event, shortcut) && !isEditable(event.target)) {
                const selection = selectedText();
                if (selection) {
                    event.preventDefault();
                    const state = targetPopupFor(null);
                    requestLookup(
                        state,
                        selection.term,
                        selection.rect,
                        selection.sentenceContext,
                    );
                }
            }
            if (
                core.matchesShortcut(event, pinShortcut) &&
                !isEditable(event.target) &&
                popups.length
            ) {
                event.preventDefault();
                const state = popups[popups.length - 1];
                setPinned(state, !state.pinned);
            }
            if (event.key === "Escape" && popups.length) {
                closePopup(popups[popups.length - 1]);
                event.stopPropagation();
            }
        },
        true,
    );

    document.addEventListener(
        "keyup",
        (event) => {
            if (event.key !== modifier) {
                return;
            }
            modifierHeld = false;
            window.clearTimeout(pendingLookupTimer);
            if (releaseBehavior === "close") {
                closeUnpinnedPopups();
            }
        },
        true,
    );
    document.addEventListener(
        "pointerdown",
        (event) => {
            if (
                event.button === 0 &&
                popups.length &&
                !popupElementFor(event.target)
            ) {
                closeUnpinnedPopups();
            }
        },
        true,
    );
    document.addEventListener("pointermove", resizePopup, true);
    document.addEventListener("pointermove", dragPopup, true);
    document.addEventListener("pointerup", finishResize, true);
    document.addEventListener("pointerup", finishDrag, true);
    document.addEventListener("pointercancel", finishResize, true);
    document.addEventListener("pointercancel", finishDrag, true);
    document.addEventListener("pointermove", scheduleLookup, true);
    window.addEventListener("resize", () => {
        for (const state of popups) {
            state.size = core.clampPopupSize(
                state.size.width,
                state.size.height,
                window.innerWidth,
                window.innerHeight,
                12,
            );
            applyPopupSize(state);
            positionPopup(state, state.anchorRect);
        }
    });
    window.addEventListener("blur", () => {
        modifierHeld = false;
        window.clearTimeout(pendingLookupTimer);
    });
})();
