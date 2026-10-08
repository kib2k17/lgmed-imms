"""
Everything that changes an e-SIRA document happens here.

The views validate a form and call one of these functions; nothing else writes
a status, a step or a version. Each function re-checks permission itself
(`esira.permissions`) and raises `PermissionDenied` or `WorkflowError`, so the
rules hold however the function is reached. Each takes a row lock on the
document, so two people pressing a button at the same moment cannot both win.
"""

import io
import time

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from . import permissions as perms
from .audit import log
from .models import (
    COMPLETION_STATUS,
    DONE_STEP_STATUSES,
    OPEN_STEP_STATUSES,
    AuditAction,
    DigitalSignature,
    DocumentStatus,
    DocumentVersion,
    EsiraDocument,
    FileIntegrityError,
    ReferenceSequence,
    RoutingStep,
    SignatureBox,
    SignatureStyle,
    SignerProfile,
    SigningCertificate,
    StepAction,
    StepStatus,
    sha256_hex,
)
from .pdf import PdfRejected, box_to_pdf_rect, images_to_pdf, inspect_pdf

MAX_BOXES_PER_DOCUMENT = 300
MIN_BOX_FRACTION = 0.01
VIEW_LOG_INTERVAL = 10 * 60  # seconds between two "viewed" entries per session


class WorkflowError(Exception):
    """The action cannot be taken. The message is written for the user."""


def _locked(document):
    return EsiraDocument.objects.select_for_update().get(pk=document.pk)


def _max_upload_bytes():
    return int(getattr(settings, "ESIRA_MAX_UPLOAD_MB", 25)) * 1024 * 1024


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def _step_key(step):
    return f"esira:step:{step.pk}"


def _notify(recipients, *, title, message, url, action=False, dedupe_key=""):
    from notifications.models import Category, Level
    from notifications.service import notify

    try:
        notify(
            recipients,
            title=title,
            message=message,
            url=url,
            category=Category.ASSIGNMENT if action else Category.SYSTEM,
            level=Level.ACTION if action else Level.INFO,
            dedupe_key=dedupe_key,
        )
    except Exception:  # pragma: no cover - a notice must not fail the action
        import logging

        logging.getLogger("lgmed.esira").exception("e-SIRA notification failed")


def _resolve(step):
    from notifications.service import resolve

    resolve(_step_key(step))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def _store_version(document, data, *, kind, user, note=""):
    number = (document.versions.aggregate(n=Max("number"))["n"] or 0) + 1
    version = DocumentVersion(
        document=document,
        number=number,
        kind=kind,
        sha256=sha256_hex(data),
        size=len(data),
        created_by=user,
        note=note[:255],
    )
    version.file = ContentFile(data, name=f"{document.reference_no}-v{number}.pdf")
    version.save()
    return version


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def create_document(owner, *, title, description="", document_type="",
                    pdf_file=None, scan_images=None):
    """Take a PDF, or a set of scanned page images, into e-SIRA as a draft."""
    if not owner.can_upload_esira:
        raise PermissionDenied("Your role does not permit uploading to e-SIRA.")

    limit = _max_upload_bytes()
    if pdf_file is not None:
        if pdf_file.size > limit:
            raise WorkflowError(
                f"The file is larger than {settings.ESIRA_MAX_UPLOAD_MB} MB."
            )
        pdf_file.seek(0)
        data = pdf_file.read()
        source, filename = "UPLOAD", pdf_file.name
    elif scan_images:
        if sum(f.size for f in scan_images) > limit:
            raise WorkflowError(
                f"The scanned pages are larger than {settings.ESIRA_MAX_UPLOAD_MB} MB together."
            )
        try:
            data = images_to_pdf(scan_images)
        except PdfRejected as exc:
            raise WorkflowError(str(exc))
        source = "SCAN"
        filename = f"Scanned document ({len(scan_images)} page{'s' if len(scan_images) != 1 else ''})"
    else:
        raise WorkflowError("Choose a PDF file or scanned pages to upload.")

    try:
        info = inspect_pdf(data)
    except PdfRejected as exc:
        raise WorkflowError(str(exc))

    with transaction.atomic():
        document = EsiraDocument.objects.create(
            reference_no=ReferenceSequence.next_reference(),
            title=title.strip(),
            description=description.strip(),
            document_type=document_type.strip(),
            owner=owner,
            source=source,
            original_filename=filename[:255],
            page_count=info.page_count,
        )
        version = _store_version(
            document, data, kind=DocumentVersion.Kind.ORIGINAL, user=owner,
            note="Original as uploaded" if source == "UPLOAD" else "Assembled from scanned pages",
        )
        log(
            AuditAction.UPLOADED,
            actor=owner,
            document=document,
            version=version,
            detail=(
                f"{filename} - {info.page_count} page{'s' if info.page_count != 1 else ''}, "
                f"SHA-256 {version.sha256[:16]}..."
            ),
            metadata={
                "source": source,
                "filename": filename,
                "pages": info.page_count,
                "sha256": version.sha256,
                "size": version.size,
                "already_signed": info.already_signed,
            },
        )
    return document


# ---------------------------------------------------------------------------
# Signature placement
# ---------------------------------------------------------------------------


