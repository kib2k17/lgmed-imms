"""
The written authority to publish, and the steps that need one: attaching it
to a document, publishing the document's public copy, and withdrawing it.

Part of programs.views - see its package docstring.
"""

import mimetypes

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from audit.models import Action
from audit.recording import record as record_audit
from core.files import send_fieldfile
from core.mixins import CanPublishPPAMixin, CanReviewPPAMixin
from core.redirects import safe_next
from ..forms import DocumentAuthorityForm, PublicationAuthorityForm
from ..models import DocumentStatus, PublicationAuthority, SupportingDocument

from .common import PPAContextMixin


# ---------------------------------------------------------------------------
# The authority to publish
# ---------------------------------------------------------------------------
#
# Recorded on its own pages, ahead of any release that cites it. That
# separation is the control: an authority created inside the same form that
# publishes a file would be a second checkbox wearing a memorandum's name.


class AuthorityListView(CanReviewPPAMixin, PPAContextMixin, ListView):
    """Every memorandum the office has recorded, in force or not."""

    template_name = "dashboard/ppa/authority_list.html"
    context_object_name = "authorities"
    model = PublicationAuthority

    def get_queryset(self):
        return PublicationAuthority.objects.annotate(
            released=Count(
                "documents",
                filter=Q(documents__status=DocumentStatus.PUBLISHED),
            )
        ).order_by("-approved_on", "reference")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Publication Authorities",
            "page_subtitle": (
                "The memoranda under which files may be released to the public"
            ),
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities"},
            ],
            "active_nav": "ppa_authorities",
            "awaiting": SupportingDocument.objects.filter(
                status=DocumentStatus.APPROVED, authority__isnull=True
            ).count(),
        })
        return context


class AuthorityDetailView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """One memorandum, and every file released under it."""

    template_name = "dashboard/ppa/authority_detail.html"
    context_object_name = "authority"
    model = PublicationAuthority

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        authority = self.object
        context.update({
            "page_title": authority.reference,
            "page_subtitle": authority.title,
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": authority.reference},
            ],
            "active_nav": "ppa_authorities",
            "documents": authority.documents.select_related(
                "program", "project", "sub_project", "activity", "uploaded_by",
            ).order_by("-published_at", "-uploaded_at"),
        })
        return context


class AuthorityFormMixin(PPAContextMixin):
    template_name = "dashboard/module_form.html"
    form_class = PublicationAuthorityForm
    model = PublicationAuthority

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "active_nav": "ppa_authorities",
            "list_url": reverse("programs:authority_list"),
            "cancel_url": (
                self.object.get_absolute_url() if getattr(self, "object", None)
                else reverse("programs:authority_list")
            ),
            "form_note": (
                "Record the memorandum here first. It can then be cited "
                "against the files it authorises - and a file cannot be "
                "published unless one is."
            ),
        })
        return context


class AuthorityCreateView(CanReviewPPAMixin, AuthorityFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Record a Publication Authority",
            "page_subtitle": "The memorandum authorising a public release",
            "submit_label": "Record the memorandum",
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": "New"},
            ],
        })
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"{self.object.reference} was recorded. Files may now be released "
            "under it.",
        )
        return response


class AuthorityUpdateView(CanReviewPPAMixin, AuthorityFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Edit Publication Authority",
            "page_subtitle": str(self.object),
            "submit_label": "Save changes",
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": self.object.reference,
                 "url": self.object.get_absolute_url()},
                {"label": "Edit"},
            ],
        })
        return context

    def form_valid(self, form):
        was_in_force = self.get_object().is_in_force()
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)

        # Withdrawing an authority stops it authorising anything further, but
        # it does not reach back and unpublish what it already released. That
        # is a separate decision and it belongs to whoever holds it, so the
        # page says plainly what is still out there rather than acting alone.
        if was_in_force and not self.object.is_in_force():
            live = self.object.documents.filter(
                status=DocumentStatus.PUBLISHED
            ).count()
            record_audit(
                Action.UPDATE, target=self.object, request=self.request,
                detail=f"Authority withdrawn; {live} file(s) remain published.",
            )
            if live:
                messages.warning(
                    self.request,
                    f"{self.object.reference} no longer authorises new "
                    f"releases. {live} file(s) already published under it are "
                    "still on the public website - unpublish the records they "
                    "belong to if they should come down.",
                )
                return response
        messages.success(
            self.request, f"Changes to {self.object.reference} were saved."
        )
        return response


