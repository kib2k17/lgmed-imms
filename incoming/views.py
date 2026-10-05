"""
Incoming Monitoring.

The list, the record and the Chief's dashboard are ordinary module views. The
workflow actions are deliberately not: each is a POST to its own URL, handled
by a small view that validates a form and hands the record to
`incoming.workflow`. Nothing here decides who may do what - the workflow
functions raise `PermissionDenied` themselves, so an action taken through the
shell or a management command is refused on the same terms as one taken
through a button.
"""

import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView, View

from core.files import serve_inline
from core.mixins import CanReviewIncomingMixin, CapabilityRequiredMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)
from documents.models import DocumentType

from . import reports as report_catalogue
from . import workflow
from .forms import AssignmentForm, IncomingDocumentForm, ReviewForm
from .models import (
    UPDATE_REMINDER_DAYS,
    IncomingDocument,
    IncomingStatus,
    Priority,
)

# The quick views offered beside the ordinary filters. Each is a question an
# officer actually asks of the list, expressed once here and reused by the
# dashboard's clickable figures.
QUICK_VIEWS = (
    ("mine", "Assigned to me"),
    ("recorded", "Recorded by me"),
    ("for_review", "For Division Chief review"),
    ("unassigned", "Not yet assigned"),
    ("unacknowledged", "Awaiting acknowledgement"),
    ("awaiting_update", "Awaiting focal person update"),
    ("open", "Open (not completed)"),
    ("overdue", "Overdue"),
)

# The date the toolbar's from/to range applies to.
DATE_BASES = {
    "received": ("date_received", "Date received"),
    "assigned": ("assigned_at__date", "Date assigned"),
    "completed": ("completed_at__date", "Date completed"),
}
DEFAULT_BASIS = "received"


class IncomingModuleMixin:
    model = IncomingDocument
    module_key = "incoming"
    module_label = "Incoming Document"
    module_url_name = "incoming:list"
    list_label = "Incoming Monitoring"


def _summary(user):
    """The figures shown above the list and on the Chief's dashboard."""
    base = IncomingDocument.objects.all()
    today = timezone.localdate()
    counts = base.aggregate(
        total=Count("pk"),
        for_review=Count("pk", filter=Q(status=IncomingStatus.FOR_REVIEW)),
        assigned=Count("pk", filter=Q(status=IncomingStatus.ASSIGNED)),
        acknowledged=Count("pk", filter=Q(status=IncomingStatus.ACKNOWLEDGED)),
        in_progress=Count("pk", filter=Q(status=IncomingStatus.IN_PROGRESS)),
        for_action=Count("pk", filter=Q(status=IncomingStatus.FOR_ACTION)),
        pending=Count("pk", filter=Q(status=IncomingStatus.PENDING)),
        returned=Count("pk", filter=Q(status=IncomingStatus.RETURNED)),
        completed=Count("pk", filter=Q(status=IncomingStatus.COMPLETED)),
    )
    counts["overdue"] = base.overdue(today).count()
    counts["awaiting_update"] = base.awaiting_update().count()
    counts["unacknowledged"] = base.awaiting_acknowledgement().count()
    counts["mine"] = (
        base.assigned_to(user).open().count() if user.is_authenticated else 0
    )
    return counts


