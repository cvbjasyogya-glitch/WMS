(function () {
    const root = document.querySelector("[data-floating-toolbelt]");
    if (!root) {
        return;
    }

    const toggle = root.querySelector("[data-floating-toolbelt-toggle]");
    const menu = root.querySelector("[data-floating-toolbelt-menu]");
    const actionButtons = Array.from(root.querySelectorAll("[data-floating-toolbelt-action]"));
    const notificationToggle = document.querySelector("[data-notification-toggle]");
    const attendanceShortcut = document.querySelector("[data-attendance-shortcut]");
    const chatLauncher = document.querySelector("[data-chat-widget-launcher]");
    const firstActionButton = actionButtons[0] || null;
    let resizeSyncFrame = 0;
    let trackedViewportWidth = window.innerWidth;

    if (!toggle || !menu) {
        return;
    }

    function getDisplayMode() {
        const bodyMode = (document.body.dataset.floatingToolbeltMode || "").trim().toLowerCase();
        const rootMode = (root.dataset.floatingToolbeltMode || "").trim().toLowerCase();
        const safeMode = rootMode || bodyMode || "grouped";
        return safeMode === "split" ? "split" : "grouped";
    }

    function isFormInteractionTarget(target) {
        if (!(target instanceof HTMLElement)) {
            return false;
        }

        if (root.contains(target)) {
            return false;
        }

        if (target.isContentEditable) {
            return true;
        }

        return Boolean(
            target.closest(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="checkbox"]):not([type="radio"]), textarea, select, [contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"]'
            )
        );
    }

    function syncDisplayMode() {
        const shouldSplitShortcuts = getDisplayMode() === "split";
        document.body.classList.toggle("floating-toolbelt-disabled", shouldSplitShortcuts);
        root.classList.toggle("is-disabled", shouldSplitShortcuts);

        if (shouldSplitShortcuts && root.classList.contains("is-open")) {
            setOpen(false);
        }

        if (shouldSplitShortcuts) {
            root.setAttribute("aria-hidden", "true");
            menu.hidden = true;
            menu.setAttribute("aria-hidden", "true");
            toggle.setAttribute("aria-expanded", "false");
        } else {
            root.removeAttribute("aria-hidden");
        }
    }

    function syncMutedState(target = document.activeElement) {
        if (root.classList.contains("is-disabled")) {
            root.classList.remove("is-muted");
            return;
        }

        const shouldMute = isFormInteractionTarget(target);
        root.classList.toggle("is-muted", shouldMute && !root.classList.contains("is-open"));
    }

    function setOpen(nextOpen, options = {}) {
        const safeOpen = Boolean(nextOpen);
        const wasOpen = root.classList.contains("is-open");
        const focusFirstAction = options.focusFirstAction !== false;
        const restoreFocus = options.restoreFocus === true;

        if (safeOpen && root.classList.contains("is-disabled")) {
            return;
        }

        if (safeOpen === wasOpen) {
            menu.hidden = !safeOpen;
            menu.setAttribute("aria-hidden", safeOpen ? "false" : "true");
            toggle.setAttribute("aria-expanded", safeOpen ? "true" : "false");
            return;
        }

        root.classList.toggle("is-open", safeOpen);
        menu.hidden = !safeOpen;
        menu.setAttribute("aria-hidden", safeOpen ? "false" : "true");
        toggle.setAttribute("aria-expanded", safeOpen ? "true" : "false");

        if (safeOpen && focusFirstAction) {
            firstActionButton?.focus();
            return;
        }

        if (restoreFocus) {
            toggle.focus({ preventScroll: true });
        }

        syncMutedState();
    }

    function triggerAction(actionName) {
        if (actionName === "notification") {
            notificationToggle?.click();
            return;
        }

        if (actionName === "camera") {
            if (attendanceShortcut instanceof HTMLAnchorElement) {
                window.location.href = attendanceShortcut.href;
            }
            return;
        }

        if (actionName === "chat") {
            chatLauncher?.click();
        }
    }

    function queueViewportSync(force = false) {
        const nextWidth = window.innerWidth;
        const widthChanged = Math.abs(nextWidth - trackedViewportWidth) > 1;
        if (!force && !widthChanged) {
            return;
        }

        trackedViewportWidth = nextWidth;

        if (resizeSyncFrame) {
            return;
        }

        resizeSyncFrame = window.requestAnimationFrame(() => {
            resizeSyncFrame = 0;
            syncDisplayMode();
            if (root.classList.contains("is-open")) {
                setOpen(false);
            }
            syncMutedState();
        });
    }

    toggle.addEventListener("click", () => {
        setOpen(!root.classList.contains("is-open"));
    });

    actionButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const actionName = button.dataset.floatingToolbeltAction || "";
            setOpen(false);
            window.setTimeout(() => {
                triggerAction(actionName);
            }, 0);
        });
    });

    document.addEventListener("click", (event) => {
        if (!root.classList.contains("is-open")) {
            return;
        }
        if (root.contains(event.target)) {
            return;
        }
        setOpen(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setOpen(false, { restoreFocus: true });
        }
    });

    document.addEventListener("focusin", (event) => {
        if (isFormInteractionTarget(event.target) && root.classList.contains("is-open")) {
            setOpen(false);
        }
        syncMutedState(event.target);
    });

    document.addEventListener("focusout", () => {
        window.requestAnimationFrame(() => {
            syncMutedState(document.activeElement);
        });
    });

    window.addEventListener("resize", () => {
        queueViewportSync(false);
    });

    menu.hidden = true;
    menu.setAttribute("aria-hidden", "true");
    syncDisplayMode();
    queueViewportSync(true);
})();
