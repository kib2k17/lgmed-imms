"""
Profile photos.

What is kept is never the file that was uploaded. Every photo is opened,
cropped to a square, shrunk and written out again as a fresh JPEG, which does
three things at once:

- a file that only claims to be an image fails here rather than being stored;
- the picture is small enough to sit in the top bar of every page;
- the metadata a phone camera writes into a photo - including the GPS position
  it was taken at, often someone's home - is left behind, because only the
  pixels are copied across.
"""

import io
import secrets

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Large enough for the profile card on a high-density screen, small enough
# that every page carrying it stays light.
PHOTO_SIZE = 320

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG": "JPEG", "PNG": "PNG", "WEBP": "WebP"}
ACCEPT = "image/jpeg,image/png,image/webp"

# Refuse images whose pixel count alone could exhaust the server's memory when
# decoded - a few kilobytes of PNG can describe an enormous canvas.
MAX_PIXELS = 40_000_000


def process_photo(upload):
    """
    Turn an uploaded file into the stored photo, or raise ValidationError.

    Returns a ContentFile carrying a new, unguessable file name.
    """
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            "The photo is larger than 5 MB. Choose a smaller file."
        )

    try:
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError(
                "Upload a JPEG, PNG or WebP photo."
            )
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise ValidationError(
                "The photo's dimensions are too large. Choose a smaller image."
            )
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError,
            Image.DecompressionBombError):
        raise ValidationError("The file is not an image, or it is damaged.")

    # A phone records which way up it was held rather than rotating the
    # pixels; apply that before the orientation tag is discarded.
    image = ImageOps.exif_transpose(image)

    # Transparent areas become white rather than black.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    image = ImageOps.fit(
        image, (PHOTO_SIZE, PHOTO_SIZE), method=Image.Resampling.LANCZOS,
    )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{secrets.token_hex(12)}.jpg")


def replace_photo(user, content):
    """
    Store `content` - the output of `process_photo` - as the user's photo and
    delete the one it replaces.
    """
    previous = user.photo.name if user.photo else ""
    user.photo.save(content.name, content, save=False)
    user.save(update_fields=["photo"])
    if previous:
        user.photo.storage.delete(previous)


def remove_photo(user):
    if not user.photo:
        return
    name = user.photo.name
    storage = user.photo.storage
    user.photo = ""
    user.save(update_fields=["photo"])
    storage.delete(name)
