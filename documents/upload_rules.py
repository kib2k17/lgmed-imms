"""
What the document register - and every module that files into it - accepts.

Kept apart from documents.models and documents.forms so both can use it: the
forms check a file as it is posted, and the model fields check it again, which
is what covers an upload made through the Django administration, where none
of the module's own forms run. Nothing here imports a model.
"""

import os

from django import forms
from django.core.files.uploadedfile import UploadedFile

from core.uploads import check_signature

ALLOWED_EXTENSIONS = (
    "pdf",
    "doc", "docx",
    "xls", "xlsx", "csv",
    "ppt", "pptx",
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff",
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ACCEPT_ATTRIBUTE = ",".join(f".{extension}" for extension in ALLOWED_EXTENSIONS)
FORMAT_HELP = (
    "PDF, Word, Excel, PowerPoint or an image (JPG, PNG, TIFF). "
    f"Up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
)


def validate_upload(uploaded):
    """
    Check an uploaded file against the module's accepted formats and size.
    Shared by every form that takes a file, so the register cannot end up
    holding something the download view will not serve.
    """
    # Only a file arriving now is judged. A record's existing file comes back
    # unchanged on every edit and was accepted under the rules of its day.
    if not uploaded or not isinstance(uploaded, UploadedFile):
        return uploaded
    extension = os.path.splitext(uploaded.name)[1].lstrip(".").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            f"'{extension or uploaded.name}' is not an accepted document "
            f"format. {FORMAT_HELP}"
        )
    if uploaded.size > MAX_UPLOAD_BYTES:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise forms.ValidationError(
            f"This file is {uploaded.size / (1024 * 1024):.1f} MB. "
            f"The limit is {limit} MB."
        )
    return check_signature(uploaded)


def validate_new_file(value):
    """
    The model-field form of validate_upload.

    A model validator is handed the field's FieldFile. Only one wrapping a
    file posted now is judged; a stored file - every edit of a record hands
    its existing file back - is left alone, as validate_upload leaves it.
    """
    if getattr(value, "_committed", True):
        return
    validate_upload(getattr(value, "_file", None))
