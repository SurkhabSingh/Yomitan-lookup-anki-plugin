(function () {
    "use strict";

    const core = window.AnkiLookupScannerCore;
    const config = window.AnkiLookupConfig || {};
    const lookupConfig = config.lookup || {};
    const appearance = config.appearance || {};
    const modifier = lookupConfig.modifier || "Shift";
    const releaseBehavior = lookupConfig.release_behavior || "remain_open";
    const debounceMs = lookupConfig.debounce_ms || 90;
    const maximumTermLength = lookupConfig.maximum_term_length || 200;
    const shortcut = lookupConfig.selection_shortcut || "Ctrl+Shift+L";

    let modifierHeld = false;
    let pinned = false;
    let lastTerm = "";
    let requestSequence = 0;
    let latestRequest = 0;
    let movementTimer = null;
    let lastPointer = null;
    let popup = null;

    function createPopup() {
        if (popup) {
            return popup;
        }

        popup = document.createElement("section");
        popup.id = "anki-lookup-popup";
        popup.setAttribute("role", "dialog");
        popup.setAttribute("aria-live", "polite");
        popup.setAttribute("aria-label", "Anki Lookup result");
        popup.dataset.theme = appearance.theme || "system";
        popup.style.setProperty("--anki-lookup-font-family", appearance.font_family || "inherit");
        popup.style.setProperty("--anki-lookup-font-size", `${appearance.font_size_px || 14}px`);
        popup.style.setProperty("--anki-lookup-width", `${appearance.popup_width_px || 360}px`);
        popup.style.setProperty(
            "--anki-lookup-max-height",
            `${appearance.popup_max_height_px || 420}px`,
        );
        popup.innerHTML = [
            '<header class="anki-lookup__header">',
            '<strong class="anki-lookup__term"></strong>',
            '<div class="anki-lookup__actions">',
            '<button type="button" data-action="pin" aria-label="Pin lookup popup">Pin</button>',
            '<button type="button" data-action="close" aria-label="Close lookup popup">Close</button>',
            "</div>",
            "</header>",
            '<div class="anki-lookup__body"></div>',
            '<footer class="anki-lookup__footer">Anki Lookup · Phase 1</footer>',
        ].join("");
        popup.addEventListener("pointermove", (event) => event.stopPropagation());
        popup.addEventListener("click", onPopupClick);
        document.body.appendChild(popup);
        return popup;
    }

    function onPopupClick(event) {
        const button = event.target.closest("button[data-action]");
        if (!button) {
            return;
        }
        if (button.dataset.action === "close") {
            pinned = false;
            hidePopup();
        } else if (button.dataset.action === "pin") {
            pinned = !pinned;
            button.textContent = pinned ? "Unpin" : "Pin";
            popup.classList.toggle("anki-lookup--pinned", pinned);
        }
    }

    function isEditable(target) {
        return Boolean(
            target &&
                target.closest &&
                target.closest(
                    "input, textarea, select, [contenteditable='true'], #anki-lookup-popup",
                ),
        );
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
                return { node: position.offsetNode, offset: position.offset };
            }
        }
        if (document.caretRangeFromPoint) {
            const range = document.caretRangeFromPoint(x, y);
            if (range) {
                return { node: range.startContainer, offset: range.startOffset };
            }
        }
        return null;
    }

    function wordAtPoint(x, y) {
        const caret = caretFromPoint(x, y);
        if (!caret || caret.node.nodeType !== Node.TEXT_NODE) {
            return null;
        }
        if (caret.node.parentElement && isEditable(caret.node.parentElement)) {
            return null;
        }

        const segment = core.segmentAt(caret.node.nodeValue || "", caret.offset);
        if (!segment) {
            return null;
        }

        const range = document.createRange();
        range.setStart(caret.node, segment.start);
        range.setEnd(caret.node, segment.end);
        const rect = range.getBoundingClientRect();
        return {
            term: core.normalizeTerm(segment.term, maximumTermLength),
            rect,
        };
    }

    function selectedText() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
            return null;
        }
        const range = selection.getRangeAt(0);
        const term = core.normalizeTerm(selection.toString(), maximumTermLength);
        return term ? { term, rect: range.getBoundingClientRect() } : null;
    }

    function scheduleLookup(event) {
        if (!modifierHeld || !modifierPressed(event) || pinned || isEditable(event.target)) {
            return;
        }
        lastPointer = { x: event.clientX, y: event.clientY };
        window.clearTimeout(movementTimer);
        movementTimer = window.setTimeout(() => {
            if (!lastPointer) {
                return;
            }
            const candidate = wordAtPoint(lastPointer.x, lastPointer.y);
            if (candidate && candidate.term && candidate.term !== lastTerm) {
                requestLookup(candidate.term, candidate.rect);
            }
        }, debounceMs);
    }

    function requestLookup(term, rect) {
        lastTerm = term;
        const requestId = ++requestSequence;
        latestRequest = requestId;
        showLoading(term, rect);
        const message = `anki_lookup:${JSON.stringify({
            action: "lookup",
            request_id: requestId,
            term,
        })}`;

        pycmd(message, (response) => {
            if (!response || response.request_id !== latestRequest) {
                return;
            }
            if (response.status === "ready") {
                showResult(response, rect);
            } else {
                showError(response.message || "Lookup failed.", rect);
            }
        });
    }

    function showLoading(term, rect) {
        const element = createPopup();
        element.querySelector(".anki-lookup__term").textContent = term;
        element.querySelector(".anki-lookup__body").innerHTML =
            '<div class="anki-lookup__status">Looking up…</div>';
        positionPopup(rect);
        element.classList.add("anki-lookup--visible");
    }

    function showResult(response, rect) {
        const element = createPopup();
        element.querySelector(".anki-lookup__term").textContent = response.term;
        const body = element.querySelector(".anki-lookup__body");
        body.replaceChildren();

        const source = document.createElement("div");
        source.className = "anki-lookup__source";
        source.textContent = response.source || "Lookup";
        body.appendChild(source);

        const list = document.createElement("ol");
        list.className = "anki-lookup__definitions";
        for (const definition of response.definitions || []) {
            const item = document.createElement("li");
            item.textContent = definition;
            list.appendChild(item);
        }
        body.appendChild(list);
        positionPopup(rect);
        element.classList.add("anki-lookup--visible");
    }

    function showError(message, rect) {
        const element = createPopup();
        element.querySelector(".anki-lookup__body").innerHTML = "";
        const error = document.createElement("div");
        error.className = "anki-lookup__status anki-lookup__status--error";
        error.textContent = message;
        element.querySelector(".anki-lookup__body").appendChild(error);
        positionPopup(rect);
        element.classList.add("anki-lookup--visible");
    }

    function positionPopup(rect) {
        const element = createPopup();
        const margin = 12;
        const anchorLeft = rect ? rect.left : window.innerWidth / 2;
        const anchorBottom = rect ? rect.bottom : window.innerHeight / 2;
        const width = Math.min(appearance.popup_width_px || 360, window.innerWidth - margin * 2);
        const left = Math.max(margin, Math.min(anchorLeft, window.innerWidth - width - margin));
        let top = anchorBottom + 10;

        element.style.width = `${width}px`;
        element.style.left = `${left}px`;
        element.style.top = `${top}px`;
        if (top + element.offsetHeight > window.innerHeight - margin && rect) {
            top = Math.max(margin, rect.top - element.offsetHeight - 10);
            element.style.top = `${top}px`;
        }
    }

    function hidePopup() {
        if (!popup) {
            return;
        }
        popup.classList.remove("anki-lookup--visible", "anki-lookup--pinned");
        lastTerm = "";
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
                    requestLookup(selection.term, selection.rect);
                }
            }
            if (event.key === "Escape" && popup && popup.classList.contains("anki-lookup--visible")) {
                pinned = false;
                hidePopup();
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
            window.clearTimeout(movementTimer);
            if (releaseBehavior === "close" && !pinned) {
                hidePopup();
            } else if (releaseBehavior === "pin" && popup) {
                pinned = true;
                popup.classList.add("anki-lookup--pinned");
            }
        },
        true,
    );
    document.addEventListener("pointermove", scheduleLookup, true);
    window.addEventListener("blur", () => {
        modifierHeld = false;
        window.clearTimeout(movementTimer);
    });
})();

