/* ==========================================================================
   e-SIRA signing workspace.

   Shows the PDF one page at a time with pdf.js (vendored under
   static/vendor/pdfjs, so nothing is fetched from outside the office
   network), and lets the user place, move, resize and remove signature
   boxes.

   A box here is a PLACEMENT. It records where a signature is to appear, as
   fractions of the displayed page, and is saved to the server. It signs
   nothing. Signing is a separate form post (the Sign dialog) that the server
   carries out with the signer's own PNPKI certificate - see esira/workflow.py.
   ========================================================================== */

const configNode = document.getElementById("esira-workspace-config");
const root = document.querySelector("[data-esira-workspace]");

if (configNode && root) {
  start(JSON.parse(configNode.textContent)).catch((error) => {
    const status = root.querySelector("[data-viewer-status]");
    if (status) {
      status.hidden = false;
      status.textContent = "The document could not be displayed. " + (error && error.message ? error.message : "");
    }
    console.error(error);
  });
}

async function start(config) {
  const pdfjs = await import(config.pdfjsUrl);
  pdfjs.GlobalWorkerOptions.workerSrc = config.workerUrl;

  // -- elements -------------------------------------------------------------
  const $ = (selector) => root.querySelector(selector);
  const scroller = $("[data-viewer-scroll]");
  const pageWrap = $("[data-page-wrap]");
  const canvas = $("[data-page-canvas]");
  const layer = $("[data-box-layer]");
  const status = $("[data-viewer-status]");
  const pageInput = $("[data-page-input]");
  const zoomLabel = $("[data-zoom-label]");
  const boxList = $("[data-box-list]");
  const saveState = $("[data-save-state]");
  const signerSelect = $("[data-signer-select]");
  const applyPagesInput = $("[data-apply-pages-input]");
  const csrf = (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";

  // -- state ----------------------------------------------------------------
  const DEFAULT_W = 0.28;
  const DEFAULT_H = 0.075;
  const MIN = 0.02;
  let boxes = [];            // {key, id, page, x, y, width, height, signer, signer_name, applied, editable}
  let selectedKey = null;
  let nextKey = 1;
  let currentPage = 1;
  let zoom = 1;
  let fitMode = true;
  let renderTask = null;
  let dirty = false;
  let saving = null;
  let saveTimer = null;

  // -- load -----------------------------------------------------------------
  const pdf = await pdfjs.getDocument({
    url: config.fileUrl,
    withCredentials: true,
    enableXfa: false,
  }).promise;

  if (signerSelect) {
    config.signers.forEach((signer) => {
      const option = document.createElement("option");
      option.value = signer.id;
      option.textContent = signer.name + (signer.id === config.userId ? " (me)" : "");
      if (signer.id === config.userId) option.selected = true;
      signerSelect.appendChild(option);
    });
  }

  await loadBoxes();
  await render();
  status.hidden = true;

  // -- rendering ------------------------------------------------------------

  async function render() {
    const page = await pdf.getPage(currentPage);
    if (fitMode) {
      const base = page.getViewport({ scale: 1 });
      const available = scroller.clientWidth - 48;
      zoom = Math.max(0.4, Math.min(2, available / base.width));
    }
    const viewport = page.getViewport({ scale: zoom });
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = Math.floor(viewport.width) + "px";
    canvas.style.height = Math.floor(viewport.height) + "px";
    pageWrap.style.width = canvas.style.width;
    pageWrap.style.height = canvas.style.height;

    if (renderTask) renderTask.cancel();
    renderTask = page.render({
      canvas,
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
    });
    try {
      await renderTask.promise;
    } catch (error) {
      if (error && error.name === "RenderingCancelledException") return;
      throw error;
    }
    renderTask = null;
    pageInput.value = currentPage;
    zoomLabel.textContent = Math.round(zoom * 100) + "%";
    canvas.setAttribute("aria-label", "Page " + currentPage + " of " + pdf.numPages);
    drawBoxes();
  }

  function goTo(page) {
    const target = Math.min(Math.max(1, page), pdf.numPages);
    if (target === currentPage) return;
    currentPage = target;
    render();
  }

  // -- boxes: drawing ---------------------------------------------------------

  function drawBoxes() {
    layer.replaceChildren();
    boxes.filter((b) => b.page === currentPage).forEach((box) => {
      const el = document.createElement("div");
      const selected = box.key === selectedKey;
      let tone;
      if (box.applied) {
        // Outline only: the signature's own appearance, drawn into the PDF by
        // the signing operation, shows through underneath.
        tone = "border-2 border-solid border-green-600";
      } else if (box.editable) {
        tone = "border-2 border-dashed border-brand-600 bg-brand-500/10 cursor-move";
      } else {
        tone = "border-2 border-dashed border-slate-400 bg-slate-400/10";
      }
      el.className = "absolute select-none rounded-sm " + tone + (selected ? " ring-2 ring-accent-400 ring-offset-1" : "");
      el.style.left = box.x * 100 + "%";
      el.style.top = box.y * 100 + "%";
      el.style.width = box.width * 100 + "%";
      el.style.height = box.height * 100 + "%";
      el.dataset.key = box.key;
      el.tabIndex = box.editable ? 0 : -1;
      el.setAttribute("role", "group");
      el.setAttribute(
        "aria-label",
        (box.applied ? "Signed by " : "Signature placement for ") + box.signer_name + ", page " + box.page
      );

      if (box.applied) {
        const tag = document.createElement("span");
        tag.className = "pointer-events-none absolute bottom-full left-0 mb-0.5 max-w-full truncate rounded-sm bg-green-700 px-1.5 py-px text-[10px] font-semibold text-white";
        tag.textContent = "✓ Signed: " + box.signer_name;
        el.appendChild(tag);
      } else {
        const label = document.createElement("div");
        label.className = "pointer-events-none absolute inset-0 flex flex-col items-center justify-center overflow-hidden px-1 text-center leading-tight";
        const name = document.createElement("span");
        name.className = "truncate text-[11px] font-semibold " + (box.editable ? "text-brand-800" : "text-slate-700");
        name.textContent = box.signer_name;
        const note = document.createElement("span");
        note.className = "truncate text-[9px] text-slate-600";
        note.textContent = "Placement only - not yet signed";
        label.append(name, note);
        el.appendChild(label);
      }

      if (box.editable) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "absolute -top-2.5 -right-2.5 grid size-5 place-items-center rounded-full bg-red-600 text-[11px] font-bold text-white shadow hover:bg-red-700";
        remove.textContent = "×";
        remove.title = "Remove this box";
        remove.setAttribute("aria-label", "Remove this signature box");
        remove.addEventListener("pointerdown", (event) => event.stopPropagation());
        remove.addEventListener("click", (event) => {
          event.stopPropagation();
          removeBox(box.key);
        });
        const handle = document.createElement("span");
        handle.className = "absolute -right-1.5 -bottom-1.5 size-3.5 cursor-se-resize rounded-sm border-2 border-white bg-brand-600 shadow";
        handle.dataset.handle = "resize";
        handle.setAttribute("aria-hidden", "true");
        el.append(remove, handle);
        el.addEventListener("pointerdown", (event) => startDrag(event, box));
        el.addEventListener("keydown", (event) => onBoxKey(event, box));
        el.addEventListener("focus", () => select(box.key, false));
      }
      layer.appendChild(el);
    });
    drawList();
  }

  function drawList() {
    if (!boxList) return;
    boxList.replaceChildren();
    const sorted = [...boxes].sort((a, b) => a.page - b.page || a.y - b.y);
    if (!sorted.length) {
      const empty = document.createElement("li");
      empty.className = "px-2.5 py-2 text-meta text-slate-500";
      empty.textContent = "None yet. Add a signature box to begin.";
      boxList.appendChild(empty);
    }
    sorted.forEach((box) => {
      const item = document.createElement("li");
      item.className = "flex items-center gap-2 px-2.5 py-1.5" + (box.key === selectedKey ? " bg-brand-50" : "");
      const go = document.createElement("button");
      go.type = "button";
      go.className = "min-w-0 flex-1 truncate text-left hover:underline";
      go.textContent = "p." + box.page + " · " + box.signer_name + (box.applied ? " (signed)" : box.editable ? "" : " (locked)");
      go.addEventListener("click", () => {
        select(box.key, false);
        if (box.page !== currentPage) {
          currentPage = box.page;
          render();
        }
      });
      item.appendChild(go);
      if (box.editable) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "shrink-0 rounded px-1.5 text-meta font-medium text-red-700 hover:bg-red-50";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => removeBox(box.key));
        item.appendChild(remove);
      }
      boxList.appendChild(item);
    });
  }

  function select(key, redraw = true) {
    selectedKey = key;
    if (redraw) drawBoxes();
    else {
      layer.querySelectorAll("[data-key]").forEach((el) => {
        const on = String(el.dataset.key) === String(key);
        el.classList.toggle("ring-2", on);
        el.classList.toggle("ring-accent-400", on);
        el.classList.toggle("ring-offset-1", on);
      });
      drawList();
    }
  }

  // -- boxes: dragging and resizing -----------------------------------------

  function startDrag(event, box) {
    if (event.button !== 0) return;
    event.preventDefault();
    select(box.key);
    const el = layer.querySelector('[data-key="' + box.key + '"]');
    if (el) el.focus({ preventScroll: true });
    const resizing = event.target.dataset && event.target.dataset.handle === "resize";
    const rect = pageWrap.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { x: box.x, y: box.y, width: box.width, height: box.height };

    const move = (e) => {
      const dx = (e.clientX - startX) / rect.width;
      const dy = (e.clientY - startY) / rect.height;
      if (resizing) {
        box.width = clamp(origin.width + dx, MIN, 1 - box.x);
        box.height = clamp(origin.height + dy, MIN, 1 - box.y);
      } else {
        box.x = clamp(origin.x + dx, 0, 1 - box.width);
        box.y = clamp(origin.y + dy, 0, 1 - box.height);
      }
      const node = layer.querySelector('[data-key="' + box.key + '"]');
      if (node) {
        node.style.left = box.x * 100 + "%";
        node.style.top = box.y * 100 + "%";
        node.style.width = box.width * 100 + "%";
        node.style.height = box.height * 100 + "%";
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (origin.x !== box.x || origin.y !== box.y || origin.width !== box.width || origin.height !== box.height) {
        changed();
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function onBoxKey(event, box) {
    const step = 0.005;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      removeBox(box.key);
      return;
    }
    const delta = moves[event.key];
    if (!delta) return;
    event.preventDefault();
    if (event.shiftKey) {
      box.width = clamp(box.width + delta[0], MIN, 1 - box.x);
      box.height = clamp(box.height + delta[1], MIN, 1 - box.y);
    } else {
      box.x = clamp(box.x + delta[0], 0, 1 - box.width);
      box.y = clamp(box.y + delta[1], 0, 1 - box.height);
    }
    drawBoxes();
    const el = layer.querySelector('[data-key="' + box.key + '"]');
    if (el) el.focus({ preventScroll: true });
    changed();
  }

  // -- boxes: tools -----------------------------------------------------------

  function signerFor() {
    if (!signerSelect || signerSelect.disabled) {
      return { id: config.userId, name: config.userName };
    }
    const option = signerSelect.selectedOptions[0];
    return { id: Number(option.value), name: option.textContent.replace(/ \(me\)$/, "") };
  }

  function makeBox(page, x, y, width, height, signer) {
    return {
      key: "n" + nextKey++, id: null, page, x, y, width, height,
      signer: signer.id, signer_name: signer.name, applied: false, editable: true,
    };
  }

  function addBox() {
    const signer = signerFor();
    const count = boxes.filter((b) => b.page === currentPage).length;
    const offset = (count % 5) * 0.03;
    const box = makeBox(
      currentPage,
      clamp(0.5 - DEFAULT_W / 2 + offset, 0, 1 - DEFAULT_W),
      clamp(0.72 + offset, 0, 1 - DEFAULT_H),
      DEFAULT_W, DEFAULT_H, signer
    );
    boxes.push(box);
    selectedKey = box.key;
    drawBoxes();
    changed();
  }

  function selectedBox() {
    return boxes.find((b) => b.key === selectedKey && b.editable)
      || boxes.find((b) => b.page === currentPage && b.editable);
  }

  function copyToPages(pages) {
    const source = selectedBox();
    if (!source) {
      alert("Select a signature box to copy first, or add one.");
      return;
    }
    let added = 0;
    pages.forEach((page) => {
      if (page === source.page || page < 1 || page > pdf.numPages) return;
      const clash = boxes.some((b) => b.page === page && b.signer === source.signer
        && Math.abs(b.x - source.x) < 0.02 && Math.abs(b.y - source.y) < 0.02);
      if (clash) return;
      boxes.push(makeBox(page, source.x, source.y, source.width, source.height,
        { id: source.signer, name: source.signer_name }));
      added += 1;
    });
    drawBoxes();
    if (added) changed();
    announce(added ? "Copied to " + added + " page" + (added === 1 ? "" : "s") + "." : "No pages needed a copy.");
  }

  function parsePages(text) {
    const pages = new Set();
    text.split(/[,\s]+/).filter(Boolean).forEach((part) => {
      const range = part.match(/^(\d+)\s*-\s*(\d+)$/);
      if (range) {
        const a = Number(range[1]);
        const b = Number(range[2]);
        for (let p = Math.min(a, b); p <= Math.max(a, b) && p <= pdf.numPages; p += 1) pages.add(p);
      } else if (/^\d+$/.test(part)) {
        pages.add(Number(part));
      }
    });
    return [...pages];
  }

  function removeBox(key) {
    const box = boxes.find((b) => b.key === key);
    if (!box || !box.editable) return;
    boxes = boxes.filter((b) => b.key !== key);
    if (selectedKey === key) selectedKey = null;
    drawBoxes();
    changed();
  }

  function removeAll() {
    const editable = boxes.filter((b) => b.editable);
    if (!editable.length) return;
    if (!confirm("Remove all " + editable.length + " signature box(es) you can edit? Signed boxes are not affected.")) return;
    boxes = boxes.filter((b) => !b.editable);
    selectedKey = null;
    drawBoxes();
    changed();
  }

  // -- saving -------------------------------------------------------------------

  async function loadBoxes() {
    const response = await fetch(config.boxesUrl, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("The signature boxes could not be loaded.");
    adopt((await response.json()).boxes);
  }

  function adopt(serverBoxes) {
    const selected = boxes.find((b) => b.key === selectedKey);
    boxes = serverBoxes.map((b) => ({ ...b, key: "s" + b.id }));
    if (selected) {
      const match = boxes.find((b) => b.page === selected.page
        && Math.abs(b.x - selected.x) < 1e-4 && Math.abs(b.y - selected.y) < 1e-4);
      selectedKey = match ? match.key : null;
    }
  }

  function changed() {
    dirty = true;
    setSaveState("Unsaved changes", "text-amber-700");
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(save, 700);
  }

  async function save() {
    window.clearTimeout(saveTimer);
    if (!config.canEdit || !dirty) return true;
    if (saving) {
      await saving;
      return save();
    }
    dirty = false;
    setSaveState("Saving…", "text-slate-500");
    const payload = boxes.filter((b) => b.editable).map((b) => ({
      id: b.id, page: b.page, x: b.x, y: b.y, width: b.width, height: b.height, signer: b.signer,
    }));
    saving = fetch(config.boxesUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, Accept: "application/json" },
      body: JSON.stringify({ boxes: payload }),
    }).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The boxes could not be saved.");
      if (!dirty) {
        adopt(data.boxes);
        drawBoxes();
      }
      setSaveState("Saved", "text-green-700");
      return true;
    }).catch((error) => {
      dirty = true;
      setSaveState("Not saved", "text-red-700");
      alert(error.message);
      return false;
    }).finally(() => {
      saving = null;
    });
    return saving;
  }

  function setSaveState(text, tone) {
    if (!saveState) return;
    saveState.textContent = text;
    saveState.className = "text-meta font-medium " + tone;
  }

  function announce(text) {
    if (saveState) saveState.textContent = text;
  }

  window.addEventListener("beforeunload", (event) => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // -- signing (hand-off to the server) --------------------------------------------

  async function openSignDialog() {
    const ok = await save();
    if (ok === false) return;
    const mine = boxes.filter((b) => b.signer === config.userId && !b.applied);
    if (!mine.length) {
      alert("Place at least one signature box for yourself before signing.");
      return;
    }
    if (config.isDraft && boxes.some((b) => !b.applied && b.signer !== config.userId)) {
      alert(
        "This draft has signature boxes for other people, so it has to be routed. "
        + "Use Route for signature, and add yourself as step 1 to sign first."
      );
      return;
    }
    const dialog = document.getElementById("sign-dialog");
    if (!dialog) return;
    const count = dialog.querySelector("[data-sign-count]");
    if (count) count.textContent = mine.length;
    dialog.showModal();
  }

  // -- wiring ---------------------------------------------------------------------

  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    switch (button.dataset.action) {
      case "prev-page": goTo(currentPage - 1); break;
      case "next-page": goTo(currentPage + 1); break;
      case "zoom-in": fitMode = false; zoom = Math.min(3, zoom + 0.25); render(); break;
      case "zoom-out": fitMode = false; zoom = Math.max(0.4, zoom - 0.25); render(); break;
      case "fit-width": fitMode = true; render(); break;
      case "add-box": addBox(); break;
      case "apply-all": copyToPages(Array.from({ length: pdf.numPages }, (_, i) => i + 1)); break;
      case "apply-pages": {
        const pages = parsePages(applyPagesInput ? applyPagesInput.value : "");
        if (!pages.length) alert("List the pages, e.g. 1, 3, 5-7.");
        else copyToPages(pages);
        break;
      }
      case "remove-all": removeAll(); break;
      case "sign": openSignDialog(); break;
      default: break;
    }
  });

  document.querySelectorAll("[data-esira-route-link]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      if (!dirty) return;
      event.preventDefault();
      if (await save()) window.location.href = link.href;
    });
  });

  layer.addEventListener("pointerdown", (event) => {
    if (event.target === layer) select(null);
  });
  pageInput.addEventListener("change", () => goTo(Number(pageInput.value) || 1));
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (!fitMode) return;
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(render, 150);
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input, select, textarea, [data-key], dialog")) return;
    if (event.key === "PageDown") { event.preventDefault(); goTo(currentPage + 1); }
    if (event.key === "PageUp") { event.preventDefault(); goTo(currentPage - 1); }
  });
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}
