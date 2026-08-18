// Radar service worker — caches the app shell so it works offline / as an installed PWA.
// API responses are always live. The shell uses NETWORK-FIRST so a freshly pulled build
// shows up on the next load instead of being pinned to a stale cache (the old cache-first
// strategy is why new tabs/features could "not appear" until you cleared site data).
const SHELL = "radar-shell-v2";
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
  // Network-first: always try the live file, refresh the cache, fall back to cache offline.
  e.respondWith(
    fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(SHELL).then(c => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(e.request).then(hit => hit || caches.match("/index.html")))
  );
});
