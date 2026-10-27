"""
Draw the installable-app icons from the LGMED-iMMS mark.

    python manage.py make_pwa_icons

Writes static/img/pwa/ and the Android app's launcher icons
(mobile/app/src/main/res/mipmap-*/ic_launcher.png). Run it again only if the
mark's source images in static/img/brand/png/ change; the output is
committed, so a deployment never draws icons at start-up.

The icons are the full-colour mark on a transparent background, by the
office's choice. Two platforms cannot show transparency in an app icon, so
those two get white instead:

  icon-*.png            Transparent. "any" - install dialogs, desktop
                        shortcuts, the Windows taskbar, and Android shortcuts
                        made with "Add to Home screen". Android sets a
                        transparent icon on a white square of its own, and on
                        the navy launch screen (core/pwa.py) that square shows.
  icon-maskable-*.png   White. Android crops launcher icons to its own shape
                        (circle, squircle, teardrop) and fills whatever is
                        transparent, so the icon must be opaque edge to edge.
                        Only the centre 80% circle is sure to survive, so the
                        mark is shrunk into it.
  apple-touch-icon.png  White. iOS paints transparency black, where the navy
                        rays would vanish.
  favicon-*.png         Transparent. The browser tab and window title bar.
                        Drawn from the favicon cut of the mark - heavier
                        strokes, shorter rays - so it stays legible at 16 px.
  ic_launcher.png       Transparent. The Android app's legacy launcher icon,
                        one per density.

The source images are rendered from the SVGs in static/img/brand/.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image

WHITE = (255, 255, 255, 255)

# Launcher icon size per Android density bucket.
ANDROID_DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


class Command(BaseCommand):
    help = "Draw the PWA and Android icons from the mark in static/img/brand/png/."

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        brand = base / "static" / "img" / "brand" / "png"
        mark_source = brand / "lgmed-imms-mark-1024.png"
        favicon_source = brand / "favicon-1024.png"
        out = base / "static" / "img" / "pwa"
        out.mkdir(parents=True, exist_ok=True)

        def mark_on(source, size, scale, background=None):
            mark = Image.open(source).convert("RGBA")
            inner = round(size * scale)
            mark = mark.resize((inner, inner), Image.LANCZOS)
            canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
            offset = (size - inner) // 2
            canvas.alpha_composite(mark, (offset, offset))
            return canvas

        for size in (192, 512):
            mark_on(mark_source, size, 0.92).save(out / f"icon-{size}.png", optimize=True)
            # 0.68 keeps the horizon's ends and the longest ray inside the 80%
            # safe-zone circle.
            mark_on(mark_source, size, 0.68, WHITE).convert("RGB").save(
                out / f"icon-maskable-{size}.png", optimize=True
            )
        mark_on(mark_source, 180, 0.84, WHITE).convert("RGB").save(
            out / "apple-touch-icon.png", optimize=True
        )
        for size in (16, 32, 48):
            mark_on(favicon_source, size, 1.0).save(out / f"favicon-{size}.png", optimize=True)

        res = base / "mobile" / "app" / "src" / "main" / "res"
        for density, size in ANDROID_DENSITIES.items():
            folder = res / f"mipmap-{density}"
            folder.mkdir(parents=True, exist_ok=True)
            mark_on(mark_source, size, 0.9).save(folder / "ic_launcher.png", optimize=True)
        self.stdout.write(self.style.SUCCESS(f"Wrote icons to {out} and {res}"))
