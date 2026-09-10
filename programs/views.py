from core.views_base import (
    ModuleCreateView, ModuleDeleteView, ModuleDetailView,
    ModuleListView, ModuleUpdateView,
)

from .forms import ProgramForm
from .models import Program, ProgramCategory, ProgramStatus


class ProgramModuleMixin:
    model = Program
    module_key = "programs"
    module_label = "Program"
    module_url_name = "programs:list"
    list_label = "Programs"


class ProgramListView(ProgramModuleMixin, ModuleListView):
    page_title = "Programs"
    page_subtitle = "Programs and projects administered by the Division"
    module_label = "Programs"
    template_name = "dashboard/programs/list.html"
    search_placeholder = "Search programs..."
    search_fields = ("title", "reference_number", "description", "focal_person")
    sort_fields = ("title", "category__name", "status", "start_date")
    default_sort = "-start_date"
    date_field = "start_date"
    date_field_label = "Start date"
    create_url_name = "programs:create"
    create_label = "Add Program"
    empty_icon = "programs"
    export_columns = (
        ("Program", "title"),
        ("Reference", "reference_number"),
        ("Category", "category.name"),
        ("Status", "get_status_display"),
        ("Start date", "start_date"),
        ("End date", "end_date"),
        ("Focal person", "focal_person"),
        ("Coverage", "coverage_label"),
    )

    @property
    def filter_fields(self):
        years = (
            Program.objects.dates("start_date", "year", order="DESC")
        )
        return (
            ("category", "Category",
             [(str(c.pk), c.name) for c in ProgramCategory.objects.filter(is_active=True)]),
            ("status", "Status", ProgramStatus.choices),
            ("start_date__year", "Year", [(d.year, d.year) for d in years]),
        )

    def get_base_queryset(self):
        return Program.objects.select_related("category").prefetch_related("covered_lgus")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = Program.objects.all()
        context["summary"] = {
            "total": base.count(),
            "active": base.filter(status=ProgramStatus.ACTIVE).count(),
            "completed": base.filter(status=ProgramStatus.COMPLETED).count(),
            "pending": base.filter(status=ProgramStatus.PENDING).count(),
        }
        return context


class ProgramDetailView(ProgramModuleMixin, ModuleDetailView):
    template_name = "dashboard/programs/detail.html"

    def get_queryset(self):
        return Program.objects.select_related("category").prefetch_related(
            "covered_lgus__province"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = self.object.category.name
        context["activities"] = self.object.monitoring_activities.select_related(
            "lgu", "lgu__province"
        ).order_by("-monitoring_date")[:10]
        context["reports"] = self.object.reports.all()[:10]
        return context


class ProgramCreateView(ProgramModuleMixin, ModuleCreateView):
    form_class = ProgramForm


class ProgramUpdateView(ProgramModuleMixin, ModuleUpdateView):
    form_class = ProgramForm


class ProgramDeleteView(ProgramModuleMixin, ModuleDeleteView):
    pass
