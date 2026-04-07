(() => {
    const TABLE_SELECTOR = ".table-box table";
    const TABLE_CLASS = "wms-layout-resizable";
    const MANUAL_LAYOUT_CLASS = "has-manual-layout";
    const COL_HANDLE_CLASS = "table-col-resizer";
    const ROW_HANDLE_CLASS = "table-row-resizer";
    const STORAGE_PREFIX = "wms-table-layout-v1:";
    const MIN_COL_WIDTH = 72;
    const MIN_ROW_HEIGHT = 44;

    let resizeState = null;
    let initFrame = 0;

    function normalizeKeyPart(value) {
        return String(value || "")
            .trim()
            .replace(/[^a-z0-9_-]+/gi, "-")
            .replace(/^-+|-+$/g, "")
            .toLowerCase();
    }

    function shouldManageTable(table) {
        if (!(table instanceof HTMLTableElement)) {
            return false;
        }
        if (!table.closest(".table-box")) {
            return false;
        }
        if (table.closest("[data-table-layout='static']")) {
            return false;
        }
        return true;
    }

    function getManagedTables(root = document) {
        return Array.from(root.querySelectorAll(TABLE_SELECTOR)).filter(shouldManageTable);
    }

    function getReferenceRow(table) {
        return table.tHead?.rows?.[0] || table.rows[0] || null;
    }

    function supportsColumnResize(table) {
        const row = getReferenceRow(table);
        if (!row) {
            return false;
        }
        return Array.from(row.cells).every((cell) => (cell.colSpan || 1) === 1);
    }

    function getLayoutId(table) {
        if (table.dataset.tableLayoutId) {
            return table.dataset.tableLayoutId;
        }

        const box = table.closest(".table-box");
        const tableIndex = getManagedTables().indexOf(table);
        const parts = [
            normalizeKeyPart(window.location.pathname),
            normalizeKeyPart(box?.id),
            normalizeKeyPart(table.id),
            normalizeKeyPart(Array.from(table.classList).filter((cls) => cls !== TABLE_CLASS).slice(0, 3).join("-")),
            tableIndex >= 0 ? `idx-${tableIndex}` : "",
        ].filter(Boolean);

        const layoutId = parts.join("__") || `table-${Date.now()}`;
        table.dataset.tableLayoutId = layoutId;
        return layoutId;
    }

    function getStorageKey(table) {
        return `${STORAGE_PREFIX}${getLayoutId(table)}`;
    }

    function readStoredLayout(table) {
        try {
            const raw = window.localStorage.getItem(getStorageKey(table));
            if (!raw) {
                return null;
            }
            const parsed = JSON.parse(raw);
            return parsed && Array.isArray(parsed.widths) ? parsed : null;
        } catch (error) {
            return null;
        }
    }

    function writeStoredLayout(table, widths) {
        try {
            window.localStorage.setItem(getStorageKey(table), JSON.stringify({ widths }));
        } catch (error) {
        }
    }

    function removeStoredLayout(table) {
        try {
            window.localStorage.removeItem(getStorageKey(table));
        } catch (error) {
        }
    }

    function getColumnCount(table) {
        const row = getReferenceRow(table);
        return row ? row.cells.length : 0;
    }

    function getOrCreateColGroup(table) {
        if (!supportsColumnResize(table)) {
            return null;
        }

        let colgroup = table.querySelector(":scope > colgroup[data-table-layout-cols='1']");
        const columnCount = getColumnCount(table);
        if (!columnCount) {
            return null;
        }

        if (!colgroup) {
            colgroup = document.createElement("colgroup");
            colgroup.dataset.tableLayoutCols = "1";
            table.insertBefore(colgroup, table.firstChild);
        }

        while (colgroup.children.length < columnCount) {
            colgroup.appendChild(document.createElement("col"));
        }

        while (colgroup.children.length > columnCount) {
            colgroup.removeChild(colgroup.lastElementChild);
        }

        return colgroup;
    }

    function getColElements(table) {
        const colgroup = getOrCreateColGroup(table);
        if (!colgroup) {
            return [];
        }
        return Array.from(colgroup.children);
    }

    function measureCurrentColumnWidths(table) {
        const row = getReferenceRow(table);
        if (!row) {
            return [];
        }
        return Array.from(row.cells).map((cell) => Math.max(MIN_COL_WIDTH, Math.round(cell.getBoundingClientRect().width)));
    }

    function syncTableWidth(table, widths) {
        const box = table.closest(".table-box");
        const totalWidth = widths.reduce((sum, value) => sum + value, 0);
        const containerWidth = box ? Math.max(0, Math.round(box.clientWidth - 2)) : totalWidth;
        table.style.tableLayout = "fixed";
        table.style.minWidth = `${totalWidth}px`;
        table.style.width = totalWidth > containerWidth ? `${totalWidth}px` : "100%";
        table.classList.add(MANUAL_LAYOUT_CLASS);
        if (typeof window.updateScrollableTableHints === "function") {
            window.updateScrollableTableHints();
        }
    }

    function clearManualLayout(table) {
        const colgroup = table.querySelector(":scope > colgroup[data-table-layout-cols='1']");
        if (colgroup) {
            Array.from(colgroup.children).forEach((col) => {
                col.style.width = "";
            });
        }
        table.style.width = "";
        table.style.minWidth = "";
        table.style.tableLayout = "";
        table.classList.remove(MANUAL_LAYOUT_CLASS);
        removeStoredLayout(table);
        if (typeof window.updateScrollableTableHints === "function") {
            window.updateScrollableTableHints();
        }
    }

    function applyStoredWidths(table, widths, persist = false) {
        const cols = getColElements(table);
        if (!cols.length || cols.length !== widths.length) {
            return false;
        }

        const safeWidths = widths.map((width) => Math.max(MIN_COL_WIDTH, Math.round(Number(width) || 0)));
        cols.forEach((col, index) => {
            col.style.width = `${safeWidths[index]}px`;
        });
        syncTableWidth(table, safeWidths);
        if (persist) {
            writeStoredLayout(table, safeWidths);
        }
        return true;
    }

    function restoreStoredWidths(table) {
        const saved = readStoredLayout(table);
        if (!saved) {
            return false;
        }
        return applyStoredWidths(table, saved.widths, false);
    }

    function ensureRelativeCell(cell) {
        if (!cell || cell.classList.contains("table-layout-cell")) {
            return;
        }
        cell.classList.add("table-layout-cell");
    }

    function createHandle(className, axisLabel) {
        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = className;
        handle.setAttribute("aria-label", axisLabel);
        handle.setAttribute("tabindex", "-1");
        handle.draggable = false;
        return handle;
    }

    function startColumnResize(event, table, columnIndex) {
        if (event.button !== 0) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();

        const widths = table.classList.contains(MANUAL_LAYOUT_CLASS)
            ? getColElements(table).map((col, index) => {
                const rawWidth = parseFloat(col.style.width);
                return Number.isFinite(rawWidth) && rawWidth > 0
                    ? rawWidth
                    : measureCurrentColumnWidths(table)[index] || MIN_COL_WIDTH;
            })
            : measureCurrentColumnWidths(table);

        if (!table.classList.contains(MANUAL_LAYOUT_CLASS)) {
            applyStoredWidths(table, widths, false);
        }

        const handle = event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
        if (handle && typeof handle.setPointerCapture === "function" && typeof event.pointerId === "number") {
            try {
                handle.setPointerCapture(event.pointerId);
            } catch (error) {
            }
        }

        resizeState = {
            type: "column",
            table,
            columnIndex,
            startX: event.clientX,
            widths,
            handle,
            pointerId: typeof event.pointerId === "number" ? event.pointerId : null,
        };
        document.body.classList.add("is-table-layout-resizing");
        document.body.dataset.tableResizeAxis = "col";
    }

    function startRowResize(event, row) {
        if (event.button !== 0) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();

        const handle = event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
        if (handle && typeof handle.setPointerCapture === "function" && typeof event.pointerId === "number") {
            try {
                handle.setPointerCapture(event.pointerId);
            } catch (error) {
            }
        }

        resizeState = {
            type: "row",
            row,
            startY: event.clientY,
            startHeight: Math.max(MIN_ROW_HEIGHT, Math.round(row.getBoundingClientRect().height)),
            handle,
            pointerId: typeof event.pointerId === "number" ? event.pointerId : null,
        };
        document.body.classList.add("is-table-layout-resizing");
        document.body.dataset.tableResizeAxis = "row";
    }

    function applyRowHeight(row, height) {
        const safeHeight = Math.max(MIN_ROW_HEIGHT, Math.round(height));
        row.style.height = `${safeHeight}px`;
        Array.from(row.cells).forEach((cell) => {
            cell.style.height = `${safeHeight}px`;
        });
    }

    function resetRowHeight(row) {
        row.style.height = "";
        Array.from(row.cells).forEach((cell) => {
            cell.style.height = "";
        });
    }

    function rebuildColumnHandles(table) {
        const row = getReferenceRow(table);
        if (!row) {
            return;
        }

        Array.from(row.cells).forEach((cell, index) => {
            ensureRelativeCell(cell);
            cell.querySelectorAll(`:scope > .${COL_HANDLE_CLASS}`).forEach((handle) => handle.remove());

            if (!supportsColumnResize(table)) {
                return;
            }

            const handle = createHandle(COL_HANDLE_CLASS, `Ubah lebar kolom ${index + 1}`);
            handle.addEventListener("pointerdown", (event) => {
                startColumnResize(event, table, index);
            });
            handle.addEventListener("dblclick", (event) => {
                event.preventDefault();
                clearManualLayout(table);
            });
            cell.appendChild(handle);
        });
    }

    function rebuildRowHandles(table) {
        Array.from(table.rows).forEach((row, rowIndex) => {
            const firstCell = row.cells[0];
            if (!firstCell) {
                return;
            }

            ensureRelativeCell(firstCell);
            firstCell.querySelectorAll(`:scope > .${ROW_HANDLE_CLASS}`).forEach((handle) => handle.remove());

            const handle = createHandle(ROW_HANDLE_CLASS, `Ubah tinggi baris ${rowIndex + 1}`);
            handle.addEventListener("pointerdown", (event) => {
                startRowResize(event, row);
            });
            handle.addEventListener("dblclick", (event) => {
                event.preventDefault();
                resetRowHeight(row);
            });
            firstCell.appendChild(handle);
        });
    }

    function hydrateTable(table) {
        if (!shouldManageTable(table)) {
            return;
        }

        table.classList.add(TABLE_CLASS);
        getLayoutId(table);
        restoreStoredWidths(table);

        const signature = [
            table.rows.length,
            getColumnCount(table),
            supportsColumnResize(table) ? "cols" : "rows",
        ].join(":");

        const expectedRowHandles = Array.from(table.rows).filter((row) => row.cells.length).length;
        const currentRowHandles = table.querySelectorAll(`.${ROW_HANDLE_CLASS}`).length;
        const currentColHandles = table.querySelectorAll(`.${COL_HANDLE_CLASS}`).length;
        const expectedColHandles = supportsColumnResize(table) ? getColumnCount(table) : 0;

        if (
            table.dataset.tableLayoutSignature === signature &&
            currentRowHandles === expectedRowHandles &&
            currentColHandles === expectedColHandles
        ) {
            return;
        }

        table.dataset.tableLayoutSignature = signature;
        rebuildColumnHandles(table);
        rebuildRowHandles(table);
    }

    function initManagedTables(root = document) {
        getManagedTables(root).forEach(hydrateTable);
    }

    function queueInitManagedTables() {
        if (initFrame) {
            return;
        }
        initFrame = window.requestAnimationFrame(() => {
            initFrame = 0;
            initManagedTables(document);
        });
    }

    function handlePointerMove(event) {
        if (!resizeState) {
            return;
        }
        if (resizeState.pointerId !== null && typeof event.pointerId === "number" && event.pointerId !== resizeState.pointerId) {
            return;
        }

        if (resizeState.type === "column") {
            const delta = event.clientX - resizeState.startX;
            const nextWidths = resizeState.widths.slice();
            nextWidths[resizeState.columnIndex] = Math.max(MIN_COL_WIDTH, resizeState.widths[resizeState.columnIndex] + delta);
            applyStoredWidths(resizeState.table, nextWidths, false);
            return;
        }

        const deltaY = event.clientY - resizeState.startY;
        applyRowHeight(resizeState.row, resizeState.startHeight + deltaY);
    }

    function stopResize(event) {
        if (!resizeState) {
            return;
        }
        if (resizeState.pointerId !== null && event && typeof event.pointerId === "number" && event.pointerId !== resizeState.pointerId) {
            return;
        }

        if (resizeState.type === "column") {
            const widths = getColElements(resizeState.table).map((col, index) => {
                const rawWidth = parseFloat(col.style.width);
                return Number.isFinite(rawWidth) && rawWidth > 0
                    ? Math.round(rawWidth)
                    : measureCurrentColumnWidths(resizeState.table)[index] || MIN_COL_WIDTH;
            });
            writeStoredLayout(resizeState.table, widths);
        }

        if (resizeState.handle && typeof resizeState.handle.releasePointerCapture === "function" && resizeState.pointerId !== null) {
            try {
                resizeState.handle.releasePointerCapture(resizeState.pointerId);
            } catch (error) {
            }
        }

        resizeState = null;
        document.body.classList.remove("is-table-layout-resizing");
        delete document.body.dataset.tableResizeAxis;
        if (typeof window.updateScrollableTableHints === "function") {
            window.updateScrollableTableHints();
        }
    }

    function bootstrap() {
        initManagedTables(document);

        const observer = new MutationObserver(() => {
            queueInitManagedTables();
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        document.addEventListener("pointermove", handlePointerMove, { passive: true });
        document.addEventListener("pointerup", stopResize);
        document.addEventListener("pointercancel", stopResize);
        window.addEventListener("blur", stopResize);
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") {
                stopResize();
            }
        });
        window.addEventListener("resize", queueInitManagedTables);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
    } else {
        bootstrap();
    }
})();