def _clean_box(item, page_count):
    try:
        page = int(item["page"])
        x, y = float(item["x"]), float(item["y"])
        width, height = float(item["width"]), float(item["height"])
    except (KeyError, TypeError, ValueError):
        raise WorkflowError("A signature box was sent without a valid position.")
    if not 1 <= page <= page_count:
        raise WorkflowError(f"Page {page} does not exist in this document.")
    tolerance = 1e-4
    if (
        width < MIN_BOX_FRACTION or height < MIN_BOX_FRACTION
        or x < -tolerance or y < -tolerance
        or x + width > 1 + tolerance or y + height > 1 + tolerance
    ):
        raise WorkflowError(f"A signature box on page {page} lies outside the page.")
    return {
        "page": page,
        "x": min(max(x, 0.0), 1.0),
        "y": min(max(y, 0.0), 1.0),
        "width": min(width, 1.0),
        "height": min(height, 1.0),
    }


def _pages_label(pages):
    pages = sorted(set(pages))
    if len(pages) > 6:
        return f"pages {pages[0]}-{pages[-1]} ({len(pages)} pages)"
    return ("page " if len(pages) == 1 else "pages ") + ", ".join(str(p) for p in pages)


def save_boxes(document, user, items):
    """
    Replace the boxes this user may edit with `items`.

    `items` is the full set the user now wants: an entry with an "id" keeps
    (and possibly moves) that box, one without adds a box, and an editable
    box that is missing is removed. Boxes the user may not edit - someone
    else's, or any that are already signed - are never touched.
    """
    from accounts.models import User

    with transaction.atomic():
        document = _locked(document)
        if not perms.can_edit_boxes(user, document):
            raise PermissionDenied("You may not change the signature boxes on this document.")

        editable = document.boxes.filter(signature__isnull=True)
        if not document.is_draft:
            editable = editable.filter(signer=user)
        existing = {box.pk: box for box in editable.select_related("signer")}

        if not isinstance(items, list):
            raise WorkflowError("The signature boxes could not be read.")
        locked_count = document.boxes.count() - len(existing)
        if locked_count + len(items) > MAX_BOXES_PER_DOCUMENT:
            raise WorkflowError(
                f"A document may carry at most {MAX_BOXES_PER_DOCUMENT} signature boxes."
            )

        signer_cache = {}

        def signer_for(value):
            if not document.is_draft:
                return user  # mid-route, a signer places only their own boxes
            try:
                pk = int(value)
            except (TypeError, ValueError):
                raise WorkflowError("Choose who is to sign each box.")
            if pk not in signer_cache:
                signer_cache[pk] = User.objects.filter(pk=pk, is_active=True).first()
            if signer_cache[pk] is None:
                raise WorkflowError("A box names a signer who has no active account.")
            return signer_cache[pk]

        added, modified, kept = [], [], set()
        for item in items:
            if not isinstance(item, dict):
                raise WorkflowError("The signature boxes could not be read.")
            values = _clean_box(item, document.page_count)
            signer = signer_for(item.get("signer"))
            box_id = item.get("id")
            if box_id not in (None, ""):
                try:
                    box = existing[int(box_id)]
                except (KeyError, TypeError, ValueError):
                    raise WorkflowError(
                        "A signature box has been signed or removed since this page "
                        "was opened. Reload the page."
                    )
                kept.add(box.pk)
                changed = signer.pk != box.signer_id or any(
                    abs(getattr(box, k) - v) > 1e-6 if k != "page" else getattr(box, k) != v
                    for k, v in values.items()
                )
                if changed:
                    for k, v in values.items():
                        setattr(box, k, v)
                    box.signer = signer
                    box.save()
                    modified.append(box)
            else:
                added.append(
                    SignatureBox.objects.create(
                        document=document, signer=signer, created_by=user, **values,
                    )
                )

        removed = [box for pk, box in existing.items() if pk not in kept]
        for box in removed:
            box.delete()

        for action, boxes, verb in (
            (AuditAction.BOX_ADDED, added, "Added"),
            (AuditAction.BOX_MODIFIED, modified, "Moved or resized"),
            (AuditAction.BOX_REMOVED, removed, "Removed"),
        ):
            if not boxes:
                continue
            signers = sorted({b.signer.get_display_name() for b in boxes})
            log(
                action,
                actor=user,
                document=document,
                detail=(
                    f"{verb} {len(boxes)} signature box{'es' if len(boxes) != 1 else ''} "
                    f"on {_pages_label(b.page for b in boxes)} for {', '.join(signers)}"
                ),
                metadata={
                    "boxes": [
                        {"page": b.page, "x": round(b.x, 4), "y": round(b.y, 4),
                         "width": round(b.width, 4), "height": round(b.height, 4),
                         "signer": b.signer_id}
                        for b in boxes
                    ][:100],
                },
            )

        return {
            "added": len(added), "modified": len(modified), "removed": len(removed),
        }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def recompute_status(document):
    """Work out where the document stands from its steps and signatures."""
    if document.is_terminal:
        return document.status

    steps = list(document.steps.order_by("sequence"))
    if not steps:
        status = DocumentStatus.DRAFT
    else:
        current = next((s for s in steps if s.status in OPEN_STEP_STATUSES), None)
        signed = document.signatures.exists()
        if current is None:
            if all(s.status in DONE_STEP_STATUSES for s in steps):
                has_signing = any(s.action == StepAction.SIGN for s in steps)
                status = (
                    DocumentStatus.FULLY_SIGNED if has_signing
                    else DocumentStatus.ROUTING_COMPLETED
                )
            else:  # pragma: no cover - a queued step with none open
                status = document.status
        elif current.action == StepAction.SIGN:
            if signed:
                status = DocumentStatus.PARTIALLY_SIGNED
            elif current.recipient_id == document.owner_id:
                status = DocumentStatus.AWAITING_SIGNATURE
            else:
                status = DocumentStatus.OUT_FOR_SIGNATURE
        else:
            signing_left = any(
                s.action == StepAction.SIGN and s.status not in DONE_STEP_STATUSES
                for s in steps
            )
            status = (
                DocumentStatus.PARTIALLY_SIGNED if signed and signing_left
                else DocumentStatus.ROUTED
            )

    if status != document.status:
        document.status = status
        document.save(update_fields=["status", "updated_at"])
    return status


