const APP_VERSION = "__APP_VERSION__";
const APP_BUILD_TOKEN = "__APP_BUILD_TOKEN__";
const CACHE_VERSION = `${APP_VERSION}-${APP_BUILD_TOKEN}`;
const APP_SHELL_CACHE = `wms-app-shell-${CACHE_VERSION}`;
const STATIC_RUNTIME_CACHE = `wms-static-runtime-${CACHE_VERSION}`;
const OFFLINE_FALLBACK_URL = "/static/offline-app.html";
const APP_SHELL_ASSETS = __APP_SHELL_ASSETS__;

function isCacheableStaticRequest(requestUrl) {
    return requestUrl.origin === self.location.origin && (
        requestUrl.pathname.startsWith("/static/")
        || requestUrl.pathname === "/service-worker.js"
    );
}

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(APP_SHELL_CACHE)
            .then((cache) => cache.addAll(APP_SHELL_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys
                .filter((key) => ![APP_SHELL_CACHE, STATIC_RUNTIME_CACHE].includes(key))
                .map((key) => caches.delete(key))
        )).then(() => self.clients.claim())
    );
});

self.addEventListener("message", (event) => {
    const payload = event.data || {};
    if (payload && payload.type === "SKIP_WAITING") {
        event.waitUntil(self.skipWaiting());
    }
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);

    if (event.request.mode === "navigate") {
        event.respondWith(
            fetch(event.request)
                .then((response) => response)
                .catch(async () => {
                    const cachedResponse = await caches.match(event.request, { ignoreSearch: true });
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    return caches.match(OFFLINE_FALLBACK_URL, { ignoreSearch: true });
                })
        );
        return;
    }

    if (!isCacheableStaticRequest(requestUrl)) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            const networkFetch = fetch(event.request)
                .then((response) => {
                    if (response && response.ok) {
                        const responseClone = response.clone();
                        caches.open(STATIC_RUNTIME_CACHE).then((cache) => cache.put(event.request, responseClone));
                    }
                    return response;
                })
                .catch(() => cachedResponse || new Response("", { status: 503, statusText: "Offline" }));

            return cachedResponse || networkFetch;
        })
    );
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
                if ("focus" in client && client.url.indexOf(targetUrl) === 0) {
                    return client.focus();
                }
            }

            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }

            return null;
        })
    );
});
