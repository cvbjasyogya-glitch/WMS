(function () {
    const root = document.getElementById("meetingSessionRoot");
    if (!root) {
        return;
    }

    const provider = root.dataset.provider || "jitsi";
    const meetingDomain = root.dataset.meetingDomain || "meet.jit.si";
    const leaveUrl = root.dataset.leaveUrl || "/meetings/";
    const participantLimit = Number(root.dataset.participantLimit || 10);
    const stageTitle = document.getElementById("meetingStageTitle");
    const stageDescription = document.getElementById("meetingStageDescription");
    const stageError = document.getElementById("meetingStageError");
    const stageBox = document.getElementById("meetingStageBox");
    const stageHost = document.getElementById("meetingStageHost");
    const profilePill = document.getElementById("meetingStageProfilePill");
    const networkPill = document.getElementById("meetingStageNetworkPill");
    const participantPill = document.getElementById("meetingStageParticipantPill");
    const stageLoader = document.getElementById("meetingStageLoader");
    const stageHints = document.getElementById("meetingStageHints");
    const MEETING_STATE_KEY_PREFIX = "wms-meeting-state:";
    const MEETING_STATE_TTL_MS = 12 * 60 * 60 * 1000;

    let participantCount = 1;
    let meetingApi = null;
    let meetingStateKey = "";
    let meetingJoined = false;

    function setStageStatus(title, description) {
        if (stageTitle) {
            stageTitle.textContent = title;
        }
        if (stageDescription) {
            stageDescription.textContent = description;
        }
    }

    function setPillState(element, text, tone) {
        if (!element) {
            return;
        }
        element.textContent = text;
        element.classList.remove("success", "warning", "danger");
        if (tone) {
            element.classList.add(tone);
        }
    }

    function updateParticipantPill() {
        const tone = participantCount > participantLimit ? "warning" : "success";
        setPillState(participantPill, `Peserta: ${participantCount}`, tone);
    }

    function refreshConnectivityUi() {
        if (navigator.onLine === false) {
            setPillState(networkPill, "Status: Offline", "danger");
            return;
        }
        if (meetingJoined) {
            setPillState(networkPill, "Status: Live", "success");
            return;
        }
        setPillState(networkPill, "Status: Menyiapkan room", "warning");
    }

    function showError(message) {
        if (stageError) {
            stageError.hidden = false;
            stageError.textContent = message;
        }
        setPillState(networkPill, "Status: Gagal", "danger");
        setStageStatus("Meeting belum bisa dibuka", message);
    }

    function readMeetingState() {
        const params = new URLSearchParams(window.location.search);
        const stateId = params.get("state");
        if (!stateId) {
            throw new Error("Data meeting tidak ditemukan. Buka lagi dari portal meeting.");
        }
        meetingStateKey = `${MEETING_STATE_KEY_PREFIX}${stateId}`;

        let rawValue = "";
        try {
            rawValue = sessionStorage.getItem(meetingStateKey) || "";
        } catch (error) {
            throw new Error("Browser menolak membaca data sesi meeting. Coba ulangi dari portal.");
        }

        if (!rawValue) {
            throw new Error("Sesi meeting sudah hilang atau kedaluwarsa. Masuk lagi dari portal meeting.");
        }

        try {
            const parsed = JSON.parse(rawValue);
            const createdAt = Number(parsed.storageCreatedAt || parsed.createdAt || 0) || 0;
            if (createdAt && Date.now() - createdAt > MEETING_STATE_TTL_MS) {
                try {
                    sessionStorage.removeItem(meetingStateKey);
                } catch (error) {
                }
                throw new Error("Sesi meeting browser sudah kedaluwarsa. Silakan masuk lagi dari portal meeting.");
            }
            return parsed;
        } catch (error) {
            if (String(error.message || "").includes("kedaluwarsa")) {
                throw error;
            }
            throw new Error("Data sesi meeting rusak. Silakan ulangi dari portal meeting.");
        }
    }

    function clearMeetingState() {
        if (!meetingStateKey) {
            return;
        }
        try {
            sessionStorage.removeItem(meetingStateKey);
        } catch (error) {
        }
    }

    function revealMeetingStage() {
        if (stageHost) {
            stageHost.hidden = false;
        }
        if (stageLoader) {
            stageLoader.hidden = true;
        }
        if (stageHints) {
            stageHints.hidden = true;
        }
        if (stageBox) {
            stageBox.classList.add("is-live");
        }
    }

    function disposeMeetingApi() {
        if (!meetingApi || typeof meetingApi.dispose !== "function") {
            return;
        }
        try {
            meetingApi.dispose();
        } catch (error) {
        }
        meetingApi = null;
    }

    function buildJitsiOptions(meetingState) {
        const options = {
            roomName: meetingState.embedRoomName || meetingState.roomName,
            width: "100%",
            height: "100%",
            parentNode: stageHost,
            lang: meetingState.language || "id-ID",
            userInfo: {
                displayName: meetingState.displayName || "Guest",
                email: meetingState.email || "",
            },
            configOverwrite: {
                prejoinPageEnabled: false,
                disableDeepLinking: true,
                startAudioOnly: Boolean(meetingState.startAudioOnly),
                startWithVideoMuted: Boolean(meetingState.startWithVideoMuted),
                startWithAudioMuted: false,
                doNotStoreRoom: true,
                enableClosePage: false,
                hideConferenceTimer: false,
                resolution: Number(meetingState.videoResolution || 360),
                constraints: {
                    video: {
                        height: {
                            ideal: Number(meetingState.videoResolution || 360),
                            max: Number(meetingState.videoResolution || 540),
                            min: 180,
                        },
                    },
                },
                channelLastN: Number(meetingState.channelLastN || 6),
                enableLayerSuspension: true,
                p2p: {
                    enabled: true,
                },
                toolbarButtons: Array.isArray(meetingState.toolbarButtons) ? meetingState.toolbarButtons : undefined,
                subject: meetingState.topic || "",
            },
            interfaceConfigOverwrite: {
                MOBILE_APP_PROMO: false,
                HIDE_INVITE_MORE_HEADER: true,
                TILE_VIEW_MAX_COLUMNS: 3,
                SHOW_JITSI_WATERMARK: false,
                SHOW_WATERMARK_FOR_GUESTS: false,
            },
        };

        if (meetingState.jwt) {
            options.jwt = meetingState.jwt;
        }

        return options;
    }

    function initBrowserMeeting(meetingState) {
        if (provider !== "jitsi") {
            throw new Error("Provider meeting ini belum didukung di browser room baru.");
        }
        if (typeof window.JitsiMeetExternalAPI === "undefined") {
            throw new Error("Engine meeting browser tidak berhasil dimuat. Coba reload halaman ini.");
        }
        if (!stageHost) {
            throw new Error("Area stage meeting tidak ditemukan.");
        }

        setPillState(profilePill, `Profil: ${meetingState.profileLabel || meetingState.profile || "-"}`, "success");
        setPillState(networkPill, "Status: Menyiapkan room", "warning");
        updateParticipantPill();
        setStageStatus("Menyiapkan Browser Room...", "Menghubungkan user ke stage meeting ringan dan menyalakan ruang meeting yang sudah diproteksi server.");

        const api = new window.JitsiMeetExternalAPI(meetingState.domain || meetingDomain, buildJitsiOptions(meetingState));
        meetingApi = api;

        api.addListener("videoConferenceJoined", function () {
            meetingJoined = true;
            revealMeetingStage();
            refreshConnectivityUi();
            setStageStatus("Meeting berhasil dibuka", "Room browser sudah aktif. Kalau audio sudah masuk, meeting siap dipakai.");
        });

        api.addListener("participantJoined", function () {
            participantCount += 1;
            updateParticipantPill();
        });

        api.addListener("participantLeft", function () {
            participantCount = Math.max(1, participantCount - 1);
            updateParticipantPill();
        });

        api.addListener("readyToClose", function () {
            clearMeetingState();
            window.location.href = leaveUrl;
        });

        api.addListener("videoConferenceLeft", function () {
            clearMeetingState();
            window.location.href = leaveUrl;
        });
    }

    try {
        const meetingState = readMeetingState();
        initBrowserMeeting(meetingState);
    } catch (error) {
        clearMeetingState();
        showError(error.message || "Meeting tidak bisa dibuka.");
    }

    window.addEventListener("online", () => {
        refreshConnectivityUi();
        if (meetingJoined) {
            setStageStatus("Meeting kembali online", "Koneksi internet kembali tersedia. Lanjutkan meeting seperti biasa.");
        }
    });

    window.addEventListener("offline", () => {
        refreshConnectivityUi();
        if (meetingJoined) {
            setStageStatus("Jaringan meeting terputus", "Internet sedang offline. Browser akan mencoba mempertahankan sesi sampai koneksi kembali.");
        }
    });

    window.addEventListener("pagehide", (event) => {
        if (event && event.persisted) {
            return;
        }
        disposeMeetingApi();
    });

    window.addEventListener("beforeunload", () => {
        disposeMeetingApi();
    });
})();
