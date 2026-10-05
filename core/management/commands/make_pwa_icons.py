"""
Draw the installable-app icons from the agency seal.

    python manage.py make_pwa_icons

Writes static/img/pwa/. Run it again only if static/img/dilg-logo.png changes;
the output is committed, so a deployment never draws icons at start-up.

Every icon is the seal on solid navy (brand-950, the app's launch-screen
colour in core/pwa.py). None is transparent, because no platform shows
transparency as transparency: Android puts a transparent icon on a WHITE
square - on the home screen and on the navy launch screen, where it looked
like a white box - and iOS paints it black. On navy, whichever icon a
platform picks runs straight into the launch screen.

  icon-*.png            "any" - install dialogs, desktop shortcuts, the Windows
                        taskbar, and Android shortcuts made with "Add to Home
                        screen".
  icon-maskable-*.png   Android crops launcher icons to its own shape (circle,
                        squircle, teardrop). Only the centre 80% circle is sure
                        to survive, so the seal is shrunk into it.
  apple-touch-icon.png  iPhone / iPad home screen.
  favicon-*.png         The browser tab and window title bar - the one place
                        the seal is transparent (see the note below).
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image

# brand-950 - core.pwa.BACKGROUND_COLOR / THEME_COLOR.
NAVY = (11, 28, 48, 255)


class Command(BaseCommand):
    help = "Draw the PWA icons in static/img/pwa/ from static/img/dilg-logo.png."

    def handle(self, *args, **options):
        static = Path(settings.BASE_DIR) / "static" / "img"
        source = static / "dilg-logo.png"
        out = static / "pwa"
        out.mkdir(parents=True, exist_ok=True)

        def seal_on(size, scale, background=None):
            seal = Image.open(source).convert("RGBA")
            inner = round(size * scale)
            seal = seal.resize((inner, inner), Image.LANCZOS)
            canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
            offset = (size - inner) // 2
            canvas.alpha_composite(seal, (offset, offset))
            return canvas

        for size in (192, 512):
            seal_on(size, 0.84, NAVY).convert("RGB").save(
                out / f"icon-{size}.png", optimize=True
            )
            # 0.76 keeps the seal's rim inside the 80% safe-zone circle.
            seal_on(size, 0.76, NAVY).convert("RGB").save(
                out / f"icon-maskable-{size}.png", optimize=True
            )
        seal_on(180, 0.84, NAVY).convert("RGB").save(
            out / "apple-touch-icon.png", optimize=True
        )
        # Browser tab / window title bar: small enough that it is never the
        # "largest icon" an Add to Home screen fallback takes, so it can stay
        # transparent.
        for size in (16, 32, 48):
            seal_on(size, 1.0).save(out / f"favicon-{size}.png", optimize=True)
        self.stdout.write(self.style.SUCCESS(f"Wrote icons to {out}"))