class DocumentAuthorityView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """Cite a memorandum against one file that has already been approved."""

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        form = DocumentAuthorityForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(e for errors in form.errors.values() for e in errors),
            )
        else:
            authority = form.cleaned_data["authority"]
            document.authority = authority
            document.save(update_fields=["authority"])
            record_audit(
                Action.UPDATE, target=document, request=request,
                detail=f"Publication authority set to {authority.reference}.",
            )
            messages.success(
                request,
                f"'{document.title}' is now cited against {authority.reference}.",
            )
        return redirect(reverse("programs:document_review", args=[document.pk]))


class AuthorityFileView(CanReviewPPAMixin, DetailView):
    """
    Stream the scanned memorandum to a reviewer.

    The issuance is evidence behind a release, not a thing being released, so
    it lives in the protected root like every other internal file and is
    reachable only through here.
    """

    model = PublicationAuthority

    def get(self, request, *args, **kwargs):
        authority = self.get_object()
        if not authority.memorandum:
            raise Http404("No memorandum has been attached to this authority.")

        record_audit(
            Action.EXPORT, target=authority, request=request,
            detail=f"Opened the memorandum for {authority.reference}.",
        )
        name = authority.memorandum.name.rsplit("/", 1)[-1]
        response = send_fieldfile(
            authority.memorandum,
            content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            as_attachment=request.GET.get("download") == "1",
            filename=name,
        )
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response


class DocumentPublishView(CanPublishPPAMixin, PPAContextMixin, DetailView):
    """
    Put one already-cleared file on the public website.

    Needed because a programme is published once and then added to for months.
    Releasing a photograph filed today should not mean unpublishing the whole
    programme and putting it back - that takes everything else offline for the
    sake of one picture, and an office that has to do it will stop publishing
    evidence at all.

    Nothing is relaxed to make this possible. The same four conditions apply as
    when the record was published: a reviewer has approved the file, a
    memorandum authorises its release, the record carrying it is public, and
    the person clicking is a publisher. A file that was published and then
    withdrawn still satisfies the first of those - the approval never went
    away - so putting it back is this one action and not a second review.
    """

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        # A second POST of the same button - an impatient click, a refreshed
        # tab, a browser replaying the request - must not rewrite the public
        # copy or write a second PUBLISH line into the audit log. The state
        # already says what the person was asking for, so say so and stop.
        if document.status == DocumentStatus.PUBLISHED:
            messages.info(
                request,
                f"'{document.title}' is already on the public website.",
            )
            return redirect(safe_next(request, self.request.POST.get("next"),
                            reverse("programs:document_review",
                                       args=[document.pk])))
        was_withdrawn = document.status == DocumentStatus.WITHDRAWN
        try:
            document.publish(request.user)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            record_audit(
                Action.PUBLISH, target=document, request=request,
                detail=(
                    ("Put back on the public website under "
                     if was_withdrawn else "Released on its own under ")
                    + f"{document.authority.reference}, to the "
                    f"already-published {document.owner_label}."
                )[:255],
            )
            messages.success(
                request,
                f"'{document.title}' is "
                + ("back on" if was_withdrawn else "now on")
                + f" the public website, under {document.authority.reference}.",
            )
        return redirect(safe_next(request, self.request.POST.get("next"),
                        reverse("programs:document_review", args=[document.pk])))


class DocumentWithdrawView(CanPublishPPAMixin, PPAContextMixin, DetailView):
    """
    Take one file off the public website, leaving the record published.

    The counterpart of releasing one file on its own: an office that spots a
    face in a photograph needs that photograph gone now, not the whole
    programme page.
    """

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        if document.status == DocumentStatus.WITHDRAWN:
            # Already down, most likely because this is the same click twice.
            # Nothing to do and nothing to warn about.
            messages.info(
                request,
                f"'{document.title}' is already off the public website. The "
                "file itself is still here.",
            )
        elif document.status != DocumentStatus.PUBLISHED:
            messages.error(request, f"'{document.title}' is not published.")
        else:
            document.withdraw(request.user)
            record_audit(
                Action.UNPUBLISH, target=document, request=request,
                detail="Withdrawn from the public website; public copy deleted.",
            )
            messages.success(
                request,
                f"'{document.title}' was taken off the public website and its "
                "public copy deleted. The file itself is untouched, and you "
                "can publish it again from this page. The record it belongs "
                "to is still published.",
            )
        return redirect(safe_next(request, self.request.POST.get("next"),
                        reverse("programs:document_review", args=[document.pk])))
