// Minimal service worker required for PWA installation
self.addEventListener('install', (e) => {
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    return self.clients.claim();
});

self.addEventListener('fetch', (e) => {
    // Passes network requests through normally
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});