import django
from django.conf import settings as django_settings
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import UpdateView

from audit.models import AuditEvent
from core.consumers import broadcast_notice
from core.forms_base import GovModelForm
from core.mixins import CanAdministerMixin, CanApproveMixin, administrator_required

from .models import PublicSiteContent, SystemSetting
from .reference import get_list, summarise


class SystemSettingForm(GovModelForm):
    class Meta:
        model = SystemSetting
        fields = [
            "records_per_page",
            "session_notice_minutes",
            "notice_message",
            "notice_level",
            "notice_takeover",
            "public_site_enabled",
        ]

    fieldsets = [
        ("Display", ["records_per_page", "session_notice_minutes"]),
        ("System notice", ["notice_message", "notice_level", "notice_takeover"]),
        ("Public website", ["public_site_enabled"]),
    ]
    wide_fields = ("notice_message",)


class SettingsView(CanAdministerMixin, UpdateView):
    """System-wide preferences. Every field here changes something visible."""

    model = SystemSetting
    form_class = SystemSettingForm
    template_name = "dashboard/settings/settings.html"

    def get_object(self, queryset=None):
        return SystemSetting.load()

    def get_success_url(self):
        return reverse("administration:settings")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "active_nav": "settings",
                "page_title": "System Settings",
                "page_subtitle": "Preferences, reference data and system information",
                "breadcrumbs": [{"label": "System Settings"}],
                "reference_lists": summarise(),
                "system_info": system_information(),
            }
        )
        return context

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        notice_fields = {"notice_message", "notice_level", "notice_takeover"}
        notice_changed = bool(notice_fields & set(form.changed_data))
        if notice_changed:
            # A changed notice is a new notice: everyone who acknowledged the
            # last one sees this one.
            form.instance.notice_posted_at = timezone.now()
        response = super().form_valid(form)
        if notice_changed:
            # Pushed to every open page once the change is committed, so no
            # page is told about a notice the database does not yet hold.
            notice = self.object.notice_payload()
            transaction.on_commit(lambda: broadcast_notice(notice))
        messages.success(self.request, "System settings were saved.")
        return response

    def form_invalid(self, form):
        messages.error(
            self.request, "The settings could not be saved. Check the fields below."
        )
        return super().form_invalid(form)


def system_information():
    """
    Facts about the deployment, for the ICT personnel who look after it.

    Read-only and derived - nothing here is a setting pretending to be a fact.
    """
    database = django_settings.DATABASES["default"]
    return [
        ("System", "LGMED-iMMS"),
        ("Django version", django.get_version()),
        ("Database engine", database["ENGINE"].rsplit(".", 1)[-1]),
        ("Time zone", django_settings.TIME_ZONE),
        ("Language", django_settings.LANGUAGE_CODE),
        (
            "Debug mode",
            "On - development only" if django_settings.DEBUG else "Off",
        ),
        ("Session length", f"{django_settings.SESSION_COOKIE_AGE // 3600} hours"),
        ("Media storage", str(django_settings.MEDIA_ROOT)),
        ("Audit entries held", AuditEvent.objects.count()),
        (
            "Server time",
            timezone.localtime().strftime("%d %B %Y, %I:%M %p"),
        ),
    ]


# ---------------------------------------------------------------------------
# Reference lists
# ---------------------------------------------------------------------------


@administrator_required
def reference_form(request, slug, pk=None):
    """Add or edit one entry in a reference list."""
    spec = get_list(slug)
    if spec is None:
        raise Http404("No such reference list.")

    instance = get_object_or_404(spec["model"], pk=pk) if pk else None
    form_class = spec["form"]
    form = form_class(request.POST or None, instance=instance)

    if request.method == "POST" and form.is_valid():
        entry = form.save()
        messages.success(
            request,
            f"{spec['label']} '{entry}' was "
            f"{'updated' if pk else 'added'}.",
        )
        return redirect(reverse("administration:settings") + f"#{slug}")

    return render(
        request,
        "dashboard/settings/reference_form.html",
        {
            "form": form,
            "spec": spec,
            "slug": slug,
            "instance": instance,
            "active_nav": "settings",
            "page_title": f"{'Edit' if pk else 'Add'} {spec['label'].lower()}",
            "page_subtitle": spec["description"],
            "breadcrumbs": [
                {"label": "System Settings", "url": reverse("administration:settings")},
                {"label": spec["plural"]},
                {"label": "Edit" if pk else "Add"},
            ],
            "cancel_url": reverse("administration:settings") + f"#{slug}",
            "submit_label": "Save changes" if pk else f"Add {spec['label'].lower()}",
        },
    )


