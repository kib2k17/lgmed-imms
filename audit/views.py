from django.db.models import Count, Q
from django.utils import timezone
from django.utils.formats import date_format

from core.mixins import CanAdministerMixin
from core.views_base import ModuleDetailView, ModuleListView

from .models import NOTABLE_ACTIONS, Action, AuditEvent


class AuditModuleMixin(CanAdministerMixin):
    model = AuditEvent
    module_key = "audit"
    module_label = "Audit Entry"
    list_label = "Audit Logs"
    module_url_name = "audit:list"


class AuditListView(AuditModuleMixin, ModuleListView):
    """
    The audit trail, read only.

    There is deliberately no create, edit or delete path: an audit log that
    can be edited from inside the system it audits is not evidence of
    anything. Entries are written by signals and removed only by the
    documented retention command.
    """

    page_title = "Audit Logs"
    page_subtitle = "Record of actions performed in the system"
    module_label = "Audit Entries"
    template_name = "dashboard/audit/list.html"
    search_placeholder = "Search actor, record, detail..."
    search_fields = ("actor_label", "target_label", "detail", "ip_address")
    sort_fields = ("timestamp", "actor_label", "action", "target_model")
    default_sort = "-timestamp"
    date_field = "timestamp__date"
    date_field_label = "Date"
    create_url_name = None
    empty_icon = "audit"
    export_columns = (
        ("Timestamp", "timestamp"),
        ("Actor", "actor_label"),
        ("Role", "actor_role"),
        ("Action", "get_action_display"),
        ("Record type", "target_model"),
        ("Record", "target_label"),
        ("Detail", "detail"),
        ("IP address", "ip_address"),
        ("Path", "path"),
    )

    @property
    def filter_fields(self):
        actors = (
            AuditEvent.objects.exclude(actor_label="")
            .values_list("actor_label", flat=True)
            .distinct()
            .order_by("actor_label")
        )
        models = (
            AuditEvent.objects.exclude(target_model="")
            .values_list("target_model", flat=True)
            .distinct()
            .order_by("target_model")
        )
        return (
            ("action", "Action", Action.choices),
            ("target_model", "Record type", [(m, m) for m in models]),
            ("actor_label", "Actor", [(a, a) for a in actors]),
        )

    def get_paginate_by(self, queryset):
        """The log is scanned rather than browsed, so it pages denser."""
        return 30

    def get_base_queryset(self):
        return AuditEvent.objects.select_related("actor")

    def apply_filters(self, queryset):
        # The date range comes from the shared toolbar; only the
        # "needs attention" switch is specific to the log.
        queryset = super().apply_filters(queryset)
        if self.request.GET.get("notable") == "1":
            queryset = queryset.filter(action__in=NOTABLE_ACTIONS)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context["is_filtered"] = context["is_filtered"] or bool(
            params.get("notable")
        )

        since = timezone.now() - timezone.timedelta(days=7)
        recent = AuditEvent.objects.filter(timestamp__gte=since)
        context["summary"] = {
            "total": AuditEvent.objects.count(),
            "week": recent.count(),
            "failed_logins": recent.filter(action=Action.LOGIN_FAILED).count(),
            "deletions": recent.filter(action=Action.DELETE).count(),
        }
        context["date_from"] = params.get("from", "")
        context["date_to"] = params.get("to", "")
        context["notable_only"] = params.get("notable") == "1"
        return context


class AuditDetailView(AuditModuleMixin, ModuleDetailView):
    template_name = "dashboard/audit/detail.html"

    def get_queryset(self):
        return AuditEvent.objects.select_related("actor")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context["page_title"] = event.get_action_display()
        stamp = date_format(timezone.localtime(event.timestamp), "j F Y, g:i A")
        context["page_subtitle"] = f"{event.actor_label} - {stamp}"
        return context
