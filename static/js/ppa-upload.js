/* ==========================================================================
   LGMED-IMMS - supporting document upload
   Vanilla JavaScript, no framework.

   What this does, and why it is worth the code:

   A file input alone gives an encoder no way back. Select thirty photographs,
   notice the fourth one has somebody's ID card in it, and the only remedy the
   browser offers is to start the selection again. So the selection is held in
   an array here, rendered as a grid of thumbnails, and written back to the
   input through a DataTransfer object every time it changes. Removing a
   picture removes it from what gets posted; dragging one moves it in the
   order the server stores; typing under one sends a caption alongside it.

   Everything degrades. With scripting off the input is still a plain
   `multiple` file control, the form still posts, and the server still writes
   one row per file in the order the browser handed them over - captions are
   simply absent, which is what `SupportingDocumentForm.captions()` expects.
   ========================================================================== */

(function () {
  "use strict";

  var input = document.querySelector("input[data-multi-upload]");
  var region = document.querySelector("[data-upload-preview]");
  if (!input || !region || typeof DataTransfer === "undefined") return;

  var list = region.querySelector("[data-preview-list]");
  var empty = region.querySelector("[data-preview-empty]");
  var summary = region.querySelector("[data-preview-summary]");
  var problems = region.querySelector("[data-preview-problems]");
  var clearBtn = region.querySelector("[data-preview-clear]");
  var addBtn = region.querySelector("[data-preview-add]");

  var captionName = input.getAttribute("data-caption-name") || "file_caption";
  var imageExtensions = (input.getAttribute("data-image-extensions") || "")
    .split(",")
    .filter(Boolean);
  var maxBytes = parseInt(input.getAttribute("data-max-bytes"), 10) || 0;

  /* The selection: one entry per file, in the order it will be posted. */
  var entries = [];
  var dragIndex = null;

  /* ----------------------------------------------------------------------
     Helpers
     ---------------------------------------------------------------------- */

  function extensionOf(name) {
    var dot = name.lastIndexOf(".");
    return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
  }

  function isImage(file) {
    if (file.type && file.type.indexOf("image/") === 0) return true;
    return imageExtensions.indexOf(extensionOf(file.name)) !== -1;
  }

  function readableSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  /* Two files can share a name and still be different files, so identity is
     name + size + last-modified. Selecting the same picture twice by accident
     is common; posting it twice is never what was meant. */
  function fingerprint(file) {
    return file.name + "|" + file.size + "|" + (file.lastModified || 0);
  }

  function say(message) {
    if (!problems) return;
    problems.textContent = message || "";
    problems.hidden = !message;
  }

  /* ----------------------------------------------------------------------
     The selection <-> the input
     ---------------------------------------------------------------------- */

  function writeBack() {
    var transfer = new DataTransfer();
    entries.forEach(function (entry) {
      transfer.items.add(entry.file);
    });
    input.files = transfer.files;
  }

  function harvestCaptions() {
    if (!list) return;
    var fields = list.querySelectorAll("[data-caption-input]");
    Array.prototype.forEach.call(fields, function (field) {
      var index = parseInt(field.getAttribute("data-index"), 10);
      if (!isNaN(index) && entries[index]) entries[index].caption = field.value;
    });
  }

  function add(files) {
    var rejected = [];
    var known = {};
    entries.forEach(function (entry) {
      known[fingerprint(entry.file)] = true;
    });

    Array.prototype.forEach.call(files, function (file) {
      var key = fingerprint(file);
      if (known[key]) {
        rejected.push("“" + file.name + "” was already selected.");
        return;
      }
      if (maxBytes && file.size > maxBytes) {
        rejected.push(
          "“" + file.name + "” is " + readableSize(file.size) +
          " – over the 25 MB limit, so it was not added."
        );
        return;
      }
      if (file.size === 0) {
        rejected.push("“" + file.name + "” is empty, so it was not added.");
        return;
      }
      known[key] = true;
      entries.push({ file: file, caption: "", url: null });
    });

    say(rejected.join(" "));
  }

  function removeAt(index) {
    harvestCaptions();
    var entry = entries[index];
    if (entry && entry.url) URL.revokeObjectURL(entry.url);
    entries.splice(index, 1);
    render();
    writeBack();
  }

  function moveTo(from, to) {
    if (to < 0 || to >= entries.length || from === to) return;
    harvestCaptions();
    var moved = entries.splice(from, 1)[0];
    entries.splice(to, 0, moved);
    render(to);
    writeBack();
  }

  /* ----------------------------------------------------------------------
     Rendering
     ---------------------------------------------------------------------- */

  function tile(entry, index) {
    var item = document.createElement("li");
    item.className =
      "group relative flex flex-col overflow-hidden rounded-lg border " +
      "border-slate-200 bg-white shadow-xs";
    item.setAttribute("draggable", "true");
    item.setAttribute("data-index", String(index));

    /* -- the picture, or a stand-in for a paper ------------------------- */
    var frame = document.createElement("div");
    frame.className =
      "relative flex aspect-4/3 items-center justify-center " +
      "border-b border-slate-200 bg-slate-100";

    if (isImage(entry.file)) {
      if (!entry.url) entry.url = URL.createObjectURL(entry.file);
      var picture = document.createElement("img");
      picture.src = entry.url;
      picture.alt = "";
      picture.className = "size-full object-cover";
      frame.appendChild(picture);
    } else {
      var stand = document.createElement("span");
      stand.className =
        "text-meta font-semibold tracking-wide text-slate-500 uppercase";
      stand.textContent = extensionOf(entry.file.name) || "file";
      frame.appendChild(stand);
    }

    var position = document.createElement("span");
    position.className =
      "absolute top-2 left-2 inline-flex size-6 items-center justify-center " +
      "rounded-full bg-brand-700 text-[0.6875rem] font-semibold text-white";
    position.textContent = String(index + 1);
    frame.appendChild(position);

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className =
      "absolute top-2 right-2 inline-flex size-7 items-center justify-center " +
      "rounded-full border border-slate-300 bg-white/95 text-slate-600 " +
      "shadow-xs hover:border-red-300 hover:bg-red-50 hover:text-red-700 " +
      "focus-visible:outline-2 focus-visible:outline-offset-2 " +
      "focus-visible:outline-brand-600";
    remove.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" class="size-4" aria-hidden="true" ' +
      'focusable="false"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    remove.setAttribute("aria-label", "Remove " + entry.file.name);
    remove.addEventListener("click", function () {
      removeAt(index);
    });
    frame.appendChild(remove);
    item.appendChild(frame);

    /* -- the caption and the controls ----------------------------------- */
    var body = document.createElement("div");
    body.className = "flex flex-1 flex-col gap-2 p-3";

    var name = document.createElement("p");
    name.className = "truncate text-meta text-slate-500";
    name.title = entry.file.name;
    name.textContent = entry.file.name + " · " + readableSize(entry.file.size);
    body.appendChild(name);

    var fieldId = "upload-caption-" + index;
    var label = document.createElement("label");
    label.className = "sr-only";
    label.setAttribute("for", fieldId);
    label.textContent = "Caption for " + entry.file.name;
    body.appendChild(label);

    var caption = document.createElement("input");
    caption.type = "text";
    caption.id = fieldId;
    caption.name = captionName;
    caption.value = entry.caption || "";
    caption.maxLength = 255;
    caption.placeholder = "What this shows (optional)";
    caption.setAttribute("data-caption-input", "true");
    caption.setAttribute("data-index", String(index));
    caption.className =
      "block w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 " +
      "text-sm text-slate-900 shadow-xs transition-colors " +
      "placeholder:text-slate-400 focus:border-brand-600 " +
      "focus:ring-2 focus:ring-brand-600/25 focus:outline-none";
    caption.addEventListener("input", function () {
      entries[index].caption = caption.value;
    });
    body.appendChild(caption);

    var controls = document.createElement("div");
    controls.className = "mt-auto flex items-center gap-1 pt-1";

    /* Buttons as well as dragging. A drag handle is no use on a touch screen
       in a field office, and no use at all to somebody working by keyboard. */
    [["Move earlier", -1, "m18 15-6-6-6 6"], ["Move later", 1, "m6 9 6 6 6-6"]]
      .forEach(function (spec) {
        var button = document.createElement("button");
        button.type = "button";
        button.className =
          "inline-flex size-7 items-center justify-center rounded-md border " +
          "border-slate-300 bg-white text-slate-600 hover:bg-slate-50 " +
          "hover:text-slate-900 disabled:pointer-events-none " +
          "disabled:opacity-40 focus-visible:outline-2 " +
          "focus-visible:outline-offset-2 focus-visible:outline-brand-600";
        button.innerHTML =
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ' +
          'fill="none" stroke="currentColor" stroke-width="2" ' +
          'stroke-linecap="round" stroke-linejoin="round" class="size-4" ' +
          'aria-hidden="true" focusable="false"><path d="' + spec[2] + '"/></svg>';
        button.setAttribute("aria-label", spec[0] + ": " + entry.file.name);
        button.disabled =
          spec[1] < 0 ? index === 0 : index === entries.length - 1;
        button.addEventListener("click", function () {
          moveTo(index, index + spec[1]);
        });
        controls.appendChild(button);
      });

    var hint = document.createElement("span");
    hint.className = "ml-auto text-meta text-slate-400";
    hint.textContent = "Drag to reorder";
    controls.appendChild(hint);

    body.appendChild(controls);
    item.appendChild(body);

    /* -- dragging -------------------------------------------------------- */
    item.addEventListener("dragstart", function (event) {
      dragIndex = index;
      item.classList.add("opacity-50");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        // Firefox will not start a drag without payload on the transfer.
        event.dataTransfer.setData("text/plain", String(index));
      }
    });
    item.addEventListener("dragend", function () {
      dragIndex = null;
      item.classList.remove("opacity-50");
    });
    item.addEventListener("dragover", function (event) {
      if (dragIndex === null) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      item.classList.add("ring-2", "ring-brand-500");
    });
    item.addEventListener("dragleave", function () {
      item.classList.remove("ring-2", "ring-brand-500");
    });
    item.addEventListener("drop", function (event) {
      event.preventDefault();
      item.classList.remove("ring-2", "ring-brand-500");
      if (dragIndex === null || dragIndex === index) return;
      moveTo(dragIndex, index);
      dragIndex = null;
    });

    return item;
  }

  function render(focusIndex) {
    if (!list) return;
    list.textContent = "";
    entries.forEach(function (entry, index) {
      list.appendChild(tile(entry, index));
    });

    var count = entries.length;
    if (empty) empty.hidden = count > 0;
    if (list) list.hidden = count === 0;
    if (clearBtn) clearBtn.hidden = count === 0;
    if (summary) {
      var pictures = entries.filter(function (entry) {
        return isImage(entry.file);
      }).length;
      var total = entries.reduce(function (sum, entry) {
        return sum + entry.file.size;
      }, 0);
      summary.textContent = count === 0
        ? ""
        : count + " file" + (count === 1 ? "" : "s") + " selected" +
          (pictures ? " (" + pictures + " photograph" +
            (pictures === 1 ? "" : "s") + ")" : "") +
          " · " + readableSize(total);
    }

    if (typeof focusIndex === "number") {
      var moved = list.querySelector('[data-index="' + focusIndex + '"]');
      if (moved) {
        var button = moved.querySelector("button:not([disabled])");
        if (button) button.focus();
      }
    }
  }

  /* ----------------------------------------------------------------------
     Wiring
     ---------------------------------------------------------------------- */

  input.addEventListener("change", function () {
    // A second trip through the picker adds to the selection rather than
    // replacing it: photographs from one activity routinely sit in two
    // folders, and losing the first batch to pick up the second is exactly
    // the frustration this whole file exists to remove.
    if (!input.files || !input.files.length) return;
    harvestCaptions();
    add(input.files);
    render();
    writeBack();
  });

  if (addBtn) {
    addBtn.addEventListener("click", function () {
      input.click();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      entries.forEach(function (entry) {
        if (entry.url) URL.revokeObjectURL(entry.url);
      });
      entries = [];
      say("");
      render();
      writeBack();
    });
  }

  /* Drop files straight onto the panel. */
  ["dragenter", "dragover"].forEach(function (name) {
    region.addEventListener(name, function (event) {
      if (dragIndex !== null) return; // reordering, not importing
      event.preventDefault();
      region.classList.add("ring-2", "ring-brand-500");
    });
  });
  ["dragleave", "drop"].forEach(function (name) {
    region.addEventListener(name, function () {
      region.classList.remove("ring-2", "ring-brand-500");
    });
  });
  region.addEventListener("drop", function (event) {
    if (dragIndex !== null) return;
    if (!event.dataTransfer || !event.dataTransfer.files.length) return;
    event.preventDefault();
    harvestCaptions();
    add(event.dataTransfer.files);
    render();
    writeBack();
  });

  /* Captions are only meaningful next to the file they belong to, so the
     browser must not restore a stale set into a fresh selection. */
  window.addEventListener("beforeunload", function () {
    entries.forEach(function (entry) {
      if (entry.url) URL.revokeObjectURL(entry.url);
    });
  });

  region.hidden = false;
  render();
})();
