// Service worker for Trainer - Day Activity PWA.
// Caches the core app shell so it opens instantly and works offline.
// IMPORTANT: bump CACHE (e.g. -v2, -v3) on every deploy so old cached
// HTML/CSS is discarded and users get the latest version automatically.
const CACHE = "trainer-ops-v6";
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

  // API calls: always go to network, fall back to cache only when offline.
  if (req.url.indexOf("/api/") !== -1) {
    e.respondWith(
      fetch(req).catch(function () { return caches.match(req); })
    );
    return;
  }

  // HTML navigation/page requests: NETWORK-FIRST so the latest deployed
  // version is always shown. Falls back to cache only when offline.
  if (req.mode === "navigate" || req.url.endsWith("/") || req.headers.get("accept").indexOf("text/html") !== -1) {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () { return caches.match(req); })
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
