(function () {
    const config = window.wmsChatRealtimeConfig;
    if (!config || !config.enabled) {
        return;
    }

    const originalTitle = document.title;
    const soundUrl = config.soundUrl || "";
    const configuredVolume = Math.max(0, Math.min(Number(config.soundVolume ?? 0.85), 1));
    const primerAudio = soundUrl ? new Audio(soundUrl) : null;
    let isHydrated = false;
    let lastToastMessageId = 0;
    let heartbeatTimer = null;
    let pollTimer = null;
    let pollInFlight = false;
    let soundUnlocked = false;
    let pendingSound = false;
    let soundHintShown = false;
    let soundUnlockBound = false;
    const compactViewport = window.matchMedia("(max-width: 1080px)").matches;
    const lowDataMode = Boolean(
        navigator.connection
        && (
            navigator.connection.saveData
            || /(?:^|[^a-z])2g/.test(String(navigator.connection.effectiveType || "").toLowerCase())
        )
    );
    const unreadPollIntervalMs = lowDataMode ? 6500 : compactViewport ? 4000 : 2500;
    const heartbeatIntervalMs = lowDataMode ? 22000 : compactViewport ? 16000 : 12000;

    if (primerAudio) {
        primerAudio.preload = "auto";
        primerAudio.volume = configuredVolume;
    }

    function getUnreadNodes() {
        return Array.from(document.querySelectorAll("[data-chat-unread-badge]"));
    }

    function getUnreadSummaryNodes() {
        return Array.from(document.querySelectorAll("[data-chat-unread-total]"));
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
        getUnreadSummaryNodes().forEach((node) => {
            node.textContent = String(safeCount);
        });
        updateDocumentTitle(safeCount);
    }

    function primeSound() {
        if (!primerAudio || soundUnlocked) {
            return;
        }

        try {
            primerAudio.muted = true;
            const playPromise = primerAudio.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise
                    .then(() => {
                        primerAudio.pause();
                        primerAudio.currentTime = 0;
                        primerAudio.muted = false;
                        soundUnlocked = true;

                        if (pendingSound) {
                            pendingSound = false;
                            playSound();
                        }
                    })
                    .catch(() => {
                        primerAudio.muted = false;
                        soundUnlockBound = false;
                    });
            }
        } catch (error) {
            primerAudio.muted = false;
            soundUnlockBound = false;
        }
    }

    function bindSoundUnlock() {
        if (!primerAudio || soundUnlocked || soundUnlockBound) {
            return;
        }

        soundUnlockBound = true;
        ["pointerdown", "keydown", "touchstart"].forEach((eventName) => {
            window.addEventListener(eventName, primeSound, { once: true, passive: true });
        });
    }

    function playSound() {
        if (!soundUrl || configuredVolume <= 0) {
            return;
        }

        try {
            const sound = new Audio(soundUrl);
            sound.preload = "auto";
            sound.currentTime = 0;
            sound.volume = configuredVolume;
            const playPromise = sound.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {
                    pendingSound = true;
                    bindSoundUnlock();
                    if (!soundHintShown && typeof window.showToast === "function") {
                        soundHintShown = true;
                        window.showToast("Klik sekali di halaman untuk mengaktifkan suara notifikasi chat.");
                    }
                });
            }
        } catch (error) {
            pendingSound = true;
            bindSoundUnlock();
        }

        try {
            if (navigator.vibrate) {
                navigator.vibrate(120);
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

            const sourceLabel = item.thread_label && item.thread_label !== item.sender_name
                ? `${item.sender_name || "Pesan baru"} | ${item.thread_label}`
                : (item.sender_name || "Pesan baru");
            const preview = `${sourceLabel}: ${item.preview || ""}`
                .replace(/â€¢/g, "|")
                .replace(/â€¦/g, "...")
                .trim();
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
        if (window.__WMS_CHAT_PAGE__ || pollInFlight || document.visibilityState === "hidden") {
            return;
        }

        pollInFlight = true;
        try {
            const widgetApi = window.WmsChatWidget;
            const widgetOpen = Boolean(widgetApi && typeof widgetApi.isOpen === "function" && widgetApi.isOpen());
            const widgetThreadId = widgetOpen && widgetApi && typeof widgetApi.getActiveThreadId === "function"
                ? widgetApi.getActiveThreadId()
                : null;
            const widgetLastMessageId = widgetOpen && widgetApi && typeof widgetApi.getLastMessageId === "function"
                ? widgetApi.getLastMessageId()
                : 0;
            const params = new URLSearchParams({
                since_message_id: String(lastToastMessageId),
            });
            if (widgetOpen) {
                params.set("include_threads", "1");
                if (widgetThreadId) {
                    params.set("selected_thread_id", String(widgetThreadId));
                    params.set("after_message_id", String(widgetLastMessageId || 0));
                }
            }
            const response = await fetch(
                `${config.pollUrl}?${params.toString()}`,
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
            syncPayload(payload, { suppressThreadId: widgetOpen ? widgetThreadId : null });
            if (widgetOpen && widgetApi && typeof widgetApi.receiveRealtimePayload === "function") {
                widgetApi.receiveRealtimePayload(payload);
            }
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

    bindSoundUnlock();
    sendHeartbeat();
    if (!window.__WMS_CHAT_PAGE__) {
        pollUnreadOnly();
        pollTimer = window.setInterval(pollUnreadOnly, unreadPollIntervalMs);
    }
    heartbeatTimer = window.setInterval(sendHeartbeat, heartbeatIntervalMs);

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