def _activate(step, *, actor):
    """Send a step to its recipient."""
    now = timezone.now()
    step.status = StepStatus.PENDING
    step.routed_at = now
    step.save(update_fields=["status", "routed_at"])

    document = step.document
    log(
        AuditAction.ROUTED,
        actor=actor,
        document=document,
        detail=(
            f"Step {step.sequence}: {step.sender.get_display_name()} to "
            f"{step.recipient.get_display_name()} for {step.get_action_display().lower()}"
            + (f" - {step.purpose}" if step.purpose else "")
        ),
        metadata={
            "step": step.pk, "sequence": step.sequence,
            "sender": step.sender_id, "recipient": step.recipient_id,
            "action": step.action, "purpose": step.purpose,
        },
    )
    url = (
        reverse("esira:workspace", args=[document.pk])
        if step.action == StepAction.SIGN
        else reverse("esira:detail", args=[document.pk])
    )
    _notify(
        [step.recipient],
        title=(
            f"For your signature: {document.reference_no}"
            if step.action == StepAction.SIGN
            else f"For your {step.get_action_display().lower()}: {document.reference_no}"
        ),
        message=(step.purpose or document.title)[:400],
        url=url,
        action=True,
        dedupe_key=_step_key(step),
    )


def _advance(document, *, actor):
    """Send the next queued step, or finish the route when none is left."""
    next_step = (
        document.steps.filter(status=StepStatus.QUEUED)
        .select_related("sender", "recipient").order_by("sequence").first()
    )
    if next_step is not None:
        _activate(next_step, actor=actor)
        return recompute_status(document)

    status = recompute_status(document)
    if status in (DocumentStatus.FULLY_SIGNED, DocumentStatus.ROUTING_COMPLETED):
        _notify(
            [document.owner],
            title=f"Routing finished: {document.reference_no}",
            message=(
                "Every recipient has acted. Review the document and mark it completed."
            ),
            url=document.get_absolute_url(),
            action=True,
            dedupe_key=f"esira:finish:{document.pk}",
        )
    return status


def start_routing(document, user, steps):
    """
    Send a draft on its route.

    `steps` is an ordered list of {"recipient": User, "action": StepAction,
    "purpose": str, "due_date": date|None}. Everyone with a signature box must
    have a signature step, or their box would never be signed.
    """
    with transaction.atomic():
        document = _locked(document)
        if not perms.can_route(user, document):
            raise PermissionDenied("Only the owner may route a draft.")
        if not steps:
            raise WorkflowError("Add at least one recipient to the route.")

        signers_in_route = set()
        for index, item in enumerate(steps, start=1):
            recipient = item["recipient"]
            if not recipient.is_active:
                raise WorkflowError(f"Step {index}: {recipient} has no active account.")
            if item["action"] == StepAction.SIGN:
                if recipient.pk in signers_in_route:
                    raise WorkflowError(
                        f"{recipient.get_display_name()} is asked to sign twice. "
                        "One signature step signs all of their boxes."
                    )
                signers_in_route.add(recipient.pk)

        box_signers = set(
            document.boxes.filter(signature__isnull=True).values_list("signer", flat=True)
        )
        missing = box_signers - signers_in_route
        if missing:
            from accounts.models import User

            names = ", ".join(
                u.get_display_name() for u in User.objects.filter(pk__in=missing)
            )
            raise WorkflowError(
                f"There are signature boxes for {names}, but no signature step for "
                "them in the route. Add a signature step, or remove their boxes."
            )

        created = [
            RoutingStep.objects.create(
                document=document,
                sequence=index,
                sender=user,
                recipient=item["recipient"],
                action=item["action"],
                purpose=(item.get("purpose") or "")[:255],
                due_date=item.get("due_date"),
            )
            for index, item in enumerate(steps, start=1)
        ]
        document.routed_at = timezone.now()
        document.save(update_fields=["routed_at", "updated_at"])
        _activate(created[0], actor=user)
        recompute_status(document)
        return document


def mark_received(document, user):
    """The recipient has opened the document. Recorded once per step."""
    step = perms.my_open_step(user, document)
    if step is None or step.status != StepStatus.PENDING:
        return None
    with transaction.atomic():
        step = RoutingStep.objects.select_for_update().get(pk=step.pk)
        if step.status != StepStatus.PENDING:
            return None
        step.status = StepStatus.RECEIVED
        step.received_at = timezone.now()
        step.save(update_fields=["status", "received_at"])
        log(
            AuditAction.RECEIVED,
            actor=user,
            document=document,
            detail=f"Step {step.sequence}: received by {user.get_display_name()}",
            metadata={"step": step.pk},
        )
    return step


def record_view(document, user, request, *, what="document"):
    """
    Log that a user opened the document.

    At most once per document per session every ten minutes: paging through a
    PDF is one view, not forty, and a trail drowned in views hides the entries
    that matter. Opening it also counts as receipt for the recipient whose
    turn it is.
    """
    key = f"esira_viewed_{document.pk}"
    now = time.time()
    last = request.session.get(key, 0) if hasattr(request, "session") else 0
    if now - last >= VIEW_LOG_INTERVAL:
        log(AuditAction.VIEWED, actor=user, document=document,
            version=document.current_version, detail=f"Opened the {what}")
        if hasattr(request, "session"):
            request.session[key] = now
    mark_received(document, user)


