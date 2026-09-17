"""
Creating the public copy of an approved document.

The module brief is explicit that publication must not be a matter of flipping
`is_public` on the file somebody uploaded. The reason is practical rather than
theoretical: the internal file is the one the office keeps, complete with
whatever the scanner did not catch and whatever a reviewer redacted in a later
version, and a flag that exposes *that* file exposes all of it.

So publishing copies the approved bytes into the served media root, under a
random token, and the public website only ever links to the copy. Withdrawing
the document deletes the copy. If the internal file is later replaced, the
public copy does not change until somebody approves and publishes again.
"""

import logging
import unicodedata
import re

from django.core.files.base import ContentFile

logger = logging.getLogger("lgmed.programs")

# Bytes per read when copying. Documents here are at most 25 MB, but a
# government office on a shared server should not be holding one in memory
# whole just because it fits.
CHUNK_SIZE = 64 * 1024


def public_filename(document):
    """
    The name the public copy is served under.

    Taken from the document's *title*, not from the uploaded filename. Office
    filenames carry information the office did not mean to publish -
    `SGLG-2025-final-BUTUAN-revised-by-jdelacruz.pdf` names a staff member,
    and `attendance_bayugan_participants.xlsx` says what is inside it. The
    title is the thing somebody wrote for the public, so it is the thing the
    public sees.
    """
    stem = unicodedata.normalize("NFKD", document.title or "document")
    stem = stem.encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower() or "document"
    return f"{stem[:80]}.{document.extension}" if document.extension else stem[:80]


def create_public_copy(document):
    """
    Write the approved document into the served media root.

    Replaces any copy already there, so republishing after a re-upload cannot
    leave the previous version reachable at its old address.
    """
    # Clear out any copy already on the served side - the one this instance
    # knows about, and the one the stored row knows about. They differ when the
    # instance in hand is stale (it was fetched before an earlier publish), and
    # in that case trusting the instance alone would leave the previous copy in
    # a served directory with nothing referencing it and nothing to ever delete
    # it: a file that is public, unreachable through the site, and invisible to
    # the office. Cheap to prevent, very hard to notice afterwards.
    stored = (
        type(document).objects.filter(pk=document.pk)
        .values_list("public_file", flat=True).first()
        if document.pk else None
    )
    for name in {document.public_file.name or None, stored or None} - {None}:
        try:
            document.public_file.storage.delete(name)
        except OSError:
            logger.exception(
                "Could not remove the previous public copy %s of document %s",
                name, document.pk,
            )
    document.public_file = ""

    source = document.file
    source.open("rb")
    try:
        payload = ContentFile(source.read())
    finally:
        source.close()

    document.public_file.save(public_filename(document), payload, save=False)
    logger.info(
        "Published PPA document %s (%s) as %s",
        document.pk, document.title, document.public_file.name,
    )
    return document.public_file
