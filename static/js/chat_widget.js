(function () {
    const root = document.getElementById("chatWidgetRoot");
    if (!root) {
        return;
    }

    const launcher = root.querySelector("[data-chat-widget-launcher]");
    const panel = root.querySelector("[data-chat-widget-panel]");
    const closeButton = root.querySelector("[data-chat-widget-close]");
    const homeView = root.querySelector("[data-chat-widget-home]");
    const threadView = root.querySelector("[data-chat-widget-thread-view]");
    const threadList = root.querySelector("[data-chat-widget-threads]");
    const contactList = root.querySelector("[data-chat-widget-contacts]");
    const searchInput = root.querySelector("[data-chat-widget-search]");
    const tabButtons = Array.from(root.querySelectorAll("[data-chat-widget-tab]"));
    const tabPanels = Array.from(root.querySelectorAll("[data-chat-widget-panel-name]"));
    const threadBackButton = root.querySelector("[data-chat-widget-back]");
    const threadAvatar = root.querySelector("[data-chat-widget-avatar]");
    const threadPartnerName = root.querySelector("[data-chat-widget-partner-name]");
    const threadPartnerMeta = root.querySelector("[data-chat-widget-partner-meta]");
    const messageBoard = root.querySelector("[data-chat-widget-messages]");
    const composerForm = root.querySelector("[data-chat-widget-composer]");
    const composerInput = root.querySelector("[data-chat-widget-input]");
    const composerSendButton = root.querySelector("[data-chat-widget-send]");
    const composerAttachButton = root.querySelector("[data-chat-widget-attach]");
    const attachmentInput = root.querySelector("[data-chat-widget-attachment]");
    const stickerImageInput = root.querySelector("[data-chat-widget-sticker-image]");
    const attachmentPreview = root.querySelector("[data-chat-widget-attachment-preview]");
    const stickerPanel = root.querySelector("[data-chat-widget-stickers]");
    const stickerToggle = root.querySelector("[data-chat-widget-sticker-toggle]");
    const voiceCallButton = root.querySelector("[data-chat-widget-voice]");
    const videoCallButton = root.querySelector("[data-chat-widget-video]");
    const fullPageButtons = Array.from(root.querySelectorAll("[data-chat-widget-fullpage]"));

    const state = {
        loaded: false,
        loading: false,
        open: false,
        activeTab: "threads",
        searchQuery: "",
        threads: [],
        contacts: [],
        stickers: [],
        currentThreadId: null,
        currentThread: null,
        lastMessageId: 0,
        pendingAttachment: null,
        attachmentMaxBytes: 10 * 1024 * 1024,
        sendInFlight: false,
    };

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

    function normalizeChatText(rootNode) {
        const target = rootNode || document.body;
        if (!target || !window.NodeFilter || !document.createTreeWalker) {
            return;
        }

        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
            if (node.nodeValue) {
                node.nodeValue = node.nodeValue
                    .replace(/ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢/g, "|")
                    .replace(/ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦/g, "...");
            }
            node = walker.nextNode();
        }
    }

    function setPanelOpen(nextOpen) {
        state.open = Boolean(nextOpen);
        root.classList.toggle("is-open", state.open);
        panel.hidden = !state.open;
        panel.setAttribute("aria-hidden", state.open ? "false" : "true");
        launcher.setAttribute("aria-expanded", state.open ? "true" : "false");
        if (!state.open) {
            toggleStickerPanel(false);
        }
        if (state.open) {
            ensureBootstrap();
            if (state.currentThreadId && composerInput) {
                window.setTimeout(() => composerInput.focus(), 80);
            }
        }
    }

    function setActiveTab(tabName) {
        state.activeTab = tabName === "contacts" ? "contacts" : "threads";
        tabButtons.forEach((button) => {
            button.classList.toggle("active", button.dataset.chatWidgetTab === state.activeTab);
        });
        tabPanels.forEach((panelNode) => {
            panelNode.classList.toggle("active", panelNode.dataset.chatWidgetPanelName === state.activeTab);
        });
        applySearchFilter();
    }

    function setThreadMode(enabled) {
        const showThread = Boolean(enabled);
        homeView.hidden = showThread;
        threadView.hidden = !showThread;
    }

    function renderThreadCard(thread) {
        const unreadCount = Number(thread.unread_count || 0);
        return `
            <button
                type="button"
                class="chat-thread-card chat-widget-thread-card"
                data-chat-widget-open-thread="${thread.id}"
                data-search="${escapeHtml((thread.search_blob || "").toLowerCase())}"
            >
                <span class="chat-avatar">${escapeHtml(thread.partner_initials || "?")}</span>
                <div class="chat-thread-body">
                    <div class="chat-thread-topline">
                        <strong>${escapeHtml(thread.partner_name || "-")}</strong>
                        ${thread.thread_type === "group" ? '<span class="badge">Grup</span>' : ""}
                        ${thread.partner_online ? '<span class="badge green">Online</span>' : ""}
                    </div>
                    <div class="chat-thread-meta">${escapeHtml(thread.partner_role_label || "-")} | ${escapeHtml(thread.partner_warehouse_label || "Global")}</div>
                    <p>${escapeHtml((thread.last_message_prefix || "") + (thread.last_message_preview || ""))}</p>
                </div>
                <div class="chat-thread-side">
                    <time>${escapeHtml(thread.last_message_label || "-")}</time>
                    ${unreadCount ? `<span class="chat-unread-badge">${unreadCount > 99 ? "99+" : unreadCount}</span>` : ""}
                </div>
            </button>
        `;
    }

    function renderContactCard(contact) {
        return `
            <button
                type="button"
                class="chat-contact-card chat-widget-contact-card"
                data-chat-widget-start-chat="${contact.id}"
                data-search="${escapeHtml((contact.search_blob || "").toLowerCase())}"
            >
                <span class="chat-avatar">${escapeHtml(contact.initials || "?")}</span>
                <div class="chat-contact-body">
                    <div class="chat-thread-topline">
                        <strong>${escapeHtml(contact.username || "-")}</strong>
                        ${contact.is_online ? '<span class="badge green">Online</span>' : ""}
                    </div>
                    <div class="chat-thread-meta">${escapeHtml(contact.role_label || "-")} | ${escapeHtml(contact.warehouse_label || "Global")}</div>
                </div>
            </button>
        `;
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

    function renderThreadList() {
        if (!threadList) {
            return;
        }
        if (!state.threads.length) {
            threadList.innerHTML = '<div class="chat-list-empty">Belum ada percakapan. Mulai chat dari tab kontak.</div>';
            return;
        }
        threadList.innerHTML = state.threads.map(renderThreadCard).join("");
        normalizeChatText(threadList);
        applySearchFilter();
    }

    function renderContactList() {
        if (!contactList) {
            return;
        }
        if (!state.contacts.length) {
            contactList.innerHTML = '<div class="chat-list-empty">Belum ada kontak chat yang tersedia.</div>';
            return;
        }
        contactList.innerHTML = state.contacts.map(renderContactCard).join("");
        normalizeChatText(contactList);
        applySearchFilter();
    }

    function renderStickerPanel() {
        if (!stickerPanel) {
            return;
        }
        if (!Array.isArray(state.stickers) || !state.stickers.length) {
            stickerPanel.innerHTML = `
                <button
                    type="button"
                    class="chat-sticker-button chat-widget-sticker-button chat-sticker-upload-button"
                    data-chat-widget-upload-sticker="1"
                >
                    <span>+</span>
                    <strong>Upload Sticker</strong>
                </button>
            `;
            return;
        }
        const uploadButton = `
            <button
                type="button"
                class="chat-sticker-button chat-widget-sticker-button chat-sticker-upload-button"
                data-chat-widget-upload-sticker="1"
            >
                <span>+</span>
                <strong>Upload Sticker</strong>
            </button>
        `;
        stickerPanel.innerHTML = uploadButton + state.stickers.map((sticker) => `
            <button
                type="button"
                class="chat-sticker-button chat-widget-sticker-button"
                data-chat-widget-sticker-code="${escapeHtml(sticker.code || "")}"
            >
                <span>${escapeHtml(sticker.emoji || "\u{1F7E6}")}</span>
                <strong>${escapeHtml(sticker.label || "Sticker")}</strong>
            </button>
        `).join("");
        normalizeChatText(stickerPanel);
    }

    function applySearchFilter() {
        const query = (state.searchQuery || "").trim().toLowerCase();
        [threadList, contactList].forEach((listNode) => {
            if (!listNode) {
                return;
            }
            Array.from(listNode.children).forEach((child) => {
                if (child.classList.contains("chat-list-empty")) {
                    child.hidden = false;
                    return;
                }
                const haystack = (child.dataset.search || "").toLowerCase();
                child.hidden = Boolean(query) && !haystack.includes(query);
            });
        });
    }

    function syncHeader(thread) {
        if (!thread) {
            threadAvatar.textContent = "MS";
            threadPartnerName.textContent = "Live Chat";
            threadPartnerMeta.textContent = "Pilih percakapan";
            return;
        }
        threadAvatar.textContent = thread.partner_initials || "MS";
        threadPartnerName.textContent = thread.partner_name || "Live Chat";
        const metaBits = [
            thread.partner_role_label || "-",
            thread.partner_warehouse_label || "Global",
        ];
        if (thread.partner_online) {
            metaBits.push("Online");
        }
        threadPartnerMeta.textContent = metaBits.join(" | ");
    }

    function scrollMessages(force) {
        if (!messageBoard) {
            return;
        }
        const nearBottom = messageBoard.scrollHeight - messageBoard.scrollTop - messageBoard.clientHeight < 140;
        if (force || nearBottom) {
            messageBoard.scrollTop = messageBoard.scrollHeight;
        }
    }

    function replaceMessages(messages) {
        if (!messageBoard) {
            return;
        }
        if (!Array.isArray(messages) || !messages.length) {
            messageBoard.innerHTML = '<div class="chat-list-empty">Belum ada pesan di percakapan ini.</div>';
            state.lastMessageId = 0;
            return;
        }
        messageBoard.innerHTML = messages.map(renderMessage).join("");
        state.lastMessageId = messages.reduce((maxId, item) => Math.max(maxId, Number(item.id || 0)), 0);
        normalizeChatText(messageBoard);
        scrollMessages(true);
    }

    function appendMessages(messages, forceScroll) {
        if (!messageBoard || !Array.isArray(messages) || !messages.length) {
            return;
        }
        const emptyState = messageBoard.querySelector(".chat-list-empty");
        if (emptyState) {
            emptyState.remove();
        }

        let inserted = false;
        messages.forEach((message) => {
            const messageId = Number(message.id || 0);
            if (messageId <= 0 || messageBoard.querySelector(`[data-message-id="${messageId}"]`)) {
                return;
            }
            messageBoard.insertAdjacentHTML("beforeend", renderMessage(message));
            state.lastMessageId = Math.max(state.lastMessageId, messageId);
            inserted = true;
        });

        if (inserted) {
            normalizeChatText(messageBoard);
            scrollMessages(Boolean(forceScroll));
        }
    }

    function autoResizeComposer() {
        if (!composerInput) {
            return;
        }
        composerInput.style.height = "auto";
        composerInput.style.height = `${Math.min(composerInput.scrollHeight, 132)}px`;
    }

    function setComposerState(disabled) {
        if (!composerSendButton || !composerInput) {
            return;
        }
        composerSendButton.disabled = disabled;
        composerInput.disabled = disabled;
        composerAttachButton && (composerAttachButton.disabled = disabled);
        stickerToggle && (stickerToggle.disabled = disabled);
        voiceCallButton && (voiceCallButton.disabled = disabled);
        videoCallButton && (videoCallButton.disabled = disabled);
    }

    function resetAttachmentPreview() {
        state.pendingAttachment = null;
        if (attachmentInput) {
            attachmentInput.value = "";
        }
        if (attachmentPreview) {
            attachmentPreview.hidden = true;
            attachmentPreview.innerHTML = "";
        }
    }

    function toggleStickerPanel(forceState) {
        if (!stickerPanel) {
            return;
        }
        const nextHidden = typeof forceState === "boolean" ? !forceState : !stickerPanel.hidden;
        stickerPanel.hidden = nextHidden;
        if (!nextHidden) {
            renderStickerPanel();
            window.setTimeout(() => scrollMessages(true), 0);
        }
    }

    function showAttachmentPreview(file) {
        if (!attachmentPreview || !file) {
            resetAttachmentPreview();
            return;
        }
        attachmentPreview.hidden = false;
        attachmentPreview.innerHTML = `
            <div>
                <strong>${escapeHtml(file.name)}</strong>
                <span>${escapeHtml(formatFileSize(file.size))}</span>
            </div>
            <button type="button" class="chat-widget-ghost" data-chat-widget-remove-attachment>Hapus</button>
        `;
    }

    async function ensureBootstrap() {
        if (state.loaded || state.loading) {
            return;
        }
        state.loading = true;
        try {
            const response = await fetch("/chat/widget/bootstrap", {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "ok") {
                throw new Error(payload.message || "Widget chat gagal dimuat");
            }
            state.loaded = true;
            state.threads = Array.isArray(payload.threads) ? payload.threads : [];
            state.contacts = Array.isArray(payload.contacts) ? payload.contacts : [];
            state.stickers = Array.isArray(payload.stickers) ? payload.stickers : [];
            state.attachmentMaxBytes = Number(payload.attachment_max_bytes || state.attachmentMaxBytes) || state.attachmentMaxBytes;
            renderThreadList();
            renderContactList();
            renderStickerPanel();
        } catch (error) {
            const fallback = `<div class="chat-list-empty">${escapeHtml(error.message || "Widget chat gagal dimuat")}</div>`;
            if (threadList) {
                threadList.innerHTML = fallback;
            }
            if (contactList) {
                contactList.innerHTML = fallback;
            }
        } finally {
            state.loading = false;
        }
    }

    async function openThread(threadId) {
        const parsedThreadId = Number(threadId || 0);
        if (!parsedThreadId) {
            return;
        }
        try {
            const params = new URLSearchParams({
                selected_thread_id: String(parsedThreadId),
                after_message_id: "0",
                include_threads: "1",
                since_message_id: String(window.WmsChatRealtime?.getLastToastMessageId?.() || 0),
            });
            const response = await fetch(`/chat/realtime?${params.toString()}`, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "ok" || !payload.selected_thread) {
                throw new Error(payload.message || "Percakapan gagal dibuka");
            }

            if (Array.isArray(payload.threads)) {
                state.currentThreadId = parsedThreadId;
                state.threads = payload.threads;
                renderThreadList();
            }

            state.currentThreadId = parsedThreadId;
            state.currentThread = payload.selected_thread;
            syncHeader(payload.selected_thread);
            replaceMessages(Array.isArray(payload.selected_thread.messages) ? payload.selected_thread.messages : []);
            setThreadMode(true);
            resetAttachmentPreview();
            toggleStickerPanel(false);
            if (composerInput) {
                composerInput.value = "";
                autoResizeComposer();
                composerInput.focus();
            }
        } catch (error) {
            window.showToast?.(error.message || "Percakapan gagal dibuka");
        }
    }

    async function startDirectThread(targetUserId) {
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
                throw new Error(payload.message || "Kontak tidak bisa dibuka");
            }
            await openThread(payload.thread_id);
        } catch (error) {
            window.showToast?.(error.message || "Kontak tidak bisa dibuka");
        }
    }

    async function sendPayload(payload, useFormData, options) {
        if (!state.currentThreadId || state.sendInFlight) {
            return;
        }

        const safeOptions = options || {};
        state.sendInFlight = true;
        setComposerState(true);
        try {
            const requestOptions = {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            };
            if (useFormData) {
                requestOptions.body = payload;
            } else {
                requestOptions.headers["Content-Type"] = "application/json";
                requestOptions.body = JSON.stringify(payload);
            }

            const response = await fetch(`/chat/thread/${state.currentThreadId}/send`, requestOptions);
            const result = await response.json();
            if (!response.ok || result.status !== "ok") {
                throw new Error(result.message || "Pesan gagal dikirim");
            }

            if (result.message) {
                appendMessages([result.message], true);
                if (window.WmsChatRealtime?.updateUnreadBadge) {
                    window.WmsChatRealtime.updateUnreadBadge(result.unread_total || 0);
                }
            }
            if (safeOptions.resetComposer !== false && composerInput) {
                composerInput.value = "";
                autoResizeComposer();
            }
            if (safeOptions.resetAttachment !== false) {
                resetAttachmentPreview();
            }
            if (safeOptions.closeStickerPanel !== false) {
                toggleStickerPanel(false);
            }
            composerInput?.focus();
            return result;
        } catch (error) {
            window.showToast?.(error.message || "Pesan gagal dikirim");
            return null;
        } finally {
            state.sendInFlight = false;
            setComposerState(false);
        }
    }

    async function sendMessage(event) {
        event.preventDefault();
        if (!state.currentThreadId) {
            return;
        }

        const message = (composerInput?.value || "").trim();
        if (!message && !state.pendingAttachment) {
            return;
        }

        if (state.pendingAttachment) {
            const formData = new FormData();
            formData.append("message", message);
            formData.append("attachment", state.pendingAttachment);
            await sendPayload(formData, true, {});
            return;
        }

        await sendPayload({ message }, false, {});
    }

    async function sendStickerImage(file) {
        if (!state.currentThreadId) {
            window.showToast?.("Pilih percakapan dulu untuk kirim sticker.");
            return;
        }
        if (!file) {
            return;
        }
        if (state.attachmentMaxBytes && file.size > state.attachmentMaxBytes) {
            window.showToast?.(`Ukuran sticker maksimal ${formatFileSize(state.attachmentMaxBytes)} per file.`);
            return;
        }
        const formData = new FormData();
        formData.append("message", (composerInput?.value || "").trim());
        formData.append("sticker_image", file);
        await sendPayload(formData, true, {});
    }

    function redirectToFullPageCall(mode) {
        if (!state.currentThreadId) {
            window.showToast?.("Pilih percakapan dulu sebelum mulai call.");
            return;
        }

        const activeThread = state.currentThread
            || state.threads.find((thread) => Number(thread.id) === Number(state.currentThreadId))
            || null;
        if (activeThread && activeThread.thread_type !== "direct") {
            window.showToast?.("Call grup belum didukung. Buka chat direct dulu.");
            return;
        }

        const params = new URLSearchParams({
            thread: String(state.currentThreadId),
            call: mode === "video" ? "video" : "voice",
        });
        window.location.href = `/chat/?${params.toString()}`;
    }

    function receiveRealtimePayload(payload) {
        if (Array.isArray(payload.threads)) {
            state.threads = payload.threads;
            renderThreadList();
        }

        if (
            payload.selected_thread
            && state.currentThreadId
            && Number(payload.selected_thread.id) === Number(state.currentThreadId)
        ) {
            state.currentThread = payload.selected_thread;
            syncHeader(payload.selected_thread);
            appendMessages(Array.isArray(payload.selected_thread.messages) ? payload.selected_thread.messages : []);
        }
    }

    function goHome() {
        state.currentThreadId = null;
        state.currentThread = null;
        state.lastMessageId = 0;
        renderThreadList();
        syncHeader(null);
        setThreadMode(false);
        resetAttachmentPreview();
        toggleStickerPanel(false);
    }

    launcher?.addEventListener("click", () => {
        setPanelOpen(!state.open);
    });

    closeButton?.addEventListener("click", () => {
        setPanelOpen(false);
    });

    threadBackButton?.addEventListener("click", () => {
        goHome();
    });

    fullPageButtons.forEach((button) => {
        button.addEventListener("click", () => {
            window.location.href = "/chat/";
        });
    });

    searchInput?.addEventListener("input", () => {
        state.searchQuery = searchInput.value || "";
        applySearchFilter();
    });

    tabButtons.forEach((button) => {
        button.addEventListener("click", () => {
            setActiveTab(button.dataset.chatWidgetTab);
        });
    });

    root.addEventListener("click", (event) => {
        const openThreadButton = event.target.closest("[data-chat-widget-open-thread]");
        if (openThreadButton) {
            openThread(openThreadButton.dataset.chatWidgetOpenThread);
            return;
        }

        const startChatButton = event.target.closest("[data-chat-widget-start-chat]");
        if (startChatButton) {
            startDirectThread(startChatButton.dataset.chatWidgetStartChat);
            return;
        }

        const uploadStickerButton = event.target.closest("[data-chat-widget-upload-sticker]");
        if (uploadStickerButton) {
            stickerImageInput?.click();
            return;
        }

        const removeAttachmentButton = event.target.closest("[data-chat-widget-remove-attachment]");
        if (removeAttachmentButton) {
            resetAttachmentPreview();
        }
    });

    composerAttachButton?.addEventListener("click", () => {
        attachmentInput?.click();
    });

    attachmentInput?.addEventListener("change", () => {
        const file = attachmentInput.files && attachmentInput.files[0];
        if (!file) {
            resetAttachmentPreview();
            return;
        }
        if (state.attachmentMaxBytes && file.size > state.attachmentMaxBytes) {
            resetAttachmentPreview();
            window.showToast?.(`Ukuran lampiran maksimal ${formatFileSize(state.attachmentMaxBytes)} per file.`);
            return;
        }
        state.pendingAttachment = file;
        showAttachmentPreview(file);
    });
    stickerImageInput?.addEventListener("change", async () => {
        const file = stickerImageInput.files && stickerImageInput.files[0];
        if (!file) {
            return;
        }
        await sendStickerImage(file);
        stickerImageInput.value = "";
    });

    composerForm?.addEventListener("submit", sendMessage);

    stickerToggle?.addEventListener("click", () => {
        if (!state.currentThreadId) {
            window.showToast?.("Pilih percakapan dulu untuk kirim sticker.");
            return;
        }
        toggleStickerPanel();
    });

    stickerPanel?.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-chat-widget-sticker-code]");
        if (!button || !state.currentThreadId) {
            return;
        }
        await sendPayload(
            { sticker_code: button.dataset.chatWidgetStickerCode },
            false,
            { resetComposer: false, closeStickerPanel: true }
        );
    });

    voiceCallButton?.addEventListener("click", async () => {
        redirectToFullPageCall("voice");
    });

    videoCallButton?.addEventListener("click", async () => {
        redirectToFullPageCall("video");
    });

    composerInput?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            composerForm?.requestSubmit();
        }
    });
    composerInput?.addEventListener("input", autoResizeComposer);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && state.open) {
            toggleStickerPanel(false);
            setPanelOpen(false);
        }
    });

    document.addEventListener("click", (event) => {
        if (!state.open) {
            return;
        }
        if (root.contains(event.target)) {
            return;
        }
        setPanelOpen(false);
    });

    syncHeader(null);
    setActiveTab("threads");
    setThreadMode(false);
    toggleStickerPanel(false);
    autoResizeComposer();

    window.WmsChatWidget = {
        isOpen() {
            return state.open;
        },
        getActiveThreadId() {
            return state.currentThreadId;
        },
        getLastMessageId() {
            return state.lastMessageId;
        },
        receiveRealtimePayload,
    };
})();
