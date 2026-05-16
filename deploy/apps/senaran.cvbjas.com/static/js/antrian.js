(function () {
    function initAntrianPage() {
    const details = document.getElementById("racket-details");
    const countInput = document.getElementById("racket_count");
    const serviceSelect = document.getElementById("service_type");
    const scheduleDate = document.getElementById("schedule_date");
    const scheduleTime = document.getElementById("schedule_time");
    const scheduleTimeDisplay = document.getElementById("schedule_time_display");
    const slotPreview = document.getElementById("form-slot-preview");
    const slotStatusLabel = document.getElementById("slot-status-label");
    const slotStatusCaption = document.getElementById("slot-status-caption");
    const expressSelect = document.getElementById("is_express");

    function escapeHtml(value) {
        return String(value || "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function optionList(options, selectedValue) {
        return options
            .map((item) => {
                const selected = item === selectedValue ? "selected" : "";
                return `<option value="${escapeHtml(item)}" ${selected}>${escapeHtml(item)}</option>`;
            })
            .join("");
    }

    function racketTypeForService() {
        if (!serviceSelect || !serviceSelect.value) {
            return "Pilih layanan dulu";
        }
        return serviceSelect.value === "Stringing Tenis" ? "Tenis" : "Badminton";
    }

    function getExistingItem(number) {
        const items = window.ticketItemValues || [];
        return items.find((item) => Number(item.item_number) === number) || {};
    }

    function syncCurrentItems() {
        if (!details) {
            return;
        }
        const max = Number(window.racketFormOptions?.maxRacketCount || 6);
        const items = [];
        for (let number = 1; number <= max; number += 1) {
            const brand = document.getElementById(`racket_brand_${number}`);
            if (!brand) {
                continue;
            }
            items.push({
                item_number: number,
                racket_brand: brand.value,
                string_type: document.getElementById(`string_type_${number}`)?.value || "",
                tension_lbs: document.getElementById(`tension_lbs_${number}`)?.value || "",
                knot_type: document.getElementById(`knot_type_${number}`)?.value || "",
                variation: document.getElementById(`variation_${number}`)?.value || "",
                grommet: document.getElementById(`grommet_${number}`)?.value || "Tidak",
                racket_note: document.getElementById(`racket_note_${number}`)?.value || "",
            });
        }
        window.ticketItemValues = items;
    }

    function clampCount(value) {
        const max = Number(window.racketFormOptions?.maxRacketCount || 6);
        const parsed = Number.parseInt(value || "1", 10);
        if (Number.isNaN(parsed)) {
            return 1;
        }
        return Math.min(Math.max(parsed, 1), max);
    }

    function renderRacketDetails() {
        if (!details || !countInput) {
            return;
        }

        const count = clampCount(countInput.value);
        if (String(countInput.value) !== String(count)) {
            countInput.value = String(count);
        }

        const racketType = racketTypeForService();
        const knotTypes = window.racketFormOptions?.knotTypes || ["S-2", "S-4"];
        const variations = window.racketFormOptions?.variations || ["Full", "L-1", "L-2", "Custom"];
        const grommetOptions = window.racketFormOptions?.grommetOptions || ["Tidak", "Ya"];
        let html = "";

        details.classList.toggle("single-racket", count === 1);

        for (let number = 1; number <= count; number += 1) {
            const item = getExistingItem(number);
            html += `
                <article class="racket-card compact-racket-card">
                    <div class="racket-card-title">
                        <span>Raket ${number}</span>
                        <strong>${escapeHtml(racketType)}</strong>
                    </div>
                    <div class="racket-item-grid racket-detail-compact-grid racket-item-grid-top">
                        <div class="racket-field racket-field-brand">
                            <label class="form-label" for="racket_brand_${number}">Merk/Seri</label>
                            <input class="form-control" id="racket_brand_${number}" name="racket_brand_${number}" value="${escapeHtml(item.racket_brand)}" placeholder="Contoh: Yonex Astrox 88D" required>
                        </div>
                        <div class="racket-field racket-field-string">
                            <label class="form-label" for="string_type_${number}">Jenis Senar</label>
                            <input class="form-control" id="string_type_${number}" name="string_type_${number}" value="${escapeHtml(item.string_type)}" placeholder="Contoh: BG66 Ultimax" required>
                        </div>
                        <div class="racket-field racket-field-tension">
                            <label class="form-label" for="tension_lbs_${number}">Tarikan</label>
                            <input class="form-control" id="tension_lbs_${number}" name="tension_lbs_${number}" value="${escapeHtml(item.tension_lbs)}" placeholder="26" required>
                        </div>
                        <div class="racket-field racket-field-knot">
                            <label class="form-label" for="knot_type_${number}">Simpul</label>
                            <select class="form-select" id="knot_type_${number}" name="knot_type_${number}" required>
                                <option value="">Pilih</option>
                                ${optionList(knotTypes, item.knot_type)}
                            </select>
                        </div>
                    </div>
                    <div class="racket-item-grid racket-detail-compact-grid racket-item-grid-bottom">
                        <div class="racket-field racket-field-variation">
                            <label class="form-label" for="variation_${number}">Variasi</label>
                            <select class="form-select" id="variation_${number}" name="variation_${number}" required>
                                <option value="">Pilih</option>
                                ${optionList(variations, item.variation)}
                            </select>
                        </div>
                        <div class="racket-field racket-field-grommet">
                            <label class="form-label" for="grommet_${number}">Mata Ayam</label>
                            <select class="form-select" id="grommet_${number}" name="grommet_${number}">
                                ${optionList(grommetOptions, item.grommet || "Tidak")}
                            </select>
                        </div>
                        <div class="racket-field racket-field-note">
                            <label class="form-label" for="racket_note_${number}">Catatan Raket</label>
                            <input class="form-control" id="racket_note_${number}" name="racket_note_${number}" value="${escapeHtml(item.racket_note)}" placeholder="Catatan khusus raket">
                        </div>
                    </div>
                </article>
            `;
        }

        details.innerHTML = html;
    }

    function updateSlotSummary(slotTime, label, caption) {
        if (scheduleTimeDisplay) {
            scheduleTimeDisplay.value = slotTime || "Pilih dari slot di bawah";
        }
        if (slotStatusLabel) {
            slotStatusLabel.textContent = slotTime || "-";
        }
        if (slotStatusCaption) {
            slotStatusCaption.textContent = label && caption ? `${label} - ${caption}` : "Pilih jam dari board slot";
        }
    }

    function applySlotSelection(slotTime, label, caption) {
        if (!scheduleTime) {
            return;
        }
        scheduleTime.value = slotTime || "";
        updateSlotSummary(slotTime, label, caption);

        slotPreview?.querySelectorAll(".slot-picker").forEach((button) => {
            button.classList.toggle("is-selected", button.getAttribute("data-slot-time") === slotTime);
        });
    }

    function bindSlotPickerEvents() {
        slotPreview?.querySelectorAll(".slot-picker:not([disabled])").forEach((button) => {
            button.addEventListener("click", () => {
                applySlotSelection(
                    button.getAttribute("data-slot-time") || "",
                    button.getAttribute("data-slot-label") || "",
                    button.getAttribute("data-slot-caption") || ""
                );
            });
        });
    }

    function renderSlotPreview(slots) {
        if (!slotPreview) {
            return;
        }

        const selected = scheduleTime?.value || "";
        slotPreview.innerHTML = slots
            .map((slot) => {
                const state = slot.unavailable ? "is-unavailable" : slot.available ? "is-available" : "is-full";
                const selectedClass = selected === slot.time ? "is-selected" : "";
                const disabled = slot.available ? "" : "disabled";
                return `
                    <button
                        class="schedule-slot slot-picker ${state} ${selectedClass}"
                        type="button"
                        data-slot-time="${escapeHtml(slot.time)}"
                        data-slot-label="${escapeHtml(slot.label)}"
                        data-slot-caption="${escapeHtml(`${slot.used}/${slot.capacity} raket`)}"
                        ${disabled}>
                        <div class="slot-time">${escapeHtml(slot.time)}</div>
                        <div class="slot-usage">${escapeHtml(slot.used)}/${escapeHtml(slot.capacity)} raket</div>
                        <span class="slot-label">${escapeHtml(slot.label)}</span>
                    </button>
                `;
            })
            .join("");

        const selectedButton = slotPreview.querySelector(".slot-picker.is-selected:not([disabled])");
        if (!selectedButton && scheduleTime) {
            scheduleTime.value = "";
        }
        if (selectedButton) {
            updateSlotSummary(
                selectedButton.getAttribute("data-slot-time") || "",
                selectedButton.getAttribute("data-slot-label") || "",
                selectedButton.getAttribute("data-slot-caption") || ""
            );
        } else {
            updateSlotSummary("", "", "");
        }

        bindSlotPickerEvents();
    }

    async function refreshScheduleSlots() {
        if (!scheduleDate || !scheduleDate.value) {
            return;
        }
        try {
            const expressParam = expressSelect?.value === "1" ? "&express=1" : "";
            const response = await fetch(`/api/schedule-slots?date=${encodeURIComponent(scheduleDate.value)}${expressParam}`, {
                headers: { "Accept": "application/json" },
                cache: "no-store",
            });
            if (!response.ok) {
                throw new Error("Gagal memuat slot");
            }
            const payload = await response.json();
            renderSlotPreview(payload.schedule_slots || []);
        } catch (error) {
            console.warn(error.message);
        }
    }

    if (details) {
        renderRacketDetails();
        bindSlotPickerEvents();
        updateSlotSummary(scheduleTime?.value || "", "", "");
        countInput?.addEventListener("change", () => {
            syncCurrentItems();
            renderRacketDetails();
        });
        serviceSelect?.addEventListener("change", () => {
            syncCurrentItems();
            renderRacketDetails();
        });
        scheduleDate?.addEventListener("change", refreshScheduleSlots);
        expressSelect?.addEventListener("change", refreshScheduleSlots);

        const initiallySelected = slotPreview?.querySelector(".slot-picker.is-selected");
        if (initiallySelected) {
            updateSlotSummary(
                initiallySelected.getAttribute("data-slot-time") || "",
                initiallySelected.getAttribute("data-slot-label") || "",
                initiallySelected.getAttribute("data-slot-caption") || ""
            );
        }
    }

    document.querySelectorAll("[data-confirm-status]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const status = form.getAttribute("data-confirm-status");
            if (!window.confirm(`Ubah status antrian menjadi ${status}?`)) {
                event.preventDefault();
            }
        });
    });

    function compareMixed(a, b) {
        const aText = String(a || "").trim();
        const bText = String(b || "").trim();
        const aNumber = Number(aText);
        const bNumber = Number(bText);

        if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber) && aText !== "" && bText !== "") {
            return aNumber - bNumber;
        }

        return aText.localeCompare(bText, "id", { numeric: true, sensitivity: "base" });
    }

    function compareValues(a, b, type) {
        if (type === "number") {
            return Number(a || 0) - Number(b || 0);
        }
        if (type === "time") {
            return String(a || "").localeCompare(String(b || ""), "id", { numeric: true, sensitivity: "base" });
        }
        if (type === "mixed") {
            return compareMixed(a, b);
        }
        return String(a || "").localeCompare(String(b || ""), "id", { numeric: true, sensitivity: "base" });
    }

    const antrianTable = document.querySelector(".antrian-table");
    if (antrianTable) {
        const tbody = antrianTable.querySelector("tbody");
        const sortButtons = antrianTable.querySelectorAll(".table-sort-button");
        const sortColumnMap = {
            "queue-number": 0,
            customer: 1,
            phone: 2,
            service: 3,
            racket: 4,
            "estimated-time": 5,
            stringer: 6,
            status: 7,
            express: 8,
        };

        sortButtons.forEach((button) => {
            button.addEventListener("click", () => {
                if (!tbody) {
                    return;
                }
                const key = button.getAttribute("data-sort-key");
                const type = button.getAttribute("data-sort-type") || "text";
                const columnIndex = sortColumnMap[key];
                if (typeof columnIndex !== "number") {
                    return;
                }

                const currentDirection = button.getAttribute("data-sort-direction") === "asc" ? "asc" : "desc";
                const nextDirection = currentDirection === "asc" ? "desc" : "asc";
                const rows = Array.from(tbody.querySelectorAll("tr")).filter((row) => !row.querySelector(".empty-state"));

                rows.sort((rowA, rowB) => {
                    const cellA = rowA.children[columnIndex];
                    const cellB = rowB.children[columnIndex];
                    const valueA = cellA?.getAttribute("data-sort-value") ?? cellA?.textContent?.trim() ?? "";
                    const valueB = cellB?.getAttribute("data-sort-value") ?? cellB?.textContent?.trim() ?? "";
                    const result = compareValues(valueA, valueB, type);
                    return nextDirection === "asc" ? result : -result;
                });

                rows.forEach((row) => tbody.appendChild(row));

                sortButtons.forEach((item) => {
                    item.removeAttribute("data-sort-direction");
                    item.classList.remove("is-active");
                });
                button.setAttribute("data-sort-direction", nextDirection);
                button.classList.add("is-active");
            });
        });
    }

    window.setTimeout(() => {
        document.querySelectorAll(".alert").forEach((alert) => {
            if (window.bootstrap) {
                const instance = window.bootstrap.Alert.getOrCreateInstance(alert);
                instance.close();
            }
        });
    }, 4200);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAntrianPage, { once: true });
    } else {
        initAntrianPage();
    }
})();
