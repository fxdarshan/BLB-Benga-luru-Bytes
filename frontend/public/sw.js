// The service worker that makes the page installable and quick to reopen.
// - Pages: network first, so a deploy shows at once; the last copy is used when offline.
// - /assets: cache first. Their names change with every build, so a cached file is never stale.
// - Other files of the page (icons, theme.js): the cached copy at once, refreshed in the background.
// - The API and anything else on another site is never touched: searches always go to the network.
const VERSION = "v1";
const PAGES = `blb-pages-${VERSION}`;
const FILES = `blb-files-${VERSION}`;
const MAX_FILES = 60;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(PAGES)
      .then((cache) => cache.add("/"))
      .catch(() => {}) // offline at install: the page is cached on the next visit instead
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== PAGES && n !== FILES).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cache) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_FILES)).map((key) => cache.delete(key)));
}

async function page(request) {
  const cache = await caches.open(PAGES);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put("/", response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match("/");
    if (cached) return cached;
    throw error;
  }
}

async function asset(request) {
  const cache = await caches.open(FILES);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    trim(cache);
  }
  return response;
}

async function file(request, event) {
  const cache = await caches.open(FILES);
  const cached = await cache.match(request);
  const fresh = fetch(request).then(async (response) => {
    if (response.ok) await cache.put(request, response.clone());
    return response;
  });
  if (cached) {
    event.waitUntil(fresh.catch(() => {}));
    return cached;
  }
  return fresh;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname === "/sw.js") return;
  if (request.mode === "navigate") event.respondWith(page(request));
  else if (url.pathname.startsWith("/assets/")) event.respondWith(asset(request));
  else event.respondWith(file(request, event));
});
