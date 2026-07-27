const CACHE_NAME = 'cockpit-v2';
const STATIC_ASSETS = [
  '/static/index.html',
  '/static/css/base.css',
  '/static/css/themes.css',
  '/static/css/components.css',
  '/static/js/fmt.js',
  '/static/js/store.js',
  '/static/js/data.js',
  '/static/js/notifications.js',
  '/static/js/commands.js',
  '/static/js/main.js',
  '/static/manifest.json',
  '/static/assets/icon.svg',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(STATIC_ASSETS.map((url) =>
        cache.add(url).catch(() => {})
      ))
    )
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
