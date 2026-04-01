(() => {
    const EXCLUDED_TABLE_CLASSES = new Set([
        "variant-builder-table",
        "ops-queue-table",
        "picker-results-table",
        "schedule-board",
        "stock-table",
    ]);

    const EXCLUDED_HEADER_LABELS = new Set([
        "aksi",
        "action",
        "opsi",
        "tools",
        "#",
    ]);

    const collator = new Intl.Collator("id", {
        numeric: true,
        sensitivity: "base",
    });

    function normalizeText(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function isExcludedTable(table) {
        if (!table || table.dataset.manualSort === "off") {
            return true;
        }

        for (const className of EXCLUDED_TABLE_CLASSES) {
            if (table.classList.contains(className)) {
                return true;
            }
        }

        return false;
    }

    function getBodyRows(table) {
        if (!table.tBodies.length) {
            return [];
        }
        return Array.from(table.tBodies[0].rows).filter((row) => !row.hidden);
    }

    function extractCellText(cell) {
        if (!cell) {
            return "";
        }

        if (cell.dataset.sortValue) {
            return normalizeText(cell.dataset.sortValue);
        }

        const field = cell.querySelector("input, select, textarea");
        if (field) {
            return normalizeText(field.value || field.getAttribute("value") || "");
        }

        return normalizeText(cell.textContent || "");
    }

    function parseSortableNumber(value) {
        const raw = normalizeText(value);
        if (!raw) {
            return null;
        }

        let normalized = raw.replace(/[^\d,.\-]/g, "");
        if (!normalized || /^[-.,]+$/.test(normalized)) {
            return null;
        }

        const commaCount = (normalized.match(/,/g) || []).length;
        const dotCount = (normalized.match(/\./g) || []).length;

        if (commaCount > 0 && dotCount > 0) {
            if (normalized.lastIndexOf(",") > normalized.lastIndexOf(".")) {
                normalized = normalized.replace(/\./g, "").replace(",", ".");
            } else {
                normalized = normalized.replace(/,/g, "");
            }
        } else if (commaCount > 1 && dotCount === 0) {
            normalized = normalized.replace(/,/g, "");
        } else if (dotCount > 1 && commaCount === 0) {
            normalized = normalized.replace(/\./g, "");
        } else if (commaCount === 1 && dotCount === 0) {
            normalized = /,\d{1,2}$/.test(normalized)
                ? normalized.replace(",", ".")
                : normalized.replace(/,/g, "");
        }

        const parsed = Number(normalized);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function parseSortableDate(value) {
        const raw = normalizeText(value);
        if (!raw) {
            return null;
        }

        let match = raw.match(
            /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2})[:.](\d{2})(?:[:.](\d{2}))?)?$/
        );
        if (match) {
            const [, year, month, day, hour = "00", minute = "00", second = "00"] = match;
            return Date.UTC(
                Number(year),
                Number(month) - 1,
                Number(day),
                Number(hour),
                Number(minute),
                Number(second)
            );
        }

        match = raw.match(
            /^(\d{2})\/(\d{2})\/(\d{4})(?:[ T](\d{2})[:.](\d{2})(?:[:.](\d{2}))?)?$/
        );
        if (match) {
            const [, day, month, year, hour = "00", minute = "00", second = "00"] = match;
            return Date.UTC(
                Number(year),
                Number(month) - 1,
                Number(day),
                Number(hour),
                Number(minute),
                Number(second)
            );
        }

        match = raw.match(
            /^(\d{2})-(\d{2})-(\d{4})(?:[ T](\d{2})[:.](\d{2})(?:[:.](\d{2}))?)?$/
        );
        if (match) {
            const [, day, month, year, hour = "00", minute = "00", second = "00"] = match;
            return Date.UTC(
                Number(year),
                Number(month) - 1,
                Number(day),
                Number(hour),
                Number(minute),
                Number(second)
            );
        }

        const fallback = Date.parse(raw);
        return Number.isFinite(fallback) ? fallback : null;
    }

    function detectColumnType(table, columnIndex) {
        const rows = getBodyRows(table).slice(0, 10);
        if (!rows.length) {
            return "text";
        }

        let numericHits = 0;
        let dateHits = 0;
        let nonEmpty = 0;

        rows.forEach((row) => {
            const text = extractCellText(row.cells[columnIndex]);
            if (!text) {
                return;
            }

            nonEmpty += 1;
            if (parseSortableDate(text) !== null) {
                dateHits += 1;
                return;
            }
            if (parseSortableNumber(text) !== null) {
                numericHits += 1;
            }
        });

        if (dateHits >= Math.max(2, Math.ceil(nonEmpty / 2))) {
            return "date";
        }
        if (numericHits >= Math.max(2, Math.ceil(nonEmpty / 2))) {
            return "number";
        }
        return "text";
    }

    function getColumns(table) {
        const headers = Array.from(table.querySelectorAll("thead th"));
        return headers
            .map((th, index) => {
                const label = normalizeText(th.dataset.sortLabel || th.textContent || "");
                return {
                    index,
                    label,
                    type: th.dataset.sortType || detectColumnType(table, index),
                };
            })
            .filter((column) => {
                if (!column.label) {
                    return false;
                }
                return !EXCLUDED_HEADER_LABELS.has(column.label.toLowerCase());
            });
    }

    function getComparableValue(cell, type) {
        const text = extractCellText(cell);

        if (type === "date") {
            const dateValue = parseSortableDate(text);
            return dateValue !== null ? dateValue : text.toLowerCase();
        }

        if (type === "number") {
            const numericValue = parseSortableNumber(text);
            return numericValue !== null ? numericValue : text.toLowerCase();
        }

        return text.toLowerCase();
    }

    function applySort(table, config) {
        const tbody = table.tBodies[0];
        if (!tbody) {
            return;
        }

        const rows = Array.from(tbody.rows);
        rows.forEach((row, index) => {
            if (!row.dataset.manualSortIndex) {
                row.dataset.manualSortIndex = String(index);
            }
        });

        const directionMultiplier = config.direction === "desc" ? -1 : 1;
        const columnIndex = Number(config.select.value);

        if (!Number.isFinite(columnIndex) || columnIndex < 0) {
            rows
                .slice()
                .sort((left, right) => {
                    return Number(left.dataset.manualSortIndex) - Number(right.dataset.manualSortIndex);
                })
                .forEach((row) => tbody.appendChild(row));
            return;
        }

        const columnMeta = config.columns.find((column) => column.index === columnIndex);
        const columnType = columnMeta ? columnMeta.type : "text";

        rows
            .slice()
            .sort((leftRow, rightRow) => {
                const leftValue = getComparableValue(leftRow.cells[columnIndex], columnType);
                const rightValue = getComparableValue(rightRow.cells[columnIndex], columnType);

                if (typeof leftValue === "number" && typeof rightValue === "number") {
                    if (leftValue !== rightValue) {
                        return (leftValue - rightValue) * directionMultiplier;
                    }
                } else {
                    const textCompare = collator.compare(String(leftValue), String(rightValue));
                    if (textCompare !== 0) {
                        return textCompare * directionMultiplier;
                    }
                }

                return Number(leftRow.dataset.manualSortIndex) - Number(rightRow.dataset.manualSortIndex);
            })
            .forEach((row) => tbody.appendChild(row));
    }

    function syncDirectionButton(button, direction) {
        const isDescending = direction === "desc";
        button.dataset.direction = isDescending ? "desc" : "asc";
        button.setAttribute("aria-pressed", isDescending ? "true" : "false");
        button.innerHTML = isDescending ? "<span>&darr;</span><strong>Turun</strong>" : "<span>&uarr;</span><strong>Naik</strong>";
        button.setAttribute(
            "aria-label",
            isDescending ? "Urutkan menurun" : "Urutkan menaik"
        );
        button.title = isDescending ? "Urutan menurun" : "Urutan menaik";
    }

    function createSortBar(table, columns) {
        const bar = document.createElement("div");
        bar.className = "table-manual-sortbar";

        const field = document.createElement("label");
        field.className = "table-manual-sortfield";

        const fieldLabel = document.createElement("span");
        fieldLabel.textContent = "Urut berdasar";

        const select = document.createElement("select");
        select.className = "table-manual-sortselect";

        const defaultOption = document.createElement("option");
        defaultOption.value = "-1";
        defaultOption.textContent = "Urutan Awal";
        select.appendChild(defaultOption);

        columns.forEach((column) => {
            const option = document.createElement("option");
            option.value = String(column.index);
            option.textContent = column.label;
            select.appendChild(option);
        });

        field.appendChild(fieldLabel);
        field.appendChild(select);

        const directionButton = document.createElement("button");
        directionButton.type = "button";
        directionButton.className = "table-manual-sortdirection";
        syncDirectionButton(directionButton, "asc");

        bar.appendChild(field);
        bar.appendChild(directionButton);

        return { bar, select, directionButton };
    }

    function initSortableTable(table, index) {
        if (!table || table.dataset.manualSortReady === "1" || isExcludedTable(table)) {
            return;
        }

        const rows = getBodyRows(table);
        if (rows.length < 2) {
            return;
        }

        const columns = getColumns(table);
        if (columns.length < 1) {
            return;
        }

        const { bar, select, directionButton } = createSortBar(table, columns);
        const box = table.closest(".table-box");

        if (box) {
            box.insertBefore(bar, table);
        } else {
            table.parentElement.insertBefore(bar, table);
        }

        table.dataset.manualSortReady = "1";
        table.dataset.manualSortId = String(index);

        const config = {
            table,
            columns,
            select,
            direction: "asc",
        };

        select.addEventListener("change", () => {
            applySort(table, config);
        });

        directionButton.addEventListener("click", () => {
            config.direction = config.direction === "asc" ? "desc" : "asc";
            syncDirectionButton(directionButton, config.direction);
            applySort(table, config);
        });

        applySort(table, config);
    }

    function initManualTableSortControls(root = document) {
        const tables = Array.from(root.querySelectorAll(".table-box table"));
        tables.forEach((table, index) => {
            initSortableTable(table, index);
        });
    }

    let initTimer = null;
    const observer = new MutationObserver((mutations) => {
        const shouldRefresh = mutations.some((mutation) => mutation.addedNodes.length || mutation.removedNodes.length);
        if (!shouldRefresh) {
            return;
        }

        window.clearTimeout(initTimer);
        initTimer = window.setTimeout(() => {
            initManualTableSortControls(document);
        }, 80);
    });

    window.initManualTableSortControls = initManualTableSortControls;
    initManualTableSortControls(document);
    observer.observe(document.body, {
        childList: true,
        subtree: true,
    });
})();
