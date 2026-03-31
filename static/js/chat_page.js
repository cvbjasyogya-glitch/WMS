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
    const searchInput = document.getElementById("chatSearchInput");
    const tabButtons = Array.from(document.querySelectorAll("[data-chat-tab-target]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-chat-tab]"));
    const partnerName = document.getElementById("chatPartnerName");
    const partnerMeta = document.getElementById("chatPartnerMeta");
    const partnerStatus = document.getElementById("chatPartnerStatus");

    let currentThreadId = Number(shell.dataset.currentThreadId || bootstrap.current_thread_id || 0) || null;
    let lastMessageId = Number(shell.dataset.lastMessageId || bootstrap.current_thread_last_message_id || 0) || 0;
    let searchQuery = "";
    let activeTab = "threads";
    let pollTimer = null;
    let pollInFlight = false;
    let sendInFlight = false;

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function renderThreadCard(thread) {
        const unreadCount = Number(thread.unread_count || 0);
        const isActive = currentThreadId && Number(thread.id) === Number(currentThreadId);
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
                        ${thread.partner_online ? '<span class="badge green">Online</span>' : ""}
                    </div>
                    <div class="chat-thread-meta">
                        ${escapeHtml(thread.partner_role_label || "-")} • ${escapeHtml(thread.partner_warehouse_label || "Global")}
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
            threadList.innerHTML = '<div class="chat-list-empty">Belum ada thread. Mulai percakapan dari tab kontak atau leader.</div>';
            return;
        }

        threadList.innerHTML = threads.map(renderThreadCard).join("");
        applySearchFilter();
    }

    function renderMessage(message) {
        const mineClass = message.is_mine ? "mine" : "other";
        const senderMeta = message.is_mine
            ? ""
            : `
                <div class="chat-message-sender">
                    <span class="chat-avatar mini">${escapeHtml(message.sender_initials || "?")}</span>
                    <strong>${escapeHtml(message.sender_name || "-")}</strong>
                </div>
            `;

        return `
            <article class="chat-message-row ${mineClass}" data-message-id="${message.id}">
                ${senderMeta}
                <div class="chat-message-bubble">
                    <p>${escapeHtml(message.body || "")}</p>
                    <time>${escapeHtml(message.created_label || "-")}</time>
                </div>
            </article>
        `;
    }

    function scrollMessages(force) {
        if (!messageBoard) {
            return;
        }

        const nearBottom =
            messageBoard.scrollHeight - messageBoard.scrollTop - messageBoard.clientHeight < 180;

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
            scrollMessages(Boolean(forceScroll));
        }
    }

    function updatePartnerState(selectedThread) {
        if (!selectedThread) {
            return;
        }

        if (partnerName) {
            partnerName.textContent = selectedThread.partner_name || "";
        }

        if (partnerMeta) {
            const statusSuffix = selectedThread.partner_online ? " • Online" : "";
            partnerMeta.textContent = `${selectedThread.partner_role_label || "-"} • ${selectedThread.partner_warehouse_label || "Global"}${statusSuffix}`;
        }

        if (partnerStatus) {
            partnerStatus.textContent = selectedThread.partner_online ? "Online" : "Offline";
            partnerStatus.className = `badge ${selectedThread.partner_online ? "green" : ""}`.trim();
        }
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

    async function sendMessage(text) {
        if (!currentThreadId || !text || sendInFlight) {
            return;
        }

        sendInFlight = true;
        setComposerState(true);
        try {
            const response = await fetch(`/chat/thread/${currentThreadId}/send`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ message: text }),
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "ok") {
                throw new Error(payload.message || "Pesan gagal dikirim");
            }

            if (payload.message) {
                appendMessages([payload.message], true);
            }

            if (window.WmsChatRealtime?.updateUnreadBadge) {
                window.WmsChatRealtime.updateUnreadBadge(payload.unread_total || 0);
            }

            if (composerInput) {
                composerInput.value = "";
                autoResizeComposer();
                composerInput.focus();
            }

            await pollNow(true);
        } catch (error) {
            window.alert(error.message || "Pesan gagal dikirim");
        } finally {
            sendInFlight = false;
            setComposerState(false);
        }
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

    async function pollNow(forceScroll) {
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
                window.WmsChatRealtime.syncPayload(payload, {
                    suppressThreadId: currentThreadId,
                });
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
        }
    });

    tabButtons.forEach((button) => {
        button.addEventListener("click", () => {
            setActiveTab(button.dataset.chatTabTarget);
        });
    });

    searchInput?.addEventListener("input", (event) => {
        searchQuery = event.target.value || "";
        applySearchFilter();
    });

    composerInput?.addEventListener("input", autoResizeComposer);
    composerInput?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            const text = composerInput.value.trim();
            if (text) {
                sendMessage(text);
            }
        }
    });

    composerForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = composerInput?.value.trim();
        if (text) {
            sendMessage(text);
        }
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
    autoResizeComposer();
    scrollMessages(true);
    if (window.WmsChatRealtime?.updateUnreadBadge) {
        window.WmsChatRealtime.updateUnreadBadge(bootstrap.unread_total || 0);
    }
    pollNow(false);
    pollTimer = window.setInterval(() => pollNow(false), 2500);

    window.addEventListener("beforeunload", () => {
        if (pollTimer) {
            window.clearInterval(pollTimer);
        }
    });
})();