def act(document, user, *, decision, remarks="", forward_to=None,
        forward_action=None, forward_purpose=""):
    """
    The recipient whose turn it is completes or rejects their step.

    `decision` is "complete" (approve, review or acknowledge, according to
    the step) or "reject". Signing is not done here - see `sign`. On
    completing, the recipient may forward the document to one more person,
    who is inserted into the route immediately after them.
    """
    if decision not in ("complete", "reject"):
        raise WorkflowError("Choose an action.")

    with transaction.atomic():
        document = _locked(document)
        step = perms.my_open_step(user, document)
        if step is None:
            raise PermissionDenied("This document is not waiting on you.")
        step = RoutingStep.objects.select_for_update().get(pk=step.pk)
        now = timezone.now()

        if decision == "reject":
            if not remarks.strip():
                raise WorkflowError("Give the reason for rejecting the document.")
            step.status = StepStatus.REJECTED
            step.acted_at = now
            step.received_at = step.received_at or now
            step.remarks = remarks.strip()
            step.save()
            document.steps.filter(status=StepStatus.QUEUED).update(status=StepStatus.CANCELLED)
            document.status = DocumentStatus.REJECTED
            document.closed_reason = remarks.strip()
            document.save(update_fields=["status", "closed_reason", "updated_at"])
            _resolve(step)
            log(
                AuditAction.REJECTED,
                actor=user,
                document=document,
                detail=f"Step {step.sequence}: {remarks.strip()}"[:500],
                metadata={"step": step.pk},
            )
            _notify(
                [document.owner],
                title=f"Rejected: {document.reference_no}",
                message=f"{user.get_display_name()}: {remarks.strip()}",
                url=document.get_absolute_url(),
                action=True,
            )
            return document

        if step.action == StepAction.SIGN:
            raise WorkflowError(
                "This step asks for your signature. Open the signing workspace to sign."
            )

        step.status = COMPLETION_STATUS[step.action]
        step.acted_at = now
        step.received_at = step.received_at or now
        step.remarks = remarks.strip()
        step.save()
        _resolve(step)
        log(
            {
                StepAction.APPROVE: AuditAction.APPROVED,
                StepAction.REVIEW: AuditAction.REVIEWED,
                StepAction.ACKNOWLEDGE: AuditAction.ACKNOWLEDGED,
            }[step.action],
            actor=user,
            document=document,
            detail=(
                f"Step {step.sequence}: {step.get_status_display().lower()} by "
                f"{user.get_display_name()}"
                + (f" - {remarks.strip()}" if remarks.strip() else "")
            )[:500],
            metadata={"step": step.pk},
        )

        if forward_to is not None:
            _insert_after(document, step, sender=user, recipient=forward_to,
                          action=forward_action or StepAction.APPROVE,
                          purpose=forward_purpose)

        _advance(document, actor=user)
        return document


def _insert_after(document, step, *, sender, recipient, action, purpose):
    if not recipient.is_active:
        raise WorkflowError(f"{recipient} has no active account.")
    if action == StepAction.SIGN and document.steps.filter(
        recipient=recipient, action=StepAction.SIGN,
    ).exclude(status=StepStatus.CANCELLED).exists():
        raise WorkflowError(f"{recipient.get_display_name()} already has a signature step.")
    later = document.steps.filter(sequence__gt=step.sequence).order_by("-sequence")
    for other in later:
        other.sequence += 1
        other.save(update_fields=["sequence"])
    new_step = RoutingStep.objects.create(
        document=document,
        sequence=step.sequence + 1,
        sender=sender,
        recipient=recipient,
        action=action,
        purpose=(purpose or "")[:255],
    )
    log(
        AuditAction.FORWARDED,
        actor=sender,
        document=document,
        detail=(
            f"Forwarded to {recipient.get_display_name()} for "
            f"{new_step.get_action_display().lower()}"
            + (f" - {purpose}" if purpose else "")
        )[:500],
        metadata={"step": new_step.pk, "after": step.pk},
    )
    return new_step


def complete(document, user):
    with transaction.atomic():
        document = _locked(document)
        if not perms.can_complete(user, document):
            raise PermissionDenied("This document cannot be completed now.")
        document.status = DocumentStatus.COMPLETED
        document.completed_at = timezone.now()
        document.completed_by = user
        document.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
        from notifications.service import resolve

        resolve(f"esira:finish:{document.pk}")
        log(
            AuditAction.COMPLETED,
            actor=user,
            document=document,
            version=document.current_version,
            detail=(
                f"Closed with {document.signatures.count()} signature(s); "
                f"final version v{document.current_version.number}"
            ),
        )
        participants = {s.recipient for s in document.steps.select_related("recipient")}
        _notify(
            participants,
            title=f"Completed: {document.reference_no}",
            message=document.title[:400],
            url=document.get_absolute_url(),
        )
        return document


