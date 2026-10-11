/* ==========================================================================
   LGMED-IMMS - arranging a record's photographs
   Vanilla JavaScript, no framework.

   The grid on this page is the gallery the public gets, in the same reading
   order: left to right, then down. Moving a tile - by dragging it, or with
   the arrows on it - rewrites a hidden field holding the identifiers in their
   new order, and that field is the only thing the server reads.

   With scripting off the page still renders, the arrows and dragging simply
   do nothing, and saving posts the order the page was served with. Nothing
   breaks and nothing moves, which is the right outcome for a control that was
   never operable.
   ========================================================================== */

(function () {
  "use strict";

  var form = document.querySelector("[data-arrange-form]");
  if (!form) return;

  var list = form.querySelector("[data-arrange-list]");
  var field = form.querySelector('input[name="order"]');
  var status = form.querySelector("[data-arrange-status]");
  if (!list || !field) return;

  var original = field.value;
  var dragged = null;

  function items() {
    return Array.prototype.slice.call(
      list.querySelectorAll("[data-arrange-item]")
    );
  }

  function sync(focusItem) {
    var current = items();

    current.forEach(function (item, index) {
      var position = item.querySelector("[data-arrange-position]");
      if (position) position.textContent = String(index + 1);

      var earlier = item.querySelector('[data-arrange-move="-1"]');
      var later = item.querySelector('[data-arrange-move="1"]');
      if (earlier) earlier.disabled = index === 0;
      if (later) later.disabled = index === current.length - 1;
    });

    field.value = current
      .map(function (item) {
        return item.getAttribute("data-pk");
      })
      .join(",");

    if (status) {
      status.textContent = field.value === original
        ? "Nothing moved yet."
        : "Order changed. Save to apply it.";
    }

    if (focusItem) {
      var button = focusItem.querySelector("[data-arrange-move]:not([disabled])");
      if (button) button.focus();
    }
  }

  /* ----------------------------------------------------------------------
     Arrows - the accessible path, and the only one that works on a phone
     ---------------------------------------------------------------------- */

  list.addEventListener("click", function (event) {
    var button = event.target.closest("[data-arrange-move]");
    if (!button || button.disabled) return;

    var item = button.closest("[data-arrange-item]");
    var step = parseInt(button.getAttribute("data-arrange-move"), 10);
    var current = items();
    var index = current.indexOf(item);
    var target = index + step;
    if (target < 0 || target >= current.length) return;

    if (step < 0) {
      list.insertBefore(item, current[target]);
    } else {
      list.insertBefore(item, current[target].nextSibling);
    }
    sync(item);
  });

  /* ----------------------------------------------------------------------
     Dragging
     ---------------------------------------------------------------------- */

  list.addEventListener("dragstart", function (event) {
    var item = event.target.closest("[data-arrange-item]");
    if (!item) return;
    dragged = item;
    item.classList.add("opacity-50");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      // Firefox refuses to start a drag with nothing on the transfer.
      event.dataTransfer.setData("text/plain", item.getAttribute("data-pk"));
    }
  });

  list.addEventListener("dragend", function () {
    if (dragged) dragged.classList.remove("opacity-50");
    dragged = null;
    clearTargets();
  });

  function clearTargets() {
    items().forEach(function (item) {
      item.classList.remove("ring-2", "ring-brand-500");
    });
  }

  list.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var over = event.target.closest("[data-arrange-item]");
    if (!over || over === dragged) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    clearTargets();
    over.classList.add("ring-2", "ring-brand-500");
  });

  list.addEventListener("drop", function (event) {
    if (!dragged) return;
    var over = event.target.closest("[data-arrange-item]");
    if (!over || over === dragged) return;
    event.preventDefault();

    var current = items();
    // Dropping onto a tile that sits later in the grid puts the dragged tile
    // in its place; dropping onto an earlier one pushes that tile along. Both
    // read as "it lands where I dropped it", which is the only rule a person
    // is holding in their head while doing this.
    if (current.indexOf(dragged) < current.indexOf(over)) {
      list.insertBefore(dragged, over.nextSibling);
    } else {
      list.insertBefore(dragged, over);
    }
    clearTargets();
    sync();
  });

  /* A half-arranged gallery left behind by a misclick is worth one question. */
  window.addEventListener("beforeunload", function (event) {
    if (field.value === original) return;
    event.preventDefault();
    event.returnValue = "";
  });
  form.addEventListener("submit", function () {
    original = field.value;
  });

  sync();
})();
