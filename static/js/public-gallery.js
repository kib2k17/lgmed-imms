/* ==========================================================================
   LGMED-IMMS public website - photograph gallery
   Vanilla JavaScript, no framework, no third-party lightbox.

   The grid on the page is already the whole feature: ordered tiles, each one
   a link to the full photograph. This file adds the enlarged view on top of
   it, and is written so that its absence costs a visitor nothing - the links
   still open the pictures.

   What it is careful about, because a government site gets every browser
   there is:

     the overlay is built once, on the first open, and reused;
     the page behind it does not scroll while it is up;
     Escape closes, arrows move, Tab stays inside the overlay;
     focus returns to the tile the visitor opened from;
     a swipe moves between photographs on a touch screen.
   ========================================================================== */

(function () {
  "use strict";

  var gallery = document.querySelector("[data-gallery]");
  if (!gallery) return;

  var tiles = Array.prototype.slice.call(
    gallery.querySelectorAll("[data-gallery-item]")
  );
  if (!tiles.length) return;

  var photographs = tiles.map(function (tile) {
    var picture = tile.querySelector("img");
    return {
      href: tile.getAttribute("href"),
      caption: tile.getAttribute("data-caption") || "",
      description: tile.getAttribute("data-description") || "",
      alt: picture ? picture.getAttribute("alt") : "",
      tile: tile
    };
  });

  var overlay = null;
  var parts = {};
  var current = 0;
  var opener = null;

  /* ----------------------------------------------------------------------
     The overlay, built once
     ---------------------------------------------------------------------- */

  function arrow(direction, label, path) {
    var button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", label);
    button.className =
      "absolute top-1/2 z-10 inline-flex size-11 -translate-y-1/2 items-center " +
      "justify-center rounded-full border border-white/25 bg-slate-900/60 " +
      "text-white transition hover:bg-slate-900/85 focus-visible:outline-2 " +
      "focus-visible:outline-offset-2 focus-visible:outline-white " +
      (direction === "previous" ? "left-2 sm:left-4" : "right-2 sm:right-4");
    button.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" class="size-6" aria-hidden="true" ' +
      'focusable="false"><path d="' + path + '"/></svg>';
    return button;
  }

  function build() {
    overlay = document.createElement("div");
    overlay.className =
      "fixed inset-0 z-100 hidden bg-slate-950/92 backdrop-blur-sm";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Photograph viewer");

    var shell = document.createElement("div");
    shell.className = "relative flex h-full w-full flex-col";

    /* -- top bar: where you are, and the way out ------------------------ */
    var bar = document.createElement("div");
    bar.className =
      "flex shrink-0 items-center justify-between gap-3 px-4 py-3 text-white sm:px-6";

    parts.counter = document.createElement("p");
    parts.counter.className = "text-meta font-medium tracking-wide text-white/75";
    parts.counter.setAttribute("aria-live", "polite");
    bar.appendChild(parts.counter);

    parts.close = document.createElement("button");
    parts.close.type = "button";
    parts.close.setAttribute("aria-label", "Close the photograph viewer");
    parts.close.className =
      "inline-flex items-center gap-1.5 rounded-md border border-white/25 " +
      "px-2.5 py-1.5 text-xs font-medium text-white transition " +
      "hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2 " +
      "focus-visible:outline-white";
    parts.close.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" class="size-4" aria-hidden="true" ' +
      'focusable="false"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>Close';
    bar.appendChild(parts.close);
    shell.appendChild(bar);

    /* -- the photograph -------------------------------------------------- */
    var stage = document.createElement("div");
    stage.className =
      "relative flex min-h-0 flex-1 items-center justify-center px-2 sm:px-16";

    parts.previous = arrow("previous", "Previous photograph", "m15 18-6-6 6-6");
    parts.next = arrow("next", "Next photograph", "m9 18 6-6-6-6");
    stage.appendChild(parts.previous);
    stage.appendChild(parts.next);

    parts.image = document.createElement("img");
    parts.image.className =
      "max-h-full max-w-full rounded-md object-contain shadow-2xl";
    parts.image.setAttribute("decoding", "async");
    stage.appendChild(parts.image);
    shell.appendChild(stage);

    /* -- the caption ----------------------------------------------------- */
    var footer = document.createElement("div");
    footer.className = "shrink-0 px-4 py-4 text-center sm:px-6";

    parts.caption = document.createElement("p");
    parts.caption.className = "text-sm font-medium text-white";
    footer.appendChild(parts.caption);

    parts.description = document.createElement("p");
    parts.description.className =
      "mx-auto mt-1 max-w-2xl text-meta leading-relaxed text-white/70";
    footer.appendChild(parts.description);

    shell.appendChild(footer);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    /* -- wiring ---------------------------------------------------------- */
    parts.close.addEventListener("click", close);
    parts.previous.addEventListener("click", function () { step(-1); });
    parts.next.addEventListener("click", function () { step(1); });

    // Clicking the dark surround closes; clicking the photograph does not.
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay || event.target === shell ||
          event.target === stage || event.target === footer) {
        close();
      }
    });

    overlay.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        step(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        step(1);
      } else if (event.key === "Tab") {
        trap(event);
      }
    });

    /* Swiping, for the phone this will mostly be read on. */
    var startX = null;
    stage.addEventListener("touchstart", function (event) {
      startX = event.changedTouches[0].clientX;
    }, { passive: true });
    stage.addEventListener("touchend", function (event) {
      if (startX === null) return;
      var shift = event.changedTouches[0].clientX - startX;
      startX = null;
      if (Math.abs(shift) > 45) step(shift < 0 ? 1 : -1);
    }, { passive: true });
  }

  /* ----------------------------------------------------------------------
     Behaviour
     ---------------------------------------------------------------------- */

  function focusable() {
    return Array.prototype.slice.call(
      overlay.querySelectorAll("button:not([disabled])")
    );
  }

  function trap(event) {
    var stops = focusable();
    if (!stops.length) return;
    var first = stops[0];
    var last = stops[stops.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function show(index) {
    var total = photographs.length;
    current = (index + total) % total;
    var photograph = photographs[current];

    parts.image.src = photograph.href;
    parts.image.alt = photograph.alt || photograph.caption;
    parts.caption.textContent = photograph.caption;
    parts.description.textContent = photograph.description;
    parts.description.hidden = !photograph.description;
    parts.counter.textContent = "Photograph " + (current + 1) + " of " + total;

    // One photograph is not a sequence; hide the controls rather than offer
    // two buttons that do nothing.
    var many = total > 1;
    parts.previous.hidden = !many;
    parts.next.hidden = !many;

    // Warm the neighbours so moving through the gallery does not flash.
    if (many) {
      [current + 1, current - 1].forEach(function (neighbour) {
        var next = new Image();
        next.src = photographs[(neighbour + total) % total].href;
      });
    }
  }

  function step(direction) {
    if (photographs.length < 2) return;
    show(current + direction);
  }

  function open(index, from) {
    if (!overlay) build();
    opener = from || null;
    show(index);
    overlay.classList.remove("hidden");
    document.documentElement.classList.add("overflow-hidden");
    parts.close.focus();
  }

  function close() {
    if (!overlay) return;
    overlay.classList.add("hidden");
    document.documentElement.classList.remove("overflow-hidden");
    parts.image.removeAttribute("src");
    if (opener) opener.focus();
    opener = null;
  }

  tiles.forEach(function (tile, index) {
    tile.addEventListener("click", function (event) {
      // Leave the ordinary ways of opening a link alone: a middle click, a
      // modified click and a right click all belong to the visitor.
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
          event.button !== 0) {
        return;
      }
      event.preventDefault();
      open(index, tile);
    });
  });
})();
