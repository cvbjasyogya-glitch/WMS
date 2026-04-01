(function () {
    const root = document.getElementById("meetingSessionRoot");
    if (!root) {
        return;
    }

    const sdkReady = root.dataset.sdkReady === "1";
    const sdkVersion = root.dataset.sdkVersion || "5.1.4";
    const webEndpoint = root.dataset.webEndpoint || "zoom.us";
    const leaveUrl = root.dataset.leaveUrl || "/meetings/";
    const stageTitle = document.getElementById("meetingStageTitle");
    const stageDescription = document.getElementById("meetingStageDescription");
    const stageError = document.getElementById("meetingStageError");
    const stageBox = document.getElementById("meetingStageBox");
    const profilePill = document.getElementById("meetingStageProfilePill");
    const networkPill = document.getElementById("meetingStageNetworkPill");

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
            rawValue = sessionStorage.getItem(`wms-zoom-state:${stateId}`) || "";
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

    function initZoomMeeting(meetingState) {
        if (typeof window.ZoomMtg === "undefined") {
            throw new Error("Zoom Meeting SDK tidak berhasil dimuat di browser ini.");
        }

        setPillState(profilePill, `Profil: ${meetingState.profileLabel || meetingState.profile || "-"}`, "success");
        setPillState(networkPill, "Status: Menyiapkan client view", "warning");
        setStageStatus("Menyiapkan Zoom Client View...", "SDK sedang memuat komponen meeting dan bahasa antarmuka.");

        window.ZoomMtg.setZoomJSLib(`https://source.zoom.us/${sdkVersion}/lib`, "/av");
        window.ZoomMtg.preLoadWasm();
        window.ZoomMtg.prepareWebSDK();
        window.ZoomMtg.i18n.load(meetingState.language || "id-ID");
        window.ZoomMtg.i18n.onLoad(function () {
            window.ZoomMtg.init({
                leaveUrl: meetingState.leaveUrl || leaveUrl,
                webEndpoint: meetingState.webEndpoint || webEndpoint,
                disableCORP: !window.crossOriginIsolated,
                disablePreview: Boolean(meetingState.disablePreview),
                success: function () {
                    setPillState(networkPill, "Status: Menghubungkan", "warning");
                    setStageStatus("Menghubungkan ke room...", "Meeting number dan signature sudah siap. Browser akan lanjut masuk ke room.");

                    window.ZoomMtg.join({
                        meetingNumber: meetingState.meetingNumber,
                        userName: meetingState.displayName,
                        signature: meetingState.signature,
                        passWord: meetingState.passcode,
                        userEmail: meetingState.email || "",
                        success: function () {
                            setPillState(networkPill, "Status: Live", "success");
                            setStageStatus("Meeting berhasil dibuka", "Client view sudah aktif. Jika UI Zoom tampil penuh, itu normal.");
                            if (stageBox) {
                                stageBox.classList.add("is-minimized");
                            }
                        },
                        error: function (error) {
                            const joinedMessage = error && (error.errorMessage || error.reason || error.message);
                            showError(joinedMessage || "Zoom menolak join meeting. Cek nomor meeting, passcode, atau status room.");
                        },
                    });
                },
                error: function (error) {
                    const initMessage = error && (error.errorMessage || error.reason || error.message);
                    showError(initMessage || "Gagal menyalakan Zoom client view.");
                },
            });

            if (typeof window.ZoomMtg.inMeetingServiceListener === "function") {
                window.ZoomMtg.inMeetingServiceListener("onMeetingStatus", function (payload) {
                    if (!payload || typeof payload.meetingStatus === "undefined") {
                        return;
                    }
                    if (payload.meetingStatus === 2) {
                        setPillState(networkPill, "Status: In Meeting", "success");
                    }
                });
            }
        });
    }

    try {
        if (!sdkReady) {
            throw new Error("Meeting SDK belum dikonfigurasi di server. Hubungi admin untuk mengisi SDK key dan secret.");
        }
        const meetingState = readMeetingState();
        initZoomMeeting(meetingState);
    } catch (error) {
        showError(error.message || "Meeting tidak bisa dibuka.");
    }
})();