def cancel(document, user, reason):
    with transaction.atomic():
        document = _locked(document)
        if not perms.can_cancel(user, document):
            raise PermissionDenied("You may not cancel this document.")
        if not reason.strip():
            raise WorkflowError("Give the reason for cancelling.")
        open_steps = list(
            document.steps.filter(status__in=list(OPEN_STEP_STATUSES)).select_related("recipient")
        )
        document.steps.filter(
            status__in=[StepStatus.QUEUED, *OPEN_STEP_STATUSES]
        ).update(status=StepStatus.CANCELLED)
        for step in open_steps:
            _resolve(step)
        document.status = DocumentStatus.CANCELLED
        document.closed_reason = reason.strip()
        document.save(update_fields=["status", "closed_reason", "updated_at"])
        log(
            AuditAction.CANCELLED,
            actor=user,
            document=document,
            detail=reason.strip()[:500],
        )
        _notify(
            [s.recipient for s in open_steps],
            title=f"Cancelled: {document.reference_no}",
            message=f"No action is needed any more. {reason.strip()}"[:400],
            url=document.get_absolute_url(),
        )
        return document


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def authorise_certificate(user, opened):
    """
    Decide whether the certificate that has just proved possession of its key
    may sign for this user. Returns (SigningCertificate, ChainResult).

    It must be registered to this account, verified by an administrator, in
    date, issued for signing, and - outside development mode - chain to an
    installed DICT PNPKI root.
    """
    from .signing.certificates import (
        check_chain,
        fingerprint,
        permits_signing,
        untrusted_allowed,
    )

    certificate = opened.certificate
    record = SigningCertificate.objects.filter(
        user=user, fingerprint_sha256=fingerprint(certificate),
    ).first()
    if record is None:
        raise WorkflowError(
            "This certificate is not registered to your account. Register it "
            "under e-SIRA > My Certificates and wait for it to be verified."
        )
    if record.status != SigningCertificate.Status.VERIFIED:
        raise WorkflowError(
            f"This certificate is {record.get_status_display().lower()} and may not sign."
        )
    now = timezone.now()
    if not (certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc):
        raise WorkflowError("This certificate is expired or not yet valid.")
    if not permits_signing(certificate):
        raise WorkflowError("This certificate is not issued for signing documents.")

    chain = check_chain(certificate, opened.chain)
    if not chain.trusted and not untrusted_allowed():
        raise WorkflowError(chain.note)
    return record, chain


def sign(document, user, *, credentials, reason="", remarks="", style=""):
    """
    Apply this user's digital signature to every one of their unsigned boxes.

    The whole operation - the signature, the new version, the step and the
    route - commits together or not at all. `style` is a signature style key
    (see `signature_styles`); empty uses the one last signed with.
    """
    from .signing import (
        CredentialError,
        Placement,
        SignatureRequest,
        SigningError,
        get_backend,
    )

    backend = get_backend()
    if not backend.is_available():
        raise WorkflowError(backend.unavailable_reason())

    def refuse(message, action=AuditAction.SIGN_FAILED, version=None):
        # Raised, not logged: the transaction below is about to roll back, and
        # an entry written inside it would roll back with it. The refusal is
        # recorded once the rollback is done - see the handler at the end.
        raise _Refusal(message, action=action, version=version)

    opened = None
    try:
        with transaction.atomic():
            document = _locked(document)
            if not perms.can_sign(user, document):
                raise PermissionDenied("This document is not waiting for your signature.")

            boxes = list(
                document.boxes.filter(signer=user, signature__isnull=True)
                .order_by("page", "y", "x", "pk")
            )
            if not boxes:
                raise WorkflowError(
                    "Place at least one signature box for yourself before signing."
                )

            step = perms.my_open_step(user, document)
            self_signing = step is None
            if self_signing:
                # An owner signing their own draft. The step is created inside
                # this transaction, so a refused signature leaves no trace of it.
                now = timezone.now()
                step = RoutingStep.objects.create(
                    document=document, sequence=1, sender=user, recipient=user,
                    action=StepAction.SIGN, purpose="Signed by the owner",
                    status=StepStatus.RECEIVED, routed_at=now, received_at=now,
                )
                document.routed_at = now
                document.save(update_fields=["routed_at", "updated_at"])

            try:
                opened = backend.open(_resolve_credentials(user, credentials))
            except CredentialError as exc:
                refuse(str(exc))

            try:
                certificate_record, chain = authorise_certificate(user, opened)
            except WorkflowError as exc:
                refuse(str(exc))

            source = document.current_version
            try:
                data = source.read_verified()
            except FileIntegrityError:
                refuse(
                    "The stored document no longer matches the version that was "
                    "recorded, so it cannot be signed. Report this to the system "
                    "administrator.",
                    action=AuditAction.INTEGRITY_FAILURE,
                    version=source,
                )
            geometry = inspect_pdf(data).pages

            placements = []
            for box in boxes:
                box.field_name = f"eSIRA-{document.pk}-{box.pk}"
                placements.append(Placement(
                    page_index=box.page - 1,
                    rect=box_to_pdf_rect(
                        geometry[box.page - 1], box.x, box.y, box.width, box.height,
                    ),
                    field_name=box.field_name,
                ))

            try:
                style_key, appearance, picture = resolve_style(user, style)
            except WorkflowError as exc:
                refuse(str(exc))

            reason = (reason or step.purpose or f"{step.get_action_display()} - {document.title}")[:255]
            try:
                signed = backend.sign(opened, SignatureRequest(
                    pdf_bytes=data,
                    placements=tuple(placements),
                    reason=reason,
                    location=getattr(settings, "ESIRA_SIGNATURE_LOCATION", ""),
                    contact_info=user.email or "",
                    appearance=appearance,
                    appearance_image=picture,
                ))
            except SigningError as exc:
                refuse(str(exc))

            _confirm_signatures(signed, [p.field_name for p in placements])

            version = _store_version(
                document, signed, kind=DocumentVersion.Kind.SIGNED, user=user,
                note=f"Signed by {user.get_display_name()}",
            )
            from .signing.certificates import describe

            details = describe(opened.certificate)
            signature = DigitalSignature.objects.create(
                document=document,
                step=step,
                signer=user,
                source_version=source,
                result_version=version,
                certificate=certificate_record,
                backend=backend.key,
                certificate_subject=details["subject"],
                certificate_issuer=details["issuer"],
                certificate_serial=details["serial_number"],
                certificate_fingerprint=details["fingerprint_sha256"],
                certificate_not_after=details["not_after"],
                chain_trusted=chain.trusted,
                trust_note=chain.note[:500],
                reason=reason,
                location=getattr(settings, "ESIRA_SIGNATURE_LOCATION", "")[:255],
                field_names=[p.field_name for p in placements],
                timestamped=bool(getattr(settings, "ESIRA_TSA_URL", "")),
            )
            for box in boxes:
                box.signature = signature
                box.save(update_fields=["signature", "field_name", "updated_at"])

            SignerProfile.objects.filter(user=user).update(preferred_style=style_key)

            step.status = StepStatus.SIGNED
            step.acted_at = timezone.now()
            step.received_at = step.received_at or step.acted_at
            step.remarks = (remarks or "").strip()
            step.save()
            _resolve(step)

            log(
                AuditAction.SIGNED,
                actor=user,
                document=document,
                version=version,
                detail=(
                    f"{len(boxes)} signature{'s' if len(boxes) != 1 else ''} on "
                    f"{_pages_label(b.page for b in boxes)} with certificate "
                    f"{details['subject_common_name'] or details['subject']} "
                    f"(serial {details['serial_number']})"
                    + ("" if chain.trusted else " - NOT PNPKI-verified")
                ),
                metadata={
                    "signature": signature.pk,
                    "certificate_fingerprint": details["fingerprint_sha256"],
                    "issuer": details["issuer"],
                    "chain_trusted": chain.trusted,
                    "fields": signature.field_names,
                    "source_version": source.number,
                    "result_version": version.number,
                    "sha256": version.sha256,
                    "self_signed_draft": self_signing,
                },
            )
            _advance(document, actor=user)
            return signature
    except _Refusal as refusal:
        log(refusal.action, actor=user, document=document,
            version=refusal.version, detail=str(refusal)[:500])
        raise WorkflowError(str(refusal))
    finally:
        backend.close(opened)


