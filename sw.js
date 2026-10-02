// Service worker mínimo: permite instalar la app. No guarda nada en caché,
// así los precios siempre vienen frescos de internet.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
