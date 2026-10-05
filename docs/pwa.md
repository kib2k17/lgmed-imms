# The installable app (PWA)

LGMED-iMMS can be installed as an app on Windows, Android, iPhone/iPad and
desktop Chrome/Edge. It is the same system as the website: the same server, the
same sign-in, the same role checks. Installing it adds an icon and a full-screen
window. It does not create a second copy of the system or store its records on
the device.

## What was added

| Piece | Where | Purpose |
|---|---|---|
| Web manifest | `/manifest.webmanifest` (`core/pwa.py`) | Name, icons, colours, start page, shortcuts |
| Service worker | `/sw.js` (`core/pwa.py`, `templates/pwa/service_worker.js`) | Keeps static files on the device and shows the offline page |
| Offline page | `/offline/` (`templates/pwa/offline.html`) | Shown in place of any page that cannot be reached |
| App script | `static/js/pwa.js` | Registration, install button, offline notice, update notice, notifications |
| Icons | `static/img/pwa/` (`manage.py make_pwa_icons`) | Drawn from `static/img/dilg-logo.png` |
| Notification check | `/app/notifications/status/` (`notifications/views.py`) | Unread count for the bell, the icon badge and device notifications |
| Phone navigation | `templates/includes/bottom_nav.html` | Dashboard, Calendar, Alerts and Menu along the bottom, below `lg` |

The manifest is linked from the system's pages and the sign-in page. The public
website doesn't link it, because citizens should not be offered the staff app.

## What is cached, and what never is

The service worker stores two kinds of thing on the device:

- **Static files** under `/static/`: stylesheet, scripts, typeface and icons.
  They are the same for every visitor and contain no records.
- **The offline page.** The worker fetches it without cookies, so it is
  anonymous.

It never caches:

- pages
- search results
- notifications
- uploaded or generated files (`/media/`, protected downloads, exports)
- any response to a POST

Pages are always fetched from the server. Sign-in, MFA and role checks
therefore run on every page view, exactly as they do in a browser tab, and
signing out leaves nothing of the system behind.

**Offline**, a notice appears at the bottom of the screen. Forms are stopped
before they are sent, and the person's entries stay on the page. Nothing is
queued to be sent later: the backend has no way to reconcile a decision posted
hours after the page it came from.

No passwords, tokens or records are written to browser storage. The only value
stored is the number of the newest notification already announced. It is kept
in `sessionStorage` and is gone when the tab closes.

## Notifications

While the system is open, `pwa.js` checks `/app/notifications/status/` once a
minute. The response drives three things:

- the bell's count
- the badge on the installed icon (Windows, Android, macOS)
- a device notification for anything new, if the person has allowed it

Permission is requested only when the person clicks **Notify me on this
device** in the bell menu.

The notification check never extends the session (`core/middleware.py`).
Otherwise an open tab would keep someone signed in indefinitely.

**Push while the app is closed** needs a Web Push sender on the server. The
service worker already handles `push` events, with the payload
`{title, body, url, tag}`, so adding push is a server-side change only:

1. Generate a VAPID key pair and store it in `lgmed.env`.
2. Add `pywebpush` and a model holding each device's `PushSubscription`.
3. In `pwa.js`, call `registration.pushManager.subscribe(...)` after
   permission is granted, then POST the subscription to the server.
4. Send from `notifications/service.py` whenever a `Notification` is created.

Step 4 contacts the browser vendors' push services, which are external, so it
was left for an explicit decision.

## HTTPS is required

Browsers only run service workers on HTTPS or on `localhost`. On the plain-HTTP
office-network address (`run-lan.ps1`), the app can't be installed and nothing
is cached. The system still works as an ordinary website, and the bell still
updates. The Cloudflare tunnel (`run-cloudflare.ps1`) is HTTPS, so installing
works there.

## Deploying

1. Build the stylesheet: `.\build-css.ps1`
2. Run `python manage.py collectstatic`. `*.src.css` is excluded
   (`core.apps.StaticFilesConfig`). `ManifestStaticFilesStorage` hashes every
   filename, and the worker's cache is named after those hashes, so each
   release replaces the previous cache.
3. In the reverse proxy, send **`/sw.js`, `/manifest.webmanifest` and
   `/offline/` to Django**. Don't serve them from `/static/`, and don't add
   long cache headers to them: Django already sends `Cache-Control: no-cache`
   and `Service-Worker-Allowed: /`.
4. Serve the site over HTTPS. Set `DJANGO_BEHIND_TLS_PROXY=1` only if the proxy
   overwrites `X-Forwarded-Proto` (see `config/settings.py`).

After a deployment, open copies of the app show **"An update is ready"**. The
new version takes over when the person clicks **Reload**, never in the middle
of a form.

## Installing

- **Windows / desktop Chrome or Edge:** account menu → **Install app**, or the
  install icon in the address bar.
- **Android (Chrome):** account menu → **Install app**, or the browser menu →
  **Install app**.
- **iPhone / iPad (Safari only):** account menu → **Install app** shows the
  steps: Share → **Add to Home Screen**. In the installed app on iOS, a back
  button appears in the header, because iOS doesn't provide one.

## Checking it

- Chrome DevTools → **Application** shows the Manifest (no errors), the
  Service worker (activated, scope `/`), and Cache storage (one
  `lgmed-static-…` cache containing only `/static/…` and `/offline/`).
- DevTools → **Network** → **Offline**: the offline notice appears, a Save is
  stopped with a message, and following a link shows the offline page.
- Tests: `python manage.py test core.tests_pwa`
