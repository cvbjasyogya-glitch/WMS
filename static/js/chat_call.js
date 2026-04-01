(function () {
    const bootstrapNode = document.getElementById("chatBootstrapData");
    const callLayer = document.getElementById("chatCallLayer");
    if (!bootstrapNode || !callLayer) {
        return;
    }

    const bootstrap = JSON.parse(bootstrapNode.textContent || "{}");
    const callCard = document.getElementById("chatCallCard");
    const callChip = document.getElementById("chatCallChip");
    const networkBadge = document.getElementById("chatCallNetworkBadge");
    const remoteVideo = document.getElementById("chatCallRemoteVideo");
    const localVideo = document.getElementById("chatCallLocalVideo");
    const fallback = document.getElementById("chatCallFallback");
    const partnerInitials = document.getElementById("chatCallPartnerInitials");
    const partnerName = document.getElementById("chatCallPartnerName");
    const statusText = document.getElementById("chatCallStatusText");
    const hintText = document.getElementById("chatCallHint");
    const acceptButton = document.getElementById("chatCallAcceptButton");
    const declineButton = document.getElementById("chatCallDeclineButton");
    const endButton = document.getElementById("chatCallEndButton");
    const muteButton = document.getElementById("chatCallMuteButton");
    const cameraButton = document.getElementById("chatCallCameraButton");
    const incomingActions = document.getElementById("chatCallIncomingActions");
    const primaryActions = document.getElementById("chatCallPrimaryActions");
    const secondaryActions = document.getElementById("chatCallSecondaryActions");

    const openStatuses = new Set(["pending", "ringing", "connecting", "active"]);
    const terminalStatuses = new Set(["declined", "ended", "missed"]);
    const iceServers = Array.isArray(bootstrap.webrtc_ice_servers) ? bootstrap.webrtc_ice_servers : [];
    const supportsWebRtc = Boolean(
        window.RTCPeerConnection
        && navigator.mediaDevices
        && typeof navigator.mediaDevices.getUserMedia === "function"
    );
    const secureMediaContext = Boolean(
        window.isSecureContext
        || ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname)
    );

    const state = {
        afterSignalId: 0,
        pollTimer: null,
        pollInFlight: false,
        call: null,
        peerConnection: null,
        peerConnectionCallId: null,
        localStream: null,
        remoteStream: null,
        dismissTimer: null,
        endingInFlight: false,
        muted: false,
        cameraOff: false,
    };

    function notify(message) {
        if (!message) {
            return;
        }
        if (typeof window.showToast === "function") {
            window.showToast(message);
            return;
        }
        window.alert(message);
    }

    function isOpenCall(call) {
        return Boolean(call && openStatuses.has(String(call.status || "").toLowerCase()));
    }

    function getSelectedThread() {
        return bootstrap.selected_thread || null;
    }

    function getCurrentThreadId() {
        return Number(bootstrap.current_thread_id || 0) || null;
    }

    function clearDismissTimer() {
        if (state.dismissTimer) {
            window.clearTimeout(state.dismissTimer);
            state.dismissTimer = null;
        }
    }

    function defaultHint(call) {
        if (!secureMediaContext) {
            return "Mic dan kamera browser butuh HTTPS atau localhost supaya panggilan bisa berjalan.";
        }
        if (call && call.can_accept) {
            return "Tekan Angkat untuk menyalakan mic/kamera lalu menerima panggilan.";
        }
        return "Pastikan browser sudah diberi izin microphone dan kamera.";
    }

    function defaultStatus(call) {
        if (!call) {
            return "Menunggu panggilan";
        }

        const status = String(call.status || "").toLowerCase();
        if (status === "active") {
            return "Panggilan aktif";
        }
        if (status === "connecting") {
            return call.is_initiator ? "Menyambungkan panggilan..." : "Menunggu koneksi stabil...";
        }
        if (status === "pending" || status === "ringing") {
            return call.can_accept ? "Panggilan masuk" : "Memanggil...";
        }
        if (status === "declined") {
            return "Panggilan ditolak";
        }
        if (status === "missed") {
            return "Panggilan tidak terjawab";
        }
        if (status === "ended") {
            return "Panggilan berakhir";
        }
        return "Status panggilan diperbarui";
    }

    function setNetworkBadge() {
        if (!networkBadge) {
            return;
        }
        if (!supportsWebRtc) {
            networkBadge.textContent = "Browser Tidak Mendukung";
            networkBadge.className = "badge";
            return;
        }
        if (!secureMediaContext) {
            networkBadge.textContent = "Butuh HTTPS";
            networkBadge.className = "badge";
            return;
        }
        networkBadge.textContent = "WebRTC Ready";
        networkBadge.className = "badge green";
    }

    function updateToggleButtons() {
        if (muteButton) {
            muteButton.textContent = state.muted ? "Unmute" : "Mute";
            muteButton.classList.toggle("is-active", state.muted);
        }
        if (cameraButton) {
            cameraButton.textContent = state.cameraOff ? "Nyalakan Kamera" : "Matikan Kamera";
            cameraButton.classList.toggle("is-active", state.cameraOff);
        }
    }

    function updateVideoVisibility() {
        const isVideoCall = String(state.call?.call_mode || "") === "video";
        const localHasVideo = Boolean(state.localStream && state.localStream.getVideoTracks().length);
        const remoteHasVideo = Boolean(
            remoteVideo
            && remoteVideo.srcObject
            && typeof remoteVideo.srcObject.getVideoTracks === "function"
            && remoteVideo.srcObject.getVideoTracks().length
        );

        if (callCard) {
            callCard.dataset.mode = isVideoCall ? "video" : "voice";
        }
        if (localVideo) {
            localVideo.hidden = !(isVideoCall && localHasVideo);
        }
        if (remoteVideo) {
            remoteVideo.hidden = !(isVideoCall && remoteHasVideo);
        }
        if (cameraButton) {
            cameraButton.hidden = !isVideoCall;
        }
        if (fallback) {
            fallback.classList.toggle("has-remote-video", Boolean(isVideoCall && remoteHasVideo));
        }
    }

    function resetVideoNodes() {
        if (remoteVideo) {
            remoteVideo.pause();
            remoteVideo.srcObject = null;
            remoteVideo.hidden = true;
        }
        if (localVideo) {
            localVideo.pause();
            localVideo.srcObject = null;
            localVideo.hidden = true;
        }
        if (fallback) {
            fallback.classList.remove("has-remote-video");
        }
    }

    function stopLocalStream() {
        if (state.localStream) {
            state.localStream.getTracks().forEach((track) => {
                try {
                    track.stop();
                } catch (error) {
                }
            });
        }
        state.localStream = null;
        if (localVideo) {
            localVideo.pause();
            localVideo.srcObject = null;
            localVideo.hidden = true;
        }
    }

    function resetPeerConnection() {
        if (state.peerConnection) {
            try {
                state.peerConnection.onicecandidate = null;
                state.peerConnection.ontrack = null;
                state.peerConnection.onconnectionstatechange = null;
                state.peerConnection.close();
            } catch (error) {
            }
        }
        state.peerConnection = null;
        state.peerConnectionCallId = null;
        state.remoteStream = null;
        if (remoteVideo) {
            remoteVideo.pause();
            remoteVideo.srcObject = null;
            remoteVideo.hidden = true;
        }
    }

    function resetCallUi() {
        clearDismissTimer();
        resetPeerConnection();
        stopLocalStream();
        state.call = null;
        state.endingInFlight = false;
        state.muted = false;
        state.cameraOff = false;
        callLayer.hidden = true;
        if (incomingActions) {
            incomingActions.hidden = true;
        }
        if (primaryActions) {
            primaryActions.hidden = true;
        }
        if (secondaryActions) {
            secondaryActions.classList.add("is-hidden");
        }
        if (partnerInitials) {
            partnerInitials.textContent = "MS";
        }
        if (partnerName) {
            partnerName.textContent = "Live Chat";
        }
        if (statusText) {
            statusText.textContent = "Menunggu panggilan";
        }
        if (hintText) {
            hintText.textContent = defaultHint(null);
        }
        if (callChip) {
            callChip.textContent = "Voice Call";
        }
        updateToggleButtons();
        setNetworkBadge();
        resetVideoNodes();
    }

    function scheduleDismiss(delayMs) {
        clearDismissTimer();
        state.dismissTimer = window.setTimeout(() => {
            resetCallUi();
        }, Math.max(Number(delayMs || 0), 0));
    }

    function renderCall(call, options) {
        if (!call) {
            return;
        }

        clearDismissTimer();
        state.call = { ...(state.call || {}), ...call };
        const settings = options || {};
        const nextCall = state.call;
        const incomingVisible = Boolean(
            settings.incomingVisible !== undefined ? settings.incomingVisible : nextCall.can_accept
        );
        const showControls = Boolean(
            settings.showControls !== undefined
                ? settings.showControls
                : Boolean(
                    nextCall.is_initiator
                    || ["connecting", "active"].includes(String(nextCall.status || "").toLowerCase())
                )
        );
        const showEndAction = Boolean(
            settings.showEndAction !== undefined ? settings.showEndAction : !incomingVisible
        );

        callLayer.hidden = false;
        if (callChip) {
            callChip.textContent = nextCall.call_label || "Voice Call";
        }
        if (partnerInitials) {
            partnerInitials.textContent = nextCall.partner_initials || "MS";
        }
        if (partnerName) {
            partnerName.textContent = nextCall.partner_name || "Live Chat";
        }
        if (statusText) {
            statusText.textContent = settings.statusText || defaultStatus(nextCall);
        }
        if (hintText) {
            hintText.textContent = settings.hintText || defaultHint(nextCall);
        }
        if (incomingActions) {
            incomingActions.hidden = !incomingVisible;
        }
        if (primaryActions) {
            primaryActions.hidden = !showEndAction;
        }
        if (secondaryActions) {
            secondaryActions.classList.toggle("is-hidden", !showControls);
        }

        updateToggleButtons();
        setNetworkBadge();
        updateVideoVisibility();
    }

    async function requestJson(url, options) {
        const safeOptions = options || {};
        const headers = {
            "X-Requested-With": "XMLHttpRequest",
            ...(safeOptions.headers || {}),
        };
        if (safeOptions.body && !headers["Content-Type"]) {
            headers["Content-Type"] = "application/json";
        }

        const response = await fetch(url, {
            method: safeOptions.method || "GET",
            headers,
            body: safeOptions.body ? JSON.stringify(safeOptions.body) : undefined,
        });
        let payload = {};
        try {
            payload = await response.json();
        } catch (error) {
        }
        if (!response.ok || payload.status !== "ok") {
            const requestError = new Error(payload.message || "Request call gagal diproses.");
            requestError.status = response.status;
            requestError.payload = payload;
            throw requestError;
        }
        return payload;
    }

    function applyLocalTrackState() {
        if (!state.localStream) {
            updateToggleButtons();
            return;
        }
        state.localStream.getAudioTracks().forEach((track) => {
            track.enabled = !state.muted;
        });
        state.localStream.getVideoTracks().forEach((track) => {
            track.enabled = !state.cameraOff;
        });
        updateToggleButtons();
        updateVideoVisibility();
    }

    async function ensureLocalMedia(mode) {
        if (!supportsWebRtc) {
            throw new Error("Browser ini belum mendukung panggilan WebRTC.");
        }
        if (!secureMediaContext) {
            throw new Error("Panggilan browser butuh HTTPS atau localhost untuk mengakses mic dan kamera.");
        }

        const needsVideo = mode === "video";
        const canReuse = Boolean(
            state.localStream
            && state.localStream.getAudioTracks().length
            && (!needsVideo || state.localStream.getVideoTracks().length)
        );
        if (!canReuse) {
            stopLocalStream();
            state.localStream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: needsVideo ? { facingMode: "user" } : false,
            });
        }

        state.muted = false;
        state.cameraOff = false;
        if (localVideo) {
            localVideo.srcObject = state.localStream;
        }
        applyLocalTrackState();
    }

    async function sendSignal(signalType, payload) {
        if (!state.call?.id) {
            return null;
        }
        const result = await requestJson(`/chat/call/${state.call.id}/signal`, {
            method: "POST",
            body: {
                signal_type: signalType,
                payload: payload || {},
            },
        });
        if (result.call) {
            state.call = { ...(state.call || {}), ...result.call };
        }
        return result;
    }

    async function ensurePeerConnection(call) {
        if (!call) {
            throw new Error("Sesi panggilan tidak ditemukan.");
        }
        if (state.peerConnection && Number(state.peerConnectionCallId) === Number(call.id)) {
            return state.peerConnection;
        }

        resetPeerConnection();
        const peerConnection = new RTCPeerConnection({ iceServers });
        state.peerConnection = peerConnection;
        state.peerConnectionCallId = call.id;
        state.remoteStream = new MediaStream();

        if (remoteVideo) {
            remoteVideo.srcObject = state.remoteStream;
        }

        peerConnection.onicecandidate = async (event) => {
            if (!event.candidate || !state.call || Number(state.call.id) !== Number(call.id)) {
                return;
            }
            try {
                const candidatePayload = typeof event.candidate.toJSON === "function"
                    ? event.candidate.toJSON()
                    : {
                        candidate: event.candidate.candidate,
                        sdpMid: event.candidate.sdpMid,
                        sdpMLineIndex: event.candidate.sdpMLineIndex,
                    };
                await sendSignal("ice", { candidate: candidatePayload });
            } catch (error) {
            }
        };

        peerConnection.ontrack = (event) => {
            const incomingStream = event.streams && event.streams[0];
            if (incomingStream && remoteVideo) {
                remoteVideo.srcObject = incomingStream;
            } else if (state.remoteStream && event.track) {
                state.remoteStream.addTrack(event.track);
            }
            updateVideoVisibility();
        };

        peerConnection.onconnectionstatechange = () => {
            const connectionState = String(peerConnection.connectionState || "").toLowerCase();
            if (connectionState === "connected") {
                renderCall(state.call, {
                    statusText: "Panggilan aktif",
                    hintText: "Koneksi sudah tersambung. Anda bisa lanjut bicara sekarang.",
                    showControls: true,
                    showEndAction: true,
                });
                return;
            }
            if (connectionState === "failed") {
                presentTerminalState("Koneksi call gagal", "Jaringan tidak berhasil menyambungkan WebRTC.");
                return;
            }
            if (connectionState === "disconnected") {
                renderCall(state.call, {
                    statusText: "Koneksi putus sementara",
                    hintText: "Mencoba menyambungkan ulang panggilan...",
                    showControls: true,
                    showEndAction: true,
                });
            }
        };

        if (state.localStream) {
            state.localStream.getTracks().forEach((track) => {
                peerConnection.addTrack(track, state.localStream);
            });
        }
        updateVideoVisibility();
        return peerConnection;
    }

    function presentTerminalState(title, hint) {
        if (!state.call) {
            return;
        }
        const terminalCall = { ...(state.call || {}) };
        if (!terminalStatuses.has(String(terminalCall.status || "").toLowerCase())) {
            terminalCall.status = "ended";
        }
        renderCall(terminalCall, {
            statusText: title,
            hintText: hint || "Sesi panggilan sudah selesai.",
            incomingVisible: false,
            showControls: false,
            showEndAction: false,
        });
        resetPeerConnection();
        stopLocalStream();
        scheduleDismiss(2200);
    }

    async function handleAcceptSignal() {
        if (!state.call) {
            return;
        }
        renderCall({ ...state.call, status: "connecting", can_accept: false }, {
            statusText: "Menyambungkan panggilan...",
            hintText: "Lawan bicara sudah menerima. Menyiapkan offer WebRTC...",
            showControls: true,
            showEndAction: true,
        });
        const peerConnection = await ensurePeerConnection(state.call);
        const offer = await peerConnection.createOffer({
            offerToReceiveAudio: true,
            offerToReceiveVideo: state.call.call_mode === "video",
        });
        await peerConnection.setLocalDescription(offer);
        await sendSignal("offer", { sdp: peerConnection.localDescription });
    }

    async function handleOfferSignal(signal) {
        if (!state.call) {
            return;
        }
        await ensureLocalMedia(state.call.call_mode);
        const peerConnection = await ensurePeerConnection(state.call);
        if (!signal.payload?.sdp) {
            return;
        }
        await peerConnection.setRemoteDescription(signal.payload.sdp);
        const answer = await peerConnection.createAnswer();
        await peerConnection.setLocalDescription(answer);
        await sendSignal("answer", { sdp: peerConnection.localDescription });
        renderCall({ ...state.call, status: "active", can_accept: false }, {
            statusText: "Panggilan aktif",
            hintText: "Koneksi sudah tersambung. Anda bisa mulai bicara sekarang.",
            showControls: true,
            showEndAction: true,
        });
    }

    async function handleAnswerSignal(signal) {
        if (!state.call || !state.peerConnection || !signal.payload?.sdp) {
            return;
        }
        await state.peerConnection.setRemoteDescription(signal.payload.sdp);
        renderCall({ ...state.call, status: "active", can_accept: false }, {
            statusText: "Panggilan aktif",
            hintText: "Jawaban dari lawan bicara sudah diterima.",
            showControls: true,
            showEndAction: true,
        });
    }

    async function handleIceSignal(signal) {
        if (!state.peerConnection || !signal.payload?.candidate) {
            return;
        }
        try {
            await state.peerConnection.addIceCandidate(signal.payload.candidate);
        } catch (error) {
        }
    }

    async function handleSignal(signal) {
        if (!signal) {
            return;
        }

        const signalType = String(signal.signal_type || "").toLowerCase();
        if (!state.call || Number(signal.call_id) !== Number(state.call.id)) {
            if (signalType === "invite" && typeof navigator.vibrate === "function") {
                try {
                    navigator.vibrate([140, 80, 140]);
                } catch (error) {
                }
            }
            return;
        }

        if (signalType === "accept") {
            await handleAcceptSignal();
            return;
        }
        if (signalType === "offer") {
            await handleOfferSignal(signal);
            return;
        }
        if (signalType === "answer") {
            await handleAnswerSignal(signal);
            return;
        }
        if (signalType === "ice") {
            await handleIceSignal(signal);
            return;
        }
        if (signalType === "decline") {
            presentTerminalState("Panggilan ditolak", "Lawan bicara menolak panggilan ini.");
            return;
        }
        if (signalType === "end") {
            presentTerminalState("Panggilan berakhir", "Panggilan ditutup oleh lawan bicara.");
        }
    }

    function syncCalls(calls) {
        const callItems = Array.isArray(calls) ? calls : [];
        const matchingCall = state.call
            ? callItems.find((item) => Number(item.id) === Number(state.call.id))
            : null;
        const incomingCall = callItems.find((item) => item.can_accept);

        if (matchingCall) {
            renderCall(matchingCall);
            return;
        }

        if ((!state.call || !isOpenCall(state.call)) && incomingCall) {
            renderCall(incomingCall, {
                statusText: "Panggilan masuk",
                hintText: "Tekan Angkat untuk menerima panggilan browser ini.",
                incomingVisible: true,
                showControls: false,
                showEndAction: false,
            });
            if (typeof navigator.vibrate === "function") {
                try {
                    navigator.vibrate([180, 80, 180]);
                } catch (error) {
                }
            }
            return;
        }

        if (state.call && isOpenCall(state.call) && !matchingCall) {
            presentTerminalState("Panggilan selesai", "Sesi panggilan ini sudah tidak aktif lagi.");
        }
    }

    async function pollCalls() {
        if (state.pollInFlight || document.visibilityState === "hidden") {
            return;
        }

        state.pollInFlight = true;
        try {
            const params = new URLSearchParams({
                after_signal_id: String(state.afterSignalId || 0),
            });
            const payload = await requestJson(`/chat/call/poll?${params.toString()}`);
            syncCalls(payload.calls);
            const signals = Array.isArray(payload.signals) ? payload.signals : [];
            for (const signal of signals) {
                await handleSignal(signal);
            }
            state.afterSignalId = Math.max(
                Number(payload.latest_signal_id || 0),
                state.afterSignalId,
            );
        } catch (error) {
        } finally {
            state.pollInFlight = false;
        }
    }

    async function startCall(mode) {
        if (state.call && isOpenCall(state.call)) {
            renderCall(state.call);
            notify("Masih ada panggilan aktif. Selesaikan dulu sebelum mulai panggilan baru.");
            return;
        }

        const selectedThread = getSelectedThread();
        const currentThreadId = getCurrentThreadId();
        if (!selectedThread || !currentThreadId) {
            notify("Pilih percakapan direct dulu sebelum memulai call.");
            return;
        }
        if (selectedThread.thread_type !== "direct") {
            notify("Call grup belum didukung. Buka chat direct dulu.");
            return;
        }

        try {
            await ensureLocalMedia(mode);
            const payload = await requestJson(`/chat/thread/${currentThreadId}/call/start`, {
                method: "POST",
                body: { mode },
            });
            if (!payload.call) {
                throw new Error("Sesi panggilan tidak berhasil dibuat.");
            }

            await ensurePeerConnection(payload.call);
            renderCall(payload.call, {
                statusText: "Memanggil...",
                hintText: defaultHint(payload.call),
                showControls: true,
                showEndAction: true,
            });
            await pollCalls();
        } catch (error) {
            if (error.status === 409 && error.payload?.call) {
                renderCall(error.payload.call, {
                    statusText: defaultStatus(error.payload.call),
                    hintText: error.message || defaultHint(error.payload.call),
                });
            } else {
                notify(error.message || "Panggilan gagal dimulai.");
                resetCallUi();
            }
        }
    }

    async function acceptCall() {
        if (!state.call?.id || !state.call.can_accept) {
            return;
        }

        try {
            await ensureLocalMedia(state.call.call_mode || "voice");
            await ensurePeerConnection(state.call);
            const payload = await requestJson(`/chat/call/${state.call.id}/accept`, {
                method: "POST",
                body: {},
            });
            if (payload.call) {
                renderCall(payload.call, {
                    statusText: "Menunggu koneksi lawan bicara...",
                    hintText: "Panggilan diterima. Offer WebRTC akan masuk sebentar lagi.",
                    incomingVisible: false,
                    showControls: true,
                    showEndAction: true,
                });
            }
        } catch (error) {
            notify(error.message || "Panggilan gagal diterima.");
            resetCallUi();
        }
    }

    async function declineCall() {
        if (!state.call?.id) {
            resetCallUi();
            return;
        }

        try {
            const payload = await requestJson(`/chat/call/${state.call.id}/decline`, {
                method: "POST",
                body: {},
            });
            if (payload.call) {
                renderCall(payload.call, {
                    statusText: "Panggilan ditolak",
                    hintText: "Sesi panggilan sudah dibatalkan.",
                    incomingVisible: false,
                    showControls: false,
                    showEndAction: false,
                });
            }
        } catch (error) {
        } finally {
            resetPeerConnection();
            stopLocalStream();
            scheduleDismiss(1200);
        }
    }

    async function endCall() {
        if (!state.call?.id || state.endingInFlight) {
            return;
        }

        state.endingInFlight = true;
        try {
            const payload = await requestJson(`/chat/call/${state.call.id}/end`, {
                method: "POST",
                body: {},
            });
            if (payload.call) {
                renderCall(payload.call, {
                    statusText: "Panggilan berakhir",
                    hintText: "Anda menutup sesi panggilan.",
                    incomingVisible: false,
                    showControls: false,
                    showEndAction: false,
                });
            }
        } catch (error) {
        } finally {
            state.endingInFlight = false;
            resetPeerConnection();
            stopLocalStream();
            scheduleDismiss(1200);
        }
    }

    function removeAutoCallQuery() {
        const url = new URL(window.location.href);
        if (!url.searchParams.has("call")) {
            return;
        }
        url.searchParams.delete("call");
        window.history.replaceState({}, "", url.toString());
    }

    acceptButton?.addEventListener("click", () => {
        acceptCall();
    });

    declineButton?.addEventListener("click", () => {
        declineCall();
    });

    endButton?.addEventListener("click", () => {
        endCall();
    });

    muteButton?.addEventListener("click", () => {
        state.muted = !state.muted;
        applyLocalTrackState();
    });

    cameraButton?.addEventListener("click", () => {
        state.cameraOff = !state.cameraOff;
        applyLocalTrackState();
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            pollCalls();
        }
    });

    window.WmsChatCall = {
        startCall,
    };

    setNetworkBadge();
    if (hintText) {
        hintText.textContent = defaultHint(null);
    }
    pollCalls();
    state.pollTimer = window.setInterval(() => {
        pollCalls();
    }, 1800);

    if (bootstrap.auto_start_call_mode) {
        const nextMode = bootstrap.auto_start_call_mode === "video" ? "video" : "voice";
        window.setTimeout(() => {
            startCall(nextMode).finally(() => {
                removeAutoCallQuery();
            });
        }, 160);
    }

    window.addEventListener("beforeunload", () => {
        if (state.pollTimer) {
            window.clearInterval(state.pollTimer);
        }
        if (state.call?.id && isOpenCall(state.call) && navigator.sendBeacon) {
            try {
                navigator.sendBeacon(
                    `/chat/call/${state.call.id}/end`,
                    new Blob([JSON.stringify({})], { type: "application/json" }),
                );
            } catch (error) {
            }
        }
    });
})();
