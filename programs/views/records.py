"""
One record: reading, creating, editing and removing it, moving it through
the publication workflow, and previewing it as the public will see it.

Part of programs.views - see its package docstring.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from audit.models import Action
from audit.recording import record as record_audit
from core.mixins import CanEncodePPAMixin, CanPublishPPAMixin, CanReviewPPAMixin
from core.redirects import safe_next
from ..forms import RecordDecisionForm
from ..models import (
    AWAITING_RELEASE_STATUSES,
    OUTCOME_DETAIL,
    DocumentStatus,
    OrganizationalOutcome,
    PublicationStatus,
    RiskLevel,
)

from .common import (
    LEVELS,
    RecordViewMixin,
    WORKFLOW_HELP,
    level_spec,
    record_breadcrumbs,
    record_trail,
    record_url,
    workflow_states,
)


# ---------------------------------------------------------------------------
# Records: read, create, edit, remove
# ---------------------------------------------------------------------------


class RecordDetailView(LoginRequiredMixin, RecordViewMixin, DetailView):
    template_name = "dashboard/ppa/detail.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        user = self.request.user

        # Cleared by a reviewer and not on the website at this moment: the
        # files that are approved and never yet released, and the files that
        # were released and later taken down. Both are one publisher click
        # from being public, and the panel below treats them the same way.
        releasable_documents = list(
            record.documents.filter(
                status__in=AWAITING_RELEASE_STATUSES
            ).select_related("authority")
        )

        context.update({
            "page_title": record.title,
            "page_subtitle": f"{self.spec['label']} · {record.get_publication_status_display()}",
            "breadcrumbs": record_breadcrumbs(record),
            "outcome": OUTCOME_DETAIL.get(record.outcome) if record.outcome else None,
            "children": self._children(record),
            "child_levels": [
                {"level": level, "label": LEVELS[level]["label"]}
                for level in self.spec["child_levels"]
            ],
            "documents": record.documents.select_related("uploaded_by", "reviewed_by"),
            "photograph_count": record.documents.photographs().count(),
            "can_encode": user.can_encode_ppa,
            "can_review": user.can_review_ppa,
            "can_publish": user.can_publish_ppa,
            "decision_form": RecordDecisionForm(),
            "unauthorised_documents": [
                document for document in releasable_documents
                if not document.may_be_released
            ],
            # Cleared, authorised, and attached to a record that is already
            # public: one click from a publisher and they are out.
            "ready_documents": [
                document for document in releasable_documents
                if document.is_awaiting_release
            ],
            # On the website now, so the one thing they are waiting for is a
            # publisher who wants them off it. Listed beside the files waiting
            # to go out so that both directions are a single confirmed click
            # from the record, rather than a trip through the review screen.
            "published_documents": list(
                record.documents.filter(
                    status=DocumentStatus.PUBLISHED
                ).select_related("authority")
            ),
            "workflow_states": workflow_states(record),
            "workflow_help": WORKFLOW_HELP.get(record.publication_status, ""),
            "trail": record_trail(record),
        })
        return context

    def _children(self, record):
        groups = []
        for level in self.spec["child_levels"]:
            attribute = {"project": "projects", "sub-project": "sub_projects",
                         "activity": "activities"}[level]
            queryset = (
                getattr(record, attribute)
                .select_related("responsible_office")
                .annotate(document_total=Count("documents", distinct=True))
            )
            groups.append({
                "level": level,
                "label": LEVELS[level]["plural"],
                "records": queryset,
            })
        return groups


class RecordCreateView(CanEncodePPAMixin, RecordViewMixin, CreateView):
    template_name = "dashboard/module_form.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.parent = self._resolve_parent(kwargs)

    def _resolve_parent(self, kwargs):
        """
        The record this one will hang off, taken from the URL.

        A programme has no parent. Everything else does, and refusing to
        create one without it is what keeps orphaned projects out of the tree.
        """
        if self.level == "program":
            return None
        parent_level = kwargs.get("parent_level")
        parent_pk = kwargs.get("parent_pk")
        if not parent_level or not parent_pk:
            raise Http404("A parent record must be named.")
        parent_model = level_spec(parent_level)["model"]
        parent = get_object_or_404(parent_model, pk=parent_pk)

        allowed = level_spec(parent_level)["child_levels"]
        if self.level not in allowed:
            raise Http404(
                f"A {self.spec['label'].lower()} cannot be created under a "
                f"{level_spec(parent_level)['label'].lower()}."
            )
        return parent

    def get_form_class(self):
        return self.spec["form"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.level != "program":
            kwargs["parent"] = self.parent
        return kwargs

    def get_initial(self):
        """
        Carry the Outcome through from the workbench.

        The empty state under each Outcome offers "add a programme", and
        arriving at the form with that Outcome already chosen is the whole
        point of offering it there.
        """
        initial = super().get_initial()
        outcome = self.request.GET.get("outcome")
        if self.level == "program" and outcome in OrganizationalOutcome.values:
            initial["outcome_code"] = outcome
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"New {self.spec['label']}",
            "page_subtitle": (
                f"Under {self.parent.title}" if self.parent
                else "Complete the required fields marked with an asterisk"
            ),
            "breadcrumbs": (
                record_breadcrumbs(self.parent, f"New {self.spec['label']}")
                if self.parent else
                [{"label": "Programs", "url": reverse("programs:list")},
                 {"label": f"New {self.spec['label']}"}]
            ),
            "submit_label": "Save",
            "cancel_url": (
                record_url(self.parent) if self.parent else reverse("programs:list")
            ),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"{self.object.title} was saved as a draft. It is not on the "
            "public website; submit it for review when it is ready.",
        )
        return response

    def get_success_url(self):
        return record_url(self.object)


class RecordUpdateView(CanEncodePPAMixin, RecordViewMixin, UpdateView):
    template_name = "dashboard/module_form.html"

    def get_form_class(self):
        return self.spec["form"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.level != "program":
            kwargs["parent"] = self.object.parent
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"Edit {self.spec['label']}",
            "page_subtitle": self.object.title,
            "breadcrumbs": record_breadcrumbs(self.object, "Edit"),
            "submit_label": "Save changes",
            "cancel_url": record_url(self.object),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        was_public = self.object.is_published
        was_approved = self.object.publication_status == PublicationStatus.APPROVED
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)

        # Cleared wording must not be swapped for uncleared wording after the
        # fact. Editing approved or published content sends it back.
        self.object.touch_content(self.request.user)
        if was_public:
            messages.warning(
                self.request,
                f"{self.object.title} was taken off the public website because "
                "its content changed. Submit it for review again.",
            )
        elif was_approved:
            messages.warning(
                self.request,
                "The approval was withdrawn because the content changed. "
                "Submit it for review again.",
            )
        else:
            messages.success(self.request, f"Changes to {self.object.title} were saved.")
        return response

    def get_success_url(self):
        return record_url(self.object)


class RecordDeleteView(CanPublishPPAMixin, RecordViewMixin, DeleteView):
    """
    Removal, which is rarer than it looks.

    Archiving is what the office normally wants and what the interface
    offers; deletion is here for a record created by mistake, is restricted to
    administrators, and takes the attached files with it.
    """

    template_name = "dashboard/module_confirm_delete.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"Delete {self.spec['label']}",
            "page_subtitle": self.object.title,
            "breadcrumbs": record_breadcrumbs(self.object, "Delete"),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        record = self.get_object()
        parent = record.parent
        # Public copies are files on disk. Deleting the row is not enough.
        for document in record.documents.all():
            document._delete_public_copy()
        messages.success(self.request, f"{record.title} was deleted.")
        self.success_url = record_url(parent) if parent else reverse("programs:list")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# The publication workflow
# ---------------------------------------------------------------------------


class RecordActionMixin(RecordViewMixin, View):
    """Base for the POST-only endpoints that move a record through the workflow."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        record = get_object_or_404(self.model, pk=kwargs["pk"])
        try:
            self.perform(record, request)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        return redirect(safe_next(request, request.POST.get("next"), record_url(record)))

    def perform(self, record, request):
        raise NotImplementedError


