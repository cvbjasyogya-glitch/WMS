(function () {
    const pushApi = window.wmsPushNotifications;
    const statusPill = document.querySelector("[data-push-status-pill]");
    const statusCopy = document.querySelector("[data-push-status-copy]");
    const enableButtons = document.querySelectorAll("[data-enable-device-notifications]");
    const disableButtons = document.querySelectorAll("[data-disable-device-notifications]");

    function renderStatus(state) {
        if (!statusPill || !statusCopy) {
            return;
        }

        if (!state || !state.supported) {
            statusPill.textContent = "Tidak Didukung";
            statusCopy.textContent = "Browser atau koneksi ini belum mendukung push notification. Email dan WhatsApp tetap bisa dipakai sebagai fallback.";
            return;
        }

        if (state.permission === "granted" && state.hasSubscription) {
            statusPill.textContent = "Aktif";
            statusCopy.textContent = "Notifikasi perangkat sudah aktif. Pengumuman dan perubahan jadwal akan dikirim ke browser ini.";
            return;
        }

        if (state.permission === "granted" && !state.configured) {
            statusPill.textContent = "Izin Aktif";
            statusCopy.textContent = "Izin browser sudah aktif, tetapi server push belum dikonfigurasi. Fallback email dan WhatsApp tetap berjalan.";
            return;
        }

        if (state.permission === "denied") {
            statusPill.textContent = "Diblokir";
            statusCopy.textContent = "Izin notifikasi perangkat diblokir di browser. Aktifkan kembali dari pengaturan browser jika ingin menerima notif langsung.";
            return;
        }

        statusPill.textContent = "Belum Aktif";
        statusCopy.textContent = "Klik tombol aktivasi untuk mengizinkan browser menerima pengumuman dan perubahan jadwal langsung ke perangkat.";
    }

    async function refreshStatus() {
        if (!pushApi || typeof pushApi.getState !== "function") {
            renderStatus({ supported: false });
            return;
        }

        try {
            const state = await pushApi.getState();
            renderStatus(state);
        } catch (error) {
            renderStatus({ supported: false });
        }
    }

    enableButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (!pushApi || typeof pushApi.enable !== "function") {
                renderStatus({ supported: false });
                return;
            }
            button.disabled = true;
            try {
                await pushApi.enable();
            } catch (error) {
            }
            button.disabled = false;
            await refreshStatus();
        });
    });

    disableButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (!pushApi || typeof pushApi.disable !== "function") {
                renderStatus({ supported: false });
                return;
            }
            button.disabled = true;
            try {
                await pushApi.disable();
            } catch (error) {
            }
            button.disabled = false;
            await refreshStatus();
        });
    });

    refreshStatus();
})();