def _stat_links(counts):
    """
    The dashboard's figures, each one a link to the documents behind it.

    A figure an officer cannot click through to is a figure they have to take
    on trust; every one of these opens the list already filtered.
    """
    url = reverse("incoming:list")

    def link(**params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{query}" if query else url

    return [
        {"label": "Total incoming", "value": counts["total"], "url": link(),
         "tone": "", "icon": "inbox"},
        {"label": "For review", "value": counts["for_review"],
         "url": link(status=IncomingStatus.FOR_REVIEW), "tone": "warning",
         "icon": "clock"},
        {"label": "Assigned", "value": counts["assigned"],
         "url": link(status=IncomingStatus.ASSIGNED), "tone": "", "icon": "users"},
        {"label": "Acknowledged", "value": counts["acknowledged"],
         "url": link(status=IncomingStatus.ACKNOWLEDGED), "tone": "",
         "icon": "check"},
        {"label": "In progress", "value": counts["in_progress"],
         "url": link(status=IncomingStatus.IN_PROGRESS), "tone": "",
         "icon": "monitoring"},
        {"label": "For action", "value": counts["for_action"],
         "url": link(status=IncomingStatus.FOR_ACTION), "tone": "warning",
         "icon": "warning"},
        {"label": "Pending", "value": counts["pending"],
         "url": link(status=IncomingStatus.PENDING), "tone": "warning",
         "icon": "clock"},
        {"label": "Overdue", "value": counts["overdue"], "url": link(view="overdue"),
         "tone": "danger", "icon": "warning"},
        {"label": "Awaiting update", "value": counts["awaiting_update"],
         "url": link(view="awaiting_update"), "tone": "warning", "icon": "bell"},
        {"label": "Returned / for revision", "value": counts["returned"],
         "url": link(status=IncomingStatus.RETURNED), "tone": "danger",
         "icon": "error"},
        {"label": "Completed", "value": counts["completed"],
         "url": link(status=IncomingStatus.COMPLETED), "tone": "success",
         "icon": "check-circle"},
    ]


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------


class IncomingListView(IncomingModuleMixin, ModuleListView):
    page_title = "Incoming Monitoring"
    page_subtitle = (
        "Documents received by the Division, from recording to completion"
    )
    module_label = "Incoming Documents"
    template_name = "dashboard/incoming/list.html"
    search_placeholder = "Search LGMED code, DNS number, subject, source..."
    search_fields = (
        "lgmed_code", "docket_number", "subject", "source_office", "initial_remarks",
        "review_notes", "assignment_remarks",
    )
    sort_fields = (
        "lgmed_code", "docket_number", "subject", "date_received", "status", "priority",
        "assigned_to__last_name", "due_date", "completed_at", "assigned_at",
    )
    default_sort = "-date_received"
    create_url_name = "incoming:create"
    create_label = "Record Incoming Document"
    empty_icon = "inbox"
    virtual_filters = ("view", "basis")
    export_columns = (
        ("LGMED code", "lgmed_code"),
        ("DNS number", "docket_number"),
        ("Subject", "subject"),
        ("Document type", "document_type.name"),
        ("Source / office", "source_office"),
        ("Date received", "date_received"),
        ("Status", "display_status_label"),
        ("Priority", "get_priority_display"),
        ("Focal person", "assigned_to.get_display_name"),
        ("Date assigned", "assigned_at"),
        ("Due date", "due_date"),
        ("Date completed", "completed_at"),
        ("Recorded by", "created_by.get_display_name"),
    )

    # -- the date the from/to range applies to ---------------------------

    @property
    def date_basis(self):
        basis = self.request.GET.get("basis", DEFAULT_BASIS)
        return basis if basis in DATE_BASES else DEFAULT_BASIS

    @property
    def date_field(self):
        return DATE_BASES[self.date_basis][0]

    @property
    def date_field_label(self):
        return DATE_BASES[self.date_basis][1]

    @property
    def filter_fields(self):
        return (
            ("view", "View", QUICK_VIEWS),
            ("status", "Status", IncomingStatus.choices),
            ("document_type", "Type",
             [(str(t.pk), t.name) for t in DocumentType.objects.filter(is_active=True)]),
            ("assigned_to", "Focal person",
             [(str(u.pk), u.get_display_name()) for u in workflow.focal_persons()]),
            ("priority", "Priority", Priority.choices),
            ("basis", "Date range applies to",
             [(key, label) for key, (_field, label) in DATE_BASES.items()]),
        )

    def get_base_queryset(self):
        return IncomingDocument.objects.select_related(
            "document_type", "assigned_to", "assigned_by", "created_by", "reviewed_by"
        ).prefetch_related("updates")

    def apply_extra_filters(self, queryset):
        """The quick views: questions about the record, not values in a column."""
        view = self.request.GET.get("view", "").strip()
        user = self.request.user
        if view == "mine":
            return queryset.assigned_to(user)
        if view == "recorded":
            return queryset.filter(created_by=user)
        if view == "for_review":
            return queryset.for_review()
        if view == "unassigned":
            return queryset.filter(assigned_to__isnull=True)
        if view == "unacknowledged":
            return queryset.awaiting_acknowledgement()
        if view == "awaiting_update":
            return queryset.awaiting_update()
        if view == "open":
            return queryset.open()
        if view == "overdue":
            return queryset.overdue()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["summary"] = _summary(self.request.user)
        context["active_view"] = self.request.GET.get("view", "")
        context["can_review"] = self.request.user.can_review_incoming
        return context


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


class IncomingDetailView(IncomingModuleMixin, ModuleDetailView):
    template_name = "dashboard/incoming/detail.html"

    def get_queryset(self):
        return IncomingDocument.objects.select_related(
            "document_type", "assigned_to", "assigned_by", "reviewed_by",
            "created_by", "updated_by",
        ).prefetch_related("updates__created_by", "events__actor")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.object
        user = self.request.user

        context["page_title"] = document.tracking_number
        context["page_subtitle"] = document.subject
        context["outgoing"] = document.outgoing_document
        context["can_review"] = user.can_review_incoming
        context["can_acknowledge"] = document.may_be_acknowledged_by(user)
        context["is_focal_person"] = document.assigned_to_id == user.pk
        context["review_form"] = ReviewForm(
            initial={"review_notes": document.review_notes}
        )
        context["assignment_form"] = AssignmentForm(
            initial={
                "assigned_to": document.assigned_to_id,
                "assignment_remarks": document.assignment_remarks,
                "priority": document.priority,
                "due_date": document.due_date,
            }
        )
        context["update_reminder_days"] = UPDATE_REMINDER_DAYS
        return context


class IncomingCreateView(IncomingModuleMixin, ModuleCreateView):
    """
    The encoder records what arrived.

    The form carries no focal person and no status, so the document can only
    come into being at "For Division Chief review".
    """

    form_class = IncomingDocumentForm
    module_label = "Incoming Document"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Record Incoming Document"
        context["page_subtitle"] = (
            "The Division Chief reviews and assigns the document after it is recorded"
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        workflow.record_received(self.object, self.request.user)
        messages.success(
            self.request,
            f"{self.object.docket_number} was recorded and is now awaiting "
            "Division Chief review.",
        )
        return response


class IncomingUpdateView(IncomingModuleMixin, ModuleUpdateView):
    """
    Correct the details of a record.

    An encoder may amend a document only while it is still awaiting review -
    once the Chief has acted on it, changing what it says would change what
    they decided about. The Chief may amend it at any point.
    """

    form_class = IncomingDocumentForm
    module_label = "Incoming Document"

    def get_object(self, queryset=None):
        document = super().get_object(queryset)
        user = self.request.user
        if document.status != IncomingStatus.FOR_REVIEW and not user.can_review_incoming:
            raise PermissionDenied(
                "This document has already been reviewed. Ask the Division Chief "
                "to amend it."
            )
        return document

    def form_valid(self, form):
        response = super().form_valid(form)
        changed = ", ".join(
            form.fields[name].label or name.replace("_", " ")
            for name in form.changed_data
        )
        workflow.record_amended(
            self.object,
            self.request.user,
            f"Amended: {changed}" if changed else "",
        )
        return response


class IncomingDeleteView(IncomingModuleMixin, ModuleDeleteView):
    module_label = "Incoming Document"


# ---------------------------------------------------------------------------
# Attachments, for the PDF viewer
# ---------------------------------------------------------------------------


@method_decorator(xframe_options_sameorigin, name="dispatch")
class AttachmentView(CapabilityRequiredMixin, View):
    """The document's attachment, for the viewer. Readable by whoever may open the record."""

    capability = "can_view"

    def get(self, request, pk):
        document = get_object_or_404(IncomingDocument, pk=pk)
        return serve_inline(document.attachment)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class UpdateAttachmentView(CapabilityRequiredMixin, View):
    """A focal person's supporting attachment, for the viewer."""

    capability = "can_view"

    def get(self, request, update_pk):
        from .models import IncomingUpdate

        update = get_object_or_404(IncomingUpdate, pk=update_pk)
        return serve_inline(update.attachment)


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------


class WorkflowActionView(CapabilityRequiredMixin, View):
    """A POST that moves one document along. GET simply returns to the record."""

    capability = "can_view"

    def get_document(self):
        return get_object_or_404(IncomingDocument, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return redirect("incoming:detail", pk=pk)

    def failure(self, request, document, form):
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(document.get_absolute_url())


class ReviewView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = ReviewForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.review(document, request.user, form.cleaned_data["review_notes"])
        messages.success(
            request,
            f"Your review notes on {document.docket_number} were saved. "
            "Assign a focal person when you are ready.",
        )
        return redirect(document.get_absolute_url())


class AssignView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = AssignmentForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.assign(
            document,
            request.user,
            assignee=form.cleaned_data["assigned_to"],
            remarks=form.cleaned_data["assignment_remarks"],
            priority=form.cleaned_data["priority"],
            due_date=form.cleaned_data["due_date"],
        )
        messages.success(
            request,
            f"{document.docket_number} was assigned to "
            f"{document.assigned_to.get_display_name()}, who has been notified. "
            f"It is now tracked as {document.lgmed_code}.",
        )
        return redirect(document.get_absolute_url())


class AcknowledgeView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        workflow.acknowledge(document, request.user)
        messages.success(
            request,
            f"You acknowledged {document.tracking_number}. It is now in Outgoing "
            "Monitoring: record your updates and the communication sent there.",
        )
        return redirect(document.action_url)


# Updates, returns for revision and completion are not here: once the focal
# person acknowledges, the document moves to Outgoing Monitoring and they are
# taken there. See outgoing/views.py.


# ---------------------------------------------------------------------------
# The Division Chief's monitoring dashboard
# ---------------------------------------------------------------------------


class IncomingDashboardView(CanReviewIncomingMixin, TemplateView):
    """
    Everything that has come in, and where each item now stands.

    Every figure is a link into the list, filtered to exactly the documents it
    counted, so the Chief can go from a number to the records behind it.
    """

    template_name = "dashboard/incoming/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = _summary(self.request.user)
        base = IncomingDocument.objects.select_related(
            "document_type", "assigned_to", "created_by"
        ).prefetch_related("updates")

        context.update(
            {
                "page_title": "Incoming Monitoring Dashboard",
                "page_subtitle": (
                    "What has come in, who is handling it, and what is happening to it"
                ),
                "breadcrumbs": [
                    {"label": "Incoming Monitoring",
                     "url": reverse("incoming:list")},
                    {"label": "Monitoring dashboard"},
                ],
                "active_nav": "incoming",
                "summary": counts,
                "stats": _stat_links(counts),
                "for_review": base.for_review().order_by("date_received")[:10],
                "overdue": base.overdue().order_by("due_date")[:10],
                "awaiting_update": base.awaiting_update().order_by("assigned_at")[:10],
                "recent_updates": _recent_updates(),
                "workload": report_catalogue.get_report("by-focal-person")["build"](
                    base.all()
                ),
                "update_reminder_days": UPDATE_REMINDER_DAYS,
                "as_of": timezone.localtime(),
            }
        )
        return context


def _recent_updates(limit=8):
    from .models import IncomingUpdate

    return (
        IncomingUpdate.objects.select_related(
            "document", "created_by", "document__assigned_to"
        ).order_by("-created_at")[:limit]
    )


# ---------------------------------------------------------------------------
# Monitoring reports
# ---------------------------------------------------------------------------


class IncomingReportsView(CapabilityRequiredMixin, TemplateView):
    """
    The reports an officer is asked for, built from the same records.

    The page and the CSV are the same figures under the same filters: what is
    exported is what was on screen, which is what makes the file safe to attach
    to a memorandum.
    """

    capability = "can_encode"
    template_name = "dashboard/incoming/reports.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            return self.export_csv()
        return super().get(request, *args, **kwargs)

    def build(self):
        slug = self.request.GET.get("report", report_catalogue.DEFAULT_REPORT)
        if slug not in report_catalogue.REPORTS:
            slug = report_catalogue.DEFAULT_REPORT
        spec = report_catalogue.REPORTS[slug]
        queryset, applied, sort = report_catalogue.filtered_queryset(self.request.GET)
        result = spec["build"](queryset)
        return slug, spec, result, applied, sort

    def export_csv(self):
        from audit.models import Action
        from audit.recording import record

        slug, spec, result, applied, _sort = self.build()
        stamp = timezone.localtime().strftime("%Y%m%d")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="lgmed-imms-{slugify(spec["label"])}-{stamp}.csv"'
        )
        response.write("﻿")

        writer = csv.writer(response)
        writer.writerow([spec["label"]])
        writer.writerow(["LGMED-iMMS - Incoming Monitoring"])
        writer.writerow([
            "Generated", timezone.localtime().strftime("%d %B %Y, %I:%M %p")
        ])
        if applied:
            writer.writerow(["Filters", "; ".join(applied)])
        writer.writerow([])
        writer.writerow(result["headers"])
        for row in result["rows"]:
            writer.writerow(row)
        if result.get("footer"):
            writer.writerow(result["footer"])

        record(
            Action.EXPORT,
            detail=f"Exported the {spec['label']} ({len(result['rows'])} rows)",
            request=self.request,
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug, spec, result, applied, sort = self.build()
        params = self.request.GET

        context.update(
            {
                "page_title": "Monitoring Reports",
                "page_subtitle": "Incoming document reports, ready to print or export",
                "breadcrumbs": [
                    {"label": "Incoming Monitoring", "url": reverse("incoming:list")},
                    {"label": "Monitoring reports"},
                ],
                "active_nav": "incoming",
                "reports": report_catalogue.catalogue(),
                "report_slug": slug,
                "report": spec,
                "result": result,
                "applied": applied,
                "row_count": len(result["rows"]),
                "sorts": report_catalogue.SORTS.items(),
                "selected_sort": sort,
                "focal_persons": workflow.focal_persons(),
                "document_types": DocumentType.objects.filter(is_active=True),
                "statuses": IncomingStatus.choices,
                "selected": {
                    "q": params.get("q", ""),
                    "from": params.get("from", ""),
                    "to": params.get("to", ""),
                    "focal": params.get("focal", ""),
                    "status": params.get("status", ""),
                    "type": params.get("type", ""),
                },
                "open_status_value": "OPEN",
                "as_of": timezone.localtime(),
            }
        )
        return context