class RecordSubmitView(CanEncodePPAMixin, RecordActionMixin):
    """Hand a record to a reviewer. Screens the attached files on the way."""

    def perform(self, record, request):
        if not record.can_be_submitted:
            raise ValidationError(
                f"{record.title} is {record.get_publication_status_display().lower()} "
                "and cannot be submitted."
            )
        outcome = record.submit_for_review(request.user)
        flagged = record.documents.exclude(risk_level=RiskLevel.LOW).count()

        record_audit(
            Action.SUBMIT, target=record, request=request,
            detail=(
                f"Submitted for review; {record.documents.count()} file(s) "
                f"screened, {flagged} flagged."
            ),
        )
        if outcome == PublicationStatus.REVIEW_REQUIRED:
            messages.warning(
                request,
                f"{record.title} was submitted. The automated screening flagged "
                f"{flagged} file(s) - a reviewer must look at them before "
                "anything is published.",
            )
        else:
            messages.success(
                request,
                f"{record.title} was submitted for review. Nothing is public yet.",
            )


class RecordDecisionView(CanReviewPPAMixin, RecordActionMixin):
    """A reviewer approves the content, sends it back, or refuses it."""

    def perform(self, record, request):
        if not record.can_be_reviewed:
            raise ValidationError(f"{record.title} is not awaiting review.")

        form = RecordDecisionForm(request.POST)
        if not form.is_valid():
            raise ValidationError(
                [error for errors in form.errors.values() for error in errors]
            )

        decision = form.cleaned_data["decision"]
        comments = form.cleaned_data["comments"]

        if decision == "approve":
            record.approve(request.user, comments)
            record_audit(Action.APPROVE, target=record, request=request,
                         detail=f"Content approved. {comments}"[:255])
            messages.success(
                request,
                f"{record.title} was approved. It is not public until an "
                "administrator publishes it.",
            )
        elif decision == "revise":
            record.request_revision(request.user, comments)
            record_audit(Action.REQUEST_REVISION, target=record, request=request,
                         detail=comments[:255])
            messages.info(request, f"{record.title} was sent back for revision.")
        else:
            record.reject(request.user, comments)
            record_audit(Action.REJECT, target=record, request=request,
                         detail=comments[:255])
            messages.info(request, f"{record.title} was rejected and returned to draft.")


