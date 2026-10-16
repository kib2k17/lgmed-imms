"""
Supporting documents: uploading and screening, arranging photographs,
review, re-screening, removal and the internal download.

Part of programs.views - see its package docstring.
"""

import mimetypes

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView
from django.views.generic.edit import FormView

from audit.models import Action
from audit.recording import record as record_audit
from core.files import send_fieldfile
from core.mixins import CanEncodePPAMixin, CanReviewPPAMixin
from ..forms import (
    DocumentAuthorityForm,
    DocumentDecisionForm,
    PhotoOrderForm,
    SupportingDocumentForm,
)
from ..models import DocumentStatus, RiskLevel, SupportingDocument

from .common import PPAContextMixin, level_of, level_spec, record_breadcrumbs, record_url


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentUploadView(CanEncodePPAMixin, PPAContextMixin, CreateView):
    """
    Attach one file, or a set of photographs, to a record.

    Every file is written to the protected directory and screened immediately,
    so the person who uploaded it sees the result while they still remember
    what is in it. Each is screened again on submission, against whatever the
    rules are by then.

    A batch is not a shortcut around any of that. Thirty photographs become
    thirty rows, thirty screenings and thirty review decisions; what the batch
    saves is the encoder filling in the same form thirty times, and the page
    reports the worst result it found so a flagged picture cannot hide inside
    a good-news message about the other twenty-nine.
    """

    template_name = "dashboard/ppa/document_upload.html"
    form_class = SupportingDocumentForm
    model = SupportingDocument

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.level = kwargs["level"]
        self.spec = level_spec(self.level)
        self.record = get_object_or_404(self.spec["model"], pk=kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["record"] = self.record
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Upload supporting documents",
            "page_subtitle": f"{self.spec['label']}: {self.record.title}",
            "breadcrumbs": record_breadcrumbs(self.record, "Upload documents"),
            "submit_label": "Upload and screen",
            "cancel_url": record_url(self.record),
            "list_url": reverse("programs:list"),
            "record": self.record,
            "level": self.level,
            "photograph_count": self.record.documents.photographs().count(),
            "arrange_url": reverse(
                "programs:photo_arrange", args=[self.level, self.record.pk]
            ),
            "form_note": (
                "Files are stored internally and are not published by "
                "uploading them. Each is screened for personal and "
                "confidential information, and a reviewer decides what happens "
                "next. Several photographs can be selected at once - the order "
                "you arrange them in below is the order the public gallery "
                "uses."
            ),
        })
        return context

    def form_valid(self, form):
        from .. import screening

        # The owner was attached to each document by the form, before
        # validation - see SupportingDocumentForm.documents().
        documents = form.documents()
        worst = RiskLevel.LOW
        severity = {RiskLevel.LOW: 0, RiskLevel.REVIEW_REQUIRED: 1, RiskLevel.HIGH: 2}

        for document in documents:
            document.uploaded_by = self.request.user
            document.save()

            record_audit(
                Action.UPLOAD, target=document, request=self.request,
                detail=f"Uploaded against {self.record.level_label.lower()} "
                       f"'{self.record.title}'.",
            )

            screening.screen_document(document)
            record_audit(
                Action.SCREEN, target=document, request=self.request,
                detail=f"Automated screening: {document.get_risk_level_display()}, "
                       f"{document.finding_count} finding(s).",
            )
            if severity[document.risk_level] > severity[worst]:
                worst = document.risk_level

        self.object = documents[-1]
        self.report(documents, worst)

        # One file still lands on its own review screen, because that is where
        # the person who uploaded it needs to be. A batch goes back to the
        # record, where the whole set is listed with its screening results -
        # sending them to the last picture's review page would hide the other
        # twenty-nine behind a back button.
        if len(documents) == 1:
            return redirect(
                reverse("programs:document_review", args=[documents[0].pk])
            )
        if any(document.is_image for document in documents):
            return redirect(
                reverse("programs:photo_arrange", args=[self.level, self.record.pk])
            )
        return redirect(record_url(self.record))

    def report(self, documents, worst):
        """Say what was stored, leading with the worst screening result."""
        total = len(documents)
        if total == 1:
            subject = f"'{documents[0].title}'"
            verb = "was"
        else:
            subject = f"{total} files"
            verb = "were"

        if worst == RiskLevel.HIGH:
            flagged = sum(1 for d in documents if d.risk_level == RiskLevel.HIGH)
            messages.error(
                self.request,
                f"{subject} {verb} stored internally. The screening flagged "
                f"{'it' if total == 1 else f'{flagged} of them'} as HIGH RISK "
                f"- {'it' if total == 1 and flagged == 1 else 'they'} cannot be "
                "published until a reviewer reads "
                f"{'it' if total == 1 and flagged == 1 else 'them'} and says "
                "otherwise.",
            )
        elif worst == RiskLevel.REVIEW_REQUIRED:
            messages.warning(
                self.request,
                f"{subject} {verb} stored internally. The screening found "
                "something a reviewer needs to look at.",
            )
        else:
            messages.success(
                self.request,
                f"{subject} {verb} stored internally. The screening found "
                "nothing obvious, which is not the same as the files being "
                "safe - a reviewer still has to clear them.",
            )


