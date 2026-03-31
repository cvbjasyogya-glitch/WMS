(function () {
    const config = window.wmsChatRealtimeConfig;
    if (!config || !config.enabled) {
        return;
    }

    const originalTitle = document.title;
    const audio = config.soundUrl ? new Audio(config.soundUrl) : null;
    let isHydrated = false;
    let lastToastMessageId = 0;
    let heartbeatTimer = null;
    let pollTimer = null;
    let pollInFlight = false;

    function getUnreadNodes() {
        return Array.from(document.querySelectorAll("#chatSidebarUnread"));
    }

    function updateDocumentTitle(count) {
        if (count > 0) {
            document.title = `(${count}) ${originalTitle}`;
            return;
        }
        document.title = originalTitle;
    }

    function updateUnreadBadge(count) {
        const safeCount = Math.max(Number(count || 0), 0);
        getUnreadNodes().forEach((node) => {
            node.hidden = safeCount <= 0;
            node.textContent = safeCount > 99 ? "99+" : String(safeCount);
        });
        updateDocumentTitle(safeCount);
    }

    function playSound() {
        if (!audio) {
            return;
        }
        try {
            audio.currentTime = 0;
            const playPromise = audio.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
        } catch (error) {
        }
    }

    function pushIncomingNotifications(items, suppressThreadId) {
        items.forEach((item) => {
            const messageId = Number(item.id || 0);
            if (messageId <= lastToastMessageId) {
                return;
            }
            lastToastMessageId = messageId;

            if (
                suppressThreadId &&
                Number(item.thread_id || 0) === Number(suppressThreadId) &&
                document.visibilityState === "visible"
            ) {
                return;
            }

            const preview = `${item.sender_name || "Pesan baru"}: ${item.preview || ""}`.trim();
            if (typeof window.showToast === "function") {
                window.showToast(preview);
            }
            playSound();
        });
    }

    function syncPayload(payload, options) {
        const settings = options || {};
        updateUnreadBadge(payload.unread_total || 0);

        const latestIncomingId = Number(payload.latest_incoming_id || 0);
        if (!isHydrated) {
            isHydrated = true;
            lastToastMessageId = Math.max(lastToastMessageId, latestIncomingId);
            return;
        }

        const incoming = Array.isArray(payload.incoming) ? payload.incoming : [];
        pushIncomingNotifications(incoming, settings.suppressThreadId || null);
        lastToastMessageId = Math.max(lastToastMessageId, latestIncomingId);
    }

    async function sendHeartbeat() {
        try {
            const threadId = typeof window.WmsChatPage?.getCurrentThreadId === "function"
                ? window.WmsChatPage.getCurrentThreadId()
                : null;

            await fetch(config.presenceUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({
                    path: `${window.location.pathname}${window.location.search}`,
                    thread_id: threadId || null,
                }),
            });
        } catch (error) {
        }
    }

    async function pollUnreadOnly() {
        if (window.__WMS_CHAT_PAGE__ || pollInFlight) {
            return;
        }

        pollInFlight = true;
        try {
            const response = await fetch(
                `${config.pollUrl}?since_message_id=${encodeURIComponent(lastToastMessageId)}`,
                {
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                },
            );
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            syncPayload(payload, {});
        } catch (error) {
        } finally {
            pollInFlight = false;
        }
    }

    window.WmsChatRealtime = {
        updateUnreadBadge,
        syncPayload,
        sendHeartbeat,
        getLastToastMessageId() {
            return lastToastMessageId;
        },
        setHydrated(latestMessageId) {
            isHydrated = true;
            lastToastMessageId = Math.max(lastToastMessageId, Number(latestMessageId || 0));
        },
    };

    sendHeartbeat();
    if (!window.__WMS_CHAT_PAGE__) {
        pollUnreadOnly();
        pollTimer = window.setInterval(pollUnreadOnly, 2500);
    }
    heartbeatTimer = window.setInterval(sendHeartbeat, 12000);

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") {
            return;
        }
        sendHeartbeat();
        if (!window.__WMS_CHAT_PAGE__) {
            pollUnreadOnly();
        }
    });

    window.addEventListener("beforeunload", () => {
        if (pollTimer) {
            window.clearInterval(pollTimer);
        }
        if (heartbeatTimer) {
            window.clearInterval(heartbeatTimer);
        }
    });
})();