def _resolve_credentials(user, credentials):
    """
    The .p12 bytes and passphrase to open, from the request or the store.

    `{"stored": True}` signs with the certificate the user keeps on file. When
    their profile requires the password, it must come with the request; the
    stored copy is used only when it does not.
    """
    from .signing import CredentialError
    from .signing.vault import unseal

    if not credentials.get("stored"):
        return credentials
    record = stored_certificate(user, usable_only=True)
    if record is None:
        raise CredentialError(
            "You have no verified certificate file on file. Upload your .p12 "
            "on the My Certificates page, or select it here."
        )
    typed = credentials.get("passphrase") or ""
    if SignerProfile.for_user(user).require_passphrase:
        if not typed:
            raise CredentialError("Enter your certificate password to sign.")
        passphrase = typed
    else:
        passphrase = typed or unseal(record.passphrase_sealed).decode("utf-8")
    return {"pkcs12": unseal(record.pkcs12_sealed), "passphrase": passphrase}


def _read_image(field):
    try:
        with field.open("rb") as handle:
            return handle.read()
    except (FileNotFoundError, OSError, ValueError):
        return b""


def signature_styles(user):
    """
    The styles this user may sign with, in display order, as dicts with
    `key`, `name`, `kind` ("description", "graphic", "image"), `built_in`
    and, for custom styles, the `style` row.
    """
    profile = SignerProfile.for_user(user)
    styles = [{
        "key": SignatureStyle.DESCRIPTION,
        "name": SignatureStyle.BUILT_IN[SignatureStyle.DESCRIPTION],
        "kind": "description", "built_in": True,
    }]
    if profile.signature_image:
        styles.append({
            "key": SignatureStyle.GRAPHIC,
            "name": SignatureStyle.BUILT_IN[SignatureStyle.GRAPHIC],
            "kind": "graphic", "built_in": True,
        })
    for row in user.esira_signature_styles.all():
        styles.append({
            "key": row.key, "name": row.name, "kind": "image",
            "built_in": False, "style": row,
        })
    return styles


def default_style_key(user):
    keys = [s["key"] for s in signature_styles(user)]
    preferred = SignerProfile.for_user(user).preferred_style
    if preferred in keys:
        return preferred
    if SignatureStyle.GRAPHIC in keys:
        return SignatureStyle.GRAPHIC
    return SignatureStyle.DESCRIPTION


def resolve_style(user, key=""):
    """(key, appearance, picture bytes) for a style key, or WorkflowError."""
    key = key or default_style_key(user)
    if key == SignatureStyle.DESCRIPTION:
        return key, "description", b""
    if key == SignatureStyle.GRAPHIC:
        profile = SignerProfile.for_user(user)
        picture = _read_image(profile.signature_image) if profile.signature_image else b""
        if not picture:
            raise WorkflowError(
                "Signature and Description needs a signature image. Upload one "
                "on the My Digital Certificate page, or choose another style."
            )
        return key, "graphic", picture
    if key.startswith("custom:") and key[7:].isdigit():
        row = user.esira_signature_styles.filter(pk=int(key[7:])).first()
        if row is not None:
            picture = _read_image(row.image)
            if picture:
                return key, "image", picture
    raise WorkflowError("That signature style is not available. Choose another.")


class _Refusal(WorkflowError):
    """A refused signing attempt, to be logged after the rollback."""

    def __init__(self, message, *, action, version=None):
        super().__init__(message)
        self.action = action
        self.version = version