class PhotoArrangeView(CanEncodePPAMixin, PPAContextMixin, FormView):
    """
    Put one record's photographs in the order the public will see them.

    A gallery whose order nobody chose is a gallery in upload order, and
    upload order is whatever a camera named its files that morning. This page
    is where somebody decides that the opening shot comes first and the group
    photograph comes last - before publication, and afterwards without
    republishing anything, because the order lives on the row rather than in
    the copy served to the public.

    It moves pictures and nothing else. No status changes here, no approvals,
    no publishing: rearranging a gallery is an editorial act, not a release
    decision, and the two must not share a button.
    """

    template_name = "dashboard/ppa/photo_arrange.html"
    form_class = PhotoOrderForm

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.level = kwargs["level"]
        self.spec = level_spec(self.level)
        self.record = get_object_or_404(self.spec["model"], pk=kwargs["pk"])

    def photographs(self):
        return list(
            self.record.documents.photographs().select_related("uploaded_by")
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["photographs"] = self.photographs()
        return kwargs

    def get_initial(self):
        """
        The hidden field starts out holding the order already on the record.

        So the page submitted without JavaScript saves the order it was shown,
        which is a no-op, rather than failing validation on an empty field and
        telling somebody their photographs had changed underneath them.
        """
        initial = super().get_initial()
        initial["order"] = ",".join(
            str(photograph.pk) for photograph in self.photographs()
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        photographs = self.photographs()
        context.update({
            "page_title": "Arrange photographs",
            "page_subtitle": f"{self.spec['label']}: {self.record.title}",
            "breadcrumbs": record_breadcrumbs(self.record, "Arrange photographs"),
            "record": self.record,
            "level": self.level,
            "photographs": photographs,
            "published_count": sum(
                1 for photograph in photographs
                if photograph.status == DocumentStatus.PUBLISHED
            ),
            "cancel_url": record_url(self.record),
            "upload_url": reverse(
                "programs:document_upload", args=[self.level, self.record.pk]
            ),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        order = form.cleaned_data["order"]
        by_pk = {photograph.pk: photograph for photograph in self.photographs()}

        moved = []
        for position, pk in enumerate(order, start=1):
            photograph = by_pk[pk]
            if photograph.display_order != position:
                photograph.display_order = position
                moved.append(photograph)

        if moved:
            SupportingDocument.objects.bulk_update(moved, ["display_order"])
            record_audit(
                Action.UPDATE, target=self.record, request=self.request,
                detail=f"Reordered the gallery: {len(moved)} photograph(s) moved.",
            )
            messages.success(
                self.request,
                f"The gallery order was saved. {len(moved)} photograph"
                f"{'' if len(moved) == 1 else 's'} moved.",
            )
        else:
            messages.info(self.request, "The photographs were already in that order.")
        return redirect(
            reverse("programs:photo_arrange", args=[self.level, self.record.pk])
        )

    def form_invalid(self, form):
        for error in form.errors.get("order", []):
            messages.error(self.request, error)
        return redirect(
            reverse("programs:photo_arrange", args=[self.level, self.record.pk])
        )


class DocumentReviewView(LoginRequiredMixin, PPAContextMixin, DetailView):
    """
    The dedicated review screen for one file.

    Shows what the file is, what it is attached to, who uploaded it and when,
    what the screening found, and what the scanner could not do - then offers
    the decision. Everything a reviewer needs is on this page so that the
    decision is never taken from a list view where only the risk badge is
    visible.
    """

    template_name = "dashboard/ppa/document_review.html"
    context_object_name = "document"
    model = SupportingDocument

    def get_queryset(self):
        return SupportingDocument.objects.select_related(
            "program", "project", "sub_project", "activity",
            "uploaded_by", "reviewed_by", "published_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.object
        owner = document.owner
        context.update({
            "page_title": "Document Review",
            "page_subtitle": document.title,
            "breadcrumbs": record_breadcrumbs(owner, "Document review") if owner else [],
            "record": owner,
            "record_level": level_of(owner) if owner else None,
            "findings": document.screening_findings or [],
            "high_findings": [
                f for f in (document.screening_findings or []) if f["severity"] == "HIGH"
            ],
            "decision_form": kwargs.get("decision_form")
            or DocumentDecisionForm(document=document),
            "authority_form": DocumentAuthorityForm(
                initial={"authority": document.authority_id}
            ),
            "can_review": self.request.user.can_review_ppa,
            "can_publish": self.request.user.can_publish_ppa,
            "can_encode": self.request.user.can_encode_ppa,
        })
        return context

    def post(self, request, *args, **kwargs):
        """The decision itself. Reviewers only, re-checked here."""
        if not request.user.can_review_ppa:
            raise PermissionDenied("Your role does not permit reviewing documents.")

        self.object = self.get_object()
        document = self.object
        form = DocumentDecisionForm(request.POST, document=document)
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(decision_form=form)
            )

        decision = form.cleaned_data["decision"]
        comments = form.cleaned_data["comments"]
        acknowledged = form.cleaned_data.get("acknowledge_risk")
        authority = form.cleaned_data.get("authority")

        if authority is not None and authority != document.authority:
            document.authority = authority
            record_audit(
                Action.UPDATE, target=document, request=request,
                detail=f"Publication authority set to {authority.reference}.",
            )

        if decision == "approve":
            document.approve(request.user, comments)
            record_audit(
                Action.APPROVE, target=document, request=request,
                detail=(
                    f"Approved for publication. Screening said "
                    f"{document.get_risk_level_display()}"
                    + ("; reviewer confirmed they read the file in full." if acknowledged else "")
                )[:255],
            )
            if document.authority_id:
                messages.success(
                    request,
                    f"'{document.title}' was approved under "
                    f"{document.authority.reference}. It becomes public when "
                    "the record it belongs to is published.",
                )
            else:
                messages.warning(
                    request,
                    f"'{document.title}' was approved, but no memorandum "
                    "authorising its release has been recorded - so it will "
                    "not be published until one is.",
                )
        elif decision == "revise":
            document.request_revision(request.user, comments)
            record_audit(Action.REQUEST_REVISION, target=document,
                         request=request, detail=comments[:255])
            messages.info(request, f"A revision of '{document.title}' was requested.")
        else:
            document.reject(request.user, comments)
            record_audit(Action.REJECT, target=document, request=request,
                         detail=comments[:255])
            messages.info(
                request,
                f"'{document.title}' was rejected. It stays in the internal "
                "record and will not be published.",
            )

        owner = document.owner
        return redirect(record_url(owner) if owner else reverse("programs:list"))


class DocumentRescreenView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """Run the screening again - after the rules change, or a re-upload."""

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        from .. import screening

        document = self.get_object()
        screening.screen_document(document)
        record_audit(
            Action.SCREEN, target=document, request=request,
            detail=f"Re-screened: {document.get_risk_level_display()}, "
                   f"{document.finding_count} finding(s).",
        )
        messages.info(
            request,
            f"'{document.title}' was screened again: "
            f"{document.get_risk_level_display()}.",
        )
        return redirect(reverse("programs:document_review", args=[document.pk]))


class DocumentDeleteView(CanEncodePPAMixin, PPAContextMixin, DeleteView):
    template_name = "dashboard/module_confirm_delete.html"
    context_object_name = "record"
    model = SupportingDocument

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Delete document",
            "page_subtitle": self.object.title,
            "list_url": reverse("programs:list"),
        })
        return context

    def dispatch(self, request, *args, **kwargs):
        """
        Deleting is for a file uploaded by mistake, not for taking one down.

        A published file is withdrawn by unpublishing the record it belongs
        to, which is an administrator's decision and leaves a trail that says
        so. Allowing an encoder to reach the same outcome by deleting the row
        would route a publication decision around the person who holds it.
        """
        if request.method == "POST" or request.method == "GET":
            document = self.get_object()
            if document.status == DocumentStatus.PUBLISHED:
                if not request.user.is_authenticated or not request.user.can_publish_ppa:
                    raise PermissionDenied(
                        "This file is on the public website. It must be "
                        "withdrawn by an administrator before it can be deleted."
                    )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        document = self.get_object()
        owner = document.owner
        document._delete_public_copy()
        record_audit(
            Action.DELETE, target=document, request=self.request,
            detail=f"Internal file deleted from {document.owner_label}.",
        )
        messages.success(self.request, f"'{document.title}' was deleted.")
        self.success_url = record_url(owner) if owner else reverse("programs:list")
        return super().form_valid(form)


class DocumentDownloadView(LoginRequiredMixin, DetailView):
    """
    Serve an internal document to a signed-in member of staff.

    This view is the entire reason the protected directory exists. The file it
    streams is never reachable by URL: there is no route to it, the storage is
    configured without a base URL, and the only way to the bytes is through
    this method - which runs after Django has authenticated the session and
    checked the role.
    """

    model = SupportingDocument

    def get(self, request, *args, **kwargs):
        if not request.user.can_encode_ppa and not request.user.can_review_ppa:
            raise PermissionDenied(
                "Your role does not permit access to internal documents."
            )

        document = self.get_object()
        if not document.file:
            raise Http404("The file is missing from storage.")

        record_audit(
            Action.EXPORT, target=document, request=request,
            detail=f"Opened the internal copy of '{document.title}'.",
        )

        content_type = (
            mimetypes.guess_type(document.original_name or document.filename)[0]
            or "application/octet-stream"
        )
        response = send_fieldfile(
            document.file,
            content_type=content_type,
            # Inline so the reviewer can read a PDF without downloading it;
            # the review screen embeds this URL in an object element.
            as_attachment=request.GET.get("download") == "1",
            filename=document.original_name or document.filename,
        )
        # Belt and braces: an internal document must not sit in a shared cache.
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
