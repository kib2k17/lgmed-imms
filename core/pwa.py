"""
The installable app: web manifest, service worker and offline page.

All three are served by Django rather than dropped into static/, for reasons
that are each easy to get wrong:

* The service worker must be served from the site root. A worker controls only
  the URLs under the directory it was served from, so one at /static/js/sw.js
  could never see /app/. It is rendered from a template so that it can name the
  real static URLs - ManifestStaticFilesStorage puts a content hash in every
  filename in production - and so that its bytes change whenever one of those
  files does, which is what tells the browser to install the new version.

* The manifest names the system and its icons from the same identity every page
  uses (core/context_processors.AGENCY) instead of a second copy that drifts.

* The offline page is fetched by the worker without cookies, so the copy kept
  on the device can never contain anyone's name, records or notifications.

What the worker does, and refuses to do, is set out in
templates/pwa/service_worker.js and docs/pwa.md.
"""

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .context_processors import AGENCY, asset_version

# The UI's own colours (static/css/app.src.css). brand-950 is the government
# band along the top of every page, so an installed window's title bar runs on
# into it. It is also the launch screen: Android draws BACKGROUND_COLOR with the
# maskable icon (whose square is the same navy), and the launch page that
# follows (templates/pwa/launch.html) is navy too, so opening the app is one
# continuous branded screen rather than a white box, then a blank page.
THEME_COLOR = "#0b1c30"
BACKGROUND_COLOR = "#0b1c30"

# Kept on the device when the worker installs, so every page can still draw
# its chrome - and the offline page can draw at all - with no connection.
# Static files only: they are the same for every visitor and hold no records.
PRECACHE = (
    "css/app.css",
    "js/app.js",
    "js/pwa.js",
    "fonts/inter-latin-wght-normal.woff2",
    "img/dilg-logo.png",
    "img/pwa/icon-192.png",
    "img/pwa/icon-512.png",
    "img/pwa/apple-touch-icon.png",
)


def _icon_url(name):
    """
    An icon's URL that changes whenever the icon does.

    In production ManifestStaticFilesStorage already puts a content hash in
    the name. In development the name stays the same, and a phone that has
    seen the old icon keeps showing it; a modification stamp makes a redrawn
    icon a new URL, so the next manifest check picks it up.
    """
    url = static(name)
    if settings.DEBUG:
        from django.contrib.staticfiles import finders

        found = finders.find(name)
        if found:
            url += f"?v={int(Path(found).stat().st_mtime)}"
    return url


def _icons():
    return [
        {"src": _icon_url("img/pwa/icon-192.png"), "sizes": "192x192",
         "type": "image/png", "purpose": "any"},
        {"src": _icon_url("img/pwa/icon-512.png"), "sizes": "512x512",
         "type": "image/png", "purpose": "any"},
        {"src": _icon_url("img/pwa/icon-maskable-192.png"), "sizes": "192x192",
         "type": "image/png", "purpose": "maskable"},
        {"src": _icon_url("img/pwa/icon-maskable-512.png"), "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ]


@require_GET
@cache_control(no_cache=True, max_age=0)
def manifest(request):
    """The web app manifest. Public: the browser fetches it without cookies."""
    icon = [{"src": _icon_url("img/pwa/icon-192.png"), "sizes": "192x192",
             "type": "image/png"}]
    data = {
        # A stable identity, so a change of start_url later does not make
        # every installed copy look like a different app.
        "id": reverse("core:dashboard"),
        "name": f"{AGENCY['system_name']} - {AGENCY['office_short']}",
        "short_name": AGENCY["system_name"],
        "description": AGENCY["system_full_name"],
        "lang": "en-PH",
        "dir": "ltr",
        # The launch page, which the service worker serves from the device
        # at once and which then loads the dashboard behind a spinner. The
        # dashboard's own login check still decides where that ends up.
        "start_url": reverse("pwa_launch"),
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "any",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "categories": ["government", "productivity", "business"],
        "prefer_related_applications": False,
        "icons": _icons(),
        # Long-press (Android) / right-click (Windows) on the installed icon.
        "shortcuts": [
            {"name": "Dashboard", "url": reverse("core:dashboard"), "icons": icon},
            {"name": "Notifications", "url": reverse("notifications:list"),
             "icons": icon},
            {"name": "Calendar", "url": reverse("activities:list"), "icons": icon},
        ],
    }
    return HttpResponse(
        json.dumps(data, indent=2),
        content_type="application/manifest+json",
    )


def _precache_urls():
    urls = [static(name) for name in PRECACHE]
    # In development the pages ask for app.css?v=<mtime> (see asset_version),
    # and the stamp belongs in the worker too: it changes the worker's bytes
    # after every CSS build, so the browser picks up the new worker.
    stamp = asset_version(None)["asset_version"] if settings.DEBUG else ""
    return urls, stamp


@require_GET
def service_worker(request):
    """
    /sw.js - the service worker, served from the root so its scope is "/".

    Never cached by the browser's HTTP cache (Cache-Control: no-cache), so a
    deployment reaches every installed copy on its next visit rather than
    after the HTTP cache happens to expire.
    """
    urls, stamp = _precache_urls()
    offline_url = reverse("pwa_offline")
    launch_url = reverse("pwa_launch")

    # The cache is named after everything it holds. Any change to a precached
    # file changes its hashed URL, so changes the name, so the activate step
    # drops the old cache whole: nothing from a previous release lingers.
    fingerprint = hashlib.sha256(
        "|".join([settings.SYSTEM_VERSION or "", stamp, offline_url, launch_url, *urls]).encode()
    ).hexdigest()[:12]

    response = render(
        request,
        "pwa/service_worker.js",
        {
            "cache_name": f"lgmed-static-{fingerprint}",
            "precache_json": json.dumps(urls),
            "offline_url_json": json.dumps(offline_url),
            "launch_url_json": json.dumps(launch_url),
            "static_prefix_json": json.dumps(settings.STATIC_URL),
            "notification_icon_json": json.dumps(static("img/pwa/icon-192.png")),
            "dashboard_url_json": json.dumps(reverse("core:dashboard")),
            "dev_json": json.dumps(bool(settings.DEBUG)),
        },
        content_type="application/javascript; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache, max-age=0"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
@cache_control(no_cache=True, max_age=0)
def offline(request):
    """
    The page shown in place of any page that cannot be reached.

    Deliberately anonymous: it names the office and nothing else, because a
    copy of it is kept on the device.
    """
    return render(request, "pwa/offline.html")


@require_GET
@cache_control(no_cache=True, max_age=0)
def launch(request):
    """
    What the installed app opens on: the seal and a spinner while the
    dashboard loads.

    Kept on the device like the offline page, and anonymous for the same
    reason - it names the office and nothing else. Without it, the screen
    between the launch screen and the first page is blank for as long as the
    server takes to answer.
    """
    next_url = reverse("core:dashboard")
    return render(
        request,
        "pwa/launch.html",
        {"next_url": next_url, "next_url_json": json.dumps(next_url)},
    )
