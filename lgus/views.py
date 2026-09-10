from django.db.models import Count, Max

from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from .forms import LGUForm
from .models import LGU, ComplianceStatus, LGUType, Province


class LGUModuleMixin:
    model = LGU
    module_key = "lgus"
    module_label = "LGU"
    module_url_name = "lgus:list"
    list_label = "LGU Management"


class LGUListView(LGUModuleMixin, ModuleListView):
    page_title = "LGU Management"
    page_subtitle = "Directory of local government units in Region XIII - Caraga"
    module_label = "LGUs"
    template_name = "dashboard/lgus/list.html"
    search_placeholder = "Search LGUs, contact person..."
    search_fields = ("name", "contact_person", "address", "province__name")
    sort_fields = ("name", "lgu_type", "province__name", "compliance_status")
    default_sort = "province__name"
    create_url_name = "lgus:create"
    create_label = "Add LGU"
    empty_icon = "lgu"
    export_columns = (
        ("LGU", "name"),
        ("Type", "get_lgu_type_display"),
        ("Province", "province.name"),
        ("Income class", "get_income_class_display"),
        ("Contact person", "contact_person"),
        ("Contact number", "contact_number"),
        ("Email", "email"),
        ("Compliance", "get_compliance_status_display"),
        ("Latest monitoring", "latest_monitoring_date"),
    )

    @property
    def filter_fields(self):
        return (
            ("province", "Province",
             [(str(p.pk), p.name) for p in Province.objects.all()]),
            ("lgu_type", "LGU type", LGUType.choices),
            ("compliance_status", "Compliance", ComplianceStatus.choices),
        )

    def get_base_queryset(self):
        return (
            LGU.objects.select_related("province")
            .annotate(
                activity_count=Count("monitoring_activities", distinct=True),
                last_monitored=Max("monitoring_activities__monitoring_date"),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = LGU.objects.all()
        context["summary"] = {
            "total": base.count(),
            "provinces": base.filter(lgu_type=LGUType.PROVINCE).count(),
            "cities": base.filter(lgu_type=LGUType.CITY).count(),
            "municipalities": base.filter(lgu_type=LGUType.MUNICIPALITY).count(),
        }
        return context


class LGUDetailView(LGUModuleMixin, ModuleDetailView):
    template_name = "dashboard/lgus/detail.html"

    def get_queryset(self):
        return LGU.objects.select_related("province")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = (
            f"{self.object.get_lgu_type_display()} - {self.object.province}"
        )
        context["activities"] = (
            self.object.monitoring_activities.select_related("lgu")
            .order_by("-monitoring_date")[:10]
        )
        context["programs"] = self.object.programs.select_related("category")[:10]
        return context


class LGUCreateView(LGUModuleMixin, ModuleCreateView):
    form_class = LGUForm
    module_label = "LGU"


class LGUUpdateView(LGUModuleMixin, ModuleUpdateView):
    form_class = LGUForm


class LGUDeleteView(LGUModuleMixin, ModuleDeleteView):
    pass
