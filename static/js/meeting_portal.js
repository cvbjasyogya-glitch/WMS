(function () {
    const root = document.getElementById("meetingPortalRoot");
    if (!root) {
        return;
    }

    const form = document.getElementById("meetingJoinForm");
    const saveRoomButton = document.getElementById("meetingSaveRoomButton");
    const resetButton = document.getElementById("meetingResetButton");
    const portalState = document.getElementById("meetingPortalState");
    const recentState = document.getElementById("meetingRecentState");
    const roomList = document.getElementById("meetingRoomList");
    const signatureEndpoint = root.dataset.signatureEndpoint || "/meetings/signature";
    const sessionEndpoint = root.dataset.sessionEndpoint || "/meetings/session";
    const sdkReady = root.dataset.sdkReady === "1";
    const profileCards = Array.from(root.querySelectorAll("[data-meeting-profile-card]"));

    const RECENT_ROOMS_KEY = "erp-zoom-recent-rooms";
    const MAX_RECENT_ROOMS = 6;

    function showPortalMessage(text, type) {
        if (portalState) {
            portalState.textContent = text;
            portalState.classList.remove("success", "warning", "danger");
            if (type) {
                portalState.classList.add(type);
            }
        }
        if (typeof window.showToast === "function") {
            window.showToast(text);
        }
    }

    function safeJsonParse(rawValue, fallback) {
        try {
            const parsed = JSON.parse(rawValue);
            return Array.isArray(fallback) ? (Array.isArray(parsed) ? parsed : fallback) : (parsed || fallback);
        } catch (error) {
            return fallback;
        }
    }

    function getRecentRooms() {
        try {
            return safeJsonParse(localStorage.getItem(RECENT_ROOMS_KEY), []);
        } catch (error) {
            return [];
        }
    }

    function saveRecentRooms(rooms) {
        try {
            localStorage.setItem(RECENT_ROOMS_KEY, JSON.stringify(rooms.slice(0, MAX_RECENT_ROOMS)));
        } catch (error) {
        }
    }

    function extractMeetingNumber(rawValue) {
        const raw = String(rawValue || "").trim();
        const numeric = raw.replace(/[^\d]/g, "");
        if (numeric.length >= 9 && numeric.length <= 12) {
            return numeric;
        }
        const matched = raw.match(/\/j\/(\d{9,12})/i) || raw.match(/\b(\d{9,12})\b/);
        return matched ? matched[1] : "";
    }

    function extractPasscode(rawValue) {
        const raw = String(rawValue || "").trim();
        const pwdMatch = raw.match(/[?&]pwd=([\w-]+)/i);
        if (pwdMatch) {
            return pwdMatch[1];
        }
        return "";
    }

    function normalizeRoomData(source) {
        const rawMeetingValue = source.meetingNumber || source.meeting_number || "";
        const normalizedMeetingNumber = extractMeetingNumber(rawMeetingValue);
        const inferredPasscode = extractPasscode(rawMeetingValue);
        const normalized = {
            meetingNumber: normalizedMeetingNumber,
            passcode: String(source.passcode || inferredPasscode || "").trim().slice(0, 64),
            topic: String(source.topic || "").trim().slice(0, 120),
            displayName: String(source.displayName || source.display_name || "").trim().slice(0, 64),
            email: String(source.email || "").trim().slice(0, 120),
            language: String(source.language || "id-ID").trim(),
            profile: String(source.profile || "smart-saver").trim(),
        };
        return normalized;
    }

    function readFormData() {
        const formData = new FormData(form);
        return normalizeRoomData(Object.fromEntries(formData.entries()));
    }

    function fillForm(data) {
        const normalized = normalizeRoomData(data);
        form.elements.meetingNumber.value = normalized.meetingNumber || "";
        form.elements.passcode.value = normalized.passcode || "";
        form.elements.topic.value = normalized.topic || "";
        form.elements.displayName.value = normalized.displayName || form.elements.displayName.value;
        form.elements.email.value = normalized.email || "";
        form.elements.language.value = normalized.language || "id-ID";
        if (form.elements.profile) {
            const profileOption = form.querySelector(`input[name="profile"][value="${normalized.profile}"]`);
            if (profileOption) {
                profileOption.checked = true;
                syncProfileCards();
            }
        }
    }

    function saveRoom(data) {
        const normalized = normalizeRoomData(data);
        if (!normalized.meetingNumber) {
            showPortalMessage("Nomor meeting belum valid, jadi room cepat belum bisa disimpan.", "warning");
            return false;
        }

        const recentRooms = getRecentRooms().filter((room) => room.meetingNumber !== normalized.meetingNumber);
        recentRooms.unshift({
            ...normalized,
            topic: normalized.topic || `Room ${normalized.meetingNumber}`,
            savedAt: new Date().toISOString(),
        });
        saveRecentRooms(recentRooms);
        renderRecentRooms();
        return true;
    }

    function removeRoom(meetingNumber) {
        const remainingRooms = getRecentRooms().filter((room) => room.meetingNumber !== meetingNumber);
        saveRecentRooms(remainingRooms);
        renderRecentRooms();
    }

    function buildRoomMarkup(room) {
        const safeTopic = escapeHtml(room.topic || `Room ${room.meetingNumber}`);
        const safeMeetingNumber = escapeHtml(room.meetingNumber || "-");
        const safeProfile = escapeHtml(room.profile || "smart-saver");
        const safeStamp = escapeHtml((room.savedAt || "").replace("T", " ").slice(0, 16));
        return `
            <article class="meeting-room-card">
                <div class="meeting-room-meta">
                    <strong>${safeTopic}</strong>
                    <span class="status-pill mono">${safeMeetingNumber}</span>
                </div>
                <p>${safeStamp || "Disimpan dari portal ini"}</p>
                <div class="meeting-room-actions">
                    <button type="button" class="ghost-button" data-room-fill="${safeMeetingNumber}">Pakai</button>
                    <button type="button" class="ghost-button subtle" data-room-join="${safeMeetingNumber}">Join</button>
                    <button type="button" class="ghost-button subtle" data-room-remove="${safeMeetingNumber}">Hapus</button>
                </div>
                <small class="helper-text">Profil terakhir: ${safeProfile}</small>
            </article>
        `;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function renderRecentRooms() {
        const rooms = getRecentRooms();
        if (recentState) {
            recentState.textContent = rooms.length ? `${rooms.length} room cepat` : "Belum ada room cepat";
        }
        if (!roomList) {
            return;
        }
        if (!rooms.length) {
            roomList.innerHTML = '<div class="empty-state">Belum ada room cepat tersimpan di browser ini.</div>';
            return;
        }
        roomList.innerHTML = rooms.map(buildRoomMarkup).join("");
    }

    function syncProfileCards() {
        profileCards.forEach((card) => {
            const input = card.querySelector('input[type="radio"]');
            card.classList.toggle("is-selected", Boolean(input && input.checked));
        });
    }

    async function requestSignature(payload) {
        const response = await fetch(signatureEndpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== "success") {
            throw new Error(data.message || "Gagal membuat signature meeting.");
        }
        return data;
    }

    function createMeetingStateId() {
        return `meeting-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    }

    function openMeetingSession(meetingPayload) {
        const stateId = createMeetingStateId();
        try {
            sessionStorage.setItem(`wms-zoom-state:${stateId}`, JSON.stringify(meetingPayload));
        } catch (error) {
            throw new Error("Browser menolak menyimpan data sesi meeting. Coba tutup tab lama lalu ulangi.");
        }
        window.location.href = `${sessionEndpoint}?state=${encodeURIComponent(stateId)}`;
    }

    async function joinMeeting(data) {
        if (!sdkReady) {
            showPortalMessage("Meeting belum aktif di server. Hubungi admin untuk mengisi SDK key dan secret.", "warning");
            return;
        }
        if (!data.meetingNumber) {
            showPortalMessage("Nomor meeting belum valid. Paste link Zoom atau isi nomor meeting yang benar.", "warning");
            return;
        }
        if (!data.displayName) {
            showPortalMessage("Nama tampilan wajib diisi sebelum masuk meeting.", "warning");
            return;
        }

        showPortalMessage("Menyiapkan signature dan ruang meeting...", "success");
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
        }

        try {
            const payload = await requestSignature(data);
            saveRoom(data);
            openMeetingSession(payload);
        } catch (error) {
            showPortalMessage(error.message || "Gagal masuk meeting.", "danger");
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
            }
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        await joinMeeting(readFormData());
    });

    form.elements.meetingNumber.addEventListener("input", () => {
        const currentValue = form.elements.meetingNumber.value;
        const meetingNumber = extractMeetingNumber(currentValue);
        const passcode = extractPasscode(currentValue);
        if (meetingNumber) {
            form.elements.meetingNumber.value = meetingNumber;
        }
        if (passcode && !form.elements.passcode.value.trim()) {
            form.elements.passcode.value = passcode;
        }
    });

    saveRoomButton.addEventListener("click", () => {
        if (saveRoom(readFormData())) {
            showPortalMessage("Room cepat berhasil disimpan.", "success");
        }
    });

    resetButton.addEventListener("click", () => {
        window.setTimeout(() => {
            syncProfileCards();
            showPortalMessage("Form meeting direset.", "success");
        }, 0);
    });

    form.addEventListener("change", (event) => {
        if (event.target.matches('input[name="profile"]')) {
            syncProfileCards();
        }
    });

    roomList.addEventListener("click", async (event) => {
        const fillButton = event.target.closest("[data-room-fill]");
        const joinButton = event.target.closest("[data-room-join]");
        const removeButton = event.target.closest("[data-room-remove]");
        const meetingNumber = (
            (fillButton && fillButton.dataset.roomFill)
            || (joinButton && joinButton.dataset.roomJoin)
            || (removeButton && removeButton.dataset.roomRemove)
            || ""
        ).trim();

        if (!meetingNumber) {
            return;
        }

        const room = getRecentRooms().find((item) => item.meetingNumber === meetingNumber);
        if (!room) {
            return;
        }

        if (removeButton) {
            removeRoom(meetingNumber);
            showPortalMessage("Room cepat dihapus.", "success");
            return;
        }

        fillForm(room);
        if (fillButton) {
            showPortalMessage("Room cepat dimuat ke form.", "success");
            return;
        }

        await joinMeeting(room);
    });

    renderRecentRooms();
    syncProfileCards();
})();
