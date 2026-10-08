"""
Signature images.

The picture a signer keeps to be drawn inside their signature boxes. As with
profile photos (accounts.photos), what is kept is never the uploaded file:
the pixels are copied into a fresh PNG, so a file that only claims to be an
image fails here and camera metadata is left behind. Transparency is kept -
a signature on a transparent background sits cleanly on any page.
"""

import io
import secrets

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG"}
ACCEPT = "image/png,image/jpeg,.png,.jpg,.jpeg"
MAX_PIXELS = 20_000_000
# Wide enough to stay crisp in a signature box when printed.
MAX_SIZE = (1200, 600)


def process_signature_image(upload):
    """Turn an upload into the stored PNG, or raise ValidationError."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("The signature image is larger than 2 MB.")
    try:
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError("Upload a PNG or JPG image.")
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise ValidationError("The image's dimensions are too large.")
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError("The file is not an image, or it is damaged.")

    image = ImageOps.exif_transpose(image)
    image = image.convert("RGBA")
    # Trim empty margins so the signature, not the paper, fills the box.
    box = image.getchannel("A").getbbox() if image.getextrema()[3][0] < 255 else None
    if box is None:
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        difference = Image.eval(
            Image.composite(image, background, image).convert("L"), lambda v: 255 - v,
        )
        box = difference.point(lambda v: 255 if v > 24 else 0).getbbox()
    if box:
        image = image.crop(box)
    image.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{secrets.token_hex(12)}.png")
