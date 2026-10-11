/* ==========================================================================
   LGMED-IMMS interface behaviour
   Vanilla JavaScript, no framework. Every control degrades to a usable state
   when scripting is unavailable.
   ========================================================================== */

(function () {
  "use strict";

  /* ----------------------------------------------------------------------
     Navigation drawer (below lg)
     ---------------------------------------------------------------------- */

  var sidebar = document.getElementById("sidebar");
  var backdrop = document.getElementById("sidebar-backdrop");
  var openBtn = document.getElementById("sidebar-open");
  var closeBtn = document.getElementById("sidebar-close");
  // The header's menu button, plus "Menu" in the phone's bottom bar
  // (templates/includes/bottom_nav.html). Focus goes back to whichever one
  // opened the drawer.
  var openers = Array.prototype.slice.call(document.querySelectorAll("[data-sidebar-open]"));
  if (openBtn) openers.unshift(openBtn);
  var lastOpener = openBtn;

  function openSidebar(event) {
    if (!sidebar) return;
    lastOpener = (event && event.currentTarget) || openBtn;
    sidebar.classList.remove("-translate-x-full");
    if (backdrop) backdrop.hidden = false;
    openers.forEach(function (button) { button.setAttribute("aria-expanded", "true"); });
    document.body.classList.add("overflow-hidden", "lg:overflow-auto");
    if (closeBtn) closeBtn.focus();
  }

  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.add("-translate-x-full");
    if (backdrop) backdrop.hidden = true;
    openers.forEach(function (button) { button.setAttribute("aria-expanded", "false"); });
    if (lastOpener) lastOpener.focus();
    document.body.classList.remove("overflow-hidden", "lg:overflow-auto");
  }

  openers.forEach(function (button) { button.addEventListener("click", openSidebar); });
  if (closeBtn) closeBtn.addEventListener("click", closeSidebar);
  if (backdrop) backdrop.addEventListener("click", closeSidebar);

  /* ----------------------------------------------------------------------
     Dropdown menus (notifications, account)
     ---------------------------------------------------------------------- */

  var menus = Array.prototype.slice.call(document.querySelectorAll("[data-menu]"));

  function closeAllMenus(except) {
    menus.forEach(function (menu) {
      if (menu === except) return;
      var button = menu.querySelector("[data-menu-button]");
      var panel = menu.querySelector("[data-menu-panel]");
      if (panel) panel.hidden = true;
      if (button) button.setAttribute("aria-expanded", "false");
    });
  }

  menus.forEach(function (menu) {
    var button = menu.querySelector("[data-menu-button]");
    var panel = menu.querySelector("[data-menu-panel]");
    if (!button || !panel) return;

    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var isOpen = !panel.hidden;
      closeAllMenus(menu);
      panel.hidden = isOpen;
      button.setAttribute("aria-expanded", String(!isOpen));
    });

    panel.addEventListener("click", function (event) {
      event.stopPropagation();
    });
  });

  document.addEventListener("click", function () {
    closeAllMenus(null);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    closeAllMenus(null);
    if (sidebar && !sidebar.classList.contains("-translate-x-full") && window.innerWidth < 1024) {
      closeSidebar();
    }
  });

  /* ----------------------------------------------------------------------
     Compact search toggle
     ---------------------------------------------------------------------- */

  var searchToggle = document.querySelector("[data-search-toggle]");
  var mobileSearch = document.getElementById("mobile-search");
  if (searchToggle && mobileSearch) {
    searchToggle.addEventListener("click", function () {
      mobileSearch.hidden = !mobileSearch.hidden;
      if (!mobileSearch.hidden) {
        var input = mobileSearch.querySelector("input");
        if (input) input.focus();
      }
    });
  }

  /* ----------------------------------------------------------------------
     Dismissible alerts
     ---------------------------------------------------------------------- */

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-dismiss]");
    if (!button) return;
    var alertEl = button.closest("[role='status'], [role='alert']");
    if (alertEl) alertEl.remove();
  });

  /* ----------------------------------------------------------------------
     One submission per click

     A form marked `data-once` may be posted once. The workflow buttons -
     publish a file, take it back down, submit a record for review - are not
     idempotent in the eyes of the person clicking them, and a server that
     takes a second or two invites a second click. Without this, that second
     click posts the same action again and the page that comes back says
     something the person did not ask for: "already on the public website", or
     a second line in the audit trail for one decision.

     Bound once, on the document, so an element that arrives later cannot end
     up with two listeners firing twice - which is the shape of bug this is
     here to prevent, not to create.

     The submission is never cancelled on the first click. The buttons are
     disabled on the next tick, after the browser has taken the post, so the
     form still travels and a keyboard submission behaves like a click.

     None of this is a control. The server re-checks every one of these
     actions and refuses a repeat on its own; this only spares the person a
     confusing message.
     ---------------------------------------------------------------------- */

  var onceButtons = function (form) {
    return form.querySelectorAll("button[type=submit], input[type=submit]");
  };

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches || !form.matches("form[data-once]")) return;

    if (form.dataset.onceSubmitted === "true") {
      event.preventDefault();
      return;
    }
    form.dataset.onceSubmitted = "true";

    window.setTimeout(function () {
      Array.prototype.forEach.call(onceButtons(form), function (button) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      });
    }, 0);
  });

  /* ----------------------------------------------------------------------
     Working... overlay

     A form marked `data-loading="some-id"` shows the element with that id
     while it is posted - for the requests that take long enough to look
     stuck, such as reading an uploaded workbook. The page that comes back
     replaces it; nothing needs to hide it on success.
     ---------------------------------------------------------------------- */

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !form || !form.matches || !form.matches("form[data-loading]")) return;
    // No file chosen: the server answers at once with the error, so a
    // loading screen would only flash.
    var files = form.querySelectorAll("input[type=file][required], input[type=file][data-loading-requires]");
    for (var i = 0; i < files.length; i++) {
      if (!files[i].files || !files[i].files.length) return;
    }
    var overlay = document.getElementById(form.getAttribute("data-loading"));
    if (!overlay) return;
    overlay.hidden = false;
    overlay.classList.remove("hidden");
    var focusable = overlay.querySelector("[tabindex]");
    if (focusable) focusable.focus();
  });

  /* ----------------------------------------------------------------------
     Please-wait screen

     Every POST form - Save, Submit, Approve, Delete - shows the shared
     dialog in templates/includes/page_loading.html while it is sent, so a
     slow save never looks like a click that did nothing. Searches and
     filters are GET and are left alone. A form words the screen with
     data-loading-title / data-loading-note, or opts out with
     data-no-loading; one with its own data-loading overlay keeps that.
     ---------------------------------------------------------------------- */

  var pageLoading = document.getElementById("page-loading");

  if (pageLoading && typeof pageLoading.showModal === "function") {
    var loadingTitle = pageLoading.querySelector("[data-loading-title]");
    var loadingNote = pageLoading.querySelector("[data-loading-note]");
    var defaultTitle = loadingTitle.textContent;
    var defaultNote = loadingNote.textContent;

    // Nothing to cancel once the post has left: Escape would only hide the
    // screen while the save carries on behind it.
    pageLoading.addEventListener("cancel", function (event) {
      event.preventDefault();
    });

    var showPageLoading = function (form) {
      loadingTitle.textContent = form.getAttribute("data-loading-title") || defaultTitle;
      loadingNote.textContent = form.getAttribute("data-loading-note") || defaultNote;
      if (!pageLoading.open) pageLoading.showModal();
    };
    // For a page script that holds a submission back before it is posted -
    // the sign-in form waits on reCAPTCHA - and so hides it from the handler
    // below.
    window.showPageLoading = showPageLoading;

    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (event.defaultPrevented || !form || !form.matches) return;
      if (form.matches("[data-no-loading], [data-loading]")) return;

      var submitter = event.submitter;
      var method = (submitter && submitter.getAttribute("formmethod")) ||
        form.getAttribute("method") || "get";
      if (method.toLowerCase() !== "post") return;
      var target = (submitter && submitter.getAttribute("formtarget")) ||
        form.getAttribute("target");
      if (target && target !== "_self") return;

      showPageLoading(form);
    });

    window.addEventListener("pageshow", function (event) {
      if (event.persisted && pageLoading.open) pageLoading.close();
    });
  }

  /* A page restored from the back/forward cache comes back with the buttons
     still disabled and the guard still set, which would leave the action
     unusable. Putting them back is the whole of the fix. */

  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    Array.prototype.forEach.call(
      document.querySelectorAll("form[data-loading]"),
      function (form) {
        var overlay = document.getElementById(form.getAttribute("data-loading"));
        if (overlay) {
          overlay.hidden = true;
          overlay.classList.add("hidden");
        }
      }
    );
    var forms = document.querySelectorAll("form[data-once]");
    Array.prototype.forEach.call(forms, function (form) {
      delete form.dataset.onceSubmitted;
      Array.prototype.forEach.call(onceButtons(form), function (button) {
        button.disabled = false;
        button.removeAttribute("aria-disabled");
      });
    });
  });

  /* ----------------------------------------------------------------------
     Confirmation dialogs
     Native <dialog> gives us focus trapping and Escape handling for free.
     ---------------------------------------------------------------------- */

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-dialog-open]");
    if (opener) {
      var dialog = document.getElementById(opener.getAttribute("data-dialog-open"));
      if (dialog && typeof dialog.showModal === "function") {
        event.preventDefault();
        dialog.showModal();
      }
      return;
    }

    var closer = event.target.closest("[data-dialog-close]");
    if (closer) {
      var openDialog = closer.closest("dialog");
      if (openDialog) openDialog.close();
    }
  });

  /* ----------------------------------------------------------------------
     PDF viewer

     A link marked data-pdf-view opens its PDF in the viewer dialog
     (templates/includes/pdf_viewer.html) instead of leaving the page. Phones
     are left to follow the link: their browsers will not draw a PDF inside a
     page, and open it in their own reader instead.
     ---------------------------------------------------------------------- */

  var pdfViewer = document.getElementById("pdf-viewer");
  if (pdfViewer && typeof pdfViewer.showModal === "function") {
    var pdfFrame = pdfViewer.querySelector("[data-pdf-frame]");
    var pdfTitle = pdfViewer.querySelector("[data-pdf-title]");
    var pdfNewTab = pdfViewer.querySelector("[data-pdf-newtab]");
    var pdfDownload = pdfViewer.querySelector("[data-pdf-download]");

    document.addEventListener("click", function (event) {
      var link = event.target.closest("a[data-pdf-view]");
      if (!link || window.matchMedia("(max-width: 639px)").matches) return;
      event.preventDefault();

      var title = link.getAttribute("data-pdf-title") || "Document";
      pdfTitle.textContent = title;
      pdfFrame.title = "Preview of " + title;
      pdfNewTab.href = link.href;
      var download = link.getAttribute("data-pdf-download");
      pdfDownload.classList.toggle("hidden", !download);
      pdfDownload.href = download || "#";
      pdfFrame.src = link.href;
      pdfViewer.showModal();
    });

    // Let go of the file when the viewer closes, so a large PDF is not kept
    // loaded behind the page and the next one does not flash the last.
    pdfViewer.addEventListener("close", function () {
      pdfFrame.src = "about:blank";
    });
  }

  /* ----------------------------------------------------------------------
     Required notices

     A dialog marked data-dialog-required opens as soon as the page loads and
     cannot be waved away with Escape: it closes only by submitting one of its
     own forms (the Data Privacy Act notice after sign-in).
     ---------------------------------------------------------------------- */

  document.querySelectorAll("dialog[data-dialog-required]").forEach(function (dialog) {
    if (typeof dialog.showModal !== "function") return;
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
    });
    // Rendered open so it still shows without scripting; reopened here as a
    // modal so the page behind it cannot be used until it is answered.
    if (dialog.open) dialog.close();
    dialog.showModal();

    var agree = dialog.querySelector("[data-agree-checkbox]");
    var submit = dialog.querySelector("[data-agree-submit]");
    if (agree && submit) {
      var sync = function () { submit.disabled = !agree.checked; };
      agree.addEventListener("change", sync);
      sync();
    }
  });

  /* ----------------------------------------------------------------------
     Full-screen announcement

     A system notice posted with "Cover the page and sound an alert" covers
     the screen and beeps until the user acknowledges it
     (templates/includes/system_notice.html). Acknowledgement is remembered
     per notice in this browser, so it is not shown again on every page - only
     when the notice is changed. A notice posted while a page is already open
     arrives over the live connection below (or, failing that, the status
     check in pwa.js) as an "lgmed:notice" event.

     Browsers refuse sound until the person has interacted with the page. If
     the first beep is refused, it plays on the first key press or click
     instead, and repeats every few seconds while the notice is unanswered.
     ---------------------------------------------------------------------- */

  var announcement = document.getElementById("system-announcement");

  if (announcement && typeof announcement.showModal === "function") {
    var ACK_KEY = "lgmed.notice.acknowledged";
    var NOTICE_LEVELS = {
      danger: { border: "border-red-600", icon: "bg-red-100 text-red-700", label: "text-red-700", title: "Urgent announcement" },
      warning: { border: "border-amber-500", icon: "bg-amber-100 text-amber-700", label: "text-amber-700", title: "Important announcement" },
      info: { border: "border-blue-600", icon: "bg-blue-100 text-blue-700", label: "text-blue-700", title: "Announcement" },
    };
    var BEEP_REPEATS = 5;
    var memoryAck = "";
    var currentKey = "";
    var beepTimer = null;
    var beepsLeft = 0;
    var audioContext = null;

    var readAck = function () {
      try { return window.localStorage.getItem(ACK_KEY) || memoryAck; } catch (error) { return memoryAck; }
    };
    var writeAck = function (key) {
      memoryAck = key;
      try { window.localStorage.setItem(ACK_KEY, key); } catch (error) { /* private mode */ }
    };

    var getAudio = function () {
      var Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return null;
      if (!audioContext) audioContext = new Context();
      return audioContext;
    };

    // Three short tones, higher for a more serious notice. False when the
    // browser is still holding sound back.
    var beep = function (level) {
      var ctx = getAudio();
      if (!ctx) return false;
      if (ctx.state === "suspended") {
        ctx.resume();
        return false;
      }
      var frequency = level === "danger" ? 1046 : level === "warning" ? 880 : 740;
      var start = ctx.currentTime + 0.05;
      for (var i = 0; i < 3; i += 1) {
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        var at = start + i * 0.32;
        osc.type = "square";
        osc.frequency.value = frequency;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.22);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(at);
        osc.stop(at + 0.24);
      }
      return true;
    };

    var stopBeeping = function () {
      window.clearInterval(beepTimer);
      beepTimer = null;
      beepsLeft = 0;
    };

    var ring = function () {
      if (!announcement.open || beepsLeft <= 0) return stopBeeping();
      if (beep(announcement.getAttribute("data-notice-level"))) beepsLeft -= 1;
    };

    var startBeeping = function () {
      stopBeeping();
      beepsLeft = BEEP_REPEATS;
      ring();
      beepTimer = window.setInterval(ring, 6000);
    };

    // Sound refused before any interaction: the first key press or click
    // unlocks it, and the first beep plays then rather than six seconds later.
    var unlock = function () {
      var ctx = getAudio();
      if (!ctx || ctx.state !== "suspended") return;
      ctx.resume().then(function () {
        if (announcement.open && beepsLeft === BEEP_REPEATS) ring();
      });
    };
    document.addEventListener("pointerdown", unlock, true);
    document.addEventListener("keydown", unlock, true);

    var setLevelClasses = function (el, kind, level) {
      Object.keys(NOTICE_LEVELS).forEach(function (name) {
        NOTICE_LEVELS[name][kind].split(" ").forEach(function (cls) { el.classList.remove(cls); });
      });
      NOTICE_LEVELS[level][kind].split(" ").forEach(function (cls) { el.classList.add(cls); });
    };

    var paint = function (notice) {
      var level = NOTICE_LEVELS[notice.level] ? notice.level : "info";
      setLevelClasses(announcement.querySelector("[data-notice-panel]"), "border", level);
      setLevelClasses(announcement.querySelector("[data-notice-icon]"), "icon", level);
      var label = announcement.querySelector("[data-notice-label]");
      setLevelClasses(label, "label", level);
      label.textContent = NOTICE_LEVELS[level].title;
      announcement.querySelector("[data-notice-message]").textContent = notice.message;
      announcement.setAttribute("data-notice-key", notice.key);
      announcement.setAttribute("data-notice-level", level);
    };

    var showAnnouncement = function (notice) {
      if (!notice || !notice.takeover || !notice.key) return;
      if (readAck() === notice.key || currentKey === notice.key) return;
      // The privacy notice comes first; answering it reloads the page, and
      // the announcement follows on the next one.
      var privacy = document.getElementById("privacy-notice");
      if (privacy && privacy.open) return;
      currentKey = notice.key;
      paint(notice);
      if (!announcement.open) announcement.showModal();
      announcement.querySelector("[data-notice-acknowledge]").focus();
      startBeeping();
    };

    announcement.addEventListener("cancel", function (event) {
      event.preventDefault();
    });

    announcement.querySelector("[data-notice-acknowledge]").addEventListener("click", function () {
      writeAck(currentKey);
      stopBeeping();
      announcement.close();
    });

    // A notice withdrawn, or replaced by one without the cover, is taken down
    // from pages still showing it.
    document.addEventListener("lgmed:notice", function (event) {
      var notice = event.detail;
      if (!notice || !notice.takeover) {
        if (announcement.open) {
          stopBeeping();
          announcement.close();
        }
        currentKey = "";
        return;
      }
      showAnnouncement(notice);
    });

    /* -- Live connection ---------------------------------------------------
       A WebSocket to core/consumers.py delivers a notice the moment it is
       posted. It reconnects by itself, waiting longer after each failure, and
       pings every 25 seconds so a proxy or tunnel does not drop it as idle.
       If it never connects, the once-a-minute status check in pwa.js still
       delivers the notice. */

    var liveSocket = null;
    var liveRetry = 1000;
    var livePing = null;
    var liveTimer = null;

    var connectLive = function () {
      if (!("WebSocket" in window)) return;
      var scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
      try {
        liveSocket = new WebSocket(scheme + window.location.host + "/ws/live/");
      } catch (error) {
        return;
      }
      liveSocket.addEventListener("open", function () {
        liveRetry = 1000;
        window.clearInterval(livePing);
        livePing = window.setInterval(function () {
          if (liveSocket && liveSocket.readyState === 1) {
            liveSocket.send(JSON.stringify({ type: "ping" }));
          }
        }, 25000);
      });
      liveSocket.addEventListener("message", function (event) {
        var data;
        try { data = JSON.parse(event.data); } catch (error) { return; }
        if (data && data.type === "notice") {
          document.dispatchEvent(new CustomEvent("lgmed:notice", { detail: data.notice }));
        }
      });
      liveSocket.addEventListener("close", function (event) {
        window.clearInterval(livePing);
        liveSocket = null;
        // 4401: no longer signed in. The next page opened goes to sign-in.
        if (event.code === 4401) return;
        liveTimer = window.setTimeout(connectLive, liveRetry);
        liveRetry = Math.min(liveRetry * 2, 30000);
      });
    };

    // Back on the network, or back from a sleeping laptop: reconnect at once.
    window.addEventListener("online", function () {
      if (!liveSocket) {
        window.clearTimeout(liveTimer);
        liveRetry = 1000;
        connectLive();
      }
    });

    connectLive();

    if (announcement.hasAttribute("data-notice-key")) {
      showAnnouncement({
        key: announcement.getAttribute("data-notice-key"),
        level: announcement.getAttribute("data-notice-level"),
        message: announcement.querySelector("[data-notice-message]").textContent,
        takeover: true,
      });
    }
  }

  /* ----------------------------------------------------------------------
     Calendar activity preview

     Clicking an activity in the month grid opens a summary rather than
     navigating away, so a Chief scanning a busy week does not lose the month
     they were reading. Everything shown is already in the markup - the server
     decided what this user may see, and nothing is fetched - and without
     scripting the same element is an ordinary link to the record.
     ---------------------------------------------------------------------- */

  var peek = document.getElementById("activity-peek");

  if (peek && typeof peek.showModal === "function") {
    var fill = function (name, value) {
      var target = peek.querySelector("[data-peek='" + name + "']");
      var row = peek.querySelector("[data-peek-row='" + name + "']");
      if (target) target.textContent = value || "—";
      /* Rows that would only say "not recorded" are removed rather than shown
         empty: a dialog of dashes is harder to read than a shorter one. */
      if (row) row.hidden = !value;
    };

    document.addEventListener("click", function (event) {
      var link = event.target.closest("[data-activity]");
      if (!link) return;
      /* Ctrl/Cmd/middle click still opens the record in a new tab. */
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;

      event.preventDefault();
      ["title", "type", "owner", "assigned", "section", "when", "time",
       "location", "priority", "status", "visibility", "description"
      ].forEach(function (name) {
        fill(name, link.getAttribute("data-" + name));
      });

      var open = peek.querySelector("[data-peek='url']");
      if (open) open.setAttribute("href", link.getAttribute("data-url"));
      peek.showModal();
    });
  }

  /* ----------------------------------------------------------------------
     Calendar day dialog

     The whole day box is a link. Scripting turns it into a dialog that opens
     on the day clicked: what is already scheduled on it, read from the panels
     the server rendered into the page, and a short form to add something to
     it. Adding is what people come to a calendar to do, so the form is the
     point of the dialog and the existing activities are the context that keeps
     it honest - you see the clash before you create it.

     Without scripting the same link loads the day beside the calendar instead,
     and the page's own Add Activity button still opens the full form.
     ---------------------------------------------------------------------- */

  var dayPeek = document.getElementById("day-peek");

  if (dayPeek && typeof dayPeek.showModal === "function") {
    var dayPanels = document.querySelector("[data-day-panels]");
    var dayTitle = dayPeek.querySelector("[data-day-title]");
    var dayCount = dayPeek.querySelector("[data-day-count]");
    var dayBody = dayPeek.querySelector("[data-day-body]");
    var dayExisting = dayPeek.querySelector("[data-day-existing]");
    var dayForm = dayPeek.querySelector("[data-day-form]");
    var dayMore = dayPeek.querySelector("[data-day-more]");
    var dayFull = dayPeek.querySelector("[data-day-full]");
    /* Read once, before the first open: each open appends a date to these.
       Appending to the previous open's href would accumulate query strings. */
    var moreUrl = dayMore ? dayMore.getAttribute("href") : null;

    var dayStart = dayPeek.querySelector("#id_start_date");
    var dayEnd = dayPeek.querySelector("#id_end_date");
    var dayFocus = dayPeek.querySelector("#id_title");

    document.addEventListener("click", function (event) {
      /* A click on an activity chip belongs to that activity, not to the day
         around it. The chip sits above the overlay so this rarely fires, but
         the guard keeps the two handlers from both claiming one click. */
      if (event.target.closest("[data-activity]")) return;

      var cell = event.target.closest("[data-day-open]");
      if (!cell) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;

      event.preventDefault();

      var iso = cell.getAttribute("data-day");
      var panel = dayPanels
        ? dayPanels.querySelector('[data-day-panel="' + iso + '"]')
        : null;
      var count = panel ? panel.querySelectorAll("li").length : 0;

      if (dayTitle) dayTitle.textContent = cell.getAttribute("data-day-label");
      if (dayCount) {
        dayCount.textContent = count
          ? count + (count === 1 ? " activity scheduled" : " activities scheduled")
          : "Nothing scheduled yet";
      }
      /* An empty day shows the form alone rather than a panel saying so - the
         count in the header has already said it. */
      if (dayExisting) dayExisting.hidden = !panel;
      if (dayBody) dayBody.innerHTML = panel ? panel.innerHTML : "";

      if (dayForm) {
        /* A fresh form each time: a title typed and abandoned on Tuesday must
           not turn up when Thursday is opened. Reset first, then set the day,
           or the reset would wipe the date that was just put in. */
        dayForm.reset();
        if (dayStart) dayStart.value = iso;
        if (dayEnd) dayEnd.value = "";
      }
      if (dayMore && moreUrl) dayMore.setAttribute("href", moreUrl + "?date=" + iso);
      if (dayFull) dayFull.setAttribute("href", cell.getAttribute("href"));

      dayPeek.showModal();
      if (dayFocus) dayFocus.focus();
    });
  }

  /* ----------------------------------------------------------------------
     Table row selection (bulk actions)
     ---------------------------------------------------------------------- */

  document.querySelectorAll("[data-select-all]").forEach(function (master) {
    var scope = master.closest("table");
    if (!scope) return;
    master.addEventListener("change", function () {
      scope.querySelectorAll("[data-select-row]").forEach(function (box) {
        box.checked = master.checked;
      });
    });
  });
})();