@administrator_required
def reference_delete(request, slug, pk):
    """
    Remove an entry from a reference list.

    An entry that records still point at is protected by the database. Rather
    than showing the user a 500, the refusal is explained: deactivate it
    instead, which keeps existing records readable while removing it from the
    dropdowns.
    """
    spec = get_list(slug)
    if spec is None:
        raise Http404("No such reference list.")

    entry = get_object_or_404(spec["model"], pk=pk)
    target = reverse("administration:settings") + f"#{slug}"

    if request.method != "POST":
        return redirect(target)

    label = str(entry)
    try:
        entry.delete()
    except ProtectedError:
        messages.error(
            request,
            f"'{label}' cannot be removed because records still refer to it. "
            "Deactivate it instead: existing records keep their classification "
            "and it stops being offered on new ones.",
        )
    else:
        messages.success(request, f"{spec['label']} '{label}' was removed.")
    return redirect(target)


# ---------------------------------------------------------------------------
# The public website's backend
# ---------------------------------------------------------------------------


class PublicSiteContentForm(GovModelForm):
    class Meta:
        model = PublicSiteContent
        fields = [
            "hero_heading", "hero_lead", "mandate_intro",
            "about_intro", "core_functions",
            "address", "telephone", "email", "office_hours", "facebook_url",
            "privacy_notice", "accessibility_statement",
        ]

    fieldsets = [
        ("Homepage", ["hero_heading", "hero_lead", "mandate_intro"]),
        ("About the Division", ["about_intro", "core_functions"]),
        ("Office details", ["address", "telephone", "email", "office_hours",
                            "facebook_url"]),
        ("Standing notices", ["privacy_notice", "accessibility_statement"]),
    ]
    wide_fields = (
        "hero_heading", "hero_lead", "mandate_intro", "about_intro",
        "core_functions", "address", "facebook_url", "privacy_notice",
        "accessibility_statement",
    )
    textarea_rows = 5


class PublicSiteView(CanApproveMixin, UpdateView):
    """
    Where the public website is managed.

    Two things in one place, because they are one job: what is published on
    the site right now - counted from the records, each figure a link to the
    module that owns it - and the standing copy that is not a record.
    """

    model = PublicSiteContent
    form_class = PublicSiteContentForm
    template_name = "dashboard/settings/public_site.html"

    def get_object(self, queryset=None):
        return PublicSiteContent.load()

    def get_success_url(self):
        return reverse("administration:public_site")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "active_nav": "public_site",
                "page_title": "Public Website",
                "page_subtitle": (
                    "What the public sees, and the text the Division controls"
                ),
                "breadcrumbs": [{"label": "Public Website"}],
                "published_content": published_content(),
                "site_enabled": SystemSetting.load().public_site_enabled,
            }
        )
        return context

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request, "The public website content was updated."
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "The content could not be saved. Correct the highlighted fields "
            "and try again.",
        )
        return super().form_invalid(form)


def published_content():
    """
    What is live on the public site, and what is waiting behind a flag.

    Each row counts the records the public can actually see against the total
    held, so an officer can tell at a glance that, say, nine of eleven reports
    are still unpublished - and reach the module that fixes it.
    """
    from activities.models import CalendarActivity
    from announcements.models import Announcement
    from documents.models import Document
    from programs.models import Program, ProgramStatus
    from reports.models import Report, ReportStatus
    from services.models import FrontlineService

    return [
        {
            "label": "News items",
            "icon": "announcements",
            "public": Announcement.objects.published().count(),
            "total": Announcement.objects.count(),
            "url_name": "announcements:list",
            "note": "Published, and dated today or earlier",
        },
        {
            "label": "Programs",
            "icon": "programs",
            "public": Program.objects.filter(
                status__in=(ProgramStatus.ACTIVE, ProgramStatus.COMPLETED)
            ).count(),
            "total": Program.objects.count(),
            "url_name": "programs:list",
            "note": "Active and completed programs are shown",
        },
        {
            "label": "Frontline services",
            "icon": "services",
            "public": FrontlineService.objects.filter(is_published=True).count(),
            "total": FrontlineService.objects.count(),
            "url_name": "services:list",
            "note": "Marked as published",
        },
        {
            "label": "Documents",
            "icon": "documents",
            "public": Document.objects.public().count(),
            "total": Document.objects.count(),
            "url_name": "documents:list",
            "note": "Completed and marked available publicly",
        },
        {
            "label": "Reports",
            "icon": "reports",
            "public": Report.objects.filter(status=ReportStatus.PUBLISHED).count(),
            "total": Report.objects.count(),
            "url_name": "reports:list",
            "note": "Status is Published",
        },
        {
            "label": "Calendar activities",
            "icon": "calendar",
            "public": CalendarActivity.objects.filter(
                is_published=True, start_date__gte=timezone.localdate()
            ).count(),
            "total": CalendarActivity.objects.count(),
            "url_name": "activities:list",
            "note": "Published and still to come",
        },
    ]
