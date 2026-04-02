(function () {
    function getConfig() {
        const config = window.wmsPushConfig || {};
        return {
            publicKey: typeof config.publicKey === "string" ? config.publicKey.trim() : "",
            subscribeUrl: config.subscribeUrl || "/announcements/push/subscribe",
            unsubscribeUrl: config.unsubscribeUrl || "/announcements/push/unsubscribe",
            serviceWorkerUrl: config.serviceWorkerUrl || "/service-worker.js"
        };
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let index = 0; index < rawData.length; index += 1) {
            outputArray[index] = rawData.charCodeAt(index);
        }
        return outputArray;
    }

    function supportsPush() {
        return Boolean(
            window.isSecureContext &&
            "serviceWorker" in navigator &&
            "PushManager" in window &&
            "Notification" in window
        );
    }

    async function ensureRegistration() {
        const config = getConfig();
        return navigator.serviceWorker.register(config.serviceWorkerUrl, { scope: "/" });
    }

    async function postSubscription(url, payload) {
        await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload || {})
        });
    }

    async function syncSubscriptionWithServer() {
        if (!supportsPush()) {
            return null;
        }

        const config = getConfig();
        const registration = await ensureRegistration();
        let subscription = await registration.pushManager.getSubscription();

        if (Notification.permission !== "granted") {
            return subscription;
        }

        if (!config.publicKey) {
            return subscription;
        }

        if (!subscription) {
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(config.publicKey)
            });
        }

        await postSubscription(config.subscribeUrl, subscription.toJSON());
        return subscription;
    }

    async function getState() {
        if (!supportsPush()) {
            return {
                supported: false,
                permission: typeof Notification !== "undefined" ? Notification.permission : "unsupported",
                hasSubscription: false,
                configured: false
            };
        }

        const config = getConfig();
        const subscription = await syncSubscriptionWithServer();

        return {
            supported: true,
            permission: Notification.permission,
            hasSubscription: Boolean(subscription),
            configured: Boolean(config.publicKey),
            subscription
        };
    }

    async function enable() {
        if (!supportsPush()) {
            return {
                ok: false,
                reason: "unsupported"
            };
        }

        const config = getConfig();
        const registration = await ensureRegistration();
        let permission = Notification.permission;

        if (permission !== "granted") {
            permission = await Notification.requestPermission();
        }

        if (permission !== "granted") {
            return {
                ok: false,
                reason: permission === "denied" ? "denied" : "dismissed"
            };
        }

        if (!config.publicKey) {
            return {
                ok: true,
                reason: "granted_without_server"
            };
        }

        let subscription = await registration.pushManager.getSubscription();
        if (!subscription) {
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(config.publicKey)
            });
        }

        await postSubscription(config.subscribeUrl, subscription.toJSON());
        await registration.showNotification("Notifikasi perangkat aktif", {
            body: "Pengumuman HRIS dan perubahan jadwal akan dikirim ke perangkat ini.",
            icon: "/static/brand/mataram-logo.png",
            badge: "/static/brand/mataram-logo.png",
            tag: "announcement-center-enabled"
        });

        return {
            ok: true,
            reason: "enabled"
        };
    }

    async function disable() {
        return {
            ok: false,
            reason: "locked_after_enabled"
        };
    }

    window.wmsPushNotifications = {
        enable,
        disable,
        getState,
        syncSubscriptionWithServer,
        supportsPush
    };

    if (supportsPush() && Notification.permission === "granted") {
        syncSubscriptionWithServer().catch(() => {});
    }
})();
