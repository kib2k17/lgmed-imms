"""Rasterise the brand SVGs with headless Edge, then downsample with Pillow.

Usage: python tools/brand/export_png.py static/img/brand
"""
import os
import subprocess
import sys
import shutil
import tempfile

from PIL import Image

BRAND = sys.argv[1]
PNG = os.path.join(BRAND, "png")
os.makedirs(PNG, exist_ok=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TMP = tempfile.mkdtemp()


def render(svg_name, w, h):
    src = os.path.join(BRAND, svg_name).replace("\\", "/")
    page = os.path.join(TMP, "r.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(f'<html><body style="margin:0;background:transparent">'
                 f'<img src="file:///{src}" style="display:block;width:{w}px;height:{h}px"></body></html>')
    out = os.path.join(TMP, "r.png")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--allow-file-access-from-files", "--default-background-color=00000000",
                    f"--window-size={w},{h}", f"--screenshot={out}", "file:///" + page.replace("\\", "/")],
                   check=True, capture_output=True)
    return Image.open(out).convert("RGBA").crop((0, 0, w, h))


def svg_size(name):
    import re
    head = open(os.path.join(BRAND, name), encoding="utf-8").read(300)
    w, h = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', head).groups()
    return float(w), float(h)


fav = render("favicon.svg", 1024, 1024)
for s in (16, 32, 48):
    fav.resize((s, s), Image.LANCZOS).save(os.path.join(PNG, f"favicon-{s}.png"))
fav.save(os.path.join(PNG, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])

app = render("lgmed-imms-app-icon.svg", 1024, 1024)
for s, name in ((512, "icon-512"), (192, "icon-192"), (512, "icon-maskable-512"),
                (192, "icon-maskable-192"), (180, "apple-touch-icon")):
    app.resize((s, s), Image.LANCZOS).convert("RGB").save(os.path.join(PNG, f"{name}.png"))

# Sources for `manage.py make_pwa_icons`.
fav.save(os.path.join(PNG, "favicon-1024.png"))
render("lgmed-imms-mark-dark.svg", 1024, 1024).save(os.path.join(PNG, "lgmed-imms-mark-dark-1024.png"))

mk = render("lgmed-imms-mark.svg", 1024, 1024)
mk.save(os.path.join(PNG, "lgmed-imms-mark-1024.png"))
for s in (512, 64):
    mk.resize((s, s), Image.LANCZOS).save(os.path.join(PNG, f"lgmed-imms-mark-{s}.png"))

# Wordmarks for reports / PDF engines / slides that want raster images.
for name in ("lgmed-imms-horizontal", "lgmed-imms-horizontal-dark", "lgmed-imms-stacked",
             "lgmed-imms-login"):
    w, h = svg_size(name + ".svg")
    big = render(name + ".svg", round(w * 6), round(h * 6))
    big.resize((round(w * 3), round(h * 3)), Image.LANCZOS).save(os.path.join(PNG, f"{name}@3x.png"))

print(fav.getpixel((2, 2)), "corner alpha (expect 0)")
for f in sorted(os.listdir(PNG)):
    print(f, Image.open(os.path.join(PNG, f)).size)

shutil.rmtree(TMP, ignore_errors=True)
