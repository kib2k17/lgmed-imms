"""
Generic module views.

Every LGMED-IMMS module presents the same shape of interface: a searchable,
filterable, sortable, paginated table; a record page; a sectioned form; and a
confirmed delete. Building that once here means a new module is a model, a
form and about forty lines of view code - and that search, sorting, export,
pagination and permissions behave identically everywhere.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from . import csv_safe
from .mixins import CanDeleteMixin, CanEncodeMixin


def _filter_or_ignore(queryset, lookup):
    """
    Apply a filter from the query string, or skip it if the value cannot be one.

    The values arrive from the address bar. "?document_type=abc" or
    "?from=yesterday" is a mistyped link, not a server fault: the ORM refuses
    it at once, and the list is shown unfiltered rather than as a 500.
    """
    try:
        return queryset.filter(**lookup)
    except (ValueError, TypeError, ValidationError):
        return queryset


class ModuleContextMixin:
    """Page title, breadcrumb and active navigation item for a module."""

    module_key = ""
    module_label = ""       # singular record noun, e.g. "Monitoring Record"
    list_label = ""         # the module's name in the sidebar, e.g. "Monitoring"
    module_url_name = ""
    page_title = ""
    page_subtitle = ""

    def get_list_label(self):
        return self.list_label or self.module_label

    def get_breadcrumbs(self):
        return [{"label": self.get_list_label()}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.module_key)
        context.setdefault("module_label", self.module_label)
        context.setdefault("module_url_name", self.module_url_name)
        context.setdefault("page_title", self.page_title or self.module_label)
        context.setdefault("page_subtitle", self.page_subtitle)
        context.setdefault("breadcrumbs", self.get_breadcrumbs())
        return context


class ModuleListView(LoginRequiredMixin, ModuleContextMixin, ListView):
    """
    Searchable, filterable, sortable, paginated and exportable record list.

    Declare on the subclass:
        search_fields   ORM lookups searched by the toolbar's search box
        filter_fields   [(param, label, choices)] rendered as select filters
        sort_fields     whitelist of columns the table headers may sort by
        default_sort    ordering applied when no ?sort= is given
    """

    template_name = "dashboard/module_list.html"
    context_object_name = "records"

    search_fields = ()
    filter_fields = ()
    sort_fields = ()
    default_sort = "-id"

    # Filter parameters that appear in the toolbar but are not ORM lookups -
    # "documents awaiting a reply", say, which is a question rather than a
    # column. The module answers them itself in `apply_extra_filters`.
    virtual_filters = ()

    # Set to the model's principal date field to offer a from/to range in the
    # toolbar. `date_field_label` names it for the person using it.
    date_field = None
    date_field_label = "Date"

    search_placeholder = "Search records..."
    create_url_name = None
    create_label = None
    exportable = True
    export_columns = ()          # [(header, ORM lookup or callable)]
    empty_icon = "inbox"

    # -- pagination ----------------------------------------------------

    paginate_by = 15  # fallback; System Settings is the source of truth

    def get_paginate_by(self, queryset):
        """Honour the administrator's `records_per_page` setting."""
        if self.paginate_by is None:
            return None
        from administration.models import SystemSetting

        return SystemSetting.load().records_per_page

    # -- querying ------------------------------------------------------

    def get_base_queryset(self):
        return super().get_queryset()

    def get_queryset(self):
        queryset = self.get_base_queryset()
        queryset = self.apply_search(queryset)
        queryset = self.apply_filters(queryset)
        return self.apply_sort(queryset)

    def apply_search(self, queryset):
        term = self.request.GET.get("q", "").strip()
        if not term or not self.search_fields:
            return queryset
        query = Q()
        for field in self.search_fields:
            query |= Q(**{f"{field}__icontains": term})
        return queryset.filter(query)

    def apply_filters(self, queryset):
        for param, _label, _choices in self.filter_fields:
            if param in self.virtual_filters:
                continue
            values = [v for v in self.request.GET.getlist(param) if v.strip()]
            if not values:
                continue
            # A repeated parameter means "any of these" - the filter selects
            # rather than narrowing to the last value the browser happened to send.
            lookup = {param: values[0]} if len(values) == 1 else {f"{param}__in": values}
            queryset = _filter_or_ignore(queryset, lookup)
        queryset = self.apply_extra_filters(queryset)
        return self.apply_date_range(queryset)

    def apply_extra_filters(self, queryset):
        """Hook for filters a module answers itself. See `virtual_filters`."""
        return queryset

    def apply_date_range(self, queryset):
        """Narrow to a from/to range on `date_field`, if the module declares one."""
        if not self.date_field:
            return queryset
        start = self.request.GET.get("from", "").strip()
        end = self.request.GET.get("to", "").strip()
        if start:
            queryset = _filter_or_ignore(queryset, {f"{self.date_field}__gte": start})
        if end:
            queryset = _filter_or_ignore(queryset, {f"{self.date_field}__lte": end})
        return queryset

    def apply_sort(self, queryset):
        requested = self.request.GET.get("sort", "").strip()
        field = requested.lstrip("-")
        if field and field in self.sort_fields:
            return queryset.order_by(requested)
        return queryset.order_by(self.default_sort)

    # -- CSV export ----------------------------------------------------

    def get(self, request, *args, **kwargs):
        if self.exportable and request.GET.get("export") == "csv":
            return self.export_csv()
        return super().get(request, *args, **kwargs)

    def export_csv(self):
        """Export the *filtered* queryset, so what you see is what you get."""
        from audit.models import Action
        from audit.recording import record
        stamp = timezone.localtime().strftime("%Y%m%d")
        name = slugify(self.module_label or "records")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="lgmed-imms-{name}-{stamp}.csv"'
        )
        response.write("﻿")  # BOM, so Excel opens UTF-8 correctly

        writer = csv_safe.writer(response)
        columns = self.export_columns or [("ID", "pk")]
        writer.writerow([header for header, _ in columns])

        rows = 0
        # Named `item`, not `record`: `record` is the audit function imported
        # above, and shadowing it here made the export blow up on its own log line.
        for item in self.get_queryset():
            row = []
            for _header, accessor in columns:
                value = accessor(item) if callable(accessor) else item
                if not callable(accessor):
                    for part in accessor.split("."):
                        value = getattr(value, part, "")
                        if value is None:
                            value = ""
                            break
                    if callable(value):
                        value = value()
                row.append(str(value))
            writer.writerow(row)
            rows += 1

        record(
            Action.EXPORT,
            detail=(
                f"Exported {rows} {self.module_label.lower()}"
                + (" matching the active filters" if self.is_filtered() else "")
            ),
            request=self.request,
        )
        return response

    def is_filtered(self):
        params = self.request.GET
        return bool(
            params.get("q")
            or params.get("from")
            or params.get("to")
            or any(params.get(name) for name, _, _ in self.filter_fields)
        )

    # -- context -------------------------------------------------------

    def get_filters_context(self):
        return [
            {
                "name": param,
                "label": label,
                "options": list(choices),
                "selected": self.request.GET.get(param, ""),
            }
            for param, label, choices in self.filter_fields
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context.update(
            {
                "filters": self.get_filters_context(),
                "search_placeholder": self.search_placeholder,
                "total_count": self.get_base_queryset().count(),
                "is_filtered": self.is_filtered(),
                "date_field": self.date_field,
                "date_field_label": self.date_field_label,
                "date_from": params.get("from", ""),
                "date_to": params.get("to", ""),
                "empty_icon": self.empty_icon,
                "exportable": self.exportable,
                "can_create": (
                    self.create_url_name and self.request.user.can_encode
                ),
                "create_url_name": self.create_url_name,
                "create_label": self.create_label or f"Add {self.module_label}",
            }
        )
        return context


class ModuleDetailView(LoginRequiredMixin, ModuleContextMixin, DetailView):
    context_object_name = "record"

    def get_breadcrumbs(self):
        return [
            {"label": self.get_list_label(), "url": self.get_list_url()},
            {"label": str(self.object)},
        ]

    def get_list_url(self):
        from django.urls import reverse

        return reverse(self.module_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = str(self.object)
        context["list_url"] = self.get_list_url()
        return context


class ModuleFormMixin(ModuleContextMixin):
    """Shared behaviour for the create and edit forms."""

    template_name = "dashboard/module_form.html"

    # Approving and publishing are `can_approve`'s, not every encoder's
    # (accounts/capabilities.py). A module names the form fields that publish
    # (`approval_fields`, removed for everyone else, so the stored value is
    # kept) and the choice values that approve (`approval_choices`, withheld
    # from everyone else; a record already in one of them keeps it). Enforced
    # on the form the server builds, so a hand-made POST carries no more
    # weight than the page it pretends to come from.
    approval_fields = ()
    approval_choices = {}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        restricted = self.approval_fields or self.approval_choices
        if restricted and not getattr(self.request.user, "can_approve", False):
            # Handed to GovModelForm, which applies it before the bound form
            # is first validated - removing a field afterwards is too late.
            kwargs["restrict_fields"] = self.restrict_to_non_approver
        return kwargs

    def restrict_to_non_approver(self, form):
        for name in self.approval_fields:
            form.fields.pop(name, None)
        for name, reserved in self.approval_choices.items():
            field = form.fields.get(name)
            if field is None:
                continue
            current = getattr(form.instance, name, None) if form.instance.pk else None
            if current in reserved:
                field.disabled = True
                field.help_text = "Set by an approver. Your changes keep it as it is."
            else:
                field.choices = [c for c in field.choices if c[0] not in reserved]

    def get_list_url(self):
        from django.urls import reverse

        return reverse(self.module_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["list_url"] = self.get_list_url()
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.get_cancel_url()
        return context

    def get_cancel_url(self):
        if getattr(self, "object", None) and self.object.pk:
            return self.object.get_absolute_url()
        return self.get_list_url()

    def form_invalid(self, form):
        messages.error(
            self.request,
            "The record could not be saved. Correct the highlighted fields "
            "and try again.",
        )
        return super().form_invalid(form)


class ModuleCreateView(CanEncodeMixin, ModuleFormMixin, CreateView):
    submit_label = "Save"

    def get_breadcrumbs(self):
        return [
            {"label": self.get_list_label(), "url": self.get_list_url()},
            {"label": f"New {self.module_label}"},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"New {self.module_label}"
        context["page_subtitle"] = "Complete the required fields marked with an asterisk"
        return context

    def form_valid(self, form):
        if hasattr(form.instance, "created_by_id") and not form.instance.created_by_id:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object} was created successfully.")
        return response


class ModuleUpdateView(CanEncodeMixin, ModuleFormMixin, UpdateView):
    submit_label = "Save changes"

    def get_breadcrumbs(self):
        return [
            {"label": self.get_list_label(), "url": self.get_list_url()},
            {"label": str(self.object), "url": self.object.get_absolute_url()},
            {"label": "Edit"},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.module_label}"
        context["page_subtitle"] = str(self.object)
        return context

    def form_valid(self, form):
        if hasattr(form.instance, "updated_by_id"):
            form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Changes to {self.object} were saved.")
        return response


class ModuleDeleteView(CanDeleteMixin, ModuleContextMixin, DeleteView):
    """
    Confirmed deletion.

    GET renders a full confirmation page so the action is never a single click
    and remains available without JavaScript; the in-page dialog posts to the
    same URL.
    """

    template_name = "dashboard/module_confirm_delete.html"
    context_object_name = "record"

    def get_list_url(self):
        from django.urls import reverse

        return reverse(self.module_url_name)

    def get_success_url(self):
        return self.get_list_url()

    def get_breadcrumbs(self):
        return [
            {"label": self.get_list_label(), "url": self.get_list_url()},
            {"label": str(self.object), "url": self.object.get_absolute_url()},
            {"label": "Delete"},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Delete {self.module_label}?"
        context["page_subtitle"] = str(self.object)
        context["cancel_url"] = self.object.get_absolute_url()
        return context

    def form_valid(self, form):
        label = str(self.object)
        response = super().form_valid(form)
        messages.success(self.request, f"{label} was deleted.")
        return response
