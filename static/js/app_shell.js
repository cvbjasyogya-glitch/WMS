(function () {
    const config = window.wmsAppShellConfig || {};
    const serviceWorkerUrl = config.serviceWorkerUrl || "/service-worker.js";
    const installButtons = Array.from(document.querySelectorAll("[data-pwa-install-trigger]"));
    const standaloneQuery = window.matchMedia ? window.matchMedia("(display-mode: standalone)") : null;
    let deferredInstallPrompt = null;
    let installUiSyncFrame = 0;
    let installUiSurfaceMode = getSurfaceMode();
    let installUiStandaloneMode = isStandaloneMode();

    function getSurfaceMode() {
        if (window.innerWidth <= 767) {
            return "mobile";
        }
        if (window.innerWidth <= 1080) {
            return "tablet";
        }
        return "desktop";
    }

    function isStandaloneMode() {
        return Boolean(
            (standaloneQuery && standaloneQuery.matches) ||
            window.navigator.standalone === true
        );
    }

    function isIosBrowser() {
        const userAgent = window.navigator.userAgent || "";
        const isiOS = /iPad|iPhone|iPod/.test(userAgent);
        const isSafari = /Safari/.test(userAgent) && !/CriOS|FxiOS|EdgiOS/.test(userAgent);
        return isiOS && isSafari;
    }

    function setBodyAppMode() {
        const standalone = isStandaloneMode();
        const surface = getSurfaceMode();
        document.body.classList.toggle("standalone-mode", standalone);
        document.body.classList.toggle("browser-mode", !standalone);
        document.body.classList.toggle("app-mobile-surface", surface === "mobile");
        document.body.classList.toggle("app-tablet-surface", surface === "tablet");
        document.body.classList.toggle("app-desktop-surface", surface === "desktop");
        document.body.dataset.appMode = standalone ? "standalone" : "browser";
        document.body.dataset.appSurface = surface;
    }

    function setInstallButtonState(visible, label) {
        installButtons.forEach((button) => {
            button.hidden = !visible;
            const labelNode = button.querySelector("[data-pwa-install-label]");
            if (labelNode && label) {
                labelNode.textContent = label;
            }
        });
    }

    function showMessage(message) {
        if (typeof window.showToast === "function") {
            window.showToast(message);
            return;
        }
        window.alert(message);
    }

    function syncInstallUi() {
        setBodyAppMode();
        let installContext = "browser";

        if (isStandaloneMode()) {
            installContext = "standalone";
            document.body.dataset.installContext = installContext;
            setInstallButtonState(false, "");
            return;
        }

        if (deferredInstallPrompt) {
            installContext = "installable-browser";
            document.body.dataset.installContext = installContext;
            setInstallButtonState(true, "Install App");
            return;
        }

        if (isIosBrowser()) {
            installContext = "ios-browser";
            document.body.dataset.installContext = installContext;
            setInstallButtonState(true, "Tambah ke Home");
            return;
        }

        document.body.dataset.installContext = installContext;
        setInstallButtonState(false, "");
    }

    function queueInstallUiSync(force = false) {
        const nextSurface = getSurfaceMode();
        const nextStandalone = isStandaloneMode();
        const surfaceChanged = nextSurface !== installUiSurfaceMode;
        const standaloneChanged = nextStandalone !== installUiStandaloneMode;

        if (!force && !surfaceChanged && !standaloneChanged) {
            return;
        }

        installUiSurfaceMode = nextSurface;
        installUiStandaloneMode = nextStandalone;

        if (installUiSyncFrame) {
            return;
        }

        installUiSyncFrame = window.requestAnimationFrame(() => {
            installUiSyncFrame = 0;
            syncInstallUi();
        });
    }

    async function handleInstallClick() {
        if (isStandaloneMode()) {
            return;
        }

        if (deferredInstallPrompt) {
            deferredInstallPrompt.prompt();
            const outcome = await deferredInstallPrompt.userChoice.catch(() => null);
            deferredInstallPrompt = null;
            syncInstallUi();

            if (outcome && outcome.outcome === "accepted") {
                showMessage("ERP-CV.BJAS sedang dipasang ke perangkat ini.");
            }
            return;
        }

        if (isIosBrowser()) {
            showMessage("Di iPhone/iPad, buka menu Share lalu pilih 'Add to Home Screen' agar ERP terpasang seperti aplikasi.");
        }
    }

    function bindInstallButtons() {
        installButtons.forEach((button) => {
            button.addEventListener("click", () => {
                handleInstallClick().catch(() => {
                    showMessage("Install aplikasi belum bisa dijalankan di perangkat ini.");
                });
            });
        });
    }

    async function registerServiceWorker() {
        if (!("serviceWorker" in navigator)) {
            return;
        }

        if (!window.isSecureContext && !/^localhost$|^127(?:\.\d{1,3}){3}$/.test(window.location.hostname)) {
            return;
        }

        try {
            await navigator.serviceWorker.register(serviceWorkerUrl, { scope: "/" });
        } catch (error) {
            console.warn("ERP app shell service worker registration failed.", error);
        }
    }

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredInstallPrompt = event;
        queueInstallUiSync(true);
    });

    window.addEventListener("appinstalled", () => {
        deferredInstallPrompt = null;
        queueInstallUiSync(true);
        showMessage("ERP-CV.BJAS sudah terpasang dan siap dipakai seperti aplikasi.");
    });

    if (standaloneQuery && typeof standaloneQuery.addEventListener === "function") {
        standaloneQuery.addEventListener("change", () => {
            queueInstallUiSync(true);
        });
    }

    window.addEventListener("resize", () => {
        queueInstallUiSync(false);
    }, { passive: true });

    bindInstallButtons();
    syncInstallUi();
    installUiSurfaceMode = getSurfaceMode();
    installUiStandaloneMode = isStandaloneMode();
    registerServiceWorker();
})();
