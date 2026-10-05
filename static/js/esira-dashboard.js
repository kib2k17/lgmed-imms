/* ==========================================================================
   e-SIRA dashboard - keeps the figures current without reloading the page.

   The figures are rendered by the server first, so the page is complete with
   scripting off; this only refreshes them once a minute, and pauses while the
   tab is hidden so an open tab in the background costs the server nothing.
   ========================================================================== */
(function () {
  "use strict";

  var section = document.querySelector("[data-esira-stats]");
  if (!section || !window.fetch) return;

  var url = section.getAttribute("data-esira-stats");
  var asOf = section.querySelector("[data-esira-asof]");
  var formatter = new Intl.NumberFormat("en-PH");
  var INTERVAL = 60 * 1000;
  var timer = null;

  function refresh() {
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        return response.json();
      })
      .then(function (data) {
        Object.keys(data.figures).forEach(function (key) {
          var node = section.querySelector('[data-esira-stat="' + key + '"]');
          if (node) node.textContent = formatter.format(data.figures[key]);
        });
        if (asOf && data.as_of) asOf.textContent = data.as_of;
      })
      .catch(function () { /* keep the last figures; try again next time */ });
  }

  function start() {
    if (timer === null) timer = window.setInterval(refresh, INTERVAL);
  }

  function stop() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stop();
    } else {
      refresh();
      start();
    }
  });

  start();
})();
