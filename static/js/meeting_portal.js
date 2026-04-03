(function () {
    const root = document.getElementById("meetingPortalRoot");
    if (!root) {
        return;
    }

    const form = document.getElementById("meetingJoinForm");
    const saveRoomButton = document.getElementById("meetingSaveRoomButton");
    const instantRoomButton = document.getElementById("meetingInstantRoomButton");
    const resetButton = document.getElementById("meetingResetButton");
    const portalState = document.getElementById("meetingPortalState");
    const recentState = document.getElementById("meetingRecentState");
    const roomList = document.getElementById("meetingRoomList");
    const prepareEndpoint = root.dataset.signatureEndpoint || "/meetings/signature";
    const sessionEndpoint = root.dataset.sessionEndpoint || "/meetings/session";
    const meetingDomain = root.dataset.meetingDomain || "meet.jit.si";
    const profileCards = Array.from(root.querySelectorAll("[data-meeting-profile-card]"));

    const RECENT_ROOMS_KEY = "erp-browser-meeting-rooms";
    const MAX_RECENT_ROOMS = 8;

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

    function sanitizeRoomName(rawValue) {
        const raw = String(rawValue || "").trim();
        let candidate = raw;
        if (/^https?:\/\//i.test(raw)) {
            try {
                const parsed = new URL(raw);
                const parts = parsed.pathname.split("/").filter(Boolean);
                candidate = parts.length ? parts[parts.length - 1] : "";
            } catch (error) {
                candidate = raw;
            }
        }

        candidate = candidate
            .toLowerCase()
            .replace(/[\\/]+/g, "-")
            .replace(/\s+/g, "-")
            .replace(/[^a-z0-9_-]+/g, "-")
            .replace(/-{2,}/g, "-")
            .replace(/^[-_]+|[-_]+$/g, "");

        return candidate.slice(0, 72);
    }

    function slugifyText(rawValue) {
        return sanitizeRoomName(rawValue);
    }

    function buildInstantRoomName() {
        const topicValue = slugifyText(form.elements.topic.value || "");
        const displayValue = slugifyText(form.elements.displayName.value || "team");
        const stamp = new Date();
        const timeToken = [
            stamp.getFullYear(),
            String(stamp.getMonth() + 1).padStart(2, "0"),
            String(stamp.getDate()).padStart(2, "0"),
            String(stamp.getHours()).padStart(2, "0"),
            String(stamp.getMinutes()).padStart(2, "0"),
        ].join("");
        return (topicValue || `erp-bjas-${displayValue || "team"}-${timeToken}`).slice(0, 72);
    }

    function normalizeRoomData(source) {
        const normalizedRoomName = sanitizeRoomName(source.roomName || source.meetingNumber || source.room_name || "");
        return {
            roomName: normalizedRoomName,
            topic: String(source.topic || "").trim().slice(0, 120),
            displayName: String(source.displayName || source.display_name || "").trim().slice(0, 64),
            email: String(source.email || "").trim().slice(0, 120),
            language: String(source.language || "id-ID").trim(),
            profile: String(source.profile || "audio-first").trim(),
        };
    }

    function readFormData() {
        const formData = new FormData(form);
        const rawData = Object.fromEntries(formData.entries());
        const normalized = normalizeRoomData(rawData);
        if (!normalized.roomName && normalized.topic) {
            normalized.roomName = slugifyText(normalized.topic);
        }
        return normalized;
    }

    function fillForm(data) {
        const normalized = normalizeRoomData(data);
        form.elements.roomName.value = normalized.roomName || "";
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
        if (!normalized.roomName) {
            showPortalMessage("Nama room belum valid, jadi room cepat belum bisa disimpan.", "warning");
            return false;
        }

        const recentRooms = getRecentRooms().filter((room) => room.roomName !== normalized.roomName);
        recentRooms.unshift({
            ...normalized,
            topic: normalized.topic || `Room ${normalized.roomName}`,
            savedAt: new Date().toISOString(),
        });
        saveRecentRooms(recentRooms);
        renderRecentRooms();
        return true;
    }

    function removeRoom(roomName) {
        const remainingRooms = getRecentRooms().filter((room) => room.roomName !== roomName);
        saveRecentRooms(remainingRooms);
        renderRecentRooms();
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function buildRoomMarkup(room) {
        const safeTopic = escapeHtml(room.topic || `Room ${room.roomName}`);
        const safeRoomName = escapeHtml(room.roomName || "-");
        const safeProfile = escapeHtml(room.profile || "audio-first");
        const safeStamp = escapeHtml((room.savedAt || "").replace("T", " ").slice(0, 16));
        const safeLink = escapeHtml(`https://${meetingDomain}/${room.roomName}`);
        return `
            <article class="meeting-room-card">
                <div class="meeting-room-meta">
                    <strong>${safeTopic}</strong>
                    <span class="status-pill mono">${safeRoomName}</span>
                </div>
                <p>${safeStamp || "Disimpan dari portal ini"}</p>
                <small class="helper-text">${safeLink}</small>
                <div class="meeting-room-actions">
                    <button type="button" class="ghost-button" data-room-fill="${safeRoomName}">Pakai</button>
                    <button type="button" class="ghost-button subtle" data-room-join="${safeRoomName}">Join</button>
                    <button type="button" class="ghost-button subtle" data-room-remove="${safeRoomName}">Hapus</button>
                </div>
                <small class="helper-text">Profil terakhir: ${safeProfile}</small>
            </article>
        `;
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

    async function requestMeetingConfig(payload) {
        const response = await fetch(prepareEndpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== "success") {
            throw new Error(data.message || "Gagal menyiapkan room meeting.");
        }
        return data;
    }

    function createMeetingStateId() {
        return `meeting-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    }

    function openMeetingSession(meetingPayload) {
        const stateId = createMeetingStateId();
        try {
            sessionStorage.setItem(`wms-meeting-state:${stateId}`, JSON.stringify(meetingPayload));
        } catch (error) {
            throw new Error("Browser menolak menyimpan data sesi meeting. Coba tutup tab lama lalu ulangi.");
        }
        window.location.href = `${sessionEndpoint}?state=${encodeURIComponent(stateId)}`;
    }

    async function joinMeeting(data) {
        if (!data.roomName && !data.topic) {
            showPortalMessage("Isi nama room atau judul meeting dulu sebelum join.", "warning");
            return;
        }
        if (!data.displayName) {
            showPortalMessage("Nama tampilan wajib diisi sebelum masuk meeting.", "warning");
            return;
        }

        showPortalMessage("Menyiapkan room browser...", "success");
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
        }

        try {
            const payload = await requestMeetingConfig(data);
            saveRoom(payload);
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

    form.elements.roomName.addEventListener("blur", () => {
        const cleaned = sanitizeRoomName(form.elements.roomName.value);
        if (cleaned) {
            form.elements.roomName.value = cleaned;
        }
    });

    instantRoomButton.addEventListener("click", () => {
        form.elements.roomName.value = buildInstantRoomName();
        showPortalMessage("Nama room instan berhasil dibuat. Kamu bisa langsung join atau simpan dulu.", "success");
    });

    saveRoomButton.addEventListener("click", () => {
        const data = readFormData();
        if (!data.roomName) {
            data.roomName = buildInstantRoomName();
            form.elements.roomName.value = data.roomName;
        }
        if (saveRoom(data)) {
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
        const roomName = (
            (fillButton && fillButton.dataset.roomFill)
            || (joinButton && joinButton.dataset.roomJoin)
            || (removeButton && removeButton.dataset.roomRemove)
            || ""
        ).trim();

        if (!roomName) {
            return;
        }

        const room = getRecentRooms().find((item) => item.roomName === roomName);
        if (!room) {
            return;
        }

        if (removeButton) {
            removeRoom(roomName);
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
