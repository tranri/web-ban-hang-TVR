const CACHE_NAME = 'tvr-electronic-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/static/images/icon-192x192.png',
    '/offline.html'
];

// Cài đặt Service Worker và cache tài nguyên tĩnh
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

// Kích hoạt và dọn dẹp cache cũ
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
            );
        })
    );
    self.clients.claim();
});

// Bắt sự kiện Fetch hỗ trợ duyệt web ngoại tuyến
self.addEventListener('fetch', event => {
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => {
                return caches.match('/offline.html');
            })
        );
    } else {
        event.respondWith(
            caches.match(event.request).then(response => {
                return response || fetch(event.request);
            })
        );
    }
});

// Xử lý thông báo đẩy (Push Notifications)
self.addEventListener('push', event => {
    const data = event.data ? event.data.json() : {};
    const title = data.title || 'Thông báo từ Điện Tử TVR';
    const options = {
        body: data.body || 'Bạn có thông tin cập nhật đơn hàng hoặc ưu đãi mới!',
        icon: '/static/images/icon-192x192.png',
        badge: '/static/images/icon-192x192.png'
    };
    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});