class RecordPublishView(CanPublishPPAMixin, RecordActionMixin):
    """
    Put approved content on the public website.

    This is the only view in the module that causes a file to be written into
    a served directory, and it refuses anything that is not approved.
    """

    def perform(self, record, request):
        outcome = record.publish(request.user)
        released, held = outcome["released"], outcome["held"]

        authorities = sorted({
            document.authority.reference for document in released
            if document.authority_id
        })
        record_audit(
            Action.PUBLISH, target=record, request=request,
            detail=(
                f"Published to the public website with {len(released)} file(s)"
                + (f" under {', '.join(authorities)}" if authorities else "")
                + (f"; {len(held)} file(s) held back for want of an authority."
                   if held else ".")
            )[:255],
        )

        messages.success(
            request,
            f"{record.title} is now on the public website"
            + (f", with {len(released)} approved file(s)." if released else "."),
        )
        if held:
            # Named rather than counted: "two files were held back" sends the
            # publisher hunting, and the whole point of the control is that
            # the missing memorandum is obvious.
            messages.warning(
                request,
                "These files were NOT published, because no memorandum "
                "authorises their release: "
                + "; ".join(f"'{d.title}' - {d.release_blocker}" for d in held),
            )


class RecordUnpublishView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        if not record.is_published:
            raise ValidationError(f"{record.title} is not published.")
        record.unpublish(request.user)
        record_audit(
            Action.UNPUBLISH, target=record, request=request,
            detail="Withdrawn from the public website; public file copies deleted.",
        )
        messages.success(
            request,
            f"{record.title} was taken off the public website, along with "
            "anything published beneath it. The public copies of its files "
            "have been deleted.",
        )


class RecordArchiveView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        record.archive(request.user)
        record_audit(Action.ARCHIVE, target=record, request=request,
                     detail="Archived.")
        messages.success(request, f"{record.title} was archived.")


class RecordRestoreView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        if not record.is_archived:
            raise ValidationError(f"{record.title} is not archived.")
        record.restore(request.user)
        record_audit(Action.RESTORE, target=record, request=request,
                     detail="Restored from the archive as a draft.")
        messages.success(
            request,
            f"{record.title} was restored as a draft. It must be reviewed and "
            "approved again before it can be published.",
        )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class RecordPreviewView(CanEncodePPAMixin, RecordViewMixin, DetailView):
    """
    The public page, exactly as a visitor would see it, before it is public.

    Rendered through the *same template* the public site uses rather than an
    imitation of it, because the point of a preview is to be able to trust it.
    A banner across the top says it is a preview, and the publish button on it
    is the real one.
    """

    context_object_name = "record"
    template_name = "public/ppa_detail.html"

    def get_context_data(self, **kwargs):
        from ..public import public_detail_context

        context = super().get_context_data(**kwargs)
        context.update(public_detail_context(self.object, preview=True))
        context.update({
            "preview": True,
            "preview_back_url": record_url(self.object),
            "can_publish": self.request.user.can_publish_ppa,
            "level": self.level,
        })
        return context
