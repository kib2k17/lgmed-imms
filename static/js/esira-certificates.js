/* ==========================================================================
   LGMED-iMMS - e-SIRA "My Digital Certificate"
   Vanilla JavaScript, no framework.

   - Drop zones: a file dragged onto the box is put into its file input, and
     the chosen file's name replaces the prompt. The signature image saves as
     soon as it is chosen.
   - The "require password" switch saves when flipped.
   - The eye button fetches the stored password (a logged POST) and hides it
     again on the second press.
   - Forms marked data-confirm ask first.

   Without scripting every form still posts through its own button.
   ========================================================================== */

(function () {
  "use strict";

  function csrfToken() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  /* -- drop zones ---------------------------------------------------------- */

  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    var label = zone.querySelector("[data-dropzone-label]");
    var hint = zone.querySelector("[data-dropzone-hint]");
    if (!input) return;

    function chosen() {
      var file = input.files && input.files[0];
      if (!file) return;
      if (label) label.textContent = file.name;
      if (hint) hint.textContent = "Selected · click to choose another";
      if (input.hasAttribute("data-dropzone-autosubmit")) {
        input.form.requestSubmit ? input.form.requestSubmit() : input.form.submit();
      }
    }

    input.addEventListener("change", chosen);

    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function (event) {
        event.preventDefault();
        zone.setAttribute("data-over", "");
      });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function (event) {
        event.preventDefault();
        zone.removeAttribute("data-over");
      });
    });
    zone.addEventListener("drop", function (event) {
      var files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length || typeof DataTransfer === "undefined") return;
      var transfer = new DataTransfer();
      transfer.items.add(files[0]);
      input.files = transfer.files;
      chosen();
    });
  });

  /* -- switches that save themselves --------------------------------------- */

  document.querySelectorAll("input[data-autosubmit]").forEach(function (input) {
    input.addEventListener("change", function () {
      input.form.requestSubmit ? input.form.requestSubmit() : input.form.submit();
    });
  });

  /* -- setup dialogs --------------------------------------------------------- */

  document.querySelectorAll("[data-dialog-open]").forEach(function (button) {
    var dialog = document.getElementById(button.getAttribute("data-dialog-open"));
    if (!dialog || typeof dialog.showModal !== "function") return;
    button.addEventListener("click", function () { dialog.showModal(); });
  });
  document.querySelectorAll("dialog [data-dialog-close]").forEach(function (button) {
    button.addEventListener("click", function () { button.closest("dialog").close(); });
  });
  document.querySelectorAll("dialog[data-open-on-load]").forEach(function (dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
  });

  /* -- confirmations -------------------------------------------------------- */

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  /* -- show / hide the stored password ------------------------------------- */

  var reveal = document.querySelector("[data-reveal-password]");
  if (reveal) {
    var button = reveal.querySelector("[data-reveal-toggle]");
    var output = reveal.querySelector("[data-reveal-output]");
    var showIcon = reveal.querySelector("[data-icon-show]");
    var hideIcon = reveal.querySelector("[data-icon-hide]");
    var hiddenText = output.textContent.trim();

    function setShown(shown, text) {
      button.setAttribute("aria-pressed", shown ? "true" : "false");
      showIcon.hidden = shown;
      hideIcon.hidden = !shown;
      output.textContent = text;
      output.classList.toggle("font-mono", shown);
      output.classList.toggle("text-slate-900", shown);
    }

    button.addEventListener("click", function () {
      if (button.getAttribute("aria-pressed") === "true") {
        setShown(false, hiddenText);
        return;
      }
      button.disabled = true;
      fetch(reveal.getAttribute("data-url"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (response) {
          return response.json().then(function (body) {
            if (!response.ok) throw new Error(body.error || "The password could not be shown.");
            return body.password;
          });
        })
        .then(function (password) {
          setShown(true, password);
        })
        .catch(function (error) {
          output.textContent = error.message;
        })
        .finally(function () {
          button.disabled = false;
        });
    });
  }
})();
