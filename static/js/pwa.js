/* ==========================================================================
   LGMED-iMMS installable app
   Service worker registration, install prompt, connection status, update
   notice and device notifications. Loaded after app.js by base.html and the
   sign-in pages; every part does nothing where the browser lacks the feature,
   so the system behaves exactly as before in a browser that has none of it.

   Nothing here stores a record, a password or a session token. The only thing
   kept in the browser is the number of the newest notification already
   announced (sessionStorage, gone when the tab closes), so the same one is not
   announced twice.
   ========================================================================== */

(function () {
  "use strict";

  var script = document.currentScript;
  var config = script ? script.dataset : {};

  var standalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  var isIOS =
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  document.documentElement.classList.toggle("is-standalone", standalone);

  function byId(id) { return document.getElementById(id); }

  /* ----------------------------------------------------------------------
     Notices (templates/includes/pwa.html)
     ---------------------------------------------------------------------- */

  var hideTimers = {};

  function show(id, ms) {
    var el = byId(id);
    if (!el) return;
    el.hidden = false;
    window.clearTimeout(hideTimers[id]);
    if (ms) hideTimers[id] = window.setTimeout(function () { el.hidden = true; }, ms);
  }

  function hide(id) {
    var el = byId(id);
    if (el) el.hidden = true;
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-pwa-dismiss]");
    if (!button) return;
    var toast = button.closest(".pwa-toast");
    if (toast) toast.hidden = true;
  });

  /* ----------------------------------------------------------------------
     Connection status
     ---------------------------------------------------------------------- */

  function updateConnection(changed) {
    var offline = !navigator.onLine;
    document.documentElement.classList.toggle("is-offline", offline);
    if (offline) {
      hide("pwa-online");
      show("pwa-offline");
    } else {
      hide("pwa-offline");
      hide("pwa-blocked");
      if (changed) show("pwa-online", 3000);
    }
  }

  window.addEventListener("online", function () { updateConnection(true); });
  window.addEventListener("offline", function () { updateConnection(true); });
  updateConnection(false);

  /* Nothing is queued to be sent later (see templates/pwa/service_worker.js),
     so a form submitted with no connection is stopped here, before app.js
     disables its buttons or puts up the please-wait screen - which would
     otherwise sit over a page that is never going to change. The person's
     entries stay where they are. Capture phase on window, so this runs
     before any form handler on the document. */
  window.addEventListener("submit", function (event) {
    if (navigator.onLine) return;
    var form = event.target;
    var submitter = event.submitter;
    var target = (submitter && submitter.getAttribute("formtarget")) || form.getAttribute("target");
    if (target && target !== "_self") return;
    event.preventDefault();
    event.stopPropagation();
    show("pwa-blocked", 8000);
  }, true);

  /* ----------------------------------------------------------------------
     Install
     ---------------------------------------------------------------------- */

  var installButtons = Array.prototype.slice.call(document.querySelectorAll("[data-pwa-install]"));
  var deferredPrompt = null;

  /* The suggestion banner (templates/includes/pwa.html). Its X hides it on
     this device for a month; the account menu item is unaffected. Only the
     time it was closed is stored - a display preference, nothing more. */
  var banner = byId("pwa-install-banner");
  var DISMISS_KEY = "lgmed.install.dismissed";
  var DISMISS_MS = 30 * 24 * 60 * 60 * 1000;

  function bannerDismissed() {
    try {
      var at = Number(window.localStorage.getItem(DISMISS_KEY));
      return at && Date.now() - at < DISMISS_MS;
    } catch (error) {
      return false;
    }
  }

  if (banner) {
    var touch = window.matchMedia("(pointer: coarse)").matches;
    var title = banner.querySelector("[data-pwa-install-title]");
    var note = banner.querySelector("[data-pwa-install-note]");
    if (!touch && title) title.textContent = "Install the desktop app";
    if (isIOS && note) note.textContent = "Add it to your Home Screen to open it like an app.";

    banner.querySelector("[data-pwa-install-dismiss]").addEventListener("click", function () {
      banner.hidden = true;
      try { window.localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (error) { /* private mode */ }
    });
  }

  function showInstall(visible) {
    installButtons.forEach(function (button) { button.hidden = !visible; });
    if (banner) banner.hidden = !visible || standalone || bannerDismissed();
  }

  /* Waiting for the browser. Chrome and Edge announce that the app can be
     installed (beforeinstallprompt) only once the service worker is running,
     which on a first visit can be a moment after the page appears. A click in
     that moment waits for the announcement - with a spinner on the button -
     rather than falling through to instructions. */
  var promptWaiters = [];
  var PREPARE_MS = 4000;   // within the click's user-activation window

  var SPINNER =
    '<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25"></circle>' +
    '<path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" stroke-width="3" stroke-linecap="round"></path></svg>';

  function setBusy(button, label) {
    if (!button.hasAttribute("data-label-html")) {
      button.setAttribute("data-label-html", button.innerHTML);
    }
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.innerHTML = SPINNER + "<span>" + label + "</span>";
  }

  function setIdle(button) {
    if (button.hasAttribute("data-label-html")) {
      button.innerHTML = button.getAttribute("data-label-html");
    }
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }

  function waitForPrompt(ms) {
    if (deferredPrompt) return Promise.resolve(deferredPrompt);
    return new Promise(function (resolve) {
      var timer = window.setTimeout(function () {
        promptWaiters = promptWaiters.filter(function (w) { return w !== done; });
        resolve(null);
      }, ms);
      function done(event) {
        window.clearTimeout(timer);
        resolve(event);
      }
      promptWaiters.push(done);
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    // Held for the Install button rather than shown as the browser's own
    // mini-infobar over the work.
    event.preventDefault();
    deferredPrompt = event;
    showInstall(true);
    var waiting = promptWaiters;
    promptWaiters = [];
    waiting.forEach(function (resolve) { resolve(event); });
  });

  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
    installButtons.forEach(setIdle);
    showInstall(false);
    show("pwa-installed", 6000);
  });

  // Safari on iOS never fires beforeinstallprompt; the menu item opens the
  // instructions instead.
  if (isIOS && !standalone) showInstall(true);

  // On plain HTTP (the office-network address) beforeinstallprompt never
  // fires, because a real install needs HTTPS. The suggestion is offered
  // anyway, and its button shows the browser's own shortcut steps instead.
  var insecure = !window.isSecureContext;
  if (insecure && !isIOS && !standalone) showInstall(true);

  function httpSteps() {
    var ua = navigator.userAgent;
    if (/android/i.test(ua)) return "android";
    if (/edg\//i.test(ua)) return "edge";
    if (/chrome\//i.test(ua)) return "chrome";
    return "other";
  }

  function showSteps() {
    var help = byId(isIOS ? "pwa-ios-install" : "pwa-http-install");
    if (!help || typeof help.showModal !== "function") return;
    if (!isIOS) {
      var which = httpSteps();
      Array.prototype.forEach.call(help.querySelectorAll("[data-pwa-steps]"), function (steps) {
        steps.hidden = steps.getAttribute("data-pwa-steps") !== which;
      });
    }
    help.showModal();
  }

  /* One click installs. Where the browser allows it (HTTPS, Chrome/Edge on
     Windows, Android, macOS), the button opens the browser's own install
     confirmation directly - no instructions. Only where a browser has no way
     for a page to install itself (Safari on iPhone, any plain-HTTP address)
     are its own steps shown instead, because nothing else can work there. */
  function install(button) {
    var canPrompt = window.isSecureContext && !isIOS;
    if (!deferredPrompt && !canPrompt) {
      showSteps();
      return;
    }

    if (!deferredPrompt) setBusy(button, "Preparing…");
    waitForPrompt(deferredPrompt ? 0 : PREPARE_MS).then(function (event) {
      if (!event) {
        // The browser never offered the install: already installed, or a
        // browser (Firefox desktop) that cannot install apps.
        setIdle(button);
        showSteps();
        return;
      }
      deferredPrompt = null;
      event.prompt();
      event.userChoice.then(function (choice) {
        if (choice && choice.outcome === "accepted") {
          // appinstalled follows once the browser has set the app up.
          setBusy(button, "Installing…");
          window.setTimeout(function () { setIdle(button); showInstall(false); }, 10000);
        } else {
          setIdle(button);
        }
      });
    }).catch(function () {
      setIdle(button);
      showSteps();
    });
  }

  installButtons.forEach(function (button) {
    button.addEventListener("click", function () { install(button); });
  });

  /* ----------------------------------------------------------------------
     Page-loading bar (installed app only)

     A browser tab shows its own progress while the next page loads; an app
     window shows nothing, so a tap on a slow connection looks ignored. This
     draws a thin bar along the top from the tap until the next page replaces
     this one. Listeners sit on window, after app.js's on document, so a click
     app.js has taken over (a dialog, the PDF viewer, a calendar preview) has
     already been marked defaultPrevented and is left alone. POST forms keep
     app.js's own please-wait screen.
     ---------------------------------------------------------------------- */

  if (standalone) {
    var progress = null;
    var progressTimer = null;

    var startProgress = function () {
      if (!progress) {
        progress = document.createElement("div");
        progress.className = "page-progress no-print";
        progress.setAttribute("aria-hidden", "true");
        document.body.appendChild(progress);
      }
      progress.innerHTML = "<span></span>";
      progress.hidden = false;
      // A link that turns out to be a download never replaces the page.
      window.clearTimeout(progressTimer);
      progressTimer = window.setTimeout(stopProgress, 15000);
    };

    var stopProgress = function () {
      window.clearTimeout(progressTimer);
      if (progress) progress.hidden = true;
    };

    window.addEventListener("click", function (event) {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link || link.hasAttribute("download")) return;
      if (link.target && link.target !== "_self") return;
      var url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      // Same page, different #section: nothing loads.
      if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
      startProgress();
    });

    window.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      var form = event.target;
      var method = ((event.submitter && event.submitter.getAttribute("formmethod")) ||
        form.getAttribute("method") || "get").toLowerCase();
      if (method === "get") startProgress();
    });

    window.addEventListener("pageshow", stopProgress);
  }

  /* ----------------------------------------------------------------------
     Running from the iPhone home screen
     ---------------------------------------------------------------------- */

  if (standalone && isIOS) {
    // No browser toolbar, so no back button: reveal the header's own.
    Array.prototype.forEach.call(document.querySelectorAll("[data-pwa-back]"), function (button) {
      button.hidden = false;
      button.addEventListener("click", function () { window.history.back(); });
    });

    // A PDF followed inside the home-screen app fills the screen with no way
    // back to the system. Opened in a new tab it goes to Safari's viewer,
    // which has a Done button. Phones only - larger screens use the viewer.
    if (window.matchMedia("(max-width: 639px)").matches) {
      document.addEventListener("click", function (event) {
        var link = event.target.closest("a[data-pdf-view]");
        if (link) link.setAttribute("target", "_blank");
      }, true);
    }
  }

  /* ----------------------------------------------------------------------
     Service worker

     Only over HTTPS (or on localhost): browsers refuse a worker anywhere
     else, so on the plain-HTTP office-network address this quietly does
     nothing and the system runs as an ordinary website.
     ---------------------------------------------------------------------- */

  var registration = null;

  if ("serviceWorker" in navigator && window.isSecureContext && config.swUrl) {
    var reloadRequested = false;

    var offerUpdate = function (worker) {
      var toast = byId("pwa-update");
      if (!toast) return;
      var reload = toast.querySelector("[data-pwa-reload]");
      reload.onclick = function () {
        reloadRequested = true;
        reload.disabled = true;
        worker.postMessage({ type: "SKIP_WAITING" });
      };
      show("pwa-update");
    };

    navigator.serviceWorker.addEventListener("controllerchange", function () {
      // Only after the person asked: the first install also changes the
      // controller, and must not reload a page under someone's typing.
      if (!reloadRequested) return;
      reloadRequested = false;
      window.location.reload();
    });

    window.addEventListener("load", function () {
      navigator.serviceWorker.register(config.swUrl, { scope: "/" }).then(function (reg) {
        registration = reg;
        if (reg.waiting && navigator.serviceWorker.controller) offerUpdate(reg.waiting);
        reg.addEventListener("updatefound", function () {
          var worker = reg.installing;
          if (!worker) return;
          worker.addEventListener("statechange", function () {
            if (worker.state === "installed" && navigator.serviceWorker.controller) {
              offerUpdate(worker);
            }
          });
        });
        startNotifications();
      }).catch(function (error) {
        if (window.console) console.warn("Service worker not registered:", error);
        startNotifications();
      });
    });
  } else {
    // No worker on the plain-HTTP address, but the check still keeps the bell
    // current and delivers a full-screen announcement to pages left open.
    window.addEventListener("load", startNotifications);
  }

  /* ----------------------------------------------------------------------
     Notifications

     The bell is the system's own notification list
     (notifications.views.notification_status reads the same records). While
     the system is open, it is asked once a minute for the unread count; the
     bell and the installed app's icon badge are kept to it, and - if the
     person has allowed it - a new notification raises a device notification
     while the system is in the background. Only the notification's title is
     shown; the detail stays behind the sign-in.
     ---------------------------------------------------------------------- */

  var POLL_MS = 60 * 1000;
  var SEEN_KEY = "lgmed.notifications.announced";
  var pollTimer = null;
  var polling = false;

  function readSeen() {
    try {
      var value = window.sessionStorage.getItem(SEEN_KEY);
      return value === null ? null : Number(value);
    } catch (error) {
      return null;
    }
  }

  function writeSeen(value) {
    try { window.sessionStorage.setItem(SEEN_KEY, String(value)); } catch (error) { /* private mode */ }
  }

  function setBadge(count) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-notif-badge]"), function (badge) {
      badge.hidden = !count;
      badge.textContent = count > 9 ? "9+" : String(count);
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-notif-sr]"), function (label) {
      label.setAttribute("data-unread", String(count));
      label.textContent = count
        ? "Notifications, " + count + " unread"
        : "Notifications, none unread";
    });
    // The installed app's icon (Windows taskbar, Android launcher, macOS dock).
    try {
      if (count && navigator.setAppBadge) navigator.setAppBadge(count);
      else if (!count && navigator.clearAppBadge) navigator.clearAppBadge();
    } catch (error) { /* not supported here */ }
  }

  function announce(items) {
    if (!items || !items.length) {
      // Nothing unread: anything that arrives from now on is new.
      if (readSeen() === null) writeSeen(0);
      return;
    }
    var newest = items.reduce(function (max, item) { return Math.max(max, item.id); }, 0);
    var seen = readSeen();
    writeSeen(Math.max(newest, seen || 0));
    // The first check of a visit only takes its bearings: everything already
    // unread was on the page when it loaded.
    if (seen === null) return;
    if (!registration || !("Notification" in window) || Notification.permission !== "granted") return;
    if (document.visibilityState === "visible") return;

    items
      .filter(function (item) { return item.id > seen; })
      .reverse()
      .forEach(function (item) {
        registration.showNotification(item.title, {
          body: "LGMED-iMMS",
          icon: config.iconUrl,
          badge: config.iconUrl,
          tag: "lgmed-notification-" + item.id,
          data: { url: item.url },
        });
      });
  }

  function poll() {
    if (polling || !config.statusUrl) return;
    if (!navigator.onLine) return schedule();
    polling = true;
    fetch(config.statusUrl, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    }).then(function (response) {
      // Signed out or the session has ended: stop asking. The next page the
      // person opens takes them to the sign-in, as it always has.
      if (response.status === 401) {
        config.statusUrl = "";
        setBadge(0);
        return null;
      }
      return response.ok ? response.json() : null;
    }).then(function (data) {
      if (!data) return;
      setBadge(data.unread);
      announce(data.latest);
      // The system notice, for a full-screen announcement posted while this
      // page was open (static/js/app.js).
      document.dispatchEvent(new CustomEvent("lgmed:notice", { detail: data.notice || null }));
    }).catch(function () {
      /* A failed check is not worth interrupting anyone for. */
    }).then(function () {
      polling = false;
      schedule();
    });
  }

  function schedule() {
    window.clearTimeout(pollTimer);
    if (config.statusUrl) pollTimer = window.setTimeout(poll, POLL_MS);
  }

  function startNotifications() {
    if (!config.statusUrl) return;
    var label = document.querySelector("[data-notif-sr]");
    if (label) setBadge(Number(label.getAttribute("data-unread")) || 0);
    poll();
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") poll();
    });

    var enable = document.querySelectorAll("[data-push-enable]");
    var syncEnable = function () {
      var undecided = "Notification" in window && Notification.permission === "default";
      Array.prototype.forEach.call(enable, function (button) { button.hidden = !undecided; });
    };
    Array.prototype.forEach.call(enable, function (button) {
      button.addEventListener("click", function () {
        // Asked only on this click: a permission prompt on page load is one
        // most people refuse, and then it cannot be asked again.
        var asked = Notification.requestPermission(syncEnable);
        if (asked && asked.then) asked.then(syncEnable);
      });
    });
    syncEnable();
  }

  // Where the worker cannot run (plain HTTP), the count still stays current.
  if (!("serviceWorker" in navigator && window.isSecureContext)) {
    window.addEventListener("load", startNotifications);
  }
})();
