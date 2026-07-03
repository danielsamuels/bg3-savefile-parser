/* Service worker: offline app shell + name table.
 *
 * - Navigations are network-first (new deploys land on next load) with the
 *   cached shell as the offline fallback.
 * - Hashed /assets/ are cache-first (immutable by construction).
 * - gamedata.json and fonts are stale-while-revalidate.
 */
const CACHE = 'bg3save-v4';
const SHELL = [
  '/',
  '/anatomy',
  '/manifest.webmanifest',
  '/gamedata.json',
  '/effects.json',
  '/fonts/ebgaramond-latin-var.woff2',
  '/icon-192.png',
  '/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // The sample save is large and only wanted on demand; never cache it.
  if (url.pathname === '/sample.lsv') return;

  if (e.request.mode === 'navigate') {
    const page = url.pathname === '/anatomy' ? '/anatomy' : '/';
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(page, copy));
          return res;
        })
        .catch(() => caches.match(page).then((hit) => hit ?? caches.match('/'))),
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) {
    e.respondWith(
      caches.match(e.request).then(
        (hit) =>
          hit ??
          fetch(e.request).then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
            return res;
          }),
      ),
    );
    return;
  }

  // Everything else (gamedata, fonts, icons): stale-while-revalidate.
  e.respondWith(
    caches.match(e.request).then((hit) => {
      const refresh = fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        })
        .catch(() => hit);
      return hit ?? refresh;
    }),
  );
});
