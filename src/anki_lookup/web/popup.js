(function () {
    "use strict";

    const core = window.AnkiLookupScannerCore;
    const initialConfig = window.AnkiLookupConfig || {};
    const lookupConfig = initialConfig.lookup || {};
    let appearance = initialConfig.appearance || {};
    const modifier = lookupConfig.modifier || "Shift";
    const releaseBehavior = lookupConfig.release_behavior || "remain_open";
    const debounceMs = Number.isFinite(lookupConfig.debounce_ms)
        ? lookupConfig.debounce_ms
        : 20;
    const maximumTermLength = lookupConfig.maximum_term_length || 200;
    const allowNestedPopups = lookupConfig.allow_nested_popups !== false;
    const maximumPopupDepth = lookupConfig.maximum_popup_depth || 4;
    const shortcut = lookupConfig.selection_shortcut || "Ctrl+Shift+L";
    let pinShortcut = lookupConfig.pin_shortcut || "Ctrl+Shift+K";
    const sourceRailWidth = 144;
    const sourceRailGap = 8;
    const popupByElement = new WeakMap();
    const popups = [];
    const lookupCache = new Map();

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
            pinned: false,
            lastTerm: "",
            latestRequest: 0,
            hasResult: false,
            lastResponse: null,
            anchorRect: null,
            manualPosition: null,
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
            '<header class="anki-lookup__header" title="Drag after pinning">',
            '<span class="anki-lookup__pin-indicator" aria-hidden="true"></span>',
            "</header>",
            '<div class="anki-lookup__body"></div>',
            '<div class="anki-lookup__resize" role="separator" aria-label="Resize popup" title="Drag to resize"></div>',
        ].join("");
        element.addEventListener("pointerdown", (event) => onPopupPointerDown(event, state));
        element.addEventListener("click", (event) => onPopupClick(event, state));
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
            const rect = state.element.getBoundingClientRect();
            resizeState = {
                state,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                width: rect.width,
                height: rect.height,
            };
            handle.setPointerCapture(event.pointerId);
            state.element.classList.add("anki-lookup--resizing");
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const header = event.target.closest(".anki-lookup__header");
        if (header && state.pinned && event.button === 0) {
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
        const { state } = resizeState;
        state.size = core.clampPopupSize(
            resizeState.width + event.clientX - resizeState.startX,
            resizeState.height + event.clientY - resizeState.startY,
            window.innerWidth,
            window.innerHeight,
            12,
        );
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
        const tab = event.target.closest("button[data-tab]");
        if (tab) {
            activateTab(state, tab.dataset.tab);
            return;
        }
    }

    function setPinned(state, value) {
        state.pinned = value;
        if (value) {
            const rect = state.element.getBoundingClientRect();
            state.manualPosition = { left: rect.left, top: rect.top };
        } else {
            state.manualPosition = null;
            positionPopup(state, state.anchorRect);
        }
        state.element.setAttribute(
            "aria-label",
            value ? "Pinned Anki Lookup result" : "Anki Lookup result",
        );
        state.element.classList.toggle("anki-lookup--pinned", value);
        state.element.querySelector(".anki-lookup__header").title = value
            ? "Pinned. Drag to move; use the pin shortcut to unpin."
            : `Press ${pinShortcut} to pin this popup`;
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
            sentence: core.sentenceAt(
                context.text,
                contextStart,
                document.documentElement.lang,
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
            sentence: core.sentenceAt(context, offset, document.documentElement.lang),
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
                candidate.sentence,
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
        sentence,
        candidates = [],
        rangeNode = null,
        rangeStart = 0,
    ) {
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
            sentence: sentence || "",
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
            expression.textContent = entry.expression;
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
            entryElement.appendChild(heading);
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
                inflection.textContent = entry.inflection_reasons.join(" → ");
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

    function createProviderPanel(provider, sentence) {
        const panel = document.createElement("div");
        panel.className = "anki-lookup__provider";
        const heading = document.createElement("h2");
        heading.textContent = `${provider} translation`;
        const contextLabel = document.createElement("div");
        contextLabel.className = "anki-lookup__section-label";
        contextLabel.textContent = "Captured sentence";
        const context = document.createElement("p");
        context.className = "anki-lookup__sentence";
        context.textContent = sentence || "No surrounding sentence was detected.";
        const status = document.createElement("p");
        status.className = "anki-lookup__status";
        status.textContent = `${provider} integration is not enabled yet.`;
        panel.append(heading, contextLabel, context, status);
        return panel;
    }

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
        tabs.appendChild(tabsLabel);
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
        addTab("Google Translate", createProviderPanel("Google Translate", response.sentence));
        addTab("DeepL", createProviderPanel("DeepL", response.sentence));
        state.element.insertBefore(tabs, body);
        body.appendChild(panels);
        activateTab(state, tabs.querySelector("button").dataset.tab);
    }

    function activateTab(state, id) {
        if (!id) {
            return;
        }
        for (const tab of state.element.querySelectorAll("button[data-tab]")) {
            const active = tab.dataset.tab === id;
            tab.classList.toggle("anki-lookup__tab--active", active);
            tab.setAttribute("aria-selected", String(active));
        }
        for (const panel of state.element.querySelectorAll(".anki-lookup__panel")) {
            panel.hidden = panel.id !== id;
        }
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
        const availableBelow = state.anchorRect
            ? window.innerHeight - margin - state.anchorRect.bottom - 10
            : state.size.height;
        const renderedSize = {
            width: state.size.width,
            height: Math.min(state.size.height, Math.max(120, availableBelow)),
        };
        state.renderedSize = renderedSize;
        applyPopupSize(state, renderedSize);
        if (state.pinned && state.manualPosition) {
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
                  renderedSize,
                  window.innerWidth,
                  margin,
                  10,
              )
            : core.popupPosition(
                  state.anchorRect,
                  renderedSize,
                  window.innerWidth,
                  margin,
                  10,
              );
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
        state.element.querySelector(".anki-lookup__header").title = state.pinned
            ? "Pinned. Drag to move; use the pin shortcut to unpin."
            : `Press ${pinShortcut} to pin this popup`;
    }

    window.AnkiLookupApplyConfig = (nextConfig) => {
        if (!nextConfig || typeof nextConfig !== "object") {
            return;
        }
        appearance = nextConfig.appearance || {};
        pinShortcut = (nextConfig.lookup || {}).pin_shortcut || "Ctrl+Shift+K";
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
        for (const popupState of [...popups]) {
            let ancestor = popupState.parent;
            while (ancestor) {
                if (ancestor === state) {
                    removePopup(popupState);
                    break;
                }
                ancestor = ancestor.parent;
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
                    requestLookup(state, selection.term, selection.rect, selection.sentence);
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
