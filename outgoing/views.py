"""
Outgoing Monitoring.

Two kinds of record are listed here. The register's historical rows are kept
in its spreadsheet and brought in through Data Sync. Every other record was
opened when a focal person acknowledged an incoming document assigned to them
(`incoming.workflow.acknowledge`): from then on the action is taken here -
progress updates, return for revision, completion, and the communication
finally sent - all under the LGMED code the Division Chief's assignment issued.

The action views hand the linked incoming document to `incoming.workflow`, which
decides who may do what, so the rules are the same wherever the button is.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import View

from core.files import serve_inline
from core.mixins import CapabilityRequiredMixin
from core.views_base import ModuleDetailView, ModuleListView, ModuleUpdateView
from incoming import workflow
from incoming.forms import IncomingUpdateForm, ReturnForm
from incoming.models import OPEN_STATUSES, UPDATE_REMINDER_DAYS, IncomingStatus
from incoming.views import WorkflowActionView

from .forms import OutgoingResponseForm
from .models import OutgoingDocument

QUICK_VIEWS = (
    ("mine", "Assigned to me"),
    ("action", "For action (open)"),
    ("completed", "Action completed"),
    ("unsent", "Communication not yet sent"),
    ("register", "From the spreadsheet register"),
)


class OutgoingModuleMixin:
    model = OutgoingDocument
    module_key = "outgoing"
    module_label = "Outgoing Document"
    module_url_name = "outgoing:list"
    list_label = "Outgoing Monitoring"


class OutgoingListView(OutgoingModuleMixin, ModuleListView):
    page_title = "Outgoing Monitoring"
    page_subtitle = (
        "Documents under action by their focal persons, and the communications sent"
    )
    module_label = "Outgoing Documents"
    template_name = "dashboard/outgoing/list.html"
    search_placeholder = "Search LGMED code, subject, recipient..."
    search_fields = (
        "control_code", "subject", "sent_to", "communication_type",
        "incoming_reference", "dms_number", "remarks",
    )
    sort_fields = ("control_code", "date_sent", "communication_type")
    date_field = "date_sent"
    date_field_label = "Date sent"
    empty_icon = "mail"
    virtual_filters = ("view",)
    filter_fields = (("view", "View", QUICK_VIEWS),)
    export_columns = (
        ("LGMED code", "control_code"),
        ("Date", "date_sent"),
        ("DMS number (incoming)", "incoming_reference"),
        ("Focal person", "incoming.assigned_to.get_display_name"),
        ("Status", "display_status_label"),
        ("Type of communication", "communication_type"),
        ("Subject / title", "subject"),
        ("Sent to", "sent_to"),
        ("Sent via", "sent_via"),
        ("Remarks", "remarks"),
        ("DMS number (outgoing)", "dms_number"),
    )

    def get_base_queryset(self):
        return OutgoingDocument.objects.select_related("incoming__assigned_to")

    def apply_extra_filters(self, queryset):
        view = self.request.GET.get("view", "").strip()
        if view == "mine":
            return queryset.filter(incoming__assigned_to=self.request.user)
        if view == "action":
            return queryset.filter(incoming__status__in=OPEN_STATUSES)
        if view == "completed":
            return queryset.filter(incoming__status=IncomingStatus.COMPLETED)
        if view == "unsent":
            return queryset.filter(date_sent__isnull=True)
        if view == "register":
            return queryset.filter(incoming__isnull=True)
        return queryset

    def apply_sort(self, queryset):
        # Work still under action has no date sent yet; it belongs at the top,
        # not after every row of the register.
        if self.request.GET.get("sort", "").strip().lstrip("-") in self.sort_fields:
            return super().apply_sort(queryset)
        return queryset.order_by(
            F("date_sent").desc(nulls_first=True), "-created_at", "-id"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = OutgoingDocument.objects.all()
        context["summary"] = {
            "total": base.count(),
            "action": base.filter(incoming__status__in=OPEN_STATUSES).count(),
            "mine": base.filter(
                incoming__assigned_to=self.request.user,
                incoming__status__in=OPEN_STATUSES,
            ).count(),
            "completed": base.filter(incoming__status=IncomingStatus.COMPLETED).count(),
            "unsent": base.filter(date_sent__isnull=True).count(),
        }
        return context


class OutgoingDetailView(OutgoingModuleMixin, ModuleDetailView):
    """The record, and - for a document under action - where the action is taken."""

    template_name = "dashboard/outgoing/detail.html"

    def get_queryset(self):
        return OutgoingDocument.objects.select_related(
            "incoming__assigned_to", "incoming__assigned_by",
            "incoming__reviewed_by", "incoming__document_type",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        user = self.request.user
        document = record.incoming

        context["page_title"] = record.control_code
        context["page_subtitle"] = (record.subject or "")[:120]
        context["details"] = [
            ("LGMED code", record.control_code),
            ("Date sent", record.date_sent.strftime("%d %B %Y") if record.date_sent else ""),
            ("Type of communication", record.communication_type),
            ("Sent to", record.sent_to),
            ("Sent via", record.sent_via),
            ("DMS number (incoming)", record.incoming_reference),
            ("DMS number (outgoing)", record.dms_number),
        ]
        context["document"] = document
        # A register row names the incoming document it answers by DNS number
        # only; it is not attached to it (see outgoing/sync.py). Point to it.
        if document is None and record.incoming_reference:
            from incoming.models import IncomingDocument

            context["referenced_incoming"] = IncomingDocument.objects.filter(
                docket_number=record.incoming_reference
            ).first()
        if document is not None:
            context.update(
                {
                    "can_review": user.can_review_incoming,
                    "can_update": document.may_be_updated_by(user),
                    "can_record_transmittal": document.may_record_transmittal(user),
                    "is_focal_person": document.assigned_to_id == user.pk,
                    "update_form": IncomingUpdateForm(),
                    "return_form": ReturnForm(),
                    "update_reminder_days": UPDATE_REMINDER_DAYS,
                    "updates": document.updates.select_related("created_by"),
                }
            )
        return context


# ---------------------------------------------------------------------------
# Action on a document under Outgoing Monitoring
# ---------------------------------------------------------------------------


class OutgoingActionView(WorkflowActionView):
    """A POST on the incoming document behind an Outgoing record."""

    def get_record(self):
        record = get_object_or_404(
            OutgoingDocument.objects.select_related("incoming"), pk=self.kwargs["pk"]
        )
        if record.incoming is None:
            raise PermissionDenied(
                "This row comes from the spreadsheet register and has no action "
                "to record."
            )
        return record

    def get(self, request, pk):
        return redirect("outgoing:detail", pk=pk)


class AddUpdateView(OutgoingActionView):
    def post(self, request, pk):
        record = self.get_record()
        document = record.incoming
        form = IncomingUpdateForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.failure(request, record, form)
        workflow.add_update(document, request.user, form.save(commit=False))
        messages.success(
            request,
            f"Your update on {record.control_code} was recorded as "
            f"'{document.get_status_display()}'.",
        )
        return redirect(record.get_absolute_url())


class ReturnView(OutgoingActionView):
    def post(self, request, pk):
        record = self.get_record()
        document = record.incoming
        form = ReturnForm(request.POST)
        if not form.is_valid():
            return self.failure(request, record, form)
        workflow.return_for_revision(document, request.user, form.cleaned_data["remarks"])
        messages.success(
            request,
            f"{record.control_code} was returned to "
            f"{document.assigned_to.get_display_name()} for revision.",
        )
        return redirect(record.get_absolute_url())


@method_decorator(xframe_options_sameorigin, name="dispatch")
class OutgoingFileView(CapabilityRequiredMixin, View):
    """The file of the communication sent, for the PDF viewer or a new tab."""

    capability = "can_view"

    def get(self, request, pk):
        record = get_object_or_404(OutgoingDocument, pk=pk)
        return serve_inline(record.file)


class TransmittalView(OutgoingModuleMixin, ModuleUpdateView):
    """
    Record the communication sent in answer: when, what, to whom and how.

    The LGMED code is not on the form - the record keeps the one the
    assignment issued.
    """

    form_class = OutgoingResponseForm
    module_label = "Outgoing Communication"
    submit_label = "Save communication details"

    def get_object(self, queryset=None):
        record = super().get_object(queryset)
        if record.incoming is None or not record.incoming.may_record_transmittal(
            self.request.user
        ):
            raise PermissionDenied(
                "Only the focal person or the Division Chief may record the "
                "communication sent for this document."
            )
        return record

    def get_initial(self):
        initial = super().get_initial()
        if not self.object.date_sent:
            initial["date_sent"] = timezone.localdate()
        if not self.object.sent_to:
            initial["sent_to"] = self.object.incoming.source_office
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Communication Sent"
        context["page_subtitle"] = (
            f"{self.object.control_code} (DMS {self.object.incoming.docket_number})"
        )
        return context

    def form_valid(self, form):
        self.object = workflow.record_transmittal(
            self.object.incoming, self.request.user, form.save(commit=False)
        )
        messages.success(
            self.request,
            f"The communication sent under {self.object.control_code} was recorded.",
        )
        return redirect(self.object.get_absolute_url())
