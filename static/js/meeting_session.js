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

    let participantCount = 1;

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

        let rawValue = "";
        try {
            rawValue = sessionStorage.getItem(`wms-meeting-state:${stateId}`) || "";
        } catch (error) {
            throw new Error("Browser menolak membaca data sesi meeting. Coba ulangi dari portal.");
        }

        if (!rawValue) {
            throw new Error("Sesi meeting sudah hilang atau kedaluwarsa. Masuk lagi dari portal meeting.");
        }

        try {
            return JSON.parse(rawValue);
        } catch (error) {
            throw new Error("Data sesi meeting rusak. Silakan ulangi dari portal meeting.");
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

    function buildJitsiOptions(meetingState) {
        return {
            roomName: meetingState.roomName,
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
        setStageStatus("Menyiapkan Browser Room...", "Menghubungkan user ke stage meeting ringan tanpa secret key server.");

        const api = new window.JitsiMeetExternalAPI(meetingState.domain || meetingDomain, buildJitsiOptions(meetingState));

        api.addListener("videoConferenceJoined", function () {
            revealMeetingStage();
            setPillState(networkPill, "Status: Live", "success");
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
            window.location.href = leaveUrl;
        });

        api.addListener("videoConferenceLeft", function () {
            window.location.href = leaveUrl;
        });
    }

    try {
        const meetingState = readMeetingState();
        initBrowserMeeting(meetingState);
    } catch (error) {
        showError(error.message || "Meeting tidak bisa dibuka.");
    }
})();
