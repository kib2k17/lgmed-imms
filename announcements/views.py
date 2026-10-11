from core.views_base import (
    ModuleCreateView, ModuleDeleteView, ModuleDetailView,
    ModuleListView, ModuleUpdateView,
)

from .forms import AnnouncementForm
from .models import Announcement, AnnouncementCategory


class AnnouncementModuleMixin:
    model = Announcement
    module_key = "announcements"
    module_label = "Announcement"
    module_url_name = "announcements:list"
    list_label = "Announcements"
    # Putting an item on the public website is an approver's decision.
    approval_fields = ("is_published", "is_featured")


class AnnouncementListView(AnnouncementModuleMixin, ModuleListView):
    page_title = "Announcements"
    page_subtitle = "News, advisories and commendations for the public website"
    template_name = "dashboard/announcements/list.html"
    search_placeholder = "Search announcements..."
    search_fields = ("title", "summary", "body", "location")
    sort_fields = ("title", "category", "published_on", "is_published")
    default_sort = "-published_on"
    date_field = "published_on"
    date_field_label = "Date published"
    create_url_name = "announcements:create"
    create_label = "Add Announcement"
    empty_icon = "announcements"
    filter_fields = (
        ("category", "Category", AnnouncementCategory.choices),
        ("is_published", "Publication", [("True", "Published"), ("False", "Draft")]),
    )
    export_columns = (
        ("Headline", "title"),
        ("Category", "get_category_display"),
        ("Date published", "published_on"),
        ("Location", "location"),
        ("Published", "is_published"),
        ("Featured", "is_featured"),
    )


class AnnouncementDetailView(AnnouncementModuleMixin, ModuleDetailView):
    template_name = "dashboard/announcements/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = "{} · {:%d %B %Y}".format(
            self.object.get_category_display(), self.object.published_on
        )
        return context


class AnnouncementCreateView(AnnouncementModuleMixin, ModuleCreateView):
    form_class = AnnouncementForm


class AnnouncementUpdateView(AnnouncementModuleMixin, ModuleUpdateView):
    form_class = AnnouncementForm


class AnnouncementDeleteView(AnnouncementModuleMixin, ModuleDeleteView):
    pass
