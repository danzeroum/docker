const CACHE_NAME = 'cockpit-' + new Date().toISOString().split('T')[0].replace(/-/g, '');
const STATIC_ASSETS = [
  '/static/index.html',
  '/static/css/base.css',
  '/static/css/components.css',
  '/static/js/state.js',
  '/static/js/helpers.js',
  '/static/js/notifications.js',
  '/static/js/api.js',
  '/static/js/containers.js',
  '/static/js/system.js',
  '/static/js/logs.js',
  '/static/js/stats.js',
  '/static/js/terminal.js',
  '/static/js/commands.js',
  '/static/js/main.js',
  '/static/manifest.json',
  '/static/assets/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    })
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.url.includes('/api/')) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request);
    })
  );
});
