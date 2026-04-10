(() => {
    const config = window.stockOpnameConfig || {};
    const app = document.getElementById("stockOpnameApp");
    if (!app) {
        return;
    }

    const state = {
        currentPage: Number.parseInt(config.page || 1, 10) || 1,
        totalPages: Number.parseInt(config.totalPages || 1, 10) || 1,
        search: String(config.search || "").trim(),
        warehouseId: Number.parseInt(config.warehouseId || 0, 10) || 0,
        saving: false,
    };

    const nodes = {
        filterForm: document.getElementById("soFilterForm"),
        warehouseSelect: document.getElementById("warehouseSelect"),
        searchInput: document.getElementById("searchInput"),
        exportSoLink: document.getElementById("exportSoLink"),
        exportReportLink: document.getElementById("exportReportLink"),
        saveHeroBtn: document.getElementById("saveSoHeroBtn"),
        saveTopBtn: document.getElementById("saveSoTopBtn"),
        saveStickyBtn: document.getElementById("saveSoStickyBtn"),
        resetBtn: document.getElementById("resetSoBtn"),
        tableBody: document.getElementById("soTable"),
        table: document.getElementById("stockOpnameTable"),
        saveBar: document.getElementById("soSaveBar"),
        pendingCount: document.getElementById("soPendingCount"),
        pendingHelp: document.getElementById("soPendingHelp"),
        summaryItems: document.getElementById("soSummaryItems"),
        summaryDisplayQty: document.getElementById("soSummaryDisplayQty"),
        summaryGudangQty: document.getElementById("soSummaryGudangQty"),
        summaryTotalQty: document.getElementById("soSummaryTotalQty"),
        summaryGapCount: document.getElementById("soSummaryGapCount"),
        summaryGapCard: document.getElementById("soSummaryGapCard"),
        pageInfo: document.getElementById("pageInfo"),
        metaPage: document.getElementById("soMetaPage"),
        warehouseName: document.getElementById("soWarehouseName"),
        prevBtn: document.getElementById("prevBtn"),
        nextBtn: document.getElementById("nextBtn"),
    };

    const messages = {
        loadError: config.messages?.loadError || "Gagal memuat data stock opname.",
        saveError: config.messages?.saveError || "Gagal menyimpan stock opname.",
        saveSuccess: config.messages?.saveSuccess || "SO berhasil disimpan.",
        emptyChanges: config.messages?.emptyChanges || "Tidak ada perubahan yang perlu disimpan.",
        invalidInput: config.messages?.invalidInput || "Cek lagi input stok fisik.",
        confirmPageChange: config.messages?.confirmPageChange || "Perubahan belum disimpan. Tetap pindah halaman?",
        confirmFilterChange: config.messages?.confirmFilterChange || "Perubahan belum disimpan. Tetap ganti filter?",
    };

    function notify(text, isError = false) {
        if (!text) {
            return;
        }
        if (typeof window.showToast === "function") {
            window.showToast(text);
            return;
        }
        if (isError) {
            window.alert(text);
        }
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    async function readResponsePayload(response) {
        const rawText = await response.text();
        let payload = {};

        try {
            payload = rawText ? JSON.parse(rawText) : {};
        } catch (error) {
            payload = {};
        }

        return { payload, rawText };
    }

    function extractServerMessage(payload, rawText, fallbackMessage) {
        const payloadMessage = payload?.error || payload?.message;
        if (payloadMessage) {
            return String(payloadMessage);
        }

        const cleanedText = String(rawText || "")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim();
        return cleanedText ? cleanedText.slice(0, 220) : fallbackMessage;
    }

    function readInt(rawValue, fallback = null) {
        const value = Number.parseInt(String(rawValue ?? "").trim(), 10);
        return Number.isNaN(value) ? fallback : value;
    }

    function parseInputValue(input) {
        const raw = String(input?.value ?? "").trim();
        if (!raw) {
            return null;
        }
        const value = Number.parseInt(raw, 10);
        if (Number.isNaN(value)) {
            return null;
        }
        return value;
    }

    function getRows() {
        return Array.from(nodes.tableBody?.querySelectorAll("tr[data-row='item']") || []);
    }

    function buildQuery(extra = {}) {
        const params = new URLSearchParams();
        const nextPage = readInt(extra.page, state.currentPage) || 1;
        params.set("page", String(nextPage));
        params.set("warehouse", String(state.warehouseId || 0));
        if (state.search) {
            params.set("q", state.search);
        }
        return params.toString();
    }

    function syncExportLinks() {
        const exportQuery = new URLSearchParams();
        exportQuery.set("warehouse", String(state.warehouseId || 0));
        if (state.search) {
            exportQuery.set("q", state.search);
        }
        if (nodes.exportSoLink) {
            nodes.exportSoLink.href = `${config.exportUrl || "/so/export"}?${exportQuery.toString()}`;
        }
        if (nodes.exportReportLink) {
            nodes.exportReportLink.href = `${config.reportUrl || "/so/export_report"}?${exportQuery.toString()}`;
        }
    }

    function renderSummary(summary) {
        if (!summary) {
            return;
        }
        if (nodes.summaryItems) {
            nodes.summaryItems.innerText = summary.items ?? 0;
        }
        if (nodes.summaryDisplayQty) {
            nodes.summaryDisplayQty.innerText = summary.display_qty ?? 0;
        }
        if (nodes.summaryGudangQty) {
            nodes.summaryGudangQty.innerText = summary.gudang_qty ?? 0;
        }
        if (nodes.summaryTotalQty) {
            nodes.summaryTotalQty.innerText = summary.total_qty ?? 0;
        }
        if (nodes.summaryGapCount) {
            nodes.summaryGapCount.innerText = summary.gap_count ?? 0;
        }
    }

    function syncSelectors() {
        if (nodes.warehouseSelect) {
            nodes.warehouseSelect.value = String(state.warehouseId || "");
        }
        if (nodes.searchInput) {
            nodes.searchInput.value = state.search;
        }
    }

    function updatePagination() {
        if (nodes.pageInfo) {
            nodes.pageInfo.innerText = `Halaman ${state.currentPage} / ${state.totalPages}`;
        }
        if (nodes.metaPage) {
            nodes.metaPage.innerText = `${state.currentPage} / ${state.totalPages}`;
        }
        if (nodes.prevBtn) {
            nodes.prevBtn.disabled = state.currentPage <= 1;
        }
        if (nodes.nextBtn) {
            nodes.nextBtn.disabled = state.currentPage >= state.totalPages;
        }
    }

    function setDiffState(cell, diff) {
        if (!cell) {
            return;
        }
        const nextValue = diff > 0 ? `+${diff}` : String(diff || 0);
        const nextState = diff > 0 ? "up" : diff < 0 ? "down" : "zero";
        cell.innerText = nextValue;
        cell.dataset.state = nextState;
        cell.className = `mono stock-opname-diff-cell ${diff > 0 ? "green" : diff < 0 ? "red" : ""}`.trim();
    }

    function readRowSnapshot(row) {
        const productId = readInt(row.dataset.productId);
        const variantId = readInt(row.dataset.variantId);
        const displaySystem = readInt(row.querySelector(".display")?.textContent, 0) || 0;
        const gudangSystem = readInt(row.querySelector(".gudang")?.textContent, 0) || 0;
        const displayPhysical = parseInputValue(row.querySelector(".physical_display"));
        const gudangPhysical = parseInputValue(row.querySelector(".physical_gudang"));
        const displayDiff = (displayPhysical ?? displaySystem) - displaySystem;
        const gudangDiff = (gudangPhysical ?? gudangSystem) - gudangSystem;
        const invalid = (
            displayPhysical === null ||
            gudangPhysical === null ||
            displayPhysical < 0 ||
            gudangPhysical < 0
        );
        const hasChanges = !invalid && (displayDiff !== 0 || gudangDiff !== 0);

        return {
            row,
            productId,
            variantId,
            displaySystem,
            gudangSystem,
            displayPhysical,
            gudangPhysical,
            displayDiff,
            gudangDiff,
            invalid,
            hasChanges,
        };
    }

    function syncRow(row) {
        const snapshot = readRowSnapshot(row);
        setDiffState(row.querySelector(".diff_display"), snapshot.displayDiff);
        setDiffState(row.querySelector(".diff_gudang"), snapshot.gudangDiff);
        row.classList.toggle("is-dirty", snapshot.hasChanges);
        row.classList.toggle("is-invalid", snapshot.invalid);
        return snapshot;
    }

    function collectPendingItems() {
        const items = [];
        let invalid = false;

        getRows().forEach((row) => {
            const snapshot = syncRow(row);
            if (snapshot.invalid) {
                invalid = true;
                return;
            }
            if (!snapshot.hasChanges) {
                return;
            }
            items.push({
                product_id: snapshot.productId,
                variant_id: snapshot.variantId,
                display_system: snapshot.displaySystem,
                display_physical: snapshot.displayPhysical,
                gudang_system: snapshot.gudangSystem,
                gudang_physical: snapshot.gudangPhysical,
            });
        });

        return { items, invalid };
    }

    function updateSaveState() {
        const pending = collectPendingItems();
        const hasChanges = pending.items.length > 0;
        const disabled = state.saving || pending.invalid || !hasChanges;

        if (nodes.pendingCount) {
            nodes.pendingCount.innerText = pending.invalid
                ? "Input belum valid"
                : `${pending.items.length} perubahan`;
        }
        if (nodes.pendingHelp) {
            nodes.pendingHelp.innerText = pending.invalid
                ? messages.invalidInput
                : hasChanges
                    ? "Perubahan di halaman ini siap disimpan ke hasil stock opname toko ini."
                    : "Belum ada perubahan fisik yang perlu disimpan.";
        }
        if (nodes.saveBar) {
            nodes.saveBar.dataset.state = pending.invalid ? "invalid" : hasChanges ? "dirty" : "clean";
        }

        [nodes.saveHeroBtn, nodes.saveTopBtn, nodes.saveStickyBtn].forEach((button) => {
            if (button) {
                button.disabled = disabled;
            }
        });
        if (nodes.resetBtn) {
            nodes.resetBtn.disabled = state.saving || !hasChanges;
        }

        return pending;
    }

    function buildRowMarkup(item) {
        const displayQty = readInt(item.display_qty, 0) || 0;
        const gudangQty = readInt(item.gudang_qty, 0) || 0;
        return `
            <tr data-row="item" data-product-id="${readInt(item.product_id, 0) || 0}" data-variant-id="${readInt(item.variant_id, 0) || 0}">
                <td class="mono">${escapeHtml(item.sku)}</td>
                <td class="stock-opname-product-cell">
                    <strong>${escapeHtml(item.name)}</strong>
                    <small>Bandingkan fisik per variant aktif.</small>
                </td>
                <td>${escapeHtml(item.variant)}</td>
                <td class="display stock-opname-system-cell">${displayQty}</td>
                <td class="stock-opname-input-cell">
                    <input type="number" min="0" inputmode="numeric" class="physical_display" value="${displayQty}">
                </td>
                <td class="diff_display mono stock-opname-diff-cell" data-state="zero">0</td>
                <td class="gudang stock-opname-system-cell">${gudangQty}</td>
                <td class="stock-opname-input-cell">
                    <input type="number" min="0" inputmode="numeric" class="physical_gudang" value="${gudangQty}">
                </td>
                <td class="diff_gudang mono stock-opname-diff-cell" data-state="zero">0</td>
            </tr>
        `.trim();
    }

    function bindRowInputs() {
        getRows().forEach((row) => {
            row.querySelectorAll(".physical_display, .physical_gudang").forEach((input) => {
                input.addEventListener("input", updateSaveState);
                input.addEventListener("change", updateSaveState);
            });
            syncRow(row);
        });
        updateSaveState();
        window.updateScrollableTableHints?.();
    }

    function renderTable(rows) {
        if (!nodes.tableBody) {
            return;
        }

        if (!rows.length) {
            nodes.tableBody.innerHTML = "<tr class=\"so-empty-row\"><td colspan=\"9\" class=\"empty-state\">Tidak ada item yang cocok untuk stock opname saat ini.</td></tr>";
            updateSaveState();
            window.updateScrollableTableHints?.();
            return;
        }

        nodes.tableBody.innerHTML = rows.map(buildRowMarkup).join("");
        bindRowInputs();
    }

    function applyPayload(payload) {
        if (!payload) {
            return;
        }

        state.currentPage = readInt(payload.page, state.currentPage) || 1;
        state.totalPages = readInt(payload.total_pages, state.totalPages) || 1;
        state.warehouseId = readInt(payload.warehouse_id, state.warehouseId)
            || readInt(payload.display_id, state.warehouseId)
            || state.warehouseId;
        state.search = String(payload.search ?? state.search).trim();

        renderTable(payload.data || []);
        renderSummary(payload.summary || {});
        syncSelectors();
        syncExportLinks();
        updatePagination();

        if (nodes.warehouseName && payload.warehouse_name) {
            nodes.warehouseName.innerText = payload.warehouse_name;
        }
    }

    async function loadPage(page) {
        const response = await fetch(`${config.listUrl || "/so"}?${buildQuery({ page })}`, {
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            credentials: "same-origin",
        });
        const { payload, rawText } = await readResponsePayload(response);
        if (!response.ok) {
            throw new Error(extractServerMessage(payload, rawText, messages.loadError));
        }
        if (!payload || typeof payload !== "object") {
            throw new Error(messages.loadError);
        }
        applyPayload(payload);
    }

    function hasUnsavedChanges() {
        const pending = collectPendingItems();
        return pending.invalid || pending.items.length > 0;
    }

    async function changePage(delta) {
        const nextPage = state.currentPage + delta;
        if (nextPage < 1 || nextPage > state.totalPages) {
            return;
        }

        if (hasUnsavedChanges() && !window.confirm(messages.confirmPageChange)) {
            return;
        }

        try {
            await loadPage(nextPage);
        } catch (error) {
            notify(error.message || messages.loadError, true);
        }
    }

    function resetInputs() {
        getRows().forEach((row) => {
            const displaySystem = readInt(row.querySelector(".display")?.textContent, 0) || 0;
            const gudangSystem = readInt(row.querySelector(".gudang")?.textContent, 0) || 0;
            const displayInput = row.querySelector(".physical_display");
            const gudangInput = row.querySelector(".physical_gudang");
            if (displayInput) {
                displayInput.value = String(displaySystem);
            }
            if (gudangInput) {
                gudangInput.value = String(gudangSystem);
            }
        });
        updateSaveState();
    }

    async function submitSO() {
        const pending = updateSaveState();

        if (pending.invalid) {
            notify(messages.invalidInput, true);
            return;
        }

        if (!pending.items.length) {
            notify(messages.emptyChanges, true);
            return;
        }

        state.saving = true;
        updateSaveState();

        try {
            const response = await fetch(config.submitUrl || "/so/submit", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
                body: JSON.stringify({
                    warehouse_id: state.warehouseId,
                    q: state.search,
                    page: state.currentPage,
                    items: pending.items,
                }),
            });

            const { payload, rawText } = await readResponsePayload(response);
            if (!response.ok) {
                throw new Error(extractServerMessage(payload, rawText, messages.saveError));
            }
            if (!payload || typeof payload !== "object") {
                throw new Error(messages.saveError);
            }

            applyPayload(payload);
            notify(payload.message || messages.saveSuccess);
        } catch (error) {
            notify(error.message || messages.saveError, true);
        } finally {
            state.saving = false;
            updateSaveState();
        }
    }

    function handleFilterSubmit(event) {
        state.search = String(nodes.searchInput?.value || "").trim();
        state.warehouseId = readInt(nodes.warehouseSelect?.value, state.warehouseId) || state.warehouseId;
        syncExportLinks();
        if (hasUnsavedChanges() && !window.confirm(messages.confirmFilterChange)) {
            event.preventDefault();
        }
    }

    function attachEvents() {
        nodes.saveHeroBtn?.addEventListener("click", submitSO);
        nodes.saveTopBtn?.addEventListener("click", submitSO);
        nodes.saveStickyBtn?.addEventListener("click", submitSO);
        nodes.resetBtn?.addEventListener("click", resetInputs);
        nodes.prevBtn?.addEventListener("click", () => changePage(-1));
        nodes.nextBtn?.addEventListener("click", () => changePage(1));

        nodes.warehouseSelect?.addEventListener("change", () => {
            state.warehouseId = readInt(nodes.warehouseSelect?.value, state.warehouseId) || state.warehouseId;
            syncExportLinks();
        });
        nodes.searchInput?.addEventListener("input", () => {
            state.search = String(nodes.searchInput?.value || "").trim();
            syncExportLinks();
        });
        nodes.searchInput?.addEventListener("change", () => {
            state.search = String(nodes.searchInput?.value || "").trim();
            syncExportLinks();
        });
        nodes.filterForm?.addEventListener("submit", handleFilterSubmit);
    }

    syncSelectors();
    syncExportLinks();
    updatePagination();
    bindRowInputs();
    attachEvents();

    window.submitSO = submitSO;
    window.changePage = changePage;
    window.resetSOInputs = resetInputs;
})();
