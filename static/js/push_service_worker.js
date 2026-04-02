self.addEventListener("install", (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    const payload = event.data ? event.data.json() : {};
    const actionUrls = payload.actionUrls || {};
    const title = payload.title || "Notifikasi Baru";
    const options = {
        body: payload.body || "Ada update baru yang perlu dicek.",
        icon: payload.icon || "/static/brand/mataram-logo.png",
        badge: payload.badge || "/static/brand/mataram-logo.png",
        tag: payload.tag || "notification-center",
        requireInteraction: Boolean(payload.requireInteraction),
        renotify: Boolean(payload.renotify),
        silent: Boolean(payload.silent),
        data: {
            url: payload.url || "/notifications/",
            notification_id: payload.notification_id || null,
            actionUrls
        }
    };
    if (Array.isArray(payload.actions) && payload.actions.length) {
        options.actions = payload.actions.slice(0, 2).map((item) => ({
            action: item.action,
            title: item.title,
            icon: item.icon
        }));
    }
    if (Array.isArray(payload.vibrate) && payload.vibrate.length) {
        options.vibrate = payload.vibrate;
    }

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    const notificationData = (event.notification && event.notification.data) || {};
    const actionUrls = notificationData.actionUrls || {};
    const targetUrl = actionUrls[event.action] || notificationData.url || "/notifications/";
    event.notification.close();

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ("focus" in client) {
                    if (client.url.indexOf(targetUrl) === 0) {
                        return client.focus();
                    }
                }
            }

            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }

            return null;
        })
    );
});
