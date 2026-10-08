"""
Capture and annotate the user manual's screenshots from the running system.

    python capture.py                 # every figure in figures.py
    python capture.py incoming- dash  # only figures whose id starts with these

Run it against the documentation instance (see README.md in docs/manual):
a fresh demonstration database, never the office's live one. For each figure
in figures.FIGURES it signs in as the figure's role, performs the listed
steps, takes the screenshot, then finds every marked control by its real
selector and draws a numbered callout over the place it actually occupies.
The legend printed under each figure in the manual is generated from the same
entry, so a number and its description cannot drift apart.

Outputs, under docs/manual/assets/:
    raw/<id>.png        the screenshot as captured
    <module>/<id>.png   the annotated screenshot used in the manual
    figures.json        caption, legend, role, page and file for each figure
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

import figures as spec

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
RAW = ASSETS / "raw"
BASE = spec.BASE_URL
PASSWORD = spec.DEMO_PASSWORD
SCALE = 1.5          # device pixel ratio: sharp when the PDF is zoomed
WIDTH = 1440

ACCENT = (234, 88, 12)       # orange-600: not used anywhere in the interface
ACCENT_FILL = (234, 88, 12, 38)
WHITE = (255, 255, 255)


def font(size, bold=True):
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


# -- browser ---------------------------------------------------------------

class Session:
    """One signed-in browser context per demonstration account."""

    def __init__(self, browser):
        self.browser = browser
        self.pages = {}

    def page(self, user, accept_privacy=True):
        key = (user, accept_privacy)
        if key in self.pages:
            return self.pages[key]
        ctx = self.browser.new_context(
            viewport={"width": WIDTH, "height": 900},
            device_scale_factor=SCALE,
            locale="en-PH",
            timezone_id="Asia/Manila",
        )
        page = ctx.new_page()
        if user:
            page.goto(BASE + "/accounts/login/")
            page.fill("input[name=username]", user)
            page.fill("input[name=password]", PASSWORD)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
            if accept_privacy:
                accept(page)
        self.pages[key] = page
        return page


def accept(page):
    box = page.locator("dialog[open] input[type=checkbox]")
    if box.count():
        box.first.check()
        page.get_by_role("button", name="I Agree and Continue").click()
        page.wait_for_load_state("networkidle")


def settle(page, ms=900):
    page.wait_for_load_state("networkidle")
    # Chart.js animates; a toast fades. Wait for both to finish.
    page.wait_for_timeout(ms)


def run_ops(page, ops):
    for op in ops:
        kind, *args = op
        if kind == "goto":
            page.goto(BASE + args[0])
        elif kind == "click":
            page.locator(args[0]).first.click()
        elif kind == "fill":
            page.locator(args[0]).first.fill(args[1])
        elif kind == "select":
            page.locator(args[0]).first.select_option(label=args[1])
        elif kind == "select_value":
            page.locator(args[0]).first.select_option(value=args[1])
        elif kind == "check":
            page.locator(args[0]).first.check()
        elif kind == "upload":
            page.locator(args[0]).first.set_input_files(args[1])
        elif kind == "hover":
            page.locator(args[0]).first.hover()
        elif kind == "press":
            page.keyboard.press(args[0])
        elif kind == "scroll":
            b = box_of(page, args[0])
            if b is None:
                raise RuntimeError(f"scroll target {args[0]!r} not found")
            offset = args[1] if len(args) > 1 else 90
            page.evaluate("y => window.scrollBy(0, y)", b["y"] - offset)
        elif kind == "scroll_top":
            page.evaluate("window.scrollTo(0, 0)")
        elif kind == "wait":
            page.wait_for_timeout(args[0])
        elif kind == "js":
            page.evaluate(args[0])
        else:
            raise ValueError(kind)
        page.wait_for_load_state("networkidle")


FIND_JS = r"""
([kind, text]) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const want = norm(text);
  let el = null;
  if (kind === 'card') {
    let hs = [...document.querySelectorAll('main h1, main h2, main h3, main h4, dialog[open] h2')]
      .filter(h => norm(h.textContent).startsWith(want) && vis(h));
    if (!hs.length) hs = [...document.querySelectorAll('main dt, main p, main span, main legend')]
      .filter(h => norm(h.textContent).startsWith(want) && vis(h));
    const h = hs[0];
    if (h) el = (h.parentElement && h.parentElement.closest('.card, section, article, dialog')) || h;
  } else if (kind === 'field') {
    const ls = [...document.querySelectorAll('main label, dialog[open] label, main legend')]
      .filter(l => norm(l.textContent).startsWith(want) && vis(l));
    const l = ls[0];
    if (l) {
      el = l.parentElement;
      // climb until the wrapper also holds the control
      while (el && !el.querySelector('input, select, textarea') && el !== document.body) el = el.parentElement;
    }
  }
  if (!el || !vis(el)) return null;
  const r = el.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
}
"""


def box_of(page, selector):
    for kind in ("card", "field"):
        if selector.startswith(kind + ":"):
            return page.evaluate(FIND_JS, [kind, selector[len(kind) + 1:]])
    loc = page.locator(selector)
    if not loc.count():
        return None
    for i in range(loc.count()):
        el = loc.nth(i)
        if el.is_visible():
            b = el.bounding_box()
            if b and b["width"] > 0 and b["height"] > 0:
                return b
    return None


# -- drawing ---------------------------------------------------------------

def annotate(raw_path, out_path, boxes, origin):
    """Draw a frame and a numbered badge for each marker (CSS px -> image px)."""
    im = Image.open(raw_path).convert("RGBA")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    badge_r = int(15 * SCALE)
    f = font(int(17 * SCALE))
    W, H = im.size
    placed = []
    for n, b in boxes:
        x0 = (b["x"] - origin[0]) * SCALE - 4 * SCALE
        y0 = (b["y"] - origin[1]) * SCALE - 4 * SCALE
        x1 = x0 + b["width"] * SCALE + 8 * SCALE
        y1 = y0 + b["height"] * SCALE + 8 * SCALE
        x0, y0 = max(x0, 2), max(y0, 2)
        x1, y1 = min(x1, W - 3), min(y1, H - 3)
        d.rounded_rectangle([x0, y0, x1, y1], radius=int(6 * SCALE),
                            outline=ACCENT + (255,), width=int(3 * SCALE),
                            fill=ACCENT_FILL)
        # Badge: outside the top-left corner, pulled inside when it would
        # leave the image, nudged when it would cover an earlier badge.
        cx, cy = x0 - badge_r * 0.35, y0 - badge_r * 0.35
        cx = min(max(cx, badge_r + 2), W - badge_r - 2)
        cy = min(max(cy, badge_r + 2), H - badge_r - 2)
        for px, py in placed:
            if abs(px - cx) < badge_r * 2 and abs(py - cy) < badge_r * 2:
                cx += badge_r * 2.2
        placed.append((cx, cy))
        d.ellipse([cx - badge_r - 3, cy - badge_r - 3, cx + badge_r + 3, cy + badge_r + 3],
                  fill=WHITE + (255,))
        d.ellipse([cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r],
                  fill=ACCENT + (255,))
        text = str(n)
        tb = d.textbbox((0, 0), text, font=f)
        d.text((cx - (tb[2] - tb[0]) / 2 - tb[0], cy - (tb[3] - tb[1]) / 2 - tb[1]),
               text, font=f, fill=WHITE + (255,))
    out = Image.alpha_composite(im, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, optimize=True)


# -- one figure --------------------------------------------------------------

def capture(session, fig):
    page = session.page(fig.get("user"), fig.get("accept_privacy", True))
    page.set_viewport_size({"width": WIDTH, "height": fig.get("height", 900)})
    if fig.get("url"):
        page.goto(BASE + fig["url"])
        settle(page, 200)
    run_ops(page, fig.get("ops", []))
    settle(page, fig.get("wait", 1100))

    clip_sel = fig.get("clip")
    if not clip_sel and fig.get("fit", True):
        # Grow the window until the lowest marker is in the picture.
        vh = fig.get("height", 900)
        bottoms = [b["y"] + b["height"] for b in
                   (box_of(page, m[0]) for m in fig.get("markers", [])) if b]
        need = int(max(bottoms, default=0) + 70)
        if need > vh:
            page.set_viewport_size({"width": WIDTH, "height": min(need, 2600)})
            settle(page, 500)

    RAW.mkdir(parents=True, exist_ok=True)
    raw = RAW / f"{fig['id']}.png"
    if clip_sel:
        b = box_of(page, clip_sel)
        if b is None:
            raise RuntimeError(f"{fig['id']}: clip {clip_sel!r} not found")
        pad = fig.get("pad", 12)
        sx, sy = page.evaluate("[window.scrollX, window.scrollY]")
        clip = {
            "x": max(b["x"] + sx - pad, 0), "y": max(b["y"] + sy - pad, 0),
            "width": min(b["width"] + 2 * pad, WIDTH),
            "height": min(b["height"] + 2 * pad, fig.get("max_height", 3200)),
        }
        page.screenshot(path=str(raw), clip=clip, full_page=True)
        origin = (clip["x"] - sx, clip["y"] - sy)
    elif fig.get("crop"):
        x, y, w, h = fig["crop"]
        page.screenshot(path=str(raw), clip={"x": x, "y": y, "width": w, "height": h})
        origin = (x, y)
    else:
        page.screenshot(path=str(raw))
        origin = (0, 0)

    with Image.open(raw) as im:
        img_w, img_h = im.size[0] / SCALE, im.size[1] / SCALE
    boxes, legend, missing = [], [], []
    for n, marker in enumerate(fig.get("markers", []), start=1):
        sel, label, text = marker
        b = box_of(page, sel)
        if b is not None:
            rx, ry = b["x"] - origin[0], b["y"] - origin[1]
            if rx > img_w - 4 or ry > img_h - 4 or rx + b["width"] < 4 or ry + b["height"] < 4:
                missing.append(f"{sel} (outside the picture)")
                b = None
        if b is None:
            if not missing or not missing[-1].startswith(sel):
                missing.append(sel)
        else:
            boxes.append((n, b))
        legend.append({"n": n, "label": label, "text": text, "found": b is not None})

    out = ASSETS / fig["module"] / f"{fig['id']}.png"
    annotate(raw, out, boxes, origin)
    for op in fig.get("after", []):
        run_ops(page, [op])
    return {
        "id": fig["id"], "module": fig["module"],
        "file": f"assets/{fig['module']}/{fig['id']}.png",
        "caption": fig["caption"], "role": spec.ROLE_LABELS.get(fig.get("user"), "Public visitor"),
        "page": fig.get("url") or "", "legend": legend, "missing": missing,
        "source": "live capture",
    }


def main(prefixes):
    manifest_path = ASSETS / "figures.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    todo = [f for f in spec.FIGURES if not prefixes or f["id"].startswith(tuple(prefixes))]
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        session = Session(browser)
        for fig in todo:
            try:
                entry = capture(session, fig)
                manifest[fig["id"]] = entry
                flag = f"  MISSING {entry['missing']}" if entry["missing"] else ""
                print(f"ok   {fig['id']}{flag}")
                if entry["missing"]:
                    problems.append(fig["id"])
            except Exception as exc:  # keep going; report at the end
                print(f"FAIL {fig['id']}: {str(exc).splitlines()[0][:200]}")
                problems.append(fig["id"])
        browser.close()
    order = [f["id"] for f in spec.FIGURES]
    manifest = {k: manifest[k] for k in order if k in manifest}
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(todo)} figure(s) attempted; problems: {problems or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1:])