/* ==========================================================================
   Chart defaults
   Shared so every chart in the system reads as one family: same typeface,
   same restrained palette, same grid weight.
   ========================================================================== */

window.LGMED = window.LGMED || {};

window.LGMED.chartPalette = {
  // Sequential brand blues carry "amount of the same thing".
  brand: ["#1e5498", "#4f8bd0", "#86b0e0", "#bcd3ed"],
  // Status colours match the badge vocabulary exactly (section 4).
  status: {
    success: "#15803d",
    warning: "#b45309",
    danger: "#b91c1c",
    info: "#1e5498",
    neutral: "#94a3b8",
  },
  grid: "#e2e8f0",
  text: "#475569",
  muted: "#94a3b8",
};

/**
 * Shared Chart.js defaults.
 *
 * Extracted so the dashboard and the analytics page read as one system: same
 * typeface, same grid weight, same tooltip. Reduced-motion is honoured here
 * rather than in each chart.
 */
window.LGMED.applyChartDefaults = function () {
  var palette = window.LGMED.chartPalette;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  Chart.defaults.font.family =
    'Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = palette.text;
  Chart.defaults.borderColor = palette.grid;
  Chart.defaults.animation = reduceMotion ? false : { duration: 300 };
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.padding = 14;
  Chart.defaults.plugins.tooltip.backgroundColor = "#0b1c30";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
  Chart.defaults.plugins.tooltip.titleFont = { weight: "600" };
  Chart.defaults.maintainAspectRatio = false;
};

