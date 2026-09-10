/* ==========================================================================
   LGMED-iMMS interface behaviour
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

  function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove("-translate-x-full");
    if (backdrop) backdrop.hidden = false;
    if (openBtn) openBtn.setAttribute("aria-expanded", "true");
    document.body.classList.add("overflow-hidden", "lg:overflow-auto");
    if (closeBtn) closeBtn.focus();
  }

  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.add("-translate-x-full");
    if (backdrop) backdrop.hidden = true;
    if (openBtn) {
      openBtn.setAttribute("aria-expanded", "false");
      openBtn.focus();
    }
    document.body.classList.remove("overflow-hidden", "lg:overflow-auto");
  }

  if (openBtn) openBtn.addEventListener("click", openSidebar);
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
