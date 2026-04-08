(function () {
    const CURRENCY_SELECTOR = 'input[data-wms-currency]';
    const INPUT_HIGHLIGHT_CLASS = "is-updated";
    const INPUT_HIGHLIGHT_DURATION_MS = 720;
    let mirrorSequence = 0;

    function trimCurrencyLeadingZeros(rawValue) {
        const [integerPart = "", fractionPart = ""] = String(rawValue || "").split(".");
        const normalizedInteger = integerPart.replace(/^0+(?=\d)/, "");
        if (!fractionPart) {
            return normalizedInteger;
        }
        return `${normalizedInteger || "0"}.${fractionPart}`;
    }

    function formatCurrencyDisplay(rawValue) {
        const [integerPart = "", fractionPart = ""] = trimCurrencyLeadingZeros(rawValue).split(".");
        if (!integerPart && !fractionPart) {
            return "";
        }

        const formattedInteger = new Intl.NumberFormat("id-ID", {
            maximumFractionDigits: 0,
        }).format(Number(integerPart || 0));

        if (!fractionPart) {
            return formattedInteger;
        }

        return `${formattedInteger},${fractionPart}`;
    }

    function normalizeCurrencyRaw(value) {
        const originalValue = String(value ?? "").trim();
        if (!originalValue) {
            return "";
        }

        // Digit-only input can skip the heavier separator parsing path.
        // We intentionally do not treat `50.000` as a ready-made decimal value here,
        // because in ID locale that usually means fifty thousand, not fifty point zero.
        if (/^\d+$/.test(originalValue)) {
            return trimCurrencyLeadingZeros(originalValue);
        }

        const cleaned = originalValue.replace(/[^\d,.\-]/g, "");
        if (!cleaned) {
            return "";
        }

        const separators = cleaned.match(/[.,]/g) || [];
        const lastComma = cleaned.lastIndexOf(",");
        const lastDot = cleaned.lastIndexOf(".");
        const decimalIndex = Math.max(lastComma, lastDot);
        const trailingDigits = decimalIndex >= 0 ? cleaned.slice(decimalIndex + 1).replace(/[^\d]/g, "") : "";
        const leadingDigits = decimalIndex >= 0 ? cleaned.slice(0, decimalIndex).replace(/[^\d]/g, "") : cleaned.replace(/[^\d]/g, "");
        const looksLikeDecimal = trailingDigits.length > 0
            && trailingDigits.length <= 2
            && (cleaned.includes(",") || separators.length === 1);

        if (!looksLikeDecimal) {
            return trimCurrencyLeadingZeros(cleaned.replace(/[^\d]/g, ""));
        }

        return trimCurrencyLeadingZeros(`${leadingDigits || "0"}.${trailingDigits}`);
    }

    function normalizePlainRaw(value) {
        let normalized = String(value ?? "")
            .replace(/\s+/g, "")
            .replace(/,/g, ".")
            .replace(/[^0-9.]/g, "");

        const decimalIndex = normalized.indexOf(".");
        if (decimalIndex >= 0) {
            normalized = normalized.slice(0, decimalIndex + 1) + normalized.slice(decimalIndex + 1).replace(/\./g, "");
        }

        if (normalized.startsWith(".")) {
            normalized = `0${normalized}`;
        }

        return normalized;
    }

    function getManagedMode(input) {
        if (!(input instanceof HTMLInputElement)) {
            return "currency";
        }

        const configuredMode = input.dataset.wmsCurrency || "currency";
        if (configuredMode !== "switch") {
            return configuredMode;
        }

        const sourceId = input.dataset.wmsCurrencySwitchSource;
        const sourceMatch = input.dataset.wmsCurrencySwitchMatch || "amount";
        const source = sourceId ? document.getElementById(sourceId) : null;
        return source && source.value === sourceMatch ? "currency" : "plain";
    }

    function findSelectionFromRightDigits(formattedValue, digitsToRight) {
        if (digitsToRight <= 0) {
            return formattedValue.length;
        }

        let seenDigits = 0;
        for (let index = formattedValue.length; index >= 0; index -= 1) {
            const char = formattedValue.charAt(index - 1);
            if (/\d/.test(char)) {
                seenDigits += 1;
                if (seenDigits === digitsToRight) {
                    return index - 1;
                }
            }
        }

        return 0;
    }

    function updateMirrorInput(input, rawValue) {
        const originalName = input.dataset.wmsCurrencyOriginalName || input.getAttribute("name");
        if (!originalName) {
            return null;
        }

        if (!input.dataset.wmsCurrencyOriginalName) {
            input.dataset.wmsCurrencyOriginalName = originalName;
        }

        let mirror = null;
        if (input.dataset.wmsCurrencyMirrorId) {
            mirror = document.getElementById(input.dataset.wmsCurrencyMirrorId);
        }

        if (!(mirror instanceof HTMLInputElement)) {
            mirror = document.createElement("input");
            mirror.type = "hidden";
            mirror.name = originalName;
            mirror.dataset.wmsCurrencyMirror = "1";
            mirror.id = input.id ? `${input.id}Raw` : `wmsCurrencyMirror${mirrorSequence += 1}`;
            input.dataset.wmsCurrencyMirrorId = mirror.id;
            input.removeAttribute("name");
            input.insertAdjacentElement("afterend", mirror);
        }

        mirror.value = rawValue;
        return mirror;
    }

    function flashInputUpdate(input) {
        if (!(input instanceof HTMLInputElement)) {
            return;
        }

        input.classList.remove(INPUT_HIGHLIGHT_CLASS);
        const previousTimer = Number(input.dataset.wmsCurrencyHighlightTimer || 0);
        if (previousTimer) {
            window.clearTimeout(previousTimer);
        }

        // Force reflow so repeated updates still replay the animation.
        void input.offsetWidth;
        input.classList.add(INPUT_HIGHLIGHT_CLASS);

        const timerId = window.setTimeout(() => {
            input.classList.remove(INPUT_HIGHLIGHT_CLASS);
            delete input.dataset.wmsCurrencyHighlightTimer;
        }, INPUT_HIGHLIGHT_DURATION_MS);
        input.dataset.wmsCurrencyHighlightTimer = String(timerId);
    }

    function applyDisplayValue(input, rawValue, options) {
        const resolvedMode = getManagedMode(input);
        const previousValue = input.value || "";
        const previousRawValue = input.dataset.wmsCurrencyRawValue || "";
        const caretStart = Number.isFinite(input.selectionStart) ? input.selectionStart : previousValue.length;
        const digitsToRight = previousValue.slice(caretStart).replace(/\D/g, "").length;

        let normalized = resolvedMode === "currency"
            ? normalizeCurrencyRaw(rawValue)
            : normalizePlainRaw(rawValue);

        input.dataset.wmsCurrencyResolvedMode = resolvedMode;
        input.dataset.wmsCurrencyRawValue = normalized;
        updateMirrorInput(input, normalized);

        if (resolvedMode === "currency") {
            input.value = normalized ? formatCurrencyDisplay(normalized) : "";
            input.inputMode = input.dataset.wmsCurrencyInputMode || "decimal";
        } else {
            input.value = normalized;
            input.inputMode = input.dataset.wmsCurrencyPlainInputMode || "decimal";
        }

        if (options?.preserveCaret && resolvedMode === "currency" && document.activeElement === input) {
            const selection = findSelectionFromRightDigits(input.value, digitsToRight);
            window.requestAnimationFrame(() => {
                try {
                    input.setSelectionRange(selection, selection);
                } catch (error) {
                    // Browser tertentu tidak mengizinkan setSelectionRange pada state tertentu.
                }
            });
        }

        if (options?.highlight && normalized !== previousRawValue) {
            flashInputUpdate(input);
        }
    }

    function prepareInput(input) {
        if (!(input instanceof HTMLInputElement)) {
            return;
        }

        if (input.dataset.wmsCurrencyPrepared === "1") {
            applyDisplayValue(input, input.dataset.wmsCurrencyRawValue || input.value || "");
            return;
        }

        input.dataset.wmsCurrencyPrepared = "1";
        input.dataset.wmsCurrencyOriginalType = input.getAttribute("type") || "text";
        input.setAttribute("type", "text");
        input.setAttribute("autocomplete", "off");
        input.spellcheck = false;
        input.classList.add("wms-currency-field");

        input.addEventListener("focus", () => {
            input.dataset.wmsCurrencyFocusRawValue = input.dataset.wmsCurrencyRawValue || "";
        });
        input.addEventListener("input", () => {
            applyDisplayValue(input, input.value, { preserveCaret: true });
        });
        input.addEventListener("change", () => {
            applyDisplayValue(input, input.value);
        });
        input.addEventListener("blur", () => {
            applyDisplayValue(input, input.value);
            if ((input.dataset.wmsCurrencyFocusRawValue || "") !== (input.dataset.wmsCurrencyRawValue || "")) {
                flashInputUpdate(input);
            }
            delete input.dataset.wmsCurrencyFocusRawValue;
        });
        input.addEventListener("paste", (event) => {
            const clipboardText = event.clipboardData?.getData("text") || "";
            if (!clipboardText) {
                return;
            }
            event.preventDefault();
            applyDisplayValue(input, clipboardText, { highlight: true });
        });

        const switchSourceId = input.dataset.wmsCurrencySwitchSource;
        if (switchSourceId) {
            const source = document.getElementById(switchSourceId);
            if (source && !source.dataset.wmsCurrencySwitchBound?.includes(input.id || "")) {
                const boundInputs = new Set((source.dataset.wmsCurrencySwitchBound || "").split(",").filter(Boolean));
                const inputKey = input.id || `anonymous-${mirrorSequence + 1}`;
                if (!boundInputs.has(inputKey)) {
                    source.addEventListener("change", () => {
                        applyDisplayValue(input, input.dataset.wmsCurrencyRawValue || input.value || "");
                    });
                    boundInputs.add(inputKey);
                    source.dataset.wmsCurrencySwitchBound = Array.from(boundInputs).join(",");
                }
            }
        }

        applyDisplayValue(input, input.value || "");
    }

    function collectManagedInputs(scope) {
        if (!scope) {
            return [];
        }

        if (scope instanceof HTMLInputElement && scope.matches(CURRENCY_SELECTOR)) {
            return [scope];
        }

        const root = scope instanceof Document ? scope : scope;
        if (!(root instanceof Element || root instanceof Document || root instanceof DocumentFragment)) {
            return [];
        }

        return Array.from(root.querySelectorAll(CURRENCY_SELECTOR));
    }

    function refresh(scope = document) {
        collectManagedInputs(scope).forEach((input) => prepareInput(input));
    }

    function getRawValue(input) {
        if (!(input instanceof HTMLInputElement)) {
            return "";
        }

        if (input.matches(CURRENCY_SELECTOR)) {
            prepareInput(input);
            const resolvedMode = getManagedMode(input);
            const rawValue = input.dataset.wmsCurrencyRawValue || "";
            return resolvedMode === "currency"
                ? normalizeCurrencyRaw(rawValue)
                : normalizePlainRaw(rawValue);
        }

        return String(input.value || "").trim();
    }

    function getNumericValue(input) {
        const rawValue = getRawValue(input);
        if (!rawValue) {
            return 0;
        }
        const numeric = Number(rawValue);
        return Number.isFinite(numeric) ? numeric : 0;
    }

    function setValue(input, value) {
        if (!(input instanceof HTMLInputElement)) {
            return;
        }

        if (!input.matches(CURRENCY_SELECTOR)) {
            input.value = value === null || value === undefined ? "" : String(value);
            return;
        }

        prepareInput(input);
        applyDisplayValue(input, value === null || value === undefined ? "" : String(value));
    }

    function isManagedInput(input) {
        return input instanceof HTMLInputElement && input.matches(CURRENCY_SELECTOR);
    }

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node instanceof Element || node instanceof DocumentFragment) {
                    refresh(node);
                }
            });
        });
    });

    window.wmsCurrencyInput = {
        refresh,
        getRawValue,
        getNumericValue,
        setValue,
        isManagedInput,
    };

    if (document.body) {
        refresh(document);
        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });
    } else {
        document.addEventListener("DOMContentLoaded", () => {
            refresh(document);
            observer.observe(document.body, {
                childList: true,
                subtree: true,
            });
        }, { once: true });
    }
})();
