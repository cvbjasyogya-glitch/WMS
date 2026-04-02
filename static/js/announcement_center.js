(function () {
    const pushApi = window.wmsPushNotifications;
    const statusPill = document.querySelector("[data-push-status-pill]");
    const statusCopy = document.querySelector("[data-push-status-copy]");
    const enableButtons = document.querySelectorAll("[data-enable-device-notifications]");

    enableButtons.forEach((button) => {
        if (!button.dataset.defaultLabel) {
            button.dataset.defaultLabel = button.textContent.trim();
        }
    });

    function syncEnableButtons(state) {
        enableButtons.forEach((button) => {
            const defaultLabel = button.dataset.defaultLabel || "Aktifkan Notif Perangkat";

            if (!state || !state.supported) {
                button.disabled = true;
                button.textContent = "Tidak Didukung";
                return;
            }

            if (state.permission === "denied") {
                button.disabled = true;
                button.textContent = "Izin Diblokir";
                return;
            }

            if (state.permission === "granted") {
                button.disabled = true;
                button.textContent = state.hasSubscription ? "Notif Aktif" : "Izin Aktif";
                return;
            }

            button.disabled = false;
            button.textContent = defaultLabel;
        });
    }

    function renderStatus(state) {
        syncEnableButtons(state);

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
            statusCopy.textContent = "Notifikasi perangkat sudah aktif dan akan tetap dipertahankan di browser ini walau halaman direfresh.";
            return;
        }

        if (state.permission === "granted" && !state.configured) {
            statusPill.textContent = "Izin Aktif";
            statusCopy.textContent = "Izin browser sudah aktif dan tetap tersimpan setelah reload. Server push belum dikonfigurasi, jadi fallback email dan WhatsApp tetap berjalan.";
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

    refreshStatus();
})();
