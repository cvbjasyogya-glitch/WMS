(function () {
    const slotList = document.getElementById("monitor-slot-list");
    const waitingProcessList = document.getElementById("waiting-process-list");
    const inProcessList = document.getElementById("in-process-list");
    const completedList = document.getElementById("completed-list");
    const waitingProcessCount = document.getElementById("waiting-process-count");
    const inProcessCount = document.getElementById("in-process-count");
    const completedCount = document.getElementById("completed-count");
    const updated = document.getElementById("monitor-updated");
    const dateEl = document.getElementById("monitor-date");
    const timeEl = document.getElementById("monitor-time");
    const scheduleDateInput = document.getElementById("schedule-date-input");
    const previousButton = document.getElementById("schedule-prev");
    const nextButton = document.getElementById("schedule-next");
    const todayButton = document.getElementById("schedule-today");
    const scheduleDateLabel = document.getElementById("schedule-date-label");
    const scheduleToolbar = document.querySelector(".schedule-toolbar");
    const autoDayToggle = document.getElementById("schedule-auto-day");
    let lastComparablePayload = "";
    let lastScheduleSnapshot = "";
    let lastWaitingSnapshot = "";
    let lastInProcessSnapshot = "";
    let lastCompletedSnapshot = "";
    let lastUpdatedValue = "";
    let lastRenderedDate = "";
    let autoDayEnabled = true;
    let autoDayIntervalId = null;

    function pad(value) {
        return String(value).padStart(2, "0");
    }

    function toIsoDate(date) {
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    }

    function parseLocalDate(value) {
        const parts = String(value || "").split("-").map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) {
            return new Date();
        }
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    function addDays(value, amount) {
        const date = parseLocalDate(value);
        date.setDate(date.getDate() + amount);
        return toIsoDate(date);
    }

    const displayToday = toIsoDate(new Date());
    const displayTomorrow = addDays(displayToday, 1);
    const displayMinDate = addDays(displayToday, -1);
    const displayMaxDate = addDays(displayToday, 3);

    function clampDate(value) {
        const candidate = parseLocalDate(value);
        const minDate = parseLocalDate(displayMinDate);
        const maxDate = parseLocalDate(displayMaxDate);
        if (candidate < minDate) {
            return displayMinDate;
        }
        if (candidate > maxDate) {
            return displayMaxDate;
        }
        return toIsoDate(candidate);
    }

    let selectedDate = clampDate(displayToday);

    function setClock() {
        const now = new Date();
        dateEl.textContent = now.toLocaleDateString("id-ID", {
            weekday: "long",
            day: "2-digit",
            month: "long",
            year: "numeric",
        });
        timeEl.textContent = `${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}`;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatEstimatedTime(value) {
        if (!value || typeof value !== "string") {
            return "-";
        }
        const timePart = value.length >= 16 ? value.slice(11, 16) : value;
        return timePart || "-";
    }

    function formatUpdated(value) {
        if (!value || typeof value !== "string") {
            return "-";
        }
        const [datePart, timePart = ""] = value.split(" ");
        const date = parseLocalDate(datePart);
        const dateText = date.toLocaleDateString("id-ID", {
            day: "2-digit",
            month: "long",
            year: "numeric",
        });
        return `${dateText} ${timePart}`;
    }

    function formatSelectedDate(value) {
        const date = parseLocalDate(value);
        return date.toLocaleDateString("id-ID", {
            weekday: "long",
            day: "2-digit",
            month: "long",
            year: "numeric",
        });
    }

    function buildMoreText(extraCount) {
        return extraCount > 0 ? `+${extraCount} lainnya` : "";
    }

    function applyPulse(element, className) {
        if (!element) {
            return;
        }
        element.classList.remove(className);
        void element.offsetWidth;
        element.classList.add(className);
    }

    function shouldRender(newData) {
        const comparable = JSON.stringify({
            selected_date: newData.selected_date || selectedDate,
            schedule_slots: newData.schedule_slots || [],
            waiting_process: newData.waiting_process || [],
            in_process: newData.in_process || [],
            completed: newData.completed || [],
        });
        if (comparable === lastComparablePayload) {
            return false;
        }
        lastComparablePayload = comparable;
        return true;
    }

    function renderStatusCards(container, countEl, items, previousSnapshot, forceAnimate = false) {
        if (!container) {
            return previousSnapshot;
        }
        const safeItems = Array.isArray(items) ? items : [];
        const currentSnapshot = JSON.stringify(safeItems);
        const visibleItems = safeItems.slice(0, 8);
        const extraCount = safeItems.length - visibleItems.length;
        container.innerHTML = "";
        if (countEl) {
            countEl.textContent = safeItems.length;
        }
        const shouldAnimate = forceAnimate || (previousSnapshot !== "" && previousSnapshot !== currentSnapshot);

        for (let index = 0; index < 9; index += 1) {
            const item = visibleItems[index];
            const card = document.createElement("div");
            if (index === 8 && extraCount > 0) {
                card.className = "status-mini-card status-mini-card-more";
                card.innerHTML = `<strong>${escapeHtml(buildMoreText(extraCount))}</strong>`;
            } else if (item) {
                card.className = "status-mini-card";
                card.innerHTML = `
                    <div class="status-mini-name" title="${escapeHtml(item.customer_name || "-")}">${escapeHtml(item.customer_name || "-")}</div>
                    <div class="status-mini-time">${escapeHtml(item.estimated_time || formatEstimatedTime(item.estimated_finish))}</div>
                    <div class="status-mini-racket">${escapeHtml(item.racket_count || 1)} raket</div>
                `;
            } else {
                card.className = "status-mini-card status-mini-card-empty";
                card.textContent = "-";
            }
            if (shouldAnimate) {
                card.classList.add("card-enter");
                card.style.animationDelay = `${Math.min(index * 40, 240)}ms`;
            }
            container.appendChild(card);
        }
        return currentSnapshot;
    }

    function renderSlots(slots, previousSnapshot, forceAnimate = false) {
        if (!slotList) {
            return previousSnapshot;
        }
        const currentSnapshot = JSON.stringify(Array.isArray(slots) ? slots : []);
        slotList.innerHTML = "";
        if (!Array.isArray(slots) || slots.length === 0) {
            slotList.innerHTML = '<div class="display-empty">-</div>';
            return currentSnapshot;
        }
        const previousMap = new Map();
        if (previousSnapshot) {
            try {
                const parsed = JSON.parse(previousSnapshot);
                if (Array.isArray(parsed)) {
                    parsed.forEach((slot) => previousMap.set(slot.time, JSON.stringify(slot)));
                }
            } catch (error) {
                // Ignore malformed previous snapshots and render normally.
            }
        }

        slots.forEach((slot, slotIndex) => {
            const state = slot.unavailable ? "unavailable" : slot.available ? "available" : "full";
            const items = Array.isArray(slot.items) ? slot.items : [];
            const isWide = slot.time === "20:00";
            const visibleItems = isWide ? items : items.slice(0, 2);
            const extraCount = items.length - visibleItems.length;
            const itemHtml = items.length
                ? `
                    <div class="slot-customer-list ${isWide ? "slot-customer-list-wide" : ""}">
                        ${visibleItems
                            .map(
                                (item, itemIndex) => `
                            <div class="slot-customer-row">
                                <strong title="${escapeHtml(item.customer_name || "-")}">${escapeHtml(item.customer_name || "-")}</strong>
                                <span>${escapeHtml(item.racket_count || 1)} raket</span>
                                <span>${escapeHtml(item.status || "-")}</span>
                            </div>
                        `
                            )
                            .join("")}
                        ${!isWide && extraCount > 0 ? `<div class="slot-more">${escapeHtml(buildMoreText(extraCount))}</div>` : ""}
                    </div>
                `
                : `
                    <div class="schedule-empty-state">
                        <i class="bi bi-bullseye"></i>
                        <span>Belum ada antrian<br>di jam ini</span>
                    </div>
                `;

            const card = document.createElement("article");
            card.className = `schedule-card ${isWide ? "schedule-card-wide" : ""} ${state}`;
            const previousSlotSnapshot = previousMap.get(slot.time) || "";
            const changed = previousSlotSnapshot !== "" && previousSlotSnapshot !== JSON.stringify(slot);
            if (changed) {
                card.classList.add("changed");
            } else if (previousSnapshot || forceAnimate) {
                card.classList.add("entering");
                card.style.animationDelay = `${Math.min(slotIndex * 45, 220)}ms`;
            }
            card.innerHTML = `
                <div class="schedule-card-top">
                    <div>
                        <div class="schedule-card-time">${escapeHtml(slot.time)}</div>
                        <div class="schedule-card-capacity">${escapeHtml(slot.used)}/${escapeHtml(slot.capacity)} raket</div>
                    </div>
                    <span class="schedule-card-badge">${escapeHtml(slot.label || "-")}</span>
                </div>
                <div class="schedule-card-body">
                    ${itemHtml}
                </div>
            `;
            if ((changed || forceAnimate) && items.length) {
                card.querySelectorAll(".slot-customer-row").forEach((row, rowIndex) => {
                    row.classList.add("card-enter");
                    row.style.animationDelay = `${Math.min(rowIndex * 50, 140)}ms`;
                });
            }
            slotList.appendChild(card);
        });
        return currentSnapshot;
    }

    function syncDateInput() {
        if (scheduleDateInput) {
            scheduleDateInput.min = displayMinDate;
            scheduleDateInput.max = displayMaxDate;
            scheduleDateInput.value = selectedDate;
            scheduleDateInput.disabled = autoDayEnabled;
        }
        if (previousButton) {
            previousButton.disabled = selectedDate <= displayMinDate;
            if (autoDayEnabled) {
                previousButton.disabled = true;
            }
        }
        if (nextButton) {
            nextButton.disabled = selectedDate >= displayMaxDate;
            if (autoDayEnabled) {
                nextButton.disabled = true;
            }
        }
        if (todayButton) {
            todayButton.disabled = autoDayEnabled;
        }
        if (scheduleDateLabel) {
            scheduleDateLabel.textContent = formatSelectedDate(selectedDate);
        }
        if (scheduleToolbar) {
            scheduleToolbar.classList.toggle("auto-running", autoDayEnabled);
        }
    }

    function advanceAutoDate() {
        if (!autoDayEnabled) {
            return;
        }
        selectedDate = selectedDate === displayTomorrow ? displayToday : displayTomorrow;
        syncDateInput();
        loadMonitor();
    }

    function stopAutoDayCycle() {
        if (autoDayIntervalId) {
            window.clearInterval(autoDayIntervalId);
            autoDayIntervalId = null;
        }
    }

    function startAutoDayCycle() {
        stopAutoDayCycle();
        autoDayIntervalId = window.setInterval(advanceAutoDate, 5000);
    }

    function setAutoDayEnabled(enabled) {
        autoDayEnabled = Boolean(enabled);
        if (autoDayToggle) {
            autoDayToggle.checked = autoDayEnabled;
        }
        if (autoDayEnabled) {
            if (selectedDate !== displayToday && selectedDate !== displayTomorrow) {
                selectedDate = displayToday;
                syncDateInput();
                loadMonitor();
            } else {
                syncDateInput();
            }
            startAutoDayCycle();
            return;
        }
        stopAutoDayCycle();
        syncDateInput();
    }

    async function loadMonitor() {
        try {
            const response = await fetch(`/api/antrian/monitor?date=${encodeURIComponent(selectedDate)}`, {
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
            });
            if (!response.ok) {
                throw new Error("Monitor API error");
            }
            const payload = await response.json();
            const payloadChanged = shouldRender(payload);
            const renderedDate = payload.selected_date || selectedDate;
            const dateChanged = lastRenderedDate !== "" && lastRenderedDate !== renderedDate;
            if (payloadChanged) {
                lastScheduleSnapshot = renderSlots(payload.schedule_slots, lastScheduleSnapshot, dateChanged);
                lastWaitingSnapshot = renderStatusCards(waitingProcessList, waitingProcessCount, payload.waiting_process, lastWaitingSnapshot, dateChanged);
                lastInProcessSnapshot = renderStatusCards(inProcessList, inProcessCount, payload.in_process, lastInProcessSnapshot, dateChanged);
                lastCompletedSnapshot = renderStatusCards(completedList, completedCount, payload.completed, lastCompletedSnapshot, dateChanged);
                lastRenderedDate = renderedDate;
            }
            if (updated && payload.updated_at) {
                const nextUpdatedText = `Update terakhir: ${formatUpdated(payload.updated_at)}`;
                if (updated.textContent !== nextUpdatedText) {
                    updated.textContent = nextUpdatedText;
                }
                if (lastUpdatedValue && lastUpdatedValue !== payload.updated_at) {
                    applyPulse(updated, "pulse-update");
                }
                lastUpdatedValue = payload.updated_at;
            }
        } catch (error) {
            if (updated) {
                updated.textContent = "Update terakhir: koneksi API belum tersedia";
            }
        }
    }

    function changeDate(value) {
        if (autoDayEnabled) {
            return;
        }
        selectedDate = clampDate(value);
        syncDateInput();
        loadMonitor();
    }

    previousButton?.addEventListener("click", () => changeDate(addDays(selectedDate, -1)));
    nextButton?.addEventListener("click", () => changeDate(addDays(selectedDate, 1)));
    todayButton?.addEventListener("click", () => changeDate(toIsoDate(new Date())));
    scheduleDateInput?.addEventListener("change", () => {
        if (scheduleDateInput.value) {
            changeDate(scheduleDateInput.value);
        }
    });
    autoDayToggle?.addEventListener("change", () => {
        setAutoDayEnabled(autoDayToggle.checked);
    });

    setClock();
    syncDateInput();
    setAutoDayEnabled(true);
    loadMonitor();
    window.setInterval(setClock, 1000);
    window.setInterval(loadMonitor, 5000);
})();