def _confirm_signatures(pdf_bytes, field_names):
    """Refuse to store output that does not carry every signature asked for."""
    from pyhanko.pdf_utils.reader import PdfFileReader

    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        present = {s.field_name for s in reader.embedded_signatures}
    except Exception:
        present = set()
    missing = [name for name in field_names if name not in present]
    if missing:
        raise WorkflowError(
            "The signed document did not contain every signature it should. "
            "Nothing was saved."
        )


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


def register_certificate(user, *, certificate_file=None, pkcs12_file=None, passphrase=""):
    """
    Register a PNPKI certificate to the user's account, awaiting verification.

    From a .p12/.pfx, the file is opened to prove the passphrase is right, then
    kept with that passphrase - both encrypted - so the user can sign without
    presenting them again. Uploading the file of a certificate already
    registered to this user replaces what is stored for it.

    Sets `created` on the returned record: False when an existing registration
    only had its stored file replaced.
    """
    from .signing.certificates import (
        CertificateRejected,
        CredentialError,
        certificate_from_pkcs12,
        check_chain,
        describe,
        load_certificate,
        permits_signing,
        to_pem,
    )

    intermediates = []
    pkcs12_data = None
    try:
        if pkcs12_file is not None:
            pkcs12_data = pkcs12_file.read()
            certificate, intermediates = certificate_from_pkcs12(pkcs12_data, passphrase)
        elif certificate_file is not None:
            certificate = load_certificate(certificate_file.read())
        else:
            raise WorkflowError("Choose a certificate file.")
    except (CertificateRejected, CredentialError) as exc:
        raise WorkflowError(str(exc))

    details = describe(certificate)
    if details["not_after"] <= timezone.now():
        raise WorkflowError("This certificate has expired. Register a current one.")
    if not permits_signing(certificate):
        raise WorkflowError("This certificate is not issued for signing documents.")

    existing = SigningCertificate.objects.filter(
        fingerprint_sha256=details["fingerprint_sha256"]
    ).first()
    if existing is not None:
        if existing.user_id == user.pk:
            if pkcs12_data is None:
                raise WorkflowError("This certificate is already registered to your account.")
            _store_pkcs12(existing, pkcs12_data, passphrase, pkcs12_file, user)
            existing.created = False
            return existing
        log(AuditAction.CERT_REGISTERED, actor=user,
            detail="Refused: certificate already registered to another account",
            metadata={"fingerprint": details["fingerprint_sha256"]})
        raise WorkflowError(
            "This certificate is registered to another account. Contact the "
            "system administrator."
        )

    chain = check_chain(certificate, intermediates)
    record = SigningCertificate.objects.create(
        user=user,
        certificate_pem=to_pem(certificate),
        chain_trusted=chain.trusted,
        chain_note=chain.note[:500],
        **details,
    )
    record.created = True
    if pkcs12_data is not None:
        _store_pkcs12(record, pkcs12_data, passphrase, pkcs12_file, user)
    log(
        AuditAction.CERT_REGISTERED,
        actor=user,
        detail=(
            f"{record.subject_common_name or record.subject} issued by "
            f"{record.issuer} (serial {record.serial_number})"
        )[:500],
        metadata={"certificate": record.pk, "fingerprint": record.fingerprint_sha256,
                  "chain_trusted": chain.trusted},
    )
    from accounts.capabilities import users_with

    _notify(
        users_with("can_verify_signing_certificates").exclude(pk=user.pk),
        title="PNPKI certificate awaiting verification",
        message=f"{user.get_display_name()} registered {record.subject_common_name or 'a certificate'}.",
        url=reverse("esira:certificate_review"),
        action=True,
        dedupe_key=f"esira:cert:{record.pk}",
    )
    return record


def review_certificate(record, reviewer, *, decision, remarks=""):
    """Verify, reject or revoke a registered certificate."""
    from notifications.service import resolve

    from .signing.certificates import check_chain, load_certificate

    if not reviewer.can_verify_signing_certificates:
        raise PermissionDenied("Your role does not permit verifying certificates.")
    if record.user_id == reviewer.pk and not reviewer.is_superuser:
        raise PermissionDenied(
            "You may not verify your own certificate. Another administrator must."
        )

    with transaction.atomic():
        record = SigningCertificate.objects.select_for_update().get(pk=record.pk)
        Status = SigningCertificate.Status
        if decision == "verify":
            if record.status != Status.PENDING:
                raise WorkflowError("Only a certificate awaiting verification can be verified.")
            if record.is_expired:
                raise WorkflowError("This certificate has expired.")
            chain = check_chain(load_certificate(record.certificate_pem.encode()))
            record.chain_trusted, record.chain_note = chain.trusted, chain.note[:500]
            record.status, action = Status.VERIFIED, AuditAction.CERT_VERIFIED
        elif decision == "reject":
            if record.status != Status.PENDING:
                raise WorkflowError("Only a certificate awaiting verification can be rejected.")
            if not remarks.strip():
                raise WorkflowError("Give the reason for rejecting the certificate.")
            record.status, action = Status.REJECTED, AuditAction.CERT_REJECTED
        elif decision == "revoke":
            if record.status != Status.VERIFIED:
                raise WorkflowError("Only a verified certificate can be revoked.")
            if not remarks.strip():
                raise WorkflowError("Give the reason for revoking the certificate.")
            record.status, action = Status.REVOKED, AuditAction.CERT_REVOKED
        else:
            raise WorkflowError("Choose an action.")

        record.reviewed_by = reviewer
        record.reviewed_at = timezone.now()
        record.review_remarks = remarks.strip()[:500]
        record.save()
        resolve(f"esira:cert:{record.pk}")
        log(
            action,
            actor=reviewer,
            detail=(
                f"{record.user.get_display_name()}: {record.subject_common_name or record.subject}"
                + (f" - {remarks.strip()}" if remarks.strip() else "")
            )[:500],
            metadata={"certificate": record.pk, "fingerprint": record.fingerprint_sha256,
                      "user": record.user_id},
        )
        _notify(
            [record.user],
            title=f"Your PNPKI certificate was {record.get_status_display().lower()}",
            message=(remarks.strip() or record.subject_common_name)[:400],
            url=reverse("esira:certificates"),
        )
        return record


