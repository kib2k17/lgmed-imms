from core.views_base import (
    ModuleCreateView, ModuleDeleteView, ModuleDetailView,
    ModuleListView, ModuleUpdateView,
)

from .forms import FrontlineServiceForm
from .models import FrontlineService, ServiceType


class ServiceModuleMixin:
    model = FrontlineService
    module_key = "services"
    module_label = "Frontline Service"
    module_url_name = "services:list"
    list_label = "Frontline Services"


class ServiceListView(ServiceModuleMixin, ModuleListView):
    page_title = "Frontline Services"
    page_subtitle = "Services delivered by the Division to LGUs and the public"
    module_label = "Frontline Services"
    template_name = "dashboard/services/list.html"
    search_placeholder = "Search services..."
    search_fields = ("name", "description", "clients", "responsible_person")
    sort_fields = ("name", "service_type", "processing_time")
    default_sort = "name"
    create_url_name = "services:create"
    create_label = "Add Service"
    empty_icon = "services"
    filter_fields = (
        ("service_type", "Service type", ServiceType.choices),
        ("is_published", "Publication", [("True", "Published"), ("False", "Not published")]),
    )
    export_columns = (
        ("Service", "name"),
        ("Type", "get_service_type_display"),
        ("Clients", "clients"),
        ("Processing time", "processing_time"),
        ("Fees", "fees"),
        ("Responsible person", "responsible_person"),
        ("Published", "is_published"),
    )


class ServiceDetailView(ServiceModuleMixin, ModuleDetailView):
    template_name = "dashboard/services/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = self.object.get_service_type_display()
        return context


class ServiceCreateView(ServiceModuleMixin, ModuleCreateView):
    form_class = FrontlineServiceForm


class ServiceUpdateView(ServiceModuleMixin, ModuleUpdateView):
    form_class = FrontlineServiceForm


class ServiceDeleteView(ServiceModuleMixin, ModuleDeleteView):
    pass
