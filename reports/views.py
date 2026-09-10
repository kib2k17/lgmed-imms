from core.views_base import (
    ModuleCreateView, ModuleDeleteView, ModuleDetailView,
    ModuleListView, ModuleUpdateView,
)

from .forms import ReportForm
from .models import Report, ReportPeriod, ReportStatus


class ReportModuleMixin:
    model = Report
    module_key = "reports"
    module_label = "Report"
    module_url_name = "reports:list"
    list_label = "Reports"


class ReportListView(ReportModuleMixin, ModuleListView):
    page_title = "Reports"
    page_subtitle = "Report submissions, review and publication"
    module_label = "Reports"
    template_name = "dashboard/reports/list.html"
    search_placeholder = "Search reports..."
    search_fields = ("title", "reference_number", "summary", "prepared_by")
    sort_fields = ("title", "period", "year", "status", "submitted_on")
    default_sort = "-year"
    date_field = "submitted_on"
    date_field_label = "Submitted"
    create_url_name = "reports:create"
    create_label = "Add Report"
    empty_icon = "reports"
    export_columns = (
        ("Report", "title"),
        ("Reference", "reference_number"),
        ("Period", "get_period_display"),
        ("Year", "year"),
        ("Prepared by", "prepared_by"),
        ("Status", "get_status_display"),
        ("Submitted", "submitted_on"),
        ("Published", "published_on"),
    )

    @property
    def filter_fields(self):
        years = Report.objects.values_list("year", flat=True).distinct().order_by("-year")
        return (
            ("period", "Period", ReportPeriod.choices),
            ("year", "Year", [(y, y) for y in years]),
            ("status", "Status", ReportStatus.choices),
        )

    def get_base_queryset(self):
        return Report.objects.select_related("program", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = Report.objects.all()
        context["summary"] = {
            "total": base.count(),
            "pending": base.filter(status__in=(
                ReportStatus.DRAFT, ReportStatus.SUBMITTED,
                ReportStatus.FOR_REVIEW, ReportStatus.RETURNED,
            )).count(),
            "approved": base.filter(status=ReportStatus.APPROVED).count(),
            "published": base.filter(status=ReportStatus.PUBLISHED).count(),
        }
        return context


class ReportDetailView(ReportModuleMixin, ModuleDetailView):
    template_name = "dashboard/reports/detail.html"

    def get_queryset(self):
        return Report.objects.select_related("program", "created_by", "updated_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = (
            f"{self.object.get_period_display()} - {self.object.year}"
        )
        return context


class ReportCreateView(ReportModuleMixin, ModuleCreateView):
    form_class = ReportForm


class ReportUpdateView(ReportModuleMixin, ModuleUpdateView):
    form_class = ReportForm


class ReportDeleteView(ReportModuleMixin, ModuleDeleteView):
    pass