def _store_pkcs12(record, data, passphrase, upload, user):
    from .signing.vault import seal

    record.pkcs12_sealed = seal(data)
    record.passphrase_sealed = seal(passphrase)
    record.pkcs12_filename = (getattr(upload, "name", "") or "certificate.p12")[:255]
    record.stored_at = timezone.now()
    record.save(update_fields=[
        "pkcs12_sealed", "passphrase_sealed", "pkcs12_filename", "stored_at",
    ])
    log(
        AuditAction.CERT_STORED,
        actor=user,
        detail=(f"{record.pkcs12_filename} stored (encrypted) for "
                f"{record.subject_common_name or record.subject}")[:500],
        metadata={"certificate": record.pk, "fingerprint": record.fingerprint_sha256},
    )


# ---------------------------------------------------------------------------
# The signer's stored certificate and signing settings
# ---------------------------------------------------------------------------


def stored_certificate(user, *, usable_only=False):
    """The newest certificate whose .p12 this user keeps on file, if any."""
    records = (
        user.esira_certificates
        .filter(pkcs12_sealed__isnull=False, passphrase_sealed__isnull=False)
        .exclude(status__in=[SigningCertificate.Status.REJECTED,
                             SigningCertificate.Status.REVOKED])
        .order_by("-stored_at", "-submitted_at")
    )
    for record in records:
        if not record.has_stored_credential:
            continue
        if usable_only and not record.is_usable:
            continue
        return record
    return None


def remove_stored_certificate(user, record):
    """Delete the stored .p12 and password. The registration itself stays."""
    if record.user_id != user.pk:
        raise PermissionDenied("This is not your certificate.")
    record.pkcs12_sealed = None
    record.passphrase_sealed = None
    record.pkcs12_filename = ""
    record.stored_at = None
    record.save(update_fields=[
        "pkcs12_sealed", "passphrase_sealed", "pkcs12_filename", "stored_at",
    ])
    log(
        AuditAction.CERT_REMOVED,
        actor=user,
        detail=f"Stored file removed for {record.subject_common_name or record.subject}"[:500],
        metadata={"certificate": record.pk, "fingerprint": record.fingerprint_sha256},
    )


def reveal_passphrase(user):
    """The stored certificate password, for its owner only. Always logged."""
    from .signing import CredentialError
    from .signing.vault import unseal

    record = stored_certificate(user)
    if record is None:
        raise WorkflowError("You have no certificate file on file.")
    try:
        passphrase = unseal(record.passphrase_sealed).decode("utf-8")
    except CredentialError as exc:
        raise WorkflowError(str(exc))
    log(
        AuditAction.CERT_PASSWORD_VIEWED,
        actor=user,
        detail=f"Password shown for {record.subject_common_name or record.subject}"[:500],
        metadata={"certificate": record.pk},
    )
    return passphrase


def set_require_passphrase(user, required):
    profile = SignerProfile.for_user(user)
    required = bool(required)
    if profile.require_passphrase == required:
        return profile
    profile.require_passphrase = required
    profile.save(update_fields=["require_passphrase", "updated_at"])
    log(
        AuditAction.SIGNING_SETTINGS,
        actor=user,
        detail=("Certificate password now required when signing" if required
                else "Certificate password no longer required when signing"),
        metadata={"require_passphrase": required},
    )
    return profile


def set_signature_image(user, content):
    """Store `content` (a processed PNG ContentFile), or remove it when None."""
    profile = SignerProfile.for_user(user)
    previous = profile.signature_image.name if profile.signature_image else ""
    if content is None:
        if not previous:
            return profile
        profile.signature_image = ""
    else:
        profile.signature_image.save(content.name, content, save=False)
    profile.save(update_fields=["signature_image", "updated_at"])
    if previous:
        profile.signature_image.storage.delete(previous)
    log(
        AuditAction.SIGNING_SETTINGS,
        actor=user,
        detail="Signature image removed" if content is None else "Signature image updated",
    )
    return profile


def add_signature_style(user, *, name, content):
    """Save a custom style. `content` is a PNG from process_signature_image."""
    if user.esira_signature_styles.count() >= SignatureStyle.MAX_PER_USER:
        raise WorkflowError(
            f"You can keep up to {SignatureStyle.MAX_PER_USER} custom styles. "
            "Delete one first."
        )
    row = SignatureStyle(user=user, name=name.strip()[:80])
    row.image.save(content.name, content, save=False)
    row.save()
    log(AuditAction.SIGNING_SETTINGS, actor=user,
        detail=f"Signature style added: {row.name}"[:500],
        metadata={"style": row.pk})
    return row


def delete_signature_style(user, row):
    if row.user_id != user.pk:
        raise PermissionDenied("This is not your signature style.")
    name, image = row.name, row.image.name
    storage = row.image.storage
    row.delete()
    if image:
        storage.delete(image)
    log(AuditAction.SIGNING_SETTINGS, actor=user,
        detail=f"Signature style deleted: {name}"[:500])
