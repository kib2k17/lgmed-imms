/* ==========================================================================
   LGMED-IMMS - Monthly Submissions (MMIA and DTR)
   Vanilla JavaScript, no framework.

   Everything here is an enhancement. Without scripting each upload card is a
   plain multipart form that posts and redirects, the reminder form posts the
   ticked rows, and the deadline dialog opens through app.js. With it:

     - a file can be dragged onto a card, and its name and size show at once;
     - a file over the size limit or of the wrong type is caught before it
       is sent (the server checks again - this only saves a wasted upload);
     - the upload shows a progress bar and, when it lands, the status figures
       and both cards are replaced with the server's fresh copy, so the page
       never shows a status the server does not hold;
     - the deadline counts down;
     - the Chief's Send Reminder dialog says how many people it will reach.
   ========================================================================== */

(function () {
  "use strict";

  var ALLOWED = ["pdf", "doc", "docx", "xls", "xlsx"];

  function readableSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function extensionOf(name) {
    var dot = name.lastIndexOf(".");
    return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
  }

  /* ----------------------------------------------------------------------
     Toasts - in the same region the installable-app notices use
     ---------------------------------------------------------------------- */

  function toastRegion() {
    var region = document.querySelector(".pwa-toast-region");
    if (!region) {
      region = document.createElement("div");
      region.className = "pwa-toast-region no-print";
      region.setAttribute("aria-live", "polite");
      document.body.appendChild(region);
    }
    return region;
  }

  function toast(message, tone) {
    var el = document.createElement("div");
    el.setAttribute("role", tone === "error" ? "alert" : "status");
    el.className = "pwa-toast " + (tone === "error"
      ? "border-red-300 bg-red-50 text-red-900"
      : "border-green-300 bg-green-50 text-green-900");
    var text = document.createElement("span");
    text.className = "min-w-0 flex-1";
    text.textContent = message;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "shrink-0 rounded px-1.5 text-lg leading-none opacity-70 hover:opacity-100";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", function () { el.remove(); });
    el.appendChild(text);
    el.appendChild(close);
    toastRegion().appendChild(el);
    window.setTimeout(function () { el.remove(); }, tone === "error" ? 9000 : 6000);
  }

  /* ----------------------------------------------------------------------
     Countdown to the deadline
     ---------------------------------------------------------------------- */

  function tick() {
    var now = Date.now();
    document.querySelectorAll("[data-countdown]").forEach(function (el) {
      var deadline = Date.parse(el.getAttribute("data-countdown"));
      if (isNaN(deadline)) return;
      var left = deadline - now;
      if (left <= 0) {
        el.textContent = "Deadline has passed";
        return;
      }
      var minutes = Math.floor(left / 60000);
      var days = Math.floor(minutes / 1440);
      var hours = Math.floor((minutes % 1440) / 60);
      var mins = minutes % 60;
      el.textContent = (days ? days + "d " : "") + hours + "h " + mins + "m left";
    });
  }
  tick();
  window.setInterval(tick, 30000);

  /* ----------------------------------------------------------------------
     Dialogs that must reopen (a deadline form returned with errors)
     ---------------------------------------------------------------------- */

  document.querySelectorAll("dialog[data-autoopen]").forEach(function (dialog) {
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
  });

  /* ----------------------------------------------------------------------
     Upload cards
     ---------------------------------------------------------------------- */

  function formOf(el) { return el && el.closest ? el.closest("form[data-upload-form]") : null; }

  function showError(form, message) {
    var box = form.querySelector("[data-upload-error]");
    if (!box) return;
    box.textContent = message || "";
    box.hidden = !message;
  }

  function checkFile(form, file) {
    var maxBytes = parseInt(form.getAttribute("data-max-bytes"), 10) || 0;
    var maxMb = form.getAttribute("data-max-mb") || "";
    if (ALLOWED.indexOf(extensionOf(file.name)) === -1) {
      return "Only PDF, Word (.doc, .docx) and Excel (.xls, .xlsx) files are accepted.";
    }
    if (!file.size) return "The file is empty.";
    if (maxBytes && file.size > maxBytes) {
      return "“" + file.name + "” is " + readableSize(file.size) +
        " – over the " + maxMb + " MB limit.";
    }
    return "";
  }

  function showChosen(form) {
    var input = form.querySelector("[data-file-input]");
    var chosen = form.querySelector("[data-chosen]");
    var file = input && input.files && input.files[0];
    if (!chosen) return;
    if (!file) {
      chosen.hidden = true;
      showError(form, "");
      return;
    }
    chosen.querySelector("[data-chosen-name]").textContent = file.name;
    chosen.querySelector("[data-chosen-size]").textContent = readableSize(file.size);
    chosen.hidden = false;
    showError(form, checkFile(form, file));
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("[data-file-input]")) {
      var form = formOf(event.target);
      if (form) showChosen(form);
    }
  });

  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = event.target.closest && event.target.closest("[data-dropzone]");
      if (!zone) return;
      event.preventDefault();
      zone.classList.add("border-brand-600", "bg-brand-50");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = event.target.closest && event.target.closest("[data-dropzone]");
      if (!zone) return;
      zone.classList.remove("border-brand-600", "bg-brand-50");
    });
  });
  document.addEventListener("drop", function (event) {
    var zone = event.target.closest && event.target.closest("[data-dropzone]");
    if (!zone) return;
    event.preventDefault();
    var files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) return;
    var form = formOf(zone);
    var input = form.querySelector("[data-file-input]");
    if (typeof DataTransfer !== "undefined") {
      var transfer = new DataTransfer();
      transfer.items.add(files[0]);
      input.files = transfer.files;
    } else {
      input.files = files;
    }
    if (files.length > 1) toast("Only one file per document - the first was taken.", "error");
    showChosen(form);
  });

  function setBusy(form, busy, percent) {
    var progress = form.querySelector("[data-upload-progress]");
    var bar = form.querySelector("[data-progress-bar]");
    var text = form.querySelector("[data-progress-text]");
    var button = form.querySelector("[data-upload-button]");
    if (progress) progress.hidden = !busy;
    if (bar) bar.style.width = (percent || 0) + "%";
    if (text) text.textContent = (percent || 0) + "%";
    if (button) {
      button.disabled = busy;
      button.setAttribute("aria-busy", busy ? "true" : "false");
    }
  }

  function swapIn(html) {
    var summary = document.querySelector("[data-submission-summary]");
    var cards = document.querySelector("[data-submission-cards]");
    if (summary && html.summary) summary.innerHTML = html.summary;
    if (cards && html.cards) cards.innerHTML = html.cards;
    tick();
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("form[data-upload-form]")) return;
    if (typeof FormData === "undefined" || typeof XMLHttpRequest === "undefined") return;

    var input = form.querySelector("[data-file-input]");
    var file = input && input.files && input.files[0];
    event.preventDefault();
    if (!file) {
      showError(form, "Choose a file, or drag one onto the box.");
      return;
    }
    var problem = checkFile(form, file);
    if (problem) {
      showError(form, problem);
      return;
    }
    showError(form, "");
    setBusy(form, true, 0);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.addEventListener("progress", function (e) {
      if (e.lengthComputable) setBusy(form, true, Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", function () {
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (err) { data = null; }
      if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
        swapIn(data.html || {});
        toast(data.message, "success");
        return;
      }
      setBusy(form, false, 0);
      var message = (data && data.errors && data.errors.join(" ")) ||
        (xhr.status === 403 ? "You are not allowed to upload here, or your session has ended. Reload the page." :
         "The upload did not go through (" + xhr.status + "). Please try again.");
      showError(form, message);
      toast(message, "error");
      if (data && data.closed) window.setTimeout(function () { window.location.reload(); }, 2500);
    });
    xhr.addEventListener("error", function () {
      setBusy(form, false, 0);
      var message = "The connection was lost before the upload finished. Please try again.";
      showError(form, message);
      toast(message, "error");
    });
    xhr.send(new FormData(form));
  });

  /* ----------------------------------------------------------------------
     The Chief's table: select rows, then Send Reminder
     ---------------------------------------------------------------------- */

  var remindForm = document.querySelector("[data-remind-form]");
  var selectAll = document.querySelector("[data-select-all]");

  function selectedRows() {
    return remindForm
      ? Array.prototype.slice.call(remindForm.querySelectorAll("[data-select-row]:checked"))
      : [];
  }

  if (selectAll && remindForm) {
    selectAll.addEventListener("change", function () {
      remindForm.querySelectorAll("[data-select-row]").forEach(function (box) {
        box.checked = selectAll.checked;
      });
    });
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest || !event.target.closest("[data-remind-open]")) return;
    var count = selectedRows().length;
    var summary = document.querySelector("[data-remind-summary]");
    var confirm = document.querySelector("[data-remind-confirm]");
    if (summary) {
      summary.textContent = count
        ? "Send an email and an in-system reminder to " + count + " selected staff member" +
          (count === 1 ? "" : "s") + "? Each message names the document still missing."
        : "No one is selected. Tick the staff with incomplete or missing submissions in the table first.";
    }
    if (confirm) confirm.disabled = !count;
  });
})();
