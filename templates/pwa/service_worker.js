/* ==========================================================================
   LGMED-iMMS service worker - served at /sw.js by core/pwa.py

   What it keeps on the device, and what it never will:

   KEPT      Static files under /static/ - the stylesheet, the scripts, the
             typeface, the seal. They are identical for every visitor and say
             nothing about any record. Plus the offline page and the launch
             page, fetched without cookies so that they are anonymous.

   NEVER     Pages, records, search results, notifications, uploaded or
             generated files (/media/, protected downloads, exports), and any
             response to anything other than a GET. A page is always fetched
             from the server, so the server's sign-in and role checks decide
             what is shown - every time, exactly as without this worker - and
             signing out leaves nothing of the system behind on the device.

   NEVER     Queued or replayed writes. A Save made with no connection is
             stopped in the page (static/js/pwa.js) with a message saying so;
             nothing is held to be sent later, because a decision posted hours
             afterwards, from a page the server has since moved on from, is
             exactly the inconsistency the workflows exist to prevent.
   ========================================================================== */

"use strict";

var CACHE = "{{ cache_name }}";
var PRECACHE = {{ precache_json|safe }};
var OFFLINE_URL = {{ offline_url_json|safe }};
// What the installed app opens on (templates/pwa/launch.html): anonymous like
// the offline page, and served from the device so it appears instantly.
var LAUNCH_URL = {{ launch_url_json|safe }};
var STATIC_PREFIX = {{ static_prefix_json|safe }};
var NOTIFICATION_ICON = {{ notification_icon_json|safe }};
var DEFAULT_URL = {{ dashboard_url_json|safe }};
// In development the static files change under the same name with every
// build, so they are read from the server first and the cache is only the
// fallback. In production every name carries a content hash and can be
// served from the cache for good.
var DEV = {{ dev_json|safe }};

/* -- Install: keep the static shell and the offline page ------------------ */

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      var requests = PRECACHE.map(function (url) {
        return new Request(url, { cache: "reload" });
      });
      // credentials: "omit" - the offline copy must be the anonymous one,
      // whoever happens to be signed in when the worker installs.
      requests.push(new Request(OFFLINE_URL, { cache: "reload", credentials: "omit" }));
      requests.push(new Request(LAUNCH_URL, { cache: "reload", credentials: "omit" }));
      return cache.addAll(requests);
    })
  );
  // No skipWaiting() here: a new version waits until the page offers to
  // reload (pwa.js), so a form being filled in is never swapped out from
  // under the person typing in it.
});

/* -- Activate: drop every previous release's cache ----------------------- */

self.addEventListener("activate", function (event) {
  event.waitUntil(
    Promise.all([
      caches.keys().then(function (names) {
        return Promise.all(
          names
            .filter(function (name) { return name.indexOf("lgmed-") === 0 && name !== CACHE; })
            .map(function (name) { return caches.delete(name); })
        );
      }),
      // Lets the browser start the page request while the worker boots, so
      // having a worker never makes a page slower to arrive.
      self.registration.navigationPreload
        ? self.registration.navigationPreload.enable()
        : Promise.resolve(),
    ]).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

/* -- Fetch ----------------------------------------------------------------- */

function offlinePage() {
  return caches.match(OFFLINE_URL, { ignoreVary: true }).then(function (cached) {
    return cached || new Response(
      "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>" +
      "<title>Offline</title><p style='font:16px system-ui;padding:2rem'>" +
      "You are offline. Check the connection and try again.</p>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  });
}

function isCacheable(response) {
  return response && response.ok && response.type === "basic";
}

function fromCache(request) {
  // ignoreSearch: in development the pages add ?v=<build> to the URLs.
  return caches.match(request, { ignoreSearch: DEV });
}

function cacheFirst(request) {
  return fromCache(request).then(function (cached) {
    if (cached) return cached;
    return fetch(request).then(function (response) {
      if (isCacheable(response)) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
      }
      return response;
    });
  });
}

function networkFirst(request) {
  return fetch(request).then(function (response) {
    if (isCacheable(response)) {
      var copy = response.clone();
      caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
    }
    return response;
  }).catch(function () {
    return fromCache(request).then(function (cached) {
      return cached || caches.match(request, { ignoreSearch: true }).then(function (loose) {
        if (loose) return loose;
        throw new Error("offline");
      });
    });
  });
}

self.addEventListener("fetch", function (event) {
  var request = event.request;

  // Writes go straight to the server, untouched.
  if (request.method !== "GET") return;

  var url = new URL(request.url);
  // Other sites (reCAPTCHA) are none of this worker's business.
  if (url.origin !== self.location.origin) return;

  // Pages: always the network. Only when there is no network at all is the
  // offline page shown instead - nothing of the page itself is ever stored.
  if (request.mode === "navigate" && url.pathname === LAUNCH_URL) {
    event.respondWith(
      caches.match(LAUNCH_URL, { ignoreVary: true, ignoreSearch: true }).then(function (cached) {
        return cached || fetch(request).catch(offlinePage);
      })
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      Promise.resolve(event.preloadResponse).then(function (preloaded) {
        return preloaded || fetch(request);
      }).catch(offlinePage)
    );
    return;
  }

  // Static files: public, identical for everyone.
  if (url.pathname.indexOf(STATIC_PREFIX) === 0) {
    event.respondWith(DEV ? networkFirst(request) : cacheFirst(request));
    return;
  }

  // Everything else - media, protected files, exports, JSON - is left to
  // the browser and the server, with no copy kept.
});

/* -- Notifications ---------------------------------------------------------
   Two ways in, one way out:

   * pwa.js asks the server (/app/notifications/status/) for the signed-in
     user's unread notifications while the app is open, and shows any new one
     through registration.showNotification().
   * A "push" event, for when the server gains a Web Push sender (VAPID). The
     payload is expected as {title, body, url, tag}. Nothing sends one yet -
     see docs/pwa.md - but the handler is here so that adding a sender is a
     server-side change alone.

   Either way, a click opens the notification's own link inside the system,
   where the server checks access as it would for any other page.
   -------------------------------------------------------------------------- */

self.addEventListener("push", function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "LGMED-iMMS", {
      body: data.body || "You have a new notification.",
      icon: NOTIFICATION_ICON,
      badge: NOTIFICATION_ICON,
      tag: data.tag || "lgmed-notification",
      data: { url: data.url || DEFAULT_URL },
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = new URL(
    (event.notification.data && event.notification.data.url) || DEFAULT_URL,
    self.location.origin
  );
  // Only ever open a page of this system.
  if (target.origin !== self.location.origin) target = new URL(DEFAULT_URL, self.location.origin);

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windows) {
      for (var i = 0; i < windows.length; i++) {
        var client = windows[i];
        if ("focus" in client && "navigate" in client) {
          return client.focus().then(function (focused) {
            return focused.navigate(target.href);
          });
        }
      }
      return self.clients.openWindow(target.href);
    })
  );
});
