(function () {
    const config = window.wmsNotificationCenterConfig || {};
    const root = document.querySelector("[data-notification-root]");
    const pageShell = document.querySelector("[data-notification-page]");

    if (!config.apiUrl || (!root && !pageShell)) {
        return;
    }

    const surfaces = {
        panel: root
            ? {
                  list: root.querySelector("[data-notification-panel-list]"),
                  summary: root.querySelector("[data-notification-panel-summary]"),
                  limit: 8
              }
            : null,
        page: pageShell
            ? {
                  list: pageShell.querySelector("[data-notification-page-list]"),
                  summary: pageShell.querySelector("[data-notification-page-summary]"),
                  limit: 80
              }
            : null
    };

    const badgeNodes = Array.from(document.querySelectorAll("[data-notification-badge]"));
    const unreadNodes = Array.from(document.querySelectorAll("[data-notification-unread]"));
    const totalNodes = Array.from(document.querySelectorAll("[data-notification-total]"));
    const devicePills = Array.from(document.querySelectorAll("[data-notification-device-status]"));
    const deviceLabelNodes = Array.from(document.querySelectorAll("[data-notification-device-label]"));
    const filterButtons = Array.from(document.querySelectorAll("[data-notification-filter]"));
    const markAllButtons = Array.from(document.querySelectorAll("[data-notification-mark-all]"));
    const deleteAllButtons = Array.from(document.querySelectorAll("[data-notification-delete-all]"));
    const enableButtons = Array.from(document.querySelectorAll("[data-notification-enable-device]"));

    enableButtons.forEach((button) => {
        if (!button.dataset.defaultLabel) {
            button.dataset.defaultLabel = button.textContent.trim();
        }
    });

    const panelToggle = root ? root.querySelector("[data-notification-toggle]") : null;
    const panel = root ? root.querySelector("[data-notification-panel]") : null;

    const categoryMeta = {
        announcement: { label: "Pengumuman", icon: "PG" },
        approval: { label: "Approval", icon: "AP" },
        attendance: { label: "Absen", icon: "AB" },
        audit: { label: "Audit", icon: "AU" },
        chat: { label: "Chat", icon: "CH" },
        crm: { label: "CRM", icon: "CM" },
        hris: { label: "HRIS", icon: "HR" },
        inventory: { label: "Stok", icon: "ST" },
        leave: { label: "Libur", icon: "LV" },
        owner_request: { label: "Owner", icon: "OW" },
        report: { label: "Report", icon: "RP" },
        request: { label: "Request", icon: "RQ" },
        schedule: { label: "Jadwal", icon: "JD" },
        system: { label: "Sistem", icon: "NT" }
    };

    const state = {
        filters: {
            panel: "unread",
            page:
                (pageShell && pageShell.dataset.notificationInitialFilter === "all")
                    ? "all"
                    : "unread"
        },
        latestId: 0,
        bootstrapped: false,
        pollInFlight: false,
        shownBrowserIds: new Set(),
        deviceState: null,
        unreadCount: 0,
        totalCount: 0,
        lastActivityAt: Date.now()
    };
    let pollTimer = null;
    const activePollIntervalMs = 12000;
    const idlePollIntervalMs = 20000;
    const quietPollIntervalMs = 30000;
    const recentPollWindowMs = 90000;
    const leaderRetryIntervalMs = 7000;
    const pollLockKey = "wms:notifications:poll-lock";
    const pollLockTtlMs = 45000;
    const tabId = `notif-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

    function markNotificationActivity() {
        state.lastActivityAt = Date.now();
    }

    function readPollLock() {
        try {
            const raw = window.localStorage ? window.localStorage.getItem(pollLockKey) : null;
            if (!raw) {
                return null;
            }
            const parsed = JSON.parse(raw);
            if (!parsed || !parsed.id) {
                return null;
            }
            return parsed;
        } catch (error) {
            return null;
        }
    }

    function writePollLock() {
        const nextLock = {
            id: tabId,
            expiresAt: Date.now() + pollLockTtlMs
        };
        try {
            if (window.localStorage) {
                window.localStorage.setItem(pollLockKey, JSON.stringify(nextLock));
            }
            return true;
        } catch (error) {
            return true;
        }
    }

    function canPollInThisTab() {
        const activeLock = readPollLock();
        if (!activeLock || Number(activeLock.expiresAt || 0) <= Date.now() || activeLock.id === tabId) {
            return writePollLock();
        }
        return false;
    }

    function releasePollLeadership() {
        try {
            const activeLock = readPollLock();
            if (activeLock && activeLock.id === tabId && window.localStorage) {
                window.localStorage.removeItem(pollLockKey);
            }
        } catch (error) {
        }
    }

    function panelIsOpen() {
        return Boolean(root && root.classList.contains("is-open"));
    }

    function resolvePollDelayMs() {
        if (panelIsOpen() || pageShell || state.unreadCount > 0) {
            return activePollIntervalMs;
        }
        if (Date.now() - state.lastActivityAt <= recentPollWindowMs) {
            return idlePollIntervalMs;
        }
        return quietPollIntervalMs;
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function getCategory(category) {
        const normalized = String(category || "system").trim().toLowerCase();
        return categoryMeta[normalized] || categoryMeta.system;
    }

    function toDate(value) {
        const text = String(value || "").trim();
        if (!text) {
            return null;
        }

        const normalized = text.endsWith("Z") ? text : `${text.replace(" ", "T")}Z`;
        const date = new Date(normalized);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    function formatRelativeTime(value) {
        const date = toDate(value);
        if (!date) {
            return "-";
        }

        const diffMs = Date.now() - date.getTime();
        const diffMinutes = Math.max(0, Math.round(diffMs / 60000));

        if (diffMinutes < 1) {
            return "Baru saja";
        }
        if (diffMinutes < 60) {
            return `${diffMinutes}m`;
        }

        const diffHours = Math.round(diffMinutes / 60);
        if (diffHours < 24) {
            return `${diffHours}j`;
        }

        const diffDays = Math.round(diffHours / 24);
        if (diffDays < 7) {
            return `${diffDays}h`;
        }

        return new Intl.DateTimeFormat("id-ID", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit"
        }).format(date);
    }

    function updateBadge(count) {
        const normalizedCount = Math.max(0, Number(count || 0));
        const badgeText = normalizedCount > 99 ? "99+" : String(normalizedCount);

        badgeNodes.forEach((node) => {
            node.textContent = badgeText;
            node.hidden = normalizedCount <= 0;
        });

        unreadNodes.forEach((node) => {
            node.textContent = String(normalizedCount);
        });

        markAllButtons.forEach((button) => {
            button.disabled = normalizedCount <= 0;
        });
    }

    function updateTotals(totalCount, unreadCount) {
        const normalizedTotalCount = Math.max(0, Number(totalCount || 0));
        const normalizedUnreadCount = Math.max(0, Number(unreadCount || 0));
        state.totalCount = normalizedTotalCount;
        state.unreadCount = normalizedUnreadCount;
        totalNodes.forEach((node) => {
            node.textContent = String(normalizedTotalCount);
        });
        deleteAllButtons.forEach((button) => {
            button.disabled = normalizedTotalCount <= 0;
        });
        updateBadge(normalizedUnreadCount);
    }

    function updateSurfaceSummary(surfaceName, payload) {
        const surface = surfaces[surfaceName];
        if (!surface || !surface.summary) {
            return;
        }

        const unreadCount = Math.max(0, Number(payload.unread_count || 0));
        const totalCount = Math.max(0, Number(payload.total_count || 0));
        surface.summary.textContent =
            unreadCount > 0
                ? `${unreadCount} belum dibaca dari ${totalCount} notifikasi.`
                : totalCount > 0
                  ? `Semua notifikasi sudah dibaca. Total ${totalCount} item.`
                  : "Belum ada notifikasi di inbox.";
    }

    function renderItems(target, items) {
        if (!target) {
            return;
        }

        if (!Array.isArray(items) || !items.length) {
            target.innerHTML = '<div class="notification-center-empty">Belum ada notifikasi yang cocok dengan filter ini.</div>';
            return;
        }

        target.innerHTML = items
            .map((item) => {
                const meta = getCategory(item.category);
                const actor = item.actor_name ? `<span>${escapeHtml(item.actor_name)}</span>` : "";
                const unreadDot = item.is_read ? "" : '<span class="notification-unread-dot" aria-hidden="true"></span>';
                const href = escapeHtml(item.link_url || config.pageUrl || "/notifications/");
                const title = escapeHtml(item.title || "Notifikasi Baru");
                const message = escapeHtml(item.message || "Ada update baru yang perlu dicek.");
                const time = escapeHtml(formatRelativeTime(item.created_at_iso || item.created_at));

                return `
                    <article class="notification-card" data-notification-card data-notification-id="${Number(item.id || 0)}">
                        <a
                            href="${href}"
                            class="notification-entry ${item.is_read ? "" : "is-unread"}"
                            data-notification-entry-link
                            data-notification-id="${Number(item.id || 0)}"
                        >
                            <span class="notification-entry-icon ${(item.category || "system").toLowerCase()}" aria-hidden="true">${escapeHtml(meta.icon)}</span>
                            <div class="notification-entry-body">
                                <div class="notification-entry-topline">
                                    <strong>${title}</strong>
                                    <time>${time}</time>
                                </div>
                                <p>${message}</p>
                                <div class="notification-entry-meta">
                                    <span class="notification-chip">${escapeHtml(meta.label)}</span>
                                    ${actor}
                                    ${unreadDot}
                                </div>
                            </div>
                        </a>
                        <div class="notification-entry-actions">
                            <button type="button" class="ghost-button notification-entry-action danger" data-notification-delete data-notification-id="${Number(item.id || 0)}">Hapus</button>
                        </div>
                    </article>
                `;
            })
            .join("");
    }

    function removeNotificationEntries(notificationId) {
        if (!notificationId) {
            return;
        }

        document.querySelectorAll(`[data-notification-id="${notificationId}"]`).forEach((node) => {
            const entry = node.closest("[data-notification-card]") || node;
            if (entry && typeof entry.remove === "function") {
                entry.remove();
            }
        });

        Object.keys(surfaces).forEach((surfaceName) => {
            const surface = surfaces[surfaceName];
            if (!surface || !surface.list) {
                return;
            }

            if (!surface.list.querySelector("[data-notification-entry-link]")) {
                surface.list.innerHTML = '<div class="notification-center-empty">Belum ada notifikasi yang cocok dengan filter ini.</div>';
            }
        });
    }

    function setFilterButtons(surfaceName) {
        filterButtons.forEach((button) => {
            if (button.dataset.notificationSurface !== surfaceName) {
                return;
            }
            button.classList.toggle(
                "active",
                button.dataset.notificationFilter === state.filters[surfaceName]
            );
        });
    }

    function buildApiUrl(options) {
        const url = new URL(config.apiUrl, window.location.origin);
        url.searchParams.set("filter", options.filter || "all");
        url.searchParams.set("limit", String(options.limit || 12));
        if (options.sinceId) {
            url.searchParams.set("since_id", String(options.sinceId));
        }
        return url.toString();
    }

    async function fetchNotifications(options) {
        const response = await fetch(buildApiUrl(options), {
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        });
        if (!response.ok) {
            throw new Error("Gagal memuat notifikasi.");
        }
        return response.json();
    }

    async function refreshSurface(surfaceName) {
        const surface = surfaces[surfaceName];
        if (!surface || !surface.list) {
            return null;
        }

        const payload = await fetchNotifications({
            filter: state.filters[surfaceName],
            limit: surface.limit
        });

        renderItems(surface.list, payload.items || []);
        updateSurfaceSummary(surfaceName, payload);
        updateTotals(payload.total_count || 0, payload.unread_count || 0);
        state.latestId = Math.max(state.latestId, Number(payload.latest_id || 0));
        setFilterButtons(surfaceName);
        return payload;
    }

    function openPanel() {
        if (!panel || !panelToggle) {
            return;
        }
        panel.hidden = false;
        panel.setAttribute("aria-hidden", "false");
        panelToggle.setAttribute("aria-expanded", "true");
        root.classList.add("is-open");
    }

    function closePanel() {
        if (!panel || !panelToggle) {
            return;
        }
        panel.hidden = true;
        panel.setAttribute("aria-hidden", "true");
        panelToggle.setAttribute("aria-expanded", "false");
        root.classList.remove("is-open");
    }

    async function markNotificationRead(notificationId) {
        const response = await fetch(
            (config.markReadUrlTemplate || "").replace("__id__", encodeURIComponent(String(notificationId))),
            {
                method: "POST",
                credentials: "same-origin",
                headers: { Accept: "application/json" }
            }
        );
        if (!response.ok) {
            throw new Error("Gagal menandai notifikasi.");
        }
        return response.json();
    }

    async function markAllRead() {
        const response = await fetch(config.markAllReadUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        });
        if (!response.ok) {
            throw new Error("Gagal menandai semua notifikasi.");
        }
        return response.json();
    }

    async function deleteNotification(notificationId) {
        const response = await fetch(
            (config.deleteUrlTemplate || "").replace("__id__", encodeURIComponent(String(notificationId))),
            {
                method: "POST",
                credentials: "same-origin",
                headers: { Accept: "application/json" }
            }
        );
        if (!response.ok) {
            throw new Error("Gagal menghapus notifikasi.");
        }
        return response.json();
    }

    async function deleteAllNotifications() {
        const response = await fetch(config.deleteAllUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        });
        if (!response.ok) {
            throw new Error("Gagal menghapus semua notifikasi.");
        }
        return response.json();
    }

    async function readThenNavigate(link) {
        window.location.href = link;
    }

    function browserNotificationsAvailable() {
        return typeof Notification !== "undefined" && Notification.permission === "granted";
    }

    async function getPushState() {
        const pushApi = window.wmsPushNotifications;
        if (pushApi && typeof pushApi.getState === "function") {
            return pushApi.getState();
        }

        return {
            supported: typeof Notification !== "undefined",
            permission: typeof Notification !== "undefined" ? Notification.permission : "unsupported",
            hasSubscription: false,
            configured: false
        };
    }

    function renderDeviceState(deviceState) {
        let pillText = "Belum Aktif";
        let labelText = "Perlu izin";

        if (!deviceState || !deviceState.supported) {
            pillText = "Tidak Didukung";
            labelText = "Tidak didukung";
        } else if (deviceState.permission === "denied") {
            pillText = "Diblokir";
            labelText = "Diblokir";
        } else if (deviceState.permission === "granted" && deviceState.hasSubscription) {
            pillText = "Aktif";
            labelText = "Aktif";
        } else if (deviceState.permission === "granted") {
            pillText = "Izin Aktif";
            labelText = "Izin aktif";
        }

        devicePills.forEach((node) => {
            node.textContent = pillText;
        });
        deviceLabelNodes.forEach((node) => {
            node.textContent = labelText;
        });

        enableButtons.forEach((button) => {
            const defaultLabel = button.dataset.defaultLabel || "Notif Device";

            if (!deviceState || !deviceState.supported) {
                button.disabled = true;
                button.textContent = "Tidak Didukung";
                return;
            }

            if (deviceState.permission === "denied") {
                button.disabled = true;
                button.textContent = "Izin Diblokir";
                return;
            }

            if (deviceState.permission === "granted") {
                button.disabled = true;
                button.textContent = deviceState.hasSubscription ? "Notif Aktif" : "Izin Aktif";
                return;
            }

            button.disabled = false;
            button.textContent = defaultLabel;
        });
    }

    async function refreshDeviceState() {
        try {
            const deviceState = await getPushState();
            state.deviceState = deviceState;
            renderDeviceState(deviceState);
        } catch (error) {
            state.deviceState = { supported: false };
            renderDeviceState({ supported: false });
        }
    }

    async function enableDeviceNotifications() {
        const pushApi = window.wmsPushNotifications;

        if (pushApi && typeof pushApi.enable === "function") {
            await pushApi.enable();
        } else if (typeof Notification !== "undefined" && Notification.permission !== "granted") {
            await Notification.requestPermission();
        }

        await refreshDeviceState();
        if (typeof window.showToast === "function") {
            window.showToast("Notifikasi perangkat sudah diperiksa. Cek status terbaru di panel notifikasi.");
        }
    }

    async function showBrowserNotification(item) {
        const notificationId = Number(item.id || 0);
        if (
            !notificationId
            || state.shownBrowserIds.has(notificationId)
            || !browserNotificationsAvailable()
            || (state.deviceState && state.deviceState.hasSubscription)
        ) {
            return;
        }

        state.shownBrowserIds.add(notificationId);

        const meta = getCategory(item.category);
        const title = item.title || `${meta.label} baru`;
        const body = item.message || "Ada update baru yang perlu dicek.";

        try {
            if ("serviceWorker" in navigator) {
                const registration = await navigator.serviceWorker.getRegistration();
                if (registration && typeof registration.showNotification === "function") {
                    await registration.showNotification(title, {
                        body,
                        icon: "/static/brand/mataram-logo.png",
                        badge: "/static/brand/mataram-logo.png",
                        tag: `web-notification-${notificationId}`,
                        data: {
                            url: item.link_url || config.pageUrl || "/notifications/",
                            notification_id: notificationId
                        }
                    });
                    return;
                }
            }

            new Notification(title, {
                body,
                icon: "/static/brand/mataram-logo.png"
            });
        } catch (error) {
        }
    }

    async function pollForNewNotifications() {
        if (state.pollInFlight) {
            return;
        }
        if (!canPollInThisTab()) {
            startPolling(leaderRetryIntervalMs);
            return;
        }

        state.pollInFlight = true;
        try {
            const payload = await fetchNotifications({
                filter: "all",
                limit: 12,
                sinceId: state.latestId
            });

            updateTotals(payload.total_count || 0, payload.unread_count || 0);
            state.latestId = Math.max(state.latestId, Number(payload.latest_id || 0));

            const newItems = Array.isArray(payload.items) ? payload.items : [];
            if (!newItems.length) {
                return;
            }

            markNotificationActivity();

            if (document.visibilityState === "hidden" || !document.hasFocus()) {
                const ordered = [...newItems].reverse();
                for (const item of ordered) {
                    await showBrowserNotification(item);
                }
            }

            await refreshSurface("panel");
            await refreshSurface("page");
        } catch (error) {
        } finally {
            state.pollInFlight = false;
            writePollLock();
            startPolling();
        }
    }

    async function bootstrap() {
        try {
            const panelPayload = await refreshSurface("panel");
            const pagePayload = await refreshSurface("page");
            state.latestId = Math.max(
                state.latestId,
                Number((panelPayload && panelPayload.latest_id) || 0),
                Number((pagePayload && pagePayload.latest_id) || 0)
            );
            state.bootstrapped = true;
        } catch (error) {
            if (surfaces.panel && surfaces.panel.list) {
                surfaces.panel.list.innerHTML = '<div class="notification-center-empty">Gagal memuat notifikasi. Coba refresh halaman ini.</div>';
            }
            if (surfaces.page && surfaces.page.list) {
                surfaces.page.list.innerHTML = '<div class="notification-center-empty">Gagal memuat notifikasi. Coba refresh halaman ini.</div>';
            }
        }

        await refreshDeviceState();
    }

    function stopPolling() {
        if (pollTimer) {
            window.clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function startPolling(forceDelayMs) {
        if (document.visibilityState === "hidden") {
            return;
        }
        stopPolling();
        if (!canPollInThisTab()) {
            pollTimer = window.setTimeout(() => {
                pollTimer = null;
                startPolling();
            }, leaderRetryIntervalMs);
            return;
        }
        const nextDelay = Math.max(Number(forceDelayMs || resolvePollDelayMs()), 1500);
        pollTimer = window.setTimeout(async () => {
            pollTimer = null;
            await pollForNewNotifications();
        }, nextDelay);
    }

    if (panelToggle) {
        panelToggle.addEventListener("click", async () => {
            if (root.classList.contains("is-open")) {
                closePanel();
                startPolling();
                return;
            }

            markNotificationActivity();
            openPanel();
            try {
                await refreshSurface("panel");
            } catch (error) {
            }
            startPolling(activePollIntervalMs);
        });
    }

    document.addEventListener("click", (event) => {
        if (!root || !root.classList.contains("is-open")) {
            return;
        }
        if (root.contains(event.target)) {
            return;
        }
        closePanel();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closePanel();
        }
    });

    filterButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            const surfaceName = button.dataset.notificationSurface;
            const nextFilter = button.dataset.notificationFilter === "unread" ? "unread" : "all";
            if (!surfaceName || !surfaces[surfaceName]) {
                return;
            }

            markNotificationActivity();
            state.filters[surfaceName] = nextFilter;
            setFilterButtons(surfaceName);

            try {
                await refreshSurface(surfaceName);
            } catch (error) {
            }
            startPolling(activePollIntervalMs);
        });
    });

    document.addEventListener("click", async (event) => {
        const deleteButton = event.target.closest("[data-notification-delete]");
        if (deleteButton) {
            event.preventDefault();
            const notificationId = Number(deleteButton.dataset.notificationId || 0);
            if (!notificationId) {
                return;
            }

            try {
                markNotificationActivity();
                const payload = await deleteNotification(notificationId);
                updateTotals(payload.total_count || 0, payload.unread_count || 0);
                removeNotificationEntries(notificationId);
                await refreshSurface("panel");
                await refreshSurface("page");
                if (typeof window.showToast === "function") {
                    window.showToast("Notifikasi berhasil dihapus.");
                }
            } catch (error) {
                if (typeof window.showToast === "function") {
                    window.showToast("Gagal menghapus notifikasi.");
                }
            }
            startPolling(activePollIntervalMs);
            return;
        }

        const readButton = event.target.closest("[data-notification-entry-link]");
        if (!readButton) {
            return;
        }

        const href = readButton.getAttribute("href");
        const notificationId = Number(readButton.dataset.notificationId || 0);

        if (!href) {
            return;
        }

        event.preventDefault();

        try {
            if (notificationId > 0) {
                markNotificationActivity();
                const payload = await markNotificationRead(notificationId);
                updateBadge(payload.unread_count || 0);
                removeNotificationEntries(notificationId);
                await refreshSurface("panel");
                await refreshSurface("page");
            }
        } catch (error) {
        }

        startPolling(activePollIntervalMs);
        await readThenNavigate(href);
    });

    markAllButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                markNotificationActivity();
                const payload = await markAllRead();
                updateTotals(payload.total_count || 0, payload.unread_count || 0);
                await refreshSurface("panel");
                await refreshSurface("page");
                if (typeof window.showToast === "function") {
                    window.showToast("Semua notifikasi sudah ditandai terbaca.");
                }
            } catch (error) {
                if (typeof window.showToast === "function") {
                    window.showToast("Gagal menandai semua notifikasi.");
                }
            }
            startPolling(activePollIntervalMs);
        });
    });

    deleteAllButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (typeof window.confirm === "function" && !window.confirm("Hapus semua notifikasi dari inbox?")) {
                return;
            }

            try {
                markNotificationActivity();
                const payload = await deleteAllNotifications();
                updateTotals(payload.total_count || 0, payload.unread_count || 0);
                await refreshSurface("panel");
                await refreshSurface("page");
                if (typeof window.showToast === "function") {
                    window.showToast("Semua notifikasi berhasil dihapus.");
                }
            } catch (error) {
                if (typeof window.showToast === "function") {
                    window.showToast("Gagal menghapus semua notifikasi.");
                }
            }
            startPolling(activePollIntervalMs);
        });
    });

    enableButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                markNotificationActivity();
                await enableDeviceNotifications();
            } catch (error) {
                if (typeof window.showToast === "function") {
                    window.showToast("Izin notifikasi perangkat belum berhasil diaktifkan.");
                }
            } finally {
                button.disabled = false;
            }
            startPolling(activePollIntervalMs);
        });
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            markNotificationActivity();
            refreshSurface("panel").catch(() => {});
            refreshSurface("page").catch(() => {});
            refreshDeviceState().catch(() => {});
            pollForNewNotifications().catch(() => {});
            startPolling(activePollIntervalMs);
            return;
        }

        stopPolling();
        releasePollLeadership();
    });

    bootstrap().then(() => {
        startPolling();
    });

    window.addEventListener("pageshow", () => {
        markNotificationActivity();
        startPolling(activePollIntervalMs);
    });

    window.addEventListener("pagehide", () => {
        stopPolling();
        releasePollLeadership();
    });

    window.addEventListener("beforeunload", () => {
        stopPolling();
        releasePollLeadership();
    });

    window.addEventListener("storage", (event) => {
        if (event.key !== pollLockKey || document.visibilityState !== "visible") {
            return;
        }
        startPolling(leaderRetryIntervalMs);
    });
})();
