// Radar service worker — caches the app shell so it opens instantly and works as an
// installed PWA. API responses are always fetched live (never cached) so the feed is
// current; only the static shell is cached.
const SHELL = "radar-shell-v1";
const ASSETS = ["/", "/index.html", "/styles.css", "/app.js", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return; // live data, don't cache
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).catch(() =>
      caches.match("/index.html")))
  );
});
