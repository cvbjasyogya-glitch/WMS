(function () {
    const shell = document.getElementById("wmsChatShell");
    if (!shell) {
        return;
    }

    const bootstrapNode = document.getElementById("chatBootstrapData");
    const bootstrap = bootstrapNode ? JSON.parse(bootstrapNode.textContent || "{}") : {};

    const threadList = document.getElementById("chatThreadList");
    const contactList = document.getElementById("chatContactList");
    const leaderList = document.getElementById("chatLeaderList");
    const messageBoard = document.getElementById("chatMessageBoard");
    const composerForm = document.getElementById("chatComposerForm");
    const composerInput = document.getElementById("chatComposerInput");
    const composerButton = document.getElementById("chatComposerButton");
    const attachmentInput = document.getElementById("chatAttachmentInput");
    const stickerImageInput = document.getElementById("chatStickerImageInput");
    const attachmentPreview = document.getElementById("chatAttachmentPreview");
    const stickerPanel = document.getElementById("chatStickerPanel");
    const stickerToggle = document.getElementById("chatStickerToggle");
    const stickerUploadButton = document.getElementById("chatStickerUploadButton");
    const attachButton = document.getElementById("chatAttachButton");
    const voiceCallButton = document.getElementById("chatVoiceCallButton");
    const videoCallButton = document.getElementById("chatVideoCallButton");
    const searchInput = document.getElementById("chatSearchInput");
    const tabButtons = Array.from(document.querySelectorAll("[data-chat-tab-target]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-chat-tab]"));
    const partnerName = document.getElementById("chatPartnerName");
    const partnerMeta = document.getElementById("chatPartnerMeta");
    const partnerStatus = document.getElementById("chatPartnerStatus");
    const participantStrip = document.getElementById("chatParticipantStrip");
    const mobileBackButton = document.getElementById("chatMobileBackButton");
    const sidebarPanel = shell.querySelector(".chat-sidebar-panel");

    const createGroupButton = document.getElementById("chatCreateGroupButton");
    const groupModal = document.getElementById("chatGroupModal");
    const groupCloseButton = document.getElementById("chatGroupCloseButton");
    const groupCancelButton = document.getElementById("chatGroupCancelButton");
    const groupSubmitButton = document.getElementById("chatGroupSubmitButton");
    const groupNameInput = document.getElementById("chatGroupNameInput");
    const groupDescriptionInput = document.getElementById("chatGroupDescriptionInput");
    const groupMemberList = document.getElementById("chatGroupMemberList");

    let currentThreadId = Number(shell.dataset.currentThreadId || bootstrap.current_thread_id || 0) || null;
    let lastMessageId = Number(shell.dataset.lastMessageId || bootstrap.current_thread_last_message_id || 0) || 0;
    let searchQuery = "";
    let pollTimer = null;
    let pollInFlight = false;
    let sendInFlight = false;
    let activeTab = "threads";
    let pendingAttachment = null;
    const maxAttachmentBytes = Number(shell.dataset.maxAttachmentBytes || 10485760) || 10485760;
    const compactViewport = window.matchMedia("(max-width: 1080px)").matches;
    const lowDataMode = Boolean(
        navigator.connection
        && (
            navigator.connection.saveData
            || /(?:^|[^a-z])2g/.test(String(navigator.connection.effectiveType || "").toLowerCase())
        )
    );
    const pollIntervalMs = lowDataMode ? 6500 : compactViewport ? 4000 : 2500;

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatFileSize(sizeBytes) {
        const safeSize = Math.max(Number(sizeBytes || 0), 0);
        if (safeSize < 1024) {
            return `${safeSize} B`;
        }
        if (safeSize < 1024 * 1024) {
            return `${(safeSize / 1024).toFixed(1)} KB`;
        }
        return `${(safeSize / (1024 * 1024)).toFixed(1)} MB`;
    }

    function normalizeChatText(root) {
        const target = root || document.body;
        if (!target || !window.NodeFilter || !document.createTreeWalker) {
            return;
        }

        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
            if (node.nodeValue) {
                node.nodeValue = node.nodeValue
                    .replace(/Ã¢â‚¬Â¢/g, "|")
                    .replace(/Ã¢â‚¬Â¦/g, "...");
            }
            node = walker.nextNode();
        }
    }

    function renderThreadCard(thread) {
        const unreadCount = Number(thread.unread_count || 0);
        const isActive = currentThreadId && Number(thread.id) === Number(currentThreadId);
        const isGroup = thread.thread_type === "group";
        return `
            <a
                href="/chat/?thread=${thread.id}"
                class="chat-thread-card ${isActive ? "active" : ""}"
                data-thread-id="${thread.id}"
                data-search="${escapeHtml((thread.search_blob || "").toLowerCase())}"
            >
                <span class="chat-avatar">${escapeHtml(thread.partner_initials || "?")}</span>
                <div class="chat-thread-body">
                    <div class="chat-thread-topline">
                        <strong>${escapeHtml(thread.partner_name || "-")}</strong>
                        ${isGroup ? '<span class="badge">Grup</span>' : ""}
                        ${thread.partner_online ? '<span class="badge green">Online</span>' : ""}
                    </div>
                    <div class="chat-thread-meta">
                        ${escapeHtml(thread.partner_role_label || "-")} | ${escapeHtml(thread.partner_warehouse_label || "Global")}
                    </div>
                    <p>${escapeHtml((thread.last_message_prefix || "") + (thread.last_message_preview || ""))}</p>
                </div>
                <div class="chat-thread-side">
                    <time>${escapeHtml(thread.last_message_label || "-")}</time>
                    ${unreadCount ? `<span class="chat-unread-badge">${unreadCount > 99 ? "99+" : unreadCount}</span>` : ""}
                </div>
            </a>
        `;
    }

    function renderThreadList(threads) {
        if (!threadList) {
            return;
        }
        if (!Array.isArray(threads) || !threads.length) {
            threadList.innerHTML = '<div class="chat-list-empty">Belum ada thread. Mulai percakapan dari tab kontak atau buat grup baru.</div>';
            return;
        }
        threadList.innerHTML = threads.map(renderThreadCard).join("");
        normalizeChatText(threadList);
        applySearchFilter();
    }

    function renderMessage(message) {
        const mineClass = message.is_mine ? "mine" : "other";
        const senderMeta = message.is_mine ? "" : `
            <div class="chat-message-sender">
                <span class="chat-avatar mini">${escapeHtml(message.sender_initials || "?")}</span>
                <strong>${escapeHtml(message.sender_name || "-")}</strong>
            </div>
        `;

        let bubbleContent = `<p>${escapeHtml(message.body || "")}</p>`;
        if (message.message_type === "attachment") {
            bubbleContent = `
                <div class="chat-message-attachment">
                    <div>
                        <strong>${escapeHtml(message.attachment_name || "Lampiran")}</strong>
                        <span>${escapeHtml(message.attachment_size_label || "")}</span>
                    </div>
                    <a href="${escapeHtml(message.attachment_url || "#")}" target="_blank" rel="noopener">Buka</a>
                </div>
                ${message.body ? `<p>${escapeHtml(message.body)}</p>` : ""}
            `;
        } else if (message.message_type === "sticker") {
            const stickerLabel = (message.sticker && message.sticker.label) || message.body || "Sticker";
            const stickerImageUrl = message.sticker_image_url || message.attachment_url || "";
            bubbleContent = `
                <div class="chat-sticker-bubble ${stickerImageUrl ? "has-image" : ""}">
                    ${stickerImageUrl
                        ? `<img src="${escapeHtml(stickerImageUrl)}" alt="${escapeHtml(stickerLabel)}" loading="lazy">`
                        : `<span>${escapeHtml((message.sticker && message.sticker.emoji) || "\u{1F7E6}")}</span>
                           <strong>${escapeHtml(stickerLabel)}</strong>`}
                </div>
            `;
        } else if (message.message_type === "call") {
            bubbleContent = `
                <div class="chat-call-bubble">
                    <strong>${escapeHtml(message.call_label || "Telp")}</strong>
                    <p>${escapeHtml(message.body || "")}</p>
                </div>
            `;
        }

        return `
            <article class="chat-message-row ${mineClass}" data-message-id="${message.id}">
                ${senderMeta}
                <div class="chat-message-bubble chat-message-type-${escapeHtml(message.message_type || "text")}">
                    ${bubbleContent}
                    <time>${escapeHtml(message.created_label || "-")}</time>
                </div>
            </article>
        `;
    }

    function renderParticipantStrip(selectedThread) {
        if (!participantStrip) {
            return;
        }
        const isGroup = selectedThread && selectedThread.thread_type === "group";
        if (!isGroup) {
            participantStrip.classList.add("is-hidden");
            participantStrip.innerHTML = "";
            return;
        }
        const participants = Array.isArray(selectedThread.participants) ? selectedThread.participants : [];
        const visibleMembers = participants.filter((participant) => !participant.is_current);
        participantStrip.innerHTML = visibleMembers.map((participant) => `
            <span class="chat-member-pill">
                <span class="chat-avatar mini">${escapeHtml(participant.initials || "?")}</span>
                <span>${escapeHtml(participant.username || "-")}</span>
            </span>
        `).join("");
        participantStrip.classList.remove("is-hidden");
    }

    function scrollMessages(force) {
        if (!messageBoard) {
            return;
        }
        const nearBottom = messageBoard.scrollHeight - messageBoard.scrollTop - messageBoard.clientHeight < 180;
        if (force || nearBottom) {
            messageBoard.scrollTop = messageBoard.scrollHeight;
        }
    }

    function appendMessages(messages, forceScroll) {
        if (!messageBoard || !Array.isArray(messages) || !messages.length) {
            return;
        }

        let inserted = false;
        messages.forEach((message) => {
            const messageId = Number(message.id || 0);
            if (messageId <= 0 || messageBoard.querySelector(`[data-message-id="${messageId}"]`)) {
                return;
            }
            messageBoard.insertAdjacentHTML("beforeend", renderMessage(message));
            lastMessageId = Math.max(lastMessageId, messageId);
            inserted = true;
        });

        if (inserted) {
            normalizeChatText(messageBoard);
            scrollMessages(Boolean(forceScroll));
        }
    }

    function updatePartnerState(selectedThread) {
        if (!selectedThread) {
            return;
        }

        const callSupported = selectedThread.thread_type === "direct";

        if (partnerName) {
            partnerName.textContent = selectedThread.partner_name || "";
        }
        if (partnerMeta) {
            const statusSuffix = selectedThread.partner_online ? " | Online" : "";
            partnerMeta.textContent = `${selectedThread.partner_role_label || "-"} | ${selectedThread.partner_warehouse_label || "Global"}${statusSuffix}`;
        }
        if (partnerStatus) {
            partnerStatus.textContent = selectedThread.partner_online ? "Online" : "Offline";
            partnerStatus.className = `badge ${selectedThread.partner_online ? "green" : ""}`.trim();
        }
        if (voiceCallButton) {
            voiceCallButton.disabled = !callSupported;
            voiceCallButton.title = callSupported ? "Mulai voice call" : "Call grup belum didukung";
        }
        if (videoCallButton) {
            videoCallButton.disabled = !callSupported;
            videoCallButton.title = callSupported ? "Mulai video call" : "Call grup belum didukung";
        }
        renderParticipantStrip(selectedThread);
    }

    function autoResizeComposer() {
        if (!composerInput) {
            return;
        }
        composerInput.style.height = "auto";
        composerInput.style.height = `${Math.min(composerInput.scrollHeight, 160)}px`;
    }

    function setComposerState(disabled) {
        if (!composerButton || !composerInput) {
            return;
        }
        composerButton.disabled = disabled;
        composerInput.disabled = disabled;
        composerButton.textContent = disabled ? "Mengirim..." : "Kirim";
    }

    function openGroupModal() {
        if (!groupModal) {
            return;
        }
        groupModal.hidden = false;
        document.body.classList.add("chat-modal-open");
        groupNameInput?.focus();
    }

    function closeGroupModal() {
        if (!groupModal) {
            return;
        }
        groupModal.hidden = true;
        document.body.classList.remove("chat-modal-open");
    }

    function resetAttachmentPreview() {
        pendingAttachment = null;
        if (attachmentInput) {
            attachmentInput.value = "";
        }
        if (attachmentPreview) {
            attachmentPreview.hidden = true;
            attachmentPreview.innerHTML = "";
        }
    }

    function showAttachmentPreview(file) {
        if (!attachmentPreview) {
            return;
        }
        if (!file) {
            resetAttachmentPreview();
            return;
        }
        attachmentPreview.hidden = false;
        attachmentPreview.innerHTML = `
            <div>
                <strong>${escapeHtml(file.name)}</strong>
                <span>${escapeHtml(formatFileSize(file.size))}</span>
            </div>
            <button type="button" class="ghost-button" data-remove-attachment="1">Hapus</button>
        `;
    }

    function toggleStickerPanel(forceState) {
        if (!stickerPanel) {
            return;
        }
        const nextHidden = typeof forceState === "boolean" ? !forceState : !stickerPanel.hidden;
        stickerPanel.hidden = nextHidden;
    }

    async function startThread(targetUserId) {
        try {
            const response = await fetch("/chat/thread/start", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ target_user_id: Number(targetUserId) }),
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "ok") {
                throw new Error(payload.message || "Thread gagal dibuka");
            }
            window.location.href = payload.redirect_url;
        } catch (error) {
            window.alert(error.message || "Thread gagal dibuka");
        }
    }

    async function createGroup() {
        const groupName = (groupNameInput?.value || "").trim();
        const groupDescription = (groupDescriptionInput?.value || "").trim();
        const memberIds = Array.from(groupMemberList?.querySelectorAll('input[type="checkbox"]:checked') || [])
            .map((node) => Number(node.value || 0))
            .filter((value) => value > 0);

        try {
            const response = await fetch("/chat/group/create", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({
                    group_name: groupName,
                    group_description: groupDescription,
                    member_ids: memberIds,
                }),
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "ok") {
                throw new Error(payload.message || "Grup gagal dibuat");
            }
            window.location.href = payload.redirect_url;
        } catch (error) {
            window.alert(error.message || "Grup gagal dibuat");
        }
    }

    async function sendPayload(payload, useFormData) {
        if (!currentThreadId || sendInFlight) {
            return;
        }

        sendInFlight = true;
        setComposerState(true);
        try {
            const options = {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            };
            if (useFormData) {
                options.body = payload;
            } else {
                options.headers["Content-Type"] = "application/json";
                options.body = JSON.stringify(payload);
            }

            const response = await fetch(`/chat/thread/${currentThreadId}/send`, options);
            const result = await response.json();
            if (!response.ok || result.status !== "ok") {
                throw new Error(result.message || "Pesan gagal dikirim");
            }

            if (result.message) {
                appendMessages([result.message], true);
            }
            if (window.WmsChatRealtime?.updateUnreadBadge) {
                window.WmsChatRealtime.updateUnreadBadge(result.unread_total || 0);
            }
            if (payload instanceof FormData || payload.message) {
                if (composerInput) {
                    composerInput.value = "";
                    autoResizeComposer();
                    composerInput.focus();
                }
            }
            resetAttachmentPreview();
            toggleStickerPanel(false);
            await pollNow(true);
        } catch (error) {
            window.alert(error.message || "Pesan gagal dikirim");
        } finally {
            sendInFlight = false;
            setComposerState(false);
        }
    }

    function sendCurrentMessage() {
        const text = (composerInput?.value || "").trim();
        if (pendingAttachment) {
            const formData = new FormData();
            formData.set("message", text);
            formData.set("attachment", pendingAttachment);
            sendPayload(formData, true);
            return;
        }
        if (!text) {
            return;
        }
        sendPayload({ message: text }, false);
    }

    function sendStickerImage(file) {
        if (!file) {
            return;
        }
        if (file.size > maxAttachmentBytes) {
            window.alert(`Sticker maksimal ${formatFileSize(maxAttachmentBytes)} per file.`);
            return;
        }
        const formData = new FormData();
        formData.set("message", (composerInput?.value || "").trim());
        formData.set("sticker_image", file);
        sendPayload(formData, true);
    }

    function applySearchFilter() {
        const query = searchQuery.trim().toLowerCase();
        const nodes = Array.from(document.querySelectorAll(".chat-thread-card, .chat-contact-card"));
        nodes.forEach((node) => {
            if (!query) {
                node.hidden = false;
                return;
            }
            const haystack = (node.dataset.search || "").toLowerCase();
            node.hidden = !haystack.includes(query);
        });
    }

    function setActiveTab(tabName) {
        activeTab = tabName;
        tabButtons.forEach((button) => {
            button.classList.toggle("active", button.dataset.chatTabTarget === tabName);
        });
        tabPanels.forEach((panel) => {
            panel.classList.toggle("active", panel.dataset.chatTab === tabName);
        });
        applySearchFilter();
    }

    function returnToThreadList() {
        if (!window.matchMedia("(max-width: 1080px)").matches || !sidebarPanel) {
            return;
        }
        sidebarPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        if (searchInput) {
            window.setTimeout(() => searchInput.focus(), 220);
        }
    }

    async function pollNow(forceScroll) {
        if (!forceScroll && document.visibilityState === "hidden") {
            return;
        }
        if (pollInFlight) {
            return;
        }

        pollInFlight = true;
        try {
            const params = new URLSearchParams();
            params.set(
                "since_message_id",
                String(window.WmsChatRealtime?.getLastToastMessageId?.() || 0),
            );
            params.set("include_threads", "1");
            if (currentThreadId) {
                params.set("selected_thread_id", String(currentThreadId));
                params.set("after_message_id", String(lastMessageId || 0));
            }

            const response = await fetch(`/chat/realtime?${params.toString()}`, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            if (window.WmsChatRealtime?.syncPayload) {
                window.WmsChatRealtime.syncPayload(payload, { suppressThreadId: currentThreadId });
            }
            if (Array.isArray(payload.threads)) {
                renderThreadList(payload.threads);
            }
            if (payload.selected_thread) {
                updatePartnerState(payload.selected_thread);
                appendMessages(payload.selected_thread.messages || [], forceScroll);
            }
        } catch (error) {
        } finally {
            pollInFlight = false;
        }
    }

    document.addEventListener("click", (event) => {
        const startButton = event.target.closest("[data-start-chat]");
        if (startButton) {
            startThread(startButton.dataset.startChat);
            return;
        }

        if (event.target.closest("[data-remove-attachment]")) {
            resetAttachmentPreview();
        }
    });

    tabButtons.forEach((button) => {
        button.addEventListener("click", () => setActiveTab(button.dataset.chatTabTarget));
    });
    mobileBackButton?.addEventListener("click", returnToThreadList);

    searchInput?.addEventListener("input", (event) => {
        searchQuery = event.target.value || "";
        applySearchFilter();
    });

    createGroupButton?.addEventListener("click", openGroupModal);
    groupCloseButton?.addEventListener("click", closeGroupModal);
    groupCancelButton?.addEventListener("click", closeGroupModal);
    groupSubmitButton?.addEventListener("click", createGroup);
    groupModal?.addEventListener("click", (event) => {
        if (event.target === groupModal) {
            closeGroupModal();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && groupModal && !groupModal.hidden) {
            closeGroupModal();
        }
    });

    attachButton?.addEventListener("click", () => attachmentInput?.click());
    stickerUploadButton?.addEventListener("click", () => stickerImageInput?.click());
    attachmentInput?.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        if (file && file.size > maxAttachmentBytes) {
            pendingAttachment = null;
            showAttachmentPreview(null);
            window.alert(`Lampiran maksimal ${formatFileSize(maxAttachmentBytes)} per file.`);
            return;
        }
        pendingAttachment = file || null;
        showAttachmentPreview(file || null);
    });
    stickerImageInput?.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        if (!file) {
            return;
        }
        sendStickerImage(file);
        event.target.value = "";
    });

    stickerToggle?.addEventListener("click", () => toggleStickerPanel());
    stickerPanel?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-sticker-code]");
        if (!button) {
            return;
        }
        sendPayload({ sticker_code: button.dataset.stickerCode }, false);
    });

    voiceCallButton?.addEventListener("click", () => {
        if (window.WmsChatCall?.startCall) {
            window.WmsChatCall.startCall("voice");
            return;
        }
        sendPayload({ call_mode: "voice" }, false);
    });
    videoCallButton?.addEventListener("click", () => {
        if (window.WmsChatCall?.startCall) {
            window.WmsChatCall.startCall("video");
            return;
        }
        sendPayload({ call_mode: "video" }, false);
    });

    composerInput?.addEventListener("input", autoResizeComposer);
    composerInput?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendCurrentMessage();
        }
    });

    composerForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        sendCurrentMessage();
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            pollNow(false);
        }
    });

    window.WmsChatPage = {
        getCurrentThreadId() {
            return currentThreadId;
        },
    };

    if (Array.isArray(bootstrap.threads)) {
        renderThreadList(bootstrap.threads);
    }
    closeGroupModal();
    autoResizeComposer();
    scrollMessages(true);
    if (window.WmsChatRealtime?.updateUnreadBadge) {
        window.WmsChatRealtime.updateUnreadBadge(bootstrap.unread_total || 0);
    }
    if (bootstrap.selected_thread) {
        updatePartnerState(bootstrap.selected_thread);
    }
    normalizeChatText(shell);
    pollNow(false);
    pollTimer = window.setInterval(() => pollNow(false), pollIntervalMs);

    window.addEventListener("beforeunload", () => {
        if (pollTimer) {
            window.clearInterval(pollTimer);
        }
    });
})();
