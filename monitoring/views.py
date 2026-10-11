from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import View

from core.mixins import CanDeleteMixin, CanEncodeMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)
from lgus.models import LGUType, Province

from .forms import MonitoringActivityForm, MonitoringAttachmentForm
from .models import MonitoringActivity, MonitoringAttachment, MonitoringStatus


class MonitoringModuleMixin:
    model = MonitoringActivity
    module_key = "monitoring"
    module_label = "Monitoring Activity"
    module_url_name = "monitoring:list"
    list_label = "Monitoring"
    # Signing off a monitoring activity as completed is an approver's act.
    approval_choices = {"status": (MonitoringStatus.COMPLETED,)}


class MonitoringListView(MonitoringModuleMixin, ModuleListView):
    page_title = "Monitoring"
    page_subtitle = "Monitoring activities, findings and follow-up actions"
    module_label = "Monitoring Activities"
    template_name = "dashboard/monitoring/list.html"
    search_placeholder = "Search activities, LGU, team..."
    search_fields = ("title", "reference_number", "lgu__name", "monitoring_team", "findings")
    sort_fields = ("title", "lgu__name", "monitoring_date", "status")
    default_sort = "-monitoring_date"
    date_field = "monitoring_date"
    date_field_label = "Monitoring date"
    create_url_name = "monitoring:create"
    create_label = "New Monitoring Record"
    empty_icon = "monitoring"
    export_columns = (
        ("Activity", "title"),
        ("Reference", "reference_number"),
        ("LGU", "lgu.name"),
        ("Province", "lgu.province.name"),
        ("Date", "monitoring_date"),
        ("Team", "monitoring_team"),
        ("Status", "get_status_display"),
        ("Follow-up due", "follow_up_date"),
    )

    @property
    def filter_fields(self):
        years = MonitoringActivity.objects.dates("monitoring_date", "year", order="DESC")
        return (
            ("lgu__province", "Province",
             [(str(p.pk), p.name) for p in Province.objects.all()]),
            ("lgu__lgu_type", "LGU type", LGUType.choices),
            ("status", "Status", MonitoringStatus.choices),
            ("monitoring_date__year", "Year", [(d.year, d.year) for d in years]),
        )

    def get_base_queryset(self):
        return MonitoringActivity.objects.select_related(
            "lgu", "lgu__province", "program"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = MonitoringActivity.objects.all()
        today = timezone.localdate()
        context["summary"] = {
            "total": base.count(),
            "for_review": base.filter(status=MonitoringStatus.FOR_REVIEW).count(),
            "completed": base.filter(status=MonitoringStatus.COMPLETED).count(),
            "overdue": base.filter(
                follow_up_date__lt=today,
            ).exclude(
                status__in=(MonitoringStatus.COMPLETED, MonitoringStatus.CANCELLED)
            ).count(),
        }
        return context


class MonitoringDetailView(MonitoringModuleMixin, ModuleDetailView):
    template_name = "dashboard/monitoring/detail.html"

    def get_queryset(self):
        return MonitoringActivity.objects.select_related(
            "lgu", "lgu__province", "program", "created_by", "updated_by"
        ).prefetch_related("attachments")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.title
        context["page_subtitle"] = (
            f"{self.object.lgu} - {self.object.lgu.province}"
        )
        context["attachment_form"] = MonitoringAttachmentForm()
        return context


class MonitoringCreateView(MonitoringModuleMixin, ModuleCreateView):
    form_class = MonitoringActivityForm
    module_label = "Monitoring Record"


class MonitoringUpdateView(MonitoringModuleMixin, ModuleUpdateView):
    form_class = MonitoringActivityForm
    module_label = "Monitoring Record"


class MonitoringDeleteView(MonitoringModuleMixin, ModuleDeleteView):
    module_label = "Monitoring Record"


class AttachmentCreateView(CanEncodeMixin, View):
    """Attach a supporting document to a monitoring activity."""

    def post(self, request, pk):
        activity = get_object_or_404(MonitoringActivity, pk=pk)
        form = MonitoringAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.activity = activity
            attachment.uploaded_by = request.user
            attachment.save()
            messages.success(request, f"'{attachment.title}' was attached to this record.")
        else:
            messages.error(
                request,
                "The file could not be attached. Provide a title and choose a file.",
            )
        return redirect(activity.get_absolute_url())


class AttachmentDeleteView(CanDeleteMixin, View):
    def post(self, request, pk, attachment_pk):
        activity = get_object_or_404(MonitoringActivity, pk=pk)
        attachment = get_object_or_404(
            MonitoringAttachment, pk=attachment_pk, activity=activity
        )
        title = attachment.title
        attachment.delete()
        messages.success(request, f"Attachment '{title}' was removed.")
        return redirect(activity.get_absolute_url())
