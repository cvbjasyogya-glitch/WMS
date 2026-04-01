self.addEventListener("install", (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    const payload = event.data ? event.data.json() : {};
    const title = payload.title || "Pengumuman Baru";
    const options = {
        body: payload.body || "Ada update baru yang perlu dicek.",
        icon: payload.icon || "/static/brand/mataram-logo.png",
        badge: payload.badge || "/static/brand/mataram-logo.png",
        tag: payload.tag || "announcement-center",
        data: {
            url: payload.url || "/announcements/"
        }
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    const targetUrl = (event.notification && event.notification.data && event.notification.data.url) || "/announcements/";
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
