// Service worker for Trainer - Day Activity PWA.
// Caches the core app shell so it opens instantly and works offline.
const CACHE = "trainer-ops-v1";
const CORE = [
  "/",
  "/icon-192.png",
  "/icon-512.png",
  "/manifest.json"
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(CORE); })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  // API calls: network-first, fall back to cache for the dashboard shell.
  if (req.url.indexOf("/api/") !== -1) {
    e.respondWith(
      fetch(req).catch(function () { return caches.match(req); })
    );
    return;
  }
  // Static assets: cache-first.
  e.respondWith(
    caches.match(req).then(function (hit) {
      return hit || fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () { return hit; });
    })
  );
});
