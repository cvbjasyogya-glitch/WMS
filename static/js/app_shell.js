(function () {
    const config = window.wmsAppShellConfig || {};
    const serviceWorkerUrl = config.serviceWorkerUrl || "/service-worker.js";
    const serviceWorkerEnabled = config.serviceWorkerEnabled !== false;
    const installButtons = Array.from(document.querySelectorAll("[data-pwa-install-trigger]"));
    const standaloneQuery = window.matchMedia ? window.matchMedia("(display-mode: standalone)") : null;
    const hadActiveServiceWorkerController = Boolean(
        "serviceWorker" in navigator && navigator.serviceWorker.controller
    );
    let deferredInstallPrompt = null;
    let installUiSyncFrame = 0;
    let installUiSurfaceMode = getSurfaceMode();
    let installUiStandaloneMode = isStandaloneMode();
    let registeredServiceWorker = null;
    let lastServiceWorkerUpdateCheckAt = 0;
    let hasAutoReloadedForServiceWorkerUpdate = false;

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

        if (!serviceWorkerEnabled) {
            installContext = config.publicHostMode
                ? `${config.publicHostMode}-public-host`
                : "disabled";
            document.body.dataset.installContext = installContext;
            setInstallButtonState(false, "");
            return;
        }

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

    async function unregisterServiceWorkers() {
        if (!("serviceWorker" in navigator)) {
            return;
        }

        try {
            const registrations = await navigator.serviceWorker.getRegistrations();
            await Promise.all(
                registrations.map((registration) => registration.unregister().catch(() => false))
            );
        } catch (error) {
            console.warn("ERP app shell service worker cleanup failed.", error);
        }

        if (!("caches" in window)) {
            return;
        }

        try {
            const cacheKeys = await caches.keys();
            await Promise.all(
                cacheKeys
                    .filter((key) => key.startsWith("wms-app-shell-") || key.startsWith("wms-static-runtime-"))
                    .map((key) => caches.delete(key))
            );
        } catch (error) {
            console.warn("ERP app shell cache cleanup failed.", error);
        }
    }

    function reloadForActivatedServiceWorker() {
        if (!hadActiveServiceWorkerController || hasAutoReloadedForServiceWorkerUpdate) {
            return;
        }
        hasAutoReloadedForServiceWorkerUpdate = true;
        window.location.reload();
    }

    function attachServiceWorkerRegistrationHooks(registration) {
        if (!registration || registration.__wmsUpdateHooksBound) {
            return registration;
        }

        registration.__wmsUpdateHooksBound = true;
        registration.addEventListener("updatefound", () => {
            const installingWorker = registration.installing;
            if (!installingWorker) {
                return;
            }
            installingWorker.addEventListener("statechange", () => {
                if (installingWorker.state === "installed" && registration.waiting) {
                    registration.waiting.postMessage({ type: "SKIP_WAITING" });
                }
            });
        });

        if (registration.waiting) {
            registration.waiting.postMessage({ type: "SKIP_WAITING" });
        }

        return registration;
    }

    async function checkForServiceWorkerUpdate(force = false) {
        if (!serviceWorkerEnabled || !("serviceWorker" in navigator)) {
            return;
        }

        const now = Date.now();
        if (!force && now - lastServiceWorkerUpdateCheckAt < 60 * 1000) {
            return;
        }
        lastServiceWorkerUpdateCheckAt = now;

        try {
            const registration = registeredServiceWorker || await navigator.serviceWorker.getRegistration("/");
            if (!registration) {
                return;
            }
            registeredServiceWorker = attachServiceWorkerRegistrationHooks(registration);
            await registeredServiceWorker.update();
            if (registeredServiceWorker.waiting) {
                registeredServiceWorker.waiting.postMessage({ type: "SKIP_WAITING" });
            }
        } catch (error) {
            console.warn("ERP app shell service worker update check failed.", error);
        }
    }

    async function registerServiceWorker() {
        if (!serviceWorkerEnabled) {
            await unregisterServiceWorkers();
            return;
        }

        if (!("serviceWorker" in navigator)) {
            return;
        }

        if (!window.isSecureContext && !/^localhost$|^127(?:\.\d{1,3}){3}$/.test(window.location.hostname)) {
            return;
        }

        try {
            registeredServiceWorker = await navigator.serviceWorker.register(serviceWorkerUrl, { scope: "/" });
            attachServiceWorkerRegistrationHooks(registeredServiceWorker);
            window.setTimeout(() => {
                void checkForServiceWorkerUpdate(true);
            }, 1200);
        } catch (error) {
            console.warn("ERP app shell service worker registration failed.", error);
        }
    }

    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.addEventListener("controllerchange", () => {
            reloadForActivatedServiceWorker();
        });
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

    window.addEventListener("focus", () => {
        void checkForServiceWorkerUpdate(false);
    });

    window.addEventListener("pageshow", () => {
        void checkForServiceWorkerUpdate(false);
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            void checkForServiceWorkerUpdate(false);
        }
    });

    bindInstallButtons();
    syncInstallUi();
    installUiSurfaceMode = getSurfaceMode();
    installUiStandaloneMode = isStandaloneMode();
    void registerServiceWorker();
})();
