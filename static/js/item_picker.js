(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    window.createItemPicker = function createItemPicker(options) {
        const modal = document.getElementById(options.modalId);
        if (!modal) {
            throw new Error("Item picker modal not found.");
        }

        const body = document.getElementById(options.bodyId);
        const searchInput = document.getElementById(options.searchId);
        const summary = document.getElementById(options.summaryId);
        const pageLabel = document.getElementById(options.pageId);
        const warehouseLabel = document.getElementById(options.warehouseIdLabel);
        const prevButton = document.getElementById(options.prevButtonId);
        const nextButton = document.getElementById(options.nextButtonId);
        const searchForm = modal.querySelector("[data-picker-search-form]");

        let activeRow = null;
        let currentPage = 1;
        let totalPages = 1;
        let currentItems = [];

        function getWarehouseLabel() {
            if (typeof options.getWarehouseLabel === "function") {
                return options.getWarehouseLabel() || options.getWarehouseId() || "-";
            }
            return options.getWarehouseId() || "-";
        }

        function setLoading(message) {
            body.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="empty-state picker-inline-state">${escapeHtml(message)}</div>
                    </td>
                </tr>
            `;
        }

        function renderRows(items) {
            currentItems = items;
            if (!items.length) {
                setLoading("Barang tidak ditemukan.");
                return;
            }

            body.innerHTML = items.map((item, index) => `
                <tr>
                    <td class="mono">${escapeHtml(item.sku)}</td>
                    <td class="mono">${escapeHtml(item.gtin || "-")}</td>
                    <td>${escapeHtml(item.name)}</td>
                    <td>${escapeHtml(item.variant_label)}</td>
                    <td><span class="badge ${item.qty <= 0 ? "red" : item.qty < 5 ? "orange" : "green"}">${escapeHtml(item.qty)}</span></td>
                    <td>${escapeHtml(item.category || "-")}</td>
                    <td>
                        <button type="button" class="ghost-button picker-choose-button" data-picker-index="${index}">Pilih</button>
                    </td>
                </tr>
            `).join("");
        }

        async function loadPage(page) {
            currentPage = page;
            setLoading("Memuat daftar barang...");
            summary.textContent = "Memuat daftar barang...";
            pageLabel.textContent = "Page ...";
            warehouseLabel.textContent = `Gudang ${getWarehouseLabel()}`;
            prevButton.disabled = true;
            nextButton.disabled = true;

            const params = new URLSearchParams({
                page: String(page),
                q: (searchInput?.value || "").trim(),
                warehouse_id: String(options.getWarehouseId() || ""),
                mode: options.mode || "",
            });

            try {
                const response = await fetch(`${options.endpoint}?${params.toString()}`);
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || "Gagal memuat barang.");
                }

                totalPages = data.total_pages || 1;
                renderRows(data.items || []);
                summary.textContent = `Total barang ditemukan: ${data.total_items || 0}`;
                pageLabel.textContent = `Page ${data.page || 1} / ${totalPages}`;
                warehouseLabel.textContent = `Gudang ${getWarehouseLabel()}`;
                prevButton.disabled = (data.page || 1) <= 1;
                nextButton.disabled = (data.page || 1) >= totalPages;
            } catch (error) {
                setLoading("Gagal memuat daftar barang.");
                summary.textContent = error.message || "Gagal memuat daftar barang.";
                pageLabel.textContent = "Page 1 / 1";
                warehouseLabel.textContent = `Gudang ${getWarehouseLabel()}`;
                prevButton.disabled = true;
                nextButton.disabled = true;
            }
        }

        function openForRow(row) {
            activeRow = row;
            modal.hidden = false;
            document.body.classList.add("picker-open");
            loadPage(1);
        }

        function close() {
            modal.hidden = true;
            document.body.classList.remove("picker-open");
            activeRow = null;
        }

        body.addEventListener("click", (event) => {
            const button = event.target.closest("[data-picker-index]");
            if (!button || !activeRow) return;

            const index = Number(button.dataset.pickerIndex);
            const item = currentItems[index];
            if (!item) return;

            options.onPick(activeRow, item);
            close();
        });

        prevButton.addEventListener("click", () => {
            if (currentPage > 1) {
                loadPage(currentPage - 1);
            }
        });

        nextButton.addEventListener("click", () => {
            if (currentPage < totalPages) {
                loadPage(currentPage + 1);
            }
        });

        searchForm?.addEventListener("submit", (event) => {
            event.preventDefault();
            loadPage(1);
        });

        modal.querySelectorAll("[data-picker-close], [data-picker-backdrop]").forEach((node) => {
            node.addEventListener("click", close);
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !modal.hidden) {
                close();
            }
        });

        return {
            close,
            openForRow,
            refresh() {
                if (!modal.hidden) {
                    loadPage(currentPage);
                }
            },
        };
    };
})();
