// Service worker: makes the app installable and the shell load fast.
// Only the static shell is cached; /api/* always goes to the network
// (probe, progress stream and file downloads must never be served stale).
const CACHE = "yt-dl-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/favicon.ico", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Network first so a new version shows up at once; cache only when offline.
  // Only plain 200s are stored, never redirects or auth errors.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.status === 200 && response.type === "basic" && SHELL.includes(url.pathname)) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(url.pathname, copy));
        }
        return response;
      })
      .catch(() => caches.match(url.pathname === "/" || event.request.mode === "navigate" ? "/" : url.pathname))
  );
});
