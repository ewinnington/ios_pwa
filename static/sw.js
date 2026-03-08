// CloudPlush Service Worker — handles push notifications

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));

self.addEventListener("push", (event) => {
  if (!event.data) return;

  const data = event.data.json();
  const options = {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    vibrate: [200, 100, 200],
    data: { url: "/" },
  };

  event.waitUntil(
    self.registration.showNotification(data.title || "CloudPlush", options)
  );

  // Tell open pages to refresh the notification log
  const ch = new BroadcastChannel("cloudplush-push");
  ch.postMessage("new");
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((wins) => {
        for (const w of wins) {
          if (new URL(w.url).pathname === "/" && "focus" in w) return w.focus();
        }
        return clients.openWindow("/");
      })
  );
});
