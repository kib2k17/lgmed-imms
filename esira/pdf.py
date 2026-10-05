"""
Reading PDFs, assembling scans into one, and placing boxes on pages.

Nothing here signs anything. It answers three questions: is this upload a PDF
we can sign, what shape is each page, and where on the page - in PDF units -
does a box the user drew on screen actually fall.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


class PdfRejected(ValueError):
    """The upload cannot be taken into e-SIRA. The message says why."""


@dataclass(frozen=True)
class PageGeometry:
    """A page's visible area in PDF user space, and its display rotation."""

    left: float
    bottom: float
    width: float
    height: float
    rotate: int  # 0, 90, 180 or 270, clockwise

    @property
    def display_width(self):
        return self.height if self.rotate in (90, 270) else self.width

    @property
    def display_height(self):
        return self.width if self.rotate in (90, 270) else self.height


@dataclass(frozen=True)
class PdfInfo:
    page_count: int
    pages: tuple
    already_signed: bool


PDF_MAGIC = b"%PDF-"

# Images accepted as scanned pages, and the resolution they are assumed to be
# at when turned into a page. 200 dpi is what office scanners default to; an
# A4 scan at 200 dpi becomes an A4 page.
SCAN_FORMATS = {"JPEG", "PNG", "TIFF", "BMP", "WEBP"}
SCAN_DPI = 200


def _inherited(page, key):
    """A page attribute that may be set on the page or on any /Pages parent."""
    node = page
    for _ in range(64):  # a page tree deeper than this is malformed
        if key in node:
            return node[key]
        if "/Parent" not in node:
            return None
        node = node["/Parent"]
    return None


def _box(value):
    numbers = [float(n) for n in value]
    x1, y1, x2, y2 = numbers
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def inspect_pdf(data):
    """
    Open a PDF and describe its pages, or raise `PdfRejected`.

    Encrypted PDFs are refused: a password-protected file cannot be signed
    without the password, and an owner-password PDF may forbid signing.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader

    if not data or PDF_MAGIC not in data[:1024]:
        raise PdfRejected("The file is not a PDF.")
    try:
        reader = PdfFileReader(io.BytesIO(data), strict=False)
    except Exception as exc:
        raise PdfRejected(f"The PDF could not be read ({exc.__class__.__name__}).")
    if reader.encrypted:
        raise PdfRejected(
            "The PDF is password-protected. Remove the protection and upload it again."
        )

    try:
        count = int(reader.root["/Pages"]["/Count"])
        pages = []
        for index in range(count):
            page = reader.find_page_for_modification(index)[0].get_object()
            media = _inherited(page, "/MediaBox")
            crop = _inherited(page, "/CropBox") or media
            if crop is None:
                raise PdfRejected(f"Page {index + 1} has no page size.")
            left, bottom, width, height = _box(crop)
            rotate = int(_inherited(page, "/Rotate") or 0) % 360
            if rotate not in (0, 90, 180, 270):
                rotate = 0
            pages.append(PageGeometry(left, bottom, width, height, rotate))
        signed = bool(reader.embedded_signatures)
    except PdfRejected:
        raise
    except Exception as exc:
        raise PdfRejected(
            f"The PDF's page structure could not be read ({exc.__class__.__name__})."
        )

    if count < 1:
        raise PdfRejected("The PDF has no pages.")
    return PdfInfo(page_count=count, pages=tuple(pages), already_signed=signed)


def images_to_pdf(image_files):
    """
    Assemble scanned pages - one image each, in the order given - into a PDF.

    Each image is opened to prove it is an image, turned upright from its
    camera orientation, and flattened to RGB. The camera's embedded metadata,
    location included, does not survive into the PDF.
    """
    pages = []
    try:
        for upload in image_files:
            upload.seek(0)
            try:
                image = Image.open(upload)
                image.load()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise PdfRejected(f"{getattr(upload, 'name', 'A file')} is not a readable image.")
            if image.format not in SCAN_FORMATS:
                raise PdfRejected(
                    f"{getattr(upload, 'name', 'A file')} is a {image.format} image; "
                    "use JPEG, PNG or TIFF."
                )
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            pages.append(image)
        if not pages:
            raise PdfRejected("No scanned pages were supplied.")
        output = io.BytesIO()
        pages[0].save(
            output, "PDF", save_all=True, append_images=pages[1:],
            resolution=SCAN_DPI,
        )
        return output.getvalue()
    finally:
        for image in pages:
            image.close()


def box_to_pdf_rect(geometry, x, y, width, height):
    """
    Convert a box drawn on the displayed page into a PDF rectangle.

    (x, y, width, height) are fractions of the displayed page, origin top
    left, exactly as the viewer records them. The result is (x1, y1, x2, y2)
    in the page's unrotated user space, which is what a signature widget's
    /Rect is written in. The page's /Rotate then turns the widget with the
    page, so the signature reads the same way up as the text around it.
    """
    dw, dh = geometry.display_width, geometry.display_height
    w, h = geometry.width, geometry.height

    def to_user(u, v):
        px, py = u * dw, v * dh  # display units, origin top left
        r = geometry.rotate
        if r == 0:
            ux, uy = px, h - py
        elif r == 90:
            ux, uy = py, px
        elif r == 180:
            ux, uy = w - px, py
        else:  # 270
            ux, uy = w - py, h - px
        return ux + geometry.left, uy + geometry.bottom

    ax, ay = to_user(x, y)
    bx, by = to_user(x + width, y + height)
    return (
        round(min(ax, bx)), round(min(ay, by)),
        round(max(ax, bx)), round(max(ay, by)),
    )
