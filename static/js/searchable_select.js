(function () {
    function normalizeSearchableSelectValue(value) {
        return String(value || "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "");
    }

    function buildSearchableSelectOptionState(option) {
        const label = String(option?.textContent || "").trim();
        const dataset = Object.fromEntries(
            Object.entries(option?.dataset || {}).map(([key, value]) => [key, String(value || "")])
        );
        const searchBlob = [label, option?.value || "", ...Object.values(dataset)].join(" ");
        return {
            value: String(option?.value || ""),
            label,
            dataset,
            plainSearch: searchBlob.toLowerCase(),
            compactSearch: normalizeSearchableSelectValue(searchBlob),
        };
    }

    function cloneSearchableSelectOption(optionState) {
        const option = document.createElement("option");
        option.value = optionState.value;
        option.textContent = optionState.label;
        Object.entries(optionState.dataset || {}).forEach(([key, value]) => {
            option.dataset[key] = value;
        });
        return option;
    }

    function matchSearchableSelectOption(optionState, query) {
        const safeQuery = String(query || "").trim().toLowerCase();
        if (!safeQuery) {
            return true;
        }
        const compactQuery = normalizeSearchableSelectValue(safeQuery);
        return optionState.plainSearch.includes(safeQuery) || (!!compactQuery && optionState.compactSearch.includes(compactQuery));
    }

    function createSearchableSelectController(select) {
        if (!select || select.dataset.searchableSelectReady === "1") {
            return null;
        }
        if (select.disabled || select.multiple || select.closest(".searchable-select-shell")) {
            return null;
        }

        const parent = select.parentElement;
        if (!parent) {
            return null;
        }

        const placeholder = String(select.dataset.searchablePlaceholder || "Cari opsi").trim();
        const defaultSummary = String(
            select.dataset.searchableSummary || "Ketik untuk mencari opsi tanpa scroll panjang."
        ).trim();

        const shell = document.createElement("div");
        shell.className = "searchable-select-shell";

        const input = document.createElement("input");
        input.type = "search";
        input.className = "searchable-select-input";
        input.placeholder = placeholder;
        input.autocomplete = "off";
        input.spellcheck = false;
        input.setAttribute("aria-label", placeholder);

        const summary = document.createElement("small");
        summary.className = "helper-text searchable-select-summary";
        summary.textContent = defaultSummary;

        parent.insertBefore(shell, select);
        shell.appendChild(input);
        shell.appendChild(select);
        shell.appendChild(summary);

        const controller = {
            select,
            input,
            summary,
            defaultSummary,
            state: {
                all: Array.from(select.options).map(buildSearchableSelectOptionState),
            },
            sync(queryOverride = null) {
                const query = queryOverride === null ? String(input.value || "") : String(queryOverride || "");
                const currentValue = String(select.value || "");
                const options = Array.isArray(controller.state.all) ? controller.state.all : [];
                if (!options.length) {
                    return;
                }

                const defaultOption = options[0];
                const visibleOptions = options.filter((option, index) => {
                    if (index === 0) {
                        return false;
                    }
                    return matchSearchableSelectOption(option, query);
                });
                const currentState = options.find((option) => option.value === currentValue) || null;

                select.replaceChildren(cloneSearchableSelectOption(defaultOption));
                visibleOptions.forEach((option) => {
                    select.appendChild(cloneSearchableSelectOption(option));
                });

                if (
                    currentState
                    && currentState.value !== defaultOption.value
                    && !visibleOptions.some((option) => option.value === currentState.value)
                ) {
                    select.appendChild(cloneSearchableSelectOption(currentState));
                }

                const nextValue = Array.from(select.options).some((option) => option.value === currentValue)
                    ? currentValue
                    : defaultOption.value;
                select.value = nextValue;

                if (!query.trim()) {
                    summary.textContent = defaultSummary;
                    return;
                }

                if (!visibleOptions.length) {
                    summary.textContent = `Tidak ada hasil yang cocok untuk "${query.trim()}".`;
                    return;
                }

                summary.textContent = `${visibleOptions.length} opsi cocok untuk "${query.trim()}".`;
            },
        };

        input.addEventListener("input", () => {
            controller.sync();
        });

        select.addEventListener("change", () => {
            if (!input.value.trim()) {
                summary.textContent = defaultSummary;
            }
        });

        const form = select.closest("form");
        form?.addEventListener("reset", () => {
            window.setTimeout(() => {
                input.value = "";
                controller.sync("");
            }, 0);
        });

        select.dataset.searchableSelectReady = "1";
        select._searchableSelectController = controller;
        controller.sync("");
        return controller;
    }

    function refreshSearchableSelects(root = document) {
        root.querySelectorAll('select[data-searchable-select="1"]').forEach((select) => {
            createSearchableSelectController(select);
        });
    }

    window.WmsSearchableSelect = {
        refresh: refreshSearchableSelects,
    };

    document.addEventListener("DOMContentLoaded", () => {
        refreshSearchableSelects(document);
    });

    document.addEventListener("wms:searchable-select-refresh", (event) => {
        refreshSearchableSelects(event.target instanceof Element ? event.target : document);
    });
})();
