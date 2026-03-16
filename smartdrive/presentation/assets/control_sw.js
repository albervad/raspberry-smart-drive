self.addEventListener("push", (event) => {
    let payload = {};

    if (event.data) {
        try {
            payload = event.data.json();
        } catch (_) {
            payload = { body: event.data.text() };
        }
    }

    const title = payload.title || "Smart Drive";
    const options = {
        body: payload.body || "Nueva actividad detectada",
        icon: "/static/img/icon.png",
        badge: "/static/img/icon.png",
        tag: payload.tag || "smartdrive-access-alert",
        data: {
            url: payload.url || "/control?non_owner_only=1",
        },
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = event.notification?.data?.url || "/control?non_owner_only=1";

    event.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ("focus" in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
            return null;
        })
    );
});