window.LGMED.initCharts = function (data) {
  if (typeof Chart === "undefined" || !data) return;

  var palette = window.LGMED.chartPalette;
  window.LGMED.applyChartDefaults();

  var axis = {
    grid: { color: palette.grid, drawTicks: false },
    border: { display: false },
    ticks: { padding: 8 },
  };
  var categoryAxis = {
    grid: { display: false },
    border: { color: palette.grid },
    ticks: { padding: 6 },
  };

  /* -- Program status ------------------------------------------------- */
  var programStatus = document.getElementById("programStatus");
  if (programStatus && data.programStatus) {
    new Chart(programStatus, {
      type: "doughnut",
      data: {
        labels: data.programStatus.labels,
        datasets: [
          {
            data: data.programStatus.values,
            backgroundColor: [
              palette.status.success,
              palette.status.info,
              palette.status.warning,
              palette.status.neutral,
            ],
            borderColor: "#ffffff",
            borderWidth: 2,
            hoverOffset: 4,
          },
        ],
      },
      options: {
        cutout: "62%",
        plugins: { legend: { position: "right" } },
      },
    });
  }

  /* -- Monitoring activities per month -------------------------------- */
  var monitoring = document.getElementById("monitoringActivity");
  if (monitoring && data.monitoringActivity) {
    new Chart(monitoring, {
      type: "bar",
      data: {
        labels: data.monitoringActivity.labels,
        datasets: [
          {
            label: "Monitoring activities",
            data: data.monitoringActivity.values,
            backgroundColor: palette.brand[0],
            hoverBackgroundColor: palette.brand[1],
            borderRadius: 3,
            maxBarThickness: 34,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: categoryAxis,
          y: Object.assign({ beginAtZero: true, ticks: { precision: 0, padding: 8 } }, axis),
        },
      },
    });
  }

  /* -- LGUs monitored, by LGU type ------------------------------------ */
  var lgu = document.getElementById("lguMonitoring");
  if (lgu && data.lguMonitoring) {
    new Chart(lgu, {
      type: "bar",
      data: {
        labels: data.lguMonitoring.labels,
        datasets: [
          {
            label: "Monitored",
            data: data.lguMonitoring.monitored,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 40,
          },
          {
            label: "Total registered",
            data: data.lguMonitoring.total,
            backgroundColor: palette.brand[2],
            borderRadius: 3,
            maxBarThickness: 40,
          },
        ],
      },
      options: {
        plugins: { legend: { position: "top", align: "end" } },
        scales: {
          x: categoryAxis,
          y: Object.assign({ beginAtZero: true, ticks: { precision: 0, padding: 8 } }, axis),
        },
      },
    });
  }

  /* -- Report submissions --------------------------------------------- */
  var reports = document.getElementById("reportSubmissions");
  if (reports && data.reportSubmissions) {
    new Chart(reports, {
      type: "line",
      data: {
        labels: data.reportSubmissions.labels,
        datasets: [
          {
            label: "Submitted",
            data: data.reportSubmissions.submitted,
            borderColor: palette.brand[0],
            backgroundColor: "rgba(30, 84, 152, 0.08)",
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: "Published",
            data: data.reportSubmissions.published,
            borderColor: palette.status.success,
            backgroundColor: "transparent",
            borderDash: [5, 4],
            tension: 0.3,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "top", align: "end" } },
        scales: {
          x: categoryAxis,
          y: Object.assign({ beginAtZero: true, ticks: { precision: 0, padding: 8 } }, axis),
        },
      },
    });
  }
};

/* ==========================================================================
   Sign-in page
   Three small aids for people typing a password issued to them by someone
   else. Each one is added by script and absent without it, so the form works
   exactly as it always has when JavaScript is unavailable.
   ========================================================================== */

(function () {
  "use strict";

  var form = document.querySelector("[data-signin-form]");
  if (!form) return;

  /* -- Show / hide the password ------------------------------------------
     Issued passwords are long and unfamiliar, and a masked field gives no way
     to tell a typo from a wrong credential. The button is revealed here
     rather than in the template so it is never shown as a dead control. */

  var toggle = form.querySelector("[data-password-toggle]");
  var field = document.getElementById(toggle && toggle.getAttribute("aria-controls"));

  if (toggle && field) {
    var iconShow = toggle.querySelector("[data-password-icon-show]");
    var iconHide = toggle.querySelector("[data-password-icon-hide]");
    var label = toggle.querySelector("[data-password-toggle-label]");

    toggle.classList.remove("hidden");
    toggle.classList.add("flex");

    toggle.addEventListener("click", function () {
      var revealed = field.type === "text";
      field.type = revealed ? "password" : "text";
      toggle.setAttribute("aria-pressed", String(!revealed));
      if (iconShow) iconShow.hidden = !revealed;
      if (iconHide) iconHide.hidden = revealed;
      if (label) label.textContent = revealed ? "Show password" : "Hide password";
      field.focus();
    });

    /* Never leave a password on screen after the form is sent. */
    form.addEventListener("submit", function () {
      field.type = "password";
    });
  }

  /* -- Caps Lock ---------------------------------------------------------
     The commonest cause of a rejected password that the person is certain
     they typed correctly. getModifierState is unsupported on some mobile
     keyboards, which simply means the warning never appears. */

  var caps = form.querySelector("[data-caps-warning]");

  if (caps && field) {
    var updateCaps = function (event) {
      if (typeof event.getModifierState !== "function") return;
      var on = event.getModifierState("CapsLock");
      caps.classList.toggle("hidden", !on);
      caps.classList.toggle("flex", on);
    };

    field.addEventListener("keyup", updateCaps);
    field.addEventListener("keydown", updateCaps);
    field.addEventListener("blur", function () {
      caps.classList.add("hidden");
      caps.classList.remove("flex");
    });
  }

  /* -- One submission ----------------------------------------------------
     A slow authentication invites a second click, which posts the form twice.
     The button is disabled only after the browser has taken the submission,
     so the credentials still travel with it. */

  var submit = form.querySelector("[data-signin-submit]");

  if (submit) {
    form.addEventListener("submit", function () {
      window.setTimeout(function () {
        var text = submit.querySelector("[data-signin-submit-label]");
        submit.disabled = true;
        submit.setAttribute("aria-disabled", "true");
        if (text) text.textContent = "Signing in\u2026";
      }, 0);
    });
  }
})();

/* --------------------------------------------------------------------------
   Declarative actions
   The Content-Security-Policy refuses inline event handlers (onclick=...),
   so the few one-line behaviours the templates need are declared as data
   attributes and handled here, once, for the whole page:
     data-print                     print the page
     data-autosubmit                submit the enclosing form when changed
     data-set-field / -set-value    set a (hidden) field before the button
                                    it sits on submits its form
   -------------------------------------------------------------------------- */

(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var target = event.target.closest ? event.target.closest("[data-print], [data-set-field]") : null;
    if (!target) return;
    if (target.hasAttribute("data-print")) {
      event.preventDefault();
      window.print();
      return;
    }
    var field = document.getElementById(target.getAttribute("data-set-field"));
    if (field) field.value = target.getAttribute("data-set-value") || "";
  });

  document.addEventListener("change", function (event) {
    var target = event.target;
    // form.submit(), as the inline handler it replaces did: no submit
    // listeners, no "saving" overlay - this is a filter, not a save.
    if (target && target.hasAttribute && target.hasAttribute("data-autosubmit") && target.form) {
      target.form.submit();
    }
  });
})();
