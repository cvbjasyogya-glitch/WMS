(function () {
    const config = window.wmsChatRealtimeConfig;
    if (!config || !config.enabled) {
        return;
    }

    const originalTitle = document.title;
    const soundUrl = config.soundUrl || "";
    const callPollUrl = config.callPollUrl || "";
    const presenceUrl = config.presenceUrl || "/chat/presence";
    const callRingtoneUrl = config.callRingtoneUrl || soundUrl;
    const configuredVolume = Math.max(0, Math.min(Number(config.soundVolume ?? 0.85), 1));
    const callVolume = Math.max(0, Math.min(Number(config.callVolume ?? configuredVolume), 1));
    const primerAudio = soundUrl ? new Audio(soundUrl) : null;
    const callPrimerAudio = callRingtoneUrl ? new Audio(callRingtoneUrl) : null;
    const incomingBanner = document.getElementById("chatIncomingBanner");
    const incomingBannerAvatar = document.getElementById("chatIncomingBannerAvatar");
    const incomingBannerTitle = document.getElementById("chatIncomingBannerTitle");
    const incomingBannerMeta = document.getElementById("chatIncomingBannerMeta");
    const incomingBannerAccept = document.getElementById("chatIncomingBannerAccept");
    const incomingBannerDecline = document.getElementById("chatIncomingBannerDecline");

    let isHydrated = false;
    let lastToastMessageId = 0;
    let lastCallSignalId = 0;
    let heartbeatTimer = null;
    let pollTimer = null;
    let callPollTimer = null;
    let pollInFlight = false;
    let callPollInFlight = false;
    let soundUnlocked = false;
    let pendingSound = false;
    let pendingCallSound = false;
    let soundHintShown = false;
    let soundUnlockBound = false;
    let activeIncomingCall = null;
    let activeCallRingtone = null;
    let bannerActionInFlight = false;
    const compactViewport = window.matchMedia("(max-width: 1080px)").matches;
    const deviceProfile = window.wmsDeviceProfile || {};
    const lowEndDevice = Boolean(deviceProfile.lowEnd);
    const lowDataMode = Boolean(
        lowEndDevice
        || (
        navigator.connection
        && (
            navigator.connection.saveData
            || /(?:^|[^a-z])2g/.test(String(navigator.connection.effectiveType || "").toLowerCase())
        )
        )
    );
    const unreadPollIntervalMs = lowDataMode ? 6500 : compactViewport ? 4000 : 2500;
    const idleUnreadPollIntervalMs = lowDataMode ? 9000 : compactViewport ? 6500 : 4500;
    const heartbeatIntervalMs = lowDataMode ? 45000 : compactViewport ? 30000 : 25000;
    const callPollIntervalMs = lowDataMode ? 3500 : compactViewport ? 2400 : 1800;
    const idleCallPollIntervalMs = lowDataMode ? 5000 : compactViewport ? 3200 : 2400;
    let lastRealtimeActivityAt = Date.now();
    const leaderRetryIntervalMs = 7000;
    const pollLockKey = "wms:chat:global-poll-lock";
    const pollLockTtlMs = 30000;
    const tabId = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

    [
        [primerAudio, configuredVolume],
        [callPrimerAudio, callVolume],
    ].forEach(([audioNode, volume]) => {
        if (!audioNode) {
            return;
        }
        audioNode.preload = "auto";
        audioNode.volume = volume;
    });

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

    function primeAudioElement(audioNode) {
        return new Promise((resolve, reject) => {
            if (!audioNode) {
                resolve(false);
                return;
            }

            try {
                audioNode.muted = true;
                const playPromise = audioNode.play();
                if (playPromise && typeof playPromise.catch === "function") {
                    playPromise
                        .then(() => {
                            audioNode.pause();
                            audioNode.currentTime = 0;
                            audioNode.muted = false;
                            resolve(true);
                        })
                        .catch((error) => {
                            audioNode.muted = false;
                            reject(error);
                        });
                    return;
                }
                audioNode.pause();
                audioNode.currentTime = 0;
                audioNode.muted = false;
                resolve(true);
            } catch (error) {
                audioNode.muted = false;
                reject(error);
            }
        });
    }

    function primeSound() {
        if (soundUnlocked) {
            return;
        }

        const primerNodes = [primerAudio, callPrimerAudio].filter(Boolean);
        if (!primerNodes.length) {
            soundUnlocked = true;
            return;
        }

        Promise.allSettled(primerNodes.map((audioNode) => primeAudioElement(audioNode)))
            .then((results) => {
                if (!results.some((item) => item.status === "fulfilled")) {
                    soundUnlockBound = false;
                    return;
                }

                soundUnlocked = true;
                if (pendingSound) {
                    pendingSound = false;
                    playSound();
                }
                if (pendingCallSound) {
                    pendingCallSound = false;
                    startCallRingtone();
                }
            })
            .catch(() => {
                soundUnlockBound = false;
            });
    }

    function bindSoundUnlock() {
        if (soundUnlocked || soundUnlockBound) {
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

    function stopCallRingtone() {
        pendingCallSound = false;
        if (!activeCallRingtone) {
            return;
        }
        try {
            activeCallRingtone.pause();
            activeCallRingtone.currentTime = 0;
        } catch (error) {
        }
        activeCallRingtone = null;
    }

    function startCallRingtone() {
        if (!callRingtoneUrl || callVolume <= 0 || activeCallRingtone) {
            return;
        }

        try {
            const ringtone = new Audio(callRingtoneUrl);
            ringtone.preload = "auto";
            ringtone.loop = true;
            ringtone.currentTime = 0;
            ringtone.volume = callVolume;
            activeCallRingtone = ringtone;
            const playPromise = ringtone.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {
                    if (activeCallRingtone === ringtone) {
                        activeCallRingtone = null;
                    }
                    pendingCallSound = true;
                    bindSoundUnlock();
                    if (!soundHintShown && typeof window.showToast === "function") {
                        soundHintShown = true;
                        window.showToast("Klik sekali di halaman untuk mengaktifkan suara notifikasi call.");
                    }
                });
            }
        } catch (error) {
            pendingCallSound = true;
            bindSoundUnlock();
        }

        try {
            if (navigator.vibrate) {
                navigator.vibrate([180, 90, 180, 90, 180]);
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
                suppressThreadId
                && Number(item.thread_id || 0) === Number(suppressThreadId) &&
                document.visibilityState === "visible"
            ) {
                return;
            }

            const sourceLabel = item.thread_label && item.thread_label !== item.sender_name
                ? `${item.sender_name || "Pesan baru"} | ${item.thread_label}`
                : (item.sender_name || "Pesan baru");
            const preview = `${sourceLabel}: ${item.preview || ""}`
                .replace(/Ã¢â‚¬Â¢/g, "|")
                .replace(/Ã¢â‚¬Â¦/g, "...")
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
        if (incoming.length || Number(payload.unread_total || 0) > 0) {
            markRealtimeActivity();
        }
        pushIncomingNotifications(incoming, settings.suppressThreadId || null);
        lastToastMessageId = Math.max(lastToastMessageId, latestIncomingId);
    }

    function setBannerBusy(isBusy) {
        bannerActionInFlight = Boolean(isBusy);
        [incomingBannerAccept, incomingBannerDecline].forEach((button) => {
            if (!button) {
                return;
            }
            button.disabled = bannerActionInFlight;
        });
    }

    function buildPickupUrl(call) {
        const url = new URL("/chat/", window.location.origin);
        url.searchParams.set("thread", String(call.thread_id || 0));
        url.searchParams.set("pickup_call", String(call.id || 0));
        return url.toString();
    }

    function hideIncomingCallBanner() {
        activeIncomingCall = null;
        setBannerBusy(false);
        if (incomingBanner) {
            incomingBanner.hidden = true;
            incomingBanner.classList.remove("is-ringing");
        }
        stopCallRingtone();
    }

    function showIncomingCallBanner(call) {
        if (!incomingBanner || !call || window.__WMS_CHAT_PAGE__) {
            return;
        }

        markRealtimeActivity();
        const previousCallId = Number(activeIncomingCall?.id || 0);
        activeIncomingCall = call;
        if (incomingBannerAvatar) {
            incomingBannerAvatar.textContent = call.partner_initials || "MS";
        }
        if (incomingBannerTitle) {
            incomingBannerTitle.textContent = `${call.call_label || "Telp"} dari ${call.partner_name || "Live Chat"}`;
        }
        if (incomingBannerMeta) {
            incomingBannerMeta.textContent = `${call.partner_role_label || "-"} | ${call.partner_warehouse_label || "Global"}`;
        }
        incomingBanner.hidden = false;
        incomingBanner.classList.add("is-ringing");
        setBannerBusy(false);
        startCallRingtone();

        if (Number(call.id || 0) !== previousCallId && typeof window.showToast === "function") {
            window.showToast(`${call.call_label || "Telp"} masuk dari ${call.partner_name || "kontak"}.`);
        }
    }

    async function declineIncomingCall() {
        if (!activeIncomingCall || bannerActionInFlight) {
            return;
        }

        setBannerBusy(true);
        try {
            const response = await fetch(`/chat/call/${activeIncomingCall.id}/decline`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({}),
            });
            if (!response.ok) {
                throw new Error("Decline call gagal diproses.");
            }
            hideIncomingCallBanner();
            if (typeof window.showToast === "function") {
                window.showToast("Panggilan ditolak.");
            }
        } catch (error) {
            setBannerBusy(false);
            if (typeof window.showToast === "function") {
                window.showToast("Panggilan belum bisa ditolak. Coba lagi.");
            }
        }
    }

    function syncCallPayload(payload) {
        const calls = Array.isArray(payload.calls) ? payload.calls : [];
        const incomingCall = calls.find((item) => item && item.can_accept);
        if (incomingCall) {
            showIncomingCallBanner(incomingCall);
        } else if (activeIncomingCall) {
            hideIncomingCallBanner();
        }
        lastCallSignalId = Math.max(lastCallSignalId, Number(payload.latest_signal_id || 0));
    }

    function stopRealtimeLoops() {
        if (pollTimer) {
            window.clearTimeout(pollTimer);
            pollTimer = null;
        }
        if (callPollTimer) {
            window.clearTimeout(callPollTimer);
            callPollTimer = null;
        }
        if (heartbeatTimer) {
            window.clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    function markRealtimeActivity() {
        lastRealtimeActivityAt = Date.now();
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
            expiresAt: Date.now() + pollLockTtlMs,
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

    function resolveUnreadPollDelayMs() {
        const widgetApi = window.WmsChatWidget;
        const widgetOpen = Boolean(widgetApi && typeof widgetApi.isOpen === "function" && widgetApi.isOpen());
        if (widgetOpen || Date.now() - lastRealtimeActivityAt <= 60000) {
            return unreadPollIntervalMs;
        }
        return idleUnreadPollIntervalMs;
    }

    function resolveCallPollDelayMs() {
        if (activeIncomingCall || Date.now() - lastRealtimeActivityAt <= 60000) {
            return callPollIntervalMs;
        }
        return idleCallPollIntervalMs;
    }

    function scheduleUnreadPoll(delayMs) {
        if (window.__WMS_CHAT_PAGE__ || document.visibilityState === "hidden") {
            return;
        }
        if (pollTimer) {
            window.clearTimeout(pollTimer);
        }
        const nextDelay = canPollInThisTab()
            ? Math.max(Number(delayMs || resolveUnreadPollDelayMs()), 500)
            : leaderRetryIntervalMs;
        pollTimer = window.setTimeout(async () => {
            pollTimer = null;
            await pollUnreadOnly();
        }, nextDelay);
    }

    function scheduleCallPoll(delayMs) {
        if (window.__WMS_CHAT_PAGE__ || document.visibilityState === "hidden") {
            return;
        }
        if (callPollTimer) {
            window.clearTimeout(callPollTimer);
        }
        const nextDelay = canPollInThisTab()
            ? Math.max(Number(delayMs || resolveCallPollDelayMs()), 500)
            : leaderRetryIntervalMs;
        callPollTimer = window.setTimeout(async () => {
            callPollTimer = null;
            await pollIncomingCalls();
        }, nextDelay);
    }

    function startRealtimeLoops() {
        if (document.visibilityState === "hidden") {
            return;
        }

        if (!window.__WMS_CHAT_PAGE__) {
            markRealtimeActivity();
            scheduleUnreadPoll(unreadPollIntervalMs);
            scheduleCallPoll(callPollIntervalMs);
            pollUnreadOnly();
            pollIncomingCalls();
        }

        if (!heartbeatTimer) {
            heartbeatTimer = window.setInterval(() => {
                if (document.visibilityState !== "hidden") {
                    sendHeartbeat();
                }
            }, heartbeatIntervalMs);
        }
    }

    async function sendHeartbeat() {
        try {
            const threadId = typeof window.WmsChatPage?.getCurrentThreadId === "function"
                ? window.WmsChatPage.getCurrentThreadId()
                : null;

            await fetch(presenceUrl, {
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
        if (!canPollInThisTab()) {
            scheduleUnreadPoll(leaderRetryIntervalMs);
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
            writePollLock();
            scheduleUnreadPoll();
        }
    }

    async function pollIncomingCalls() {
        if (window.__WMS_CHAT_PAGE__ || !callPollUrl || callPollInFlight || document.visibilityState === "hidden") {
            return;
        }
        if (!canPollInThisTab()) {
            scheduleCallPoll(leaderRetryIntervalMs);
            return;
        }

        callPollInFlight = true;
        try {
            const response = await fetch(`${callPollUrl}?after_signal_id=${encodeURIComponent(String(lastCallSignalId || 0))}`, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            syncCallPayload(payload);
        } catch (error) {
        } finally {
            callPollInFlight = false;
            writePollLock();
            scheduleCallPoll();
        }
    }

    incomingBannerAccept?.addEventListener("click", () => {
        if (!activeIncomingCall || bannerActionInFlight) {
            return;
        }
        stopCallRingtone();
        setBannerBusy(true);
        window.location.href = buildPickupUrl(activeIncomingCall);
    });

    incomingBannerDecline?.addEventListener("click", () => {
        declineIncomingCall();
    });

    window.WmsChatRealtime = {
        updateUnreadBadge,
        syncPayload,
        sendHeartbeat,
        playSound,
        startCallRingtone,
        stopCallRingtone,
        getLastToastMessageId() {
            return lastToastMessageId;
        },
        setHydrated(latestMessageId) {
            isHydrated = true;
            lastToastMessageId = Math.max(lastToastMessageId, Number(latestMessageId || 0));
        },
    };

    bindSoundUnlock();
    markRealtimeActivity();
    sendHeartbeat();
    startRealtimeLoops();

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") {
            stopRealtimeLoops();
            releasePollLeadership();
            return;
        }
        sendHeartbeat();
        markRealtimeActivity();
        startRealtimeLoops();
    });

    window.addEventListener("pageshow", () => {
        sendHeartbeat();
        markRealtimeActivity();
        startRealtimeLoops();
    });

    window.addEventListener("pagehide", () => {
        stopRealtimeLoops();
        stopCallRingtone();
        releasePollLeadership();
    });

    window.addEventListener("beforeunload", () => {
        stopRealtimeLoops();
        stopCallRingtone();
        releasePollLeadership();
    });

    window.addEventListener("storage", (event) => {
        if (event.key !== pollLockKey || document.visibilityState !== "visible" || window.__WMS_CHAT_PAGE__) {
            return;
        }
        markRealtimeActivity();
        scheduleUnreadPoll(leaderRetryIntervalMs);
        scheduleCallPoll(leaderRetryIntervalMs);
    });
})();
