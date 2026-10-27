"""Generate the LGMED-iMMS logo system as outlined SVG.

Usage: python tools/brand/build_logo.py .
Writes static/img/brand/*.svg. See tools/brand/README.md.
"""
import math
import os
import sys

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = sys.argv[1]
OUT = os.path.join(ROOT, "static", "img", "brand")
os.makedirs(OUT, exist_ok=True)

NAVY = "#102A43"
ROYAL = "#1565C0"
GOLD = "#F4B400"
WHITE = "#FFFFFF"
GRAY = "#64748B"
# Dark-surface companions (tints of Royal Blue, for navy backgrounds)
ROYAL_LT = "#5B9BEA"
ROYAL_DK_L = "#1565C0"
ROYAL_DK_R = "#2B7FE0"
GRAY_LT = "#A9B6C8"

FONT = TTFont(os.path.join(ROOT, "static", "fonts", "inter-latin-wght-normal.woff2"))
UPM = FONT["head"].unitsPerEm
CMAP = FONT.getBestCmap()
_gs = {}


def n(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def glyphset(w):
    if w not in _gs:
        _gs[w] = FONT.getGlyphSet(location={"wght": w})
    return _gs[w]


def text_path(s, weight, size, x, y, track=0.0):
    """Outline `s` with its baseline at y. Returns (d, advance_width)."""
    gs = glyphset(weight)
    sc = size / UPM
    pen = SVGPathPen(gs, ntos=n)
    cx = 0.0
    for i, ch in enumerate(s):
        g = gs[CMAP[ord(ch)]]
        g.draw(TransformPen(pen, (sc, 0, 0, -sc, x + cx * sc, y)))
        cx += g.width + (track * UPM if i < len(s) - 1 else 0)
    return pen.getCommands(), cx * sc


def text_width(s, weight, size, track=0.0):
    return text_path(s, weight, size, 0, 0, track)[1]


def i_dot_geometry(weight, size):
    """Centre (x offset from glyph origin, y above baseline) and radius of Inter's i-dot."""
    gs = glyphset(weight)
    rec = DecomposingRecordingPen(gs)
    gs[CMAP[ord("i")]].draw(rec)
    contours, cur = [], []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(cur)
            cur = []
    best = None
    for c in contours:
        pts = [p for _, a in c for p in a]
        ys = [p[1] for p in pts]
        if best is None or min(ys) > min(p[1] for p in best):
            best = pts
    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    sc = size / UPM
    return ((min(xs) + max(xs)) / 2 * sc, (min(ys) + max(ys)) / 2 * sc,
            (max(xs) - min(xs)) / 2 * sc)


# ---------------------------------------------------------------- the mark
# 64-unit grid. A shield split down the middle (navy | royal blue) carries a
# single continuous line that rises and falls through five nodes - an M read
# as a monitoring trend line, one node per Caraga province - with an "i"
# whose gold dot sits level with the two peaks.

SHIELD = "M12 6H52Q56 6 56 10V30C56 45 46 54 32 60C18 54 8 45 8 30V10Q8 6 12 6Z"
SHIELD_R = "M32 6H52Q56 6 56 10V30C56 45 46 54 32 60Z"
M_PTS = [(25, 41), (29.5, 19), (36, 31), (42.5, 19), (47, 41)]
I_STEM = ((17, 28), (17, 41))
I_DOT = (17, 19)
NODE_R = 3.35
STROKE = 5


def glyph_parts(line, dot, node, dx=0, dy=0, nodes=True, stroke=STROKE, dot_r=3.8):
    (sx, sy1), (_, sy2) = I_STEM
    seg = "M" + " L".join(f"{n(x + dx)} {n(y + dy)}" for x, y in M_PTS)
    out = [f'<path d="M{n(sx + dx)} {n(sy1 + dy)}V{n(sy2 + dy)}{seg}" fill="none" stroke="{line}" '
           f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round"/>']
    if nodes:
        out += [f'<circle cx="{n(x + dx)}" cy="{n(y + dy)}" r="{NODE_R}" fill="{node}"/>' for x, y in M_PTS]
    out.append(f'<circle cx="{n(I_DOT[0] + dx)}" cy="{n(I_DOT[1] + dy)}" r="{dot_r}" fill="{dot}"/>')
    return out


# ------------------------------------------------- the adopted mark: Rising Sun
# A gold sun rises over a horizon line. Its five rays lengthen from left to
# right like a performance trend; the last ray, in royal blue, is the result
# reached. Centred optically on the 64 grid (content spans x 4-61, y 14-50).
SUN_TILE = "#0B1C30"  # brand-950, the app's launch-screen navy


def sun_parts(ray, lead, sun, horizon, stroke=5.6, r0=14.5, lengths=(5, 7.5, 10, 12.5, 15),
              cx=30, cy=41, sun_r=11):
    out = []
    for k, (ang, ln) in enumerate(zip((198, 234, 270, 306, 342), lengths)):
        a = math.radians(ang)
        x0, y0 = cx + r0 * math.cos(a), cy + r0 * math.sin(a)
        x1, y1 = cx + (r0 + ln) * math.cos(a), cy + (r0 + ln) * math.sin(a)
        out.append(f'<path d="M{n(x0)} {n(y0)}L{n(x1)} {n(y1)}" stroke="{lead if k == 4 else ray}" '
                   f'stroke-width="{stroke}" stroke-linecap="round"/>')
    out.append(f'<path d="M{n(cx - sun_r)} {n(cy)}A{sun_r} {sun_r} 0 0 1 {n(cx + sun_r)} {n(cy)}Z" fill="{sun}"/>')
    out.append(f'<path d="M{n(cx - 23)} {n(cy + 6.5)}H{n(cx + 23)}" stroke="{horizon}" '
               f'stroke-width="{stroke}" stroke-linecap="round"/>')
    return out


def mark(variant="color", uid="m"):
    """Inner elements of the 64x64 mark (Rising Sun)."""
    if variant == "color":
        return sun_parts(NAVY, ROYAL, GOLD, NAVY)
    if variant == "dark":
        return sun_parts(WHITE, ROYAL_LT, GOLD, WHITE)
    if variant == "favicon":
        # Tuned for 16-32 px: transparent, heavier strokes, shorter rays.
        return sun_parts(NAVY, ROYAL, GOLD, NAVY, stroke=7, r0=15.5,
                         lengths=(3.5, 5.5, 7.5, 9.5, 11.5), cx=30, cy=40)
    if variant.startswith("mono"):
        ink = NAVY if variant == "mono" else (WHITE if variant == "mono-white" else "#000000")
        return sun_parts(ink, ink, ink, ink)
    raise ValueError(variant)


def shield_mark(variant="color", uid="m"):
    """The first adopted mark (Pulse Shield), kept so its presentation page can be rebuilt."""
    if variant in ("color", "dark"):
        left, right = (NAVY, ROYAL) if variant == "color" else (ROYAL_DK_L, ROYAL_DK_R)
        return [f'<path d="{SHIELD}" fill="{left}"/>', f'<path d="{SHIELD_R}" fill="{right}"/>',
                *glyph_parts(WHITE, GOLD, WHITE)]
    if variant == "favicon":
        # Tuned for 16-32 px: heavier line, no node beads, gold dot kept.
        return [f'<path d="{SHIELD}" fill="{NAVY}"/>', f'<path d="{SHIELD_R}" fill="{ROYAL}"/>',
                *glyph_parts(WHITE, GOLD, WHITE, nodes=False, stroke=6.4, dot_r=4.4)]
    if variant.startswith("mono"):
        ink = NAVY if variant == "mono" else (WHITE if variant == "mono-white" else "#000000")
        return [f'<mask id="{uid}"><rect width="64" height="64" fill="#fff"/>'
                + "".join(glyph_parts("#000", "#000", "#000")) + "</mask>",
                f'<path d="{SHIELD}" fill="{ink}" mask="url(#{uid})"/>']
    raise ValueError(variant)


def svg(w, h, body, title, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n(w)} {n(h)}" '
            f'width="{n(w)}" height="{n(h)}" role="img" aria-labelledby="t"{extra}>'
            f'<title id="t">{title}</title>' + "".join(body) + "</svg>\n")


def g(x, y, s, items):
    return f'<g transform="translate({n(x)} {n(y)}) scale({n(s)})">' + "".join(items) + "</g>"


# ------------------------------------------------------------- wordmark
def wordmark(x, baseline, size, scheme="light"):
    """LGMED (heavy, navy) + hyphen (gray) + iMMS (semibold, royal, gold i-dot)."""
    c_lg, c_dash, c_imms = (NAVY, GRAY, ROYAL) if scheme == "light" else (
        (WHITE, GRAY_LT, ROYAL_LT) if scheme == "dark" else (scheme, scheme, scheme))
    dot_c = GOLD if scheme in ("light", "dark") else scheme
    items = []
    d, w1 = text_path("LGMED", 800, size, x, baseline, 0.012)
    items.append(f'<path d="{d}" fill="{c_lg}"/>')
    cx = x + w1 + size * 0.035
    d, w2 = text_path("-", 600, size, cx, baseline)
    items.append(f'<path d="{d}" fill="{c_dash}"/>')
    cx += w2 + size * 0.02
    d, wi = text_path("ı", 650, size, cx, baseline)
    items.append(f'<path d="{d}" fill="{c_imms}"/>')
    ox, oy, r = i_dot_geometry(650, size)
    items.append(f'<circle cx="{n(cx + ox)}" cy="{n(baseline - oy)}" r="{n(r * 1.12)}" fill="{dot_c}"/>')
    cx += wi + size * 0.01
    d, w3 = text_path("MMS", 650, size, cx, baseline, 0.008)
    items.append(f'<path d="{d}" fill="{c_imms}"/>')
    return items, cx + w3 - x


TAGLINE = "EMPOWERING GOVERNANCE THROUGH DIGITAL INNOVATION"
FULLNAME = "Integrated Monitoring and Management System"
OFFICE = "DILG REGIONAL OFFICE XIII · CARAGA"


def fitted_line(s, weight, width, x, baseline, color, track=0.08):
    """Set `s` so its width equals `width` exactly (size solved, tracking fixed in em)."""
    w1 = text_width(s, weight, 10, track)
    size = 10 * width / w1
    d, _ = text_path(s, weight, size, x, baseline, track)
    return f'<path d="{d}" fill="{color}"/>', size


CAP = 1490 / 2048


def horizontal(scheme="light", tagline=True):
    size = 34
    mk = "color" if scheme == "light" else ("dark" if scheme == "dark" else scheme)
    tx = 78
    if tagline:
        base = 12 + size * CAP
        items, ww = wordmark(tx, base, size, scheme if not scheme.startswith("mono") else MONO_INK[scheme])
        tag_c = GRAY if scheme == "light" else (GRAY_LT if scheme == "dark" else MONO_INK[scheme])
        tl, _ = fitted_line(TAGLINE, 560, ww, tx, base + 15.5, tag_c, 0.09)
        items.append(tl)
    else:
        base = 31 + size * CAP / 2
        items, ww = wordmark(tx, base, size, scheme if not scheme.startswith("mono") else MONO_INK[scheme])
    W = tx + ww + 2
    body = [g(0, 0, 1, mark(mk, "hm")), *items]
    return W, 64, body


MONO_INK = {"mono": NAVY, "mono-white": WHITE, "mono-black": "#000000"}


def stacked(scheme="light", tagline=True, login=False):
    size = 40
    probe, ww = wordmark(0, 0, size, "light")
    W = max(ww, 230) + 24
    ms = 1.5
    mx = (W - 64 * ms) / 2
    mk = "color" if scheme == "light" else ("dark" if scheme == "dark" else scheme)
    ink = scheme if scheme in ("light", "dark") else MONO_INK[scheme]
    sub_c = GRAY if scheme == "light" else (GRAY_LT if scheme == "dark" else MONO_INK[scheme])
    base = 64 * ms + 16 + size * CAP
    items, ww = wordmark((W - ww) / 2, base, size, ink)
    y = base
    if login:
        fn_size = 13.2
        fw = text_width(FULLNAME, 500, fn_size)
        d, _ = text_path(FULLNAME, 500, fn_size, (W - fw) / 2, y + 22, 0)
        items.append(f'<path d="{d}" fill="{sub_c}"/>')
        rule_y = y + 36
        items.append(f'<rect x="{n(W / 2 - 14)}" y="{n(rule_y)}" width="28" height="2" rx="1" fill="{GOLD if scheme in ("light", "dark") else sub_c}"/>')
        ow_size = 9.4
        ow = text_width(OFFICE, 600, ow_size, 0.12)
        d, _ = text_path(OFFICE, 600, ow_size, (W - ow) / 2, rule_y + 17, 0.12)
        items.append(f'<path d="{d}" fill="{sub_c}"/>')
        H = rule_y + 22
    elif tagline:
        tl, _ = fitted_line(TAGLINE, 560, ww, (W - ww) / 2, y + 18, sub_c, 0.09)
        items.append(tl)
        H = y + 24
    else:
        H = y + 8
    body = [g(mx, 0, ms, mark(mk, "sm")), *items]
    return W, H, body


def sidebar():
    """Compact lock-up for the navy navigation drawer (brand-950)."""
    size = 19
    ms = 36 / 64
    tx = 46
    base = 4.5 + size * CAP
    items, ww = wordmark(tx, base, size, "dark")
    d, _ = text_path("DILG Region XIII · Caraga", 500, 9.6, tx, base + 14, 0.01)
    items.append(f'<path d="{d}" fill="{GRAY_LT}"/>')
    return tx + ww + 2, 40, [g(0, 2, ms, mark("dark", "sb")), *items]


# --------------------------------------------------------------- concepts
def arc(cx, cy, r, a0, a1):
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{n(x0)} {n(y0)}A{n(r)} {n(r)} 0 {large} 1 {n(x1)} {n(y1)}"


def concept1():
    hub = (32, 31)
    pts = [(32 + 14.5 * math.cos(math.radians(a)), 31 + 14.5 * math.sin(math.radians(a)))
           for a in (-90, -18, 54, 126, 198)]
    ring = "M" + " L".join(f"{n(x)} {n(y)}" for x, y in pts) + "Z"
    spokes = "".join(f"M{hub[0]} {hub[1]}L{n(x)} {n(y)}" for x, y in pts)
    return [f'<path d="{SHIELD}" fill="none" stroke="{NAVY}" stroke-width="3.6" stroke-linejoin="round"/>',
            f'<path d="{ring}" fill="none" stroke="{NAVY}" stroke-width="1.8" stroke-linejoin="round"/>',
            f'<path d="{spokes}" stroke="{ROYAL}" stroke-width="2.4" stroke-linecap="round"/>',
            *[f'<circle cx="{n(x)}" cy="{n(y)}" r="3.6" fill="{ROYAL}"/>' for x, y in pts],
            f'<circle cx="32" cy="31" r="5" fill="{GOLD}"/>']


def concept2():
    return [f'<rect x="4" y="4" width="56" height="56" rx="14" fill="{NAVY}"/>',
            *glyph_parts(WHITE, GOLD, WHITE, dy=2)]


def concept3():
    return [f'<path d="{arc(32, 32, 23, 135, 350)}" fill="none" stroke="{ROYAL}" stroke-width="6" stroke-linecap="round"/>',
            f'<path d="{arc(32, 32, 23, 362, 405)}" fill="none" stroke="{GOLD}" stroke-width="6" stroke-linecap="round"/>',
            f'<path d="M21.5 33.5 L29 41 L43.5 25.5" fill="none" stroke="{NAVY}" stroke-width="5.4" stroke-linecap="round" stroke-linejoin="round"/>',
            f'<circle cx="43.5" cy="25.5" r="3.4" fill="{NAVY}"/>']


def concept4():
    hexp = "M32 5L55.4 18.5V45.5L32 59L8.6 45.5V18.5Z"
    def plate(y, fill=None, stroke=None):
        d = f"M32 {n(y - 7)}L46 {n(y)}L32 {n(y + 7)}L18 {n(y)}Z"
        if fill:
            return f'<path d="{d}" fill="{fill}" stroke="{fill}" stroke-width="1.5" stroke-linejoin="round"/>'
        return (f'<path d="M18 {n(y)}L32 {n(y + 7)}L46 {n(y)}" fill="none" stroke="{stroke}" '
                f'stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>')
    return [f'<path d="{hexp}" fill="{NAVY}" stroke="{NAVY}" stroke-width="4" stroke-linejoin="round"/>',
            plate(40, stroke="#8FB8EA"), plate(33, stroke=WHITE), plate(24, fill=GOLD)]


# ------------------------------------------------------------------ write
FILES = {}


def write(name, content):
    FILES[name] = content
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


T = "LGMED-iMMS"
write("lgmed-imms-mark.svg", svg(64, 64, mark("color", "a"), T))
write("lgmed-imms-mark-dark.svg", svg(64, 64, mark("dark", "a"), T))
write("lgmed-imms-mark-mono.svg", svg(64, 64, mark("mono", "a"), T))
write("lgmed-imms-mark-mono-white.svg", svg(64, 64, mark("mono-white", "a"), T))
write("favicon.svg", svg(64, 64, mark("favicon", "a"), T))
# App tile for platforms that need an opaque icon (maskable, iOS): white,
# colour mark inside the maskable safe zone (centre 80% circle).
write("lgmed-imms-app-icon.svg", svg(64, 64, [f'<rect width="64" height="64" fill="{WHITE}"/>',
                                              g(32 - 64 * 0.74 / 2, 32 - 64 * 0.74 / 2, 0.74, mark("color", "a"))], T))

for scheme, suffix in (("light", ""), ("dark", "-dark"), ("mono", "-mono"), ("mono-white", "-mono-white")):
    w, h, b = horizontal(scheme, True)
    write(f"lgmed-imms-horizontal{suffix}.svg", svg(w, h, b, T))
    w, h, b = horizontal(scheme, False)
    write(f"lgmed-imms-horizontal-compact{suffix}.svg", svg(w, h, b, T))
    w, h, b = stacked(scheme, True)
    write(f"lgmed-imms-stacked{suffix}.svg", svg(w, h, b, T))

w, h, b = stacked("light", login=True)
write("lgmed-imms-login.svg", svg(w, h, b, T))
w, h, b = stacked("dark", login=True)
write("lgmed-imms-login-dark.svg", svg(w, h, b, T))
w, h, b = sidebar()
write("lgmed-imms-sidebar.svg", svg(w, h, b, T))

print("\n".join(f"{k}  {len(v)}" for k, v in FILES.items()))
