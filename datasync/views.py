"""
Data Sync: upload a register, preview what it would change, then commit.

Three steps, three kinds of request. The upload stores the workbook and draws
a preview; the preview page lets the person narrow the sheets and read every
create, update and skip; only the commit writes to the module, and it plans the
file again at that moment so it acts on the records as they then stand.

A migration (the Outgoing register) runs the same way, in four steps the page
shows: upload, preview and validate, confirm, result. Its preview pages
through every row with its status, and the rows not imported can be
downloaded as an Import Error Report.
"""

import logging
import zipfile

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, TemplateView, View
from openpyxl.utils.exceptions import InvalidFileException

from core.mixins import CanEncodeMixin

from . import engine, profiles, report
from .forms import UploadForm
from .models import NOT_IMPORTED, BatchStatus, RowStatus, SyncBatch

logger = logging.getLogger("lgmed.datasync")

# What openpyxl raises for a file that is not a workbook it can read: a renamed
# .xls, a corrupt download, a CSV given an .xlsx extension.
UNREADABLE = (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError, OSError)

ROWS_PER_PAGE = 50

# The preview's row filter: (value, label, statuses shown).
ROW_FILTERS = (
    ("", "All rows", None),
    ("valid", "Valid", (RowStatus.VALID, RowStatus.WARNING, RowStatus.IMPORTED)),
    ("warning", "Warnings", (RowStatus.WARNING,)),
    ("duplicate", "Duplicates", (RowStatus.DUPLICATE,)),
    ("error", "Errors", (RowStatus.ERROR,)),
    ("ignored", "Not records", (RowStatus.IGNORED,)),
)

MIGRATION_STEPS = ("Upload", "Preview & Validate", "Confirm Import", "Migration Result")


def _require(user, profile):
    if not getattr(user, profile.capability, False):
        raise PermissionDenied(
            f"Your role does not permit syncing into {profile.label}."
        )


def _base_context(**extra):
    context = {
        "active_nav": "datasync",
        "page_title": "Data Sync",
        "breadcrumbs": [{"label": "Data Sync"}],
    }
    context.update(extra)
    return context


def _steps(current):
    """The migration's four steps, each marked done, current or to come."""
    return [
        {"number": number, "label": label,
         "state": "done" if number < current else "current" if number == current else "todo"}
        for number, label in enumerate(MIGRATION_STEPS, start=1)
    ]


class SyncHomeView(CanEncodeMixin, TemplateView):
    template_name = "dashboard/sync/home.html"

    def selected_profile(self, form=None):
        key = form.data.get("module") if form is not None and form.is_bound else None
        key = key or self.request.GET.get("module") or "outgoing"
        return profiles.PROFILES.get(key, profiles.OUTGOING)

    def get_context_data(self, form=None, **kwargs):
        context = super().get_context_data(**kwargs)
        selected = self.selected_profile(form)
        if form is None:
            form = UploadForm(user=self.request.user, initial={"module": selected.key})
        user = self.request.user
        context.update(
            _base_context(
                page_title="Data Sync / Data Migration",
                page_subtitle="Bring existing Excel records into the system",
                form=form,
                selected=selected,
                can_upload=getattr(user, selected.capability, False),
                module_tabs=[
                    {"profile": profile,
                     "allowed": getattr(user, profile.capability, False)}
                    for profile in profiles.PROFILES.values()
                ],
                steps=_steps(1),
                batches=SyncBatch.objects.select_related(
                    "uploaded_by", "committed_by"
                )[:20],
            )
        )
        return context

    def post(self, request, *args, **kwargs):
        form = UploadForm(request.POST, request.FILES, user=request.user)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        profile = profiles.get_profile(form.cleaned_data["module"])
        _require(request.user, profile)
        upload = form.cleaned_data["file"]
        batch = SyncBatch.objects.create(
            module=profile.key,
            file=upload,
            original_name=upload.name[:255],
            uploaded_by=request.user,
        )
        try:
            engine.preview(batch)
        except UNREADABLE:
            logger.warning("Could not read uploaded workbook %s", upload.name,
                           exc_info=True)
            batch.delete_file()
            batch.delete()
            form.add_error(
                "file",
                "This file could not be read as an Excel workbook. Save it as "
                ".xlsx in Excel and try again.",
            )
            return self.render_to_response(self.get_context_data(form=form))
        return redirect(batch.get_absolute_url())


class BatchView(CanEncodeMixin, DetailView):
    """The preview, before a commit; the summary, after one."""

    model = SyncBatch
    context_object_name = "batch"
    template_name = "dashboard/sync/batch.html"

    def get_template_names(self):
        if self.object.profile.is_migration:
            return ["dashboard/sync/migration.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object
        summary = batch.summary
        profile = batch.profile
        target = profile.get_target()
        sheet_names = [sheet["name"] for sheet in summary.get("sheets", [])]
        context.update(
            _base_context(
                page_title=(
                    f"Preview: {batch.original_name}" if batch.is_preview
                    else f"Sync summary: {batch.original_name}"
                ),
                page_subtitle=(
                    f"{profile.label} - {batch.get_status_display().lower()}"
                ),
                breadcrumbs=[
                    {"label": "Data Sync", "url": reverse("datasync:home")},
                    {"label": batch.original_name},
                ],
                summary=summary,
                counts=summary.get("counts", {}),
                profile=profile,
                list_url=reverse(target.list_url_name),
                can_commit=(
                    batch.is_preview
                    and getattr(self.request.user, profile.capability, False)
                ),
                selected_sheets=batch.sheets or sheet_names,
            )
        )
        if profile.is_migration:
            context.update(self.migration_context(batch))
        return context

    def migration_context(self, batch):
        chosen = self.request.GET.get("status", "")
        filters = {value: statuses for value, _label, statuses in ROW_FILTERS}
        if chosen not in filters:
            chosen = ""
        rows = batch.rows.all()
        if filters[chosen]:
            rows = rows.filter(status__in=filters[chosen])
        page = Paginator(rows, ROWS_PER_PAGE).get_page(self.request.GET.get("page"))

        counts = batch.counts
        committed = batch.status == BatchStatus.COMMITTED
        return {
            "page_title": (
                f"Outgoing migration: {batch.original_name}" if not committed
                else f"Migration result: {batch.original_name}"
            ),
            "steps": _steps(
                4 if committed else 2 if batch.is_preview else 1
            ),
            "row_filters": [
                {"value": value, "label": label, "active": value == chosen,
                 "count": _filter_count(counts, value)}
                for value, label, _statuses in ROW_FILTERS
            ],
            "status_filter": chosen,
            "page_obj": page,
            "rows": page.object_list,
            "not_imported": batch.rows.filter(status__in=NOT_IMPORTED).exists(),
            "strict_types": bool(batch.options.get("strict_types")),
            "confirm_detail": (
                f"{counts.get('created', 0):,} record(s) will be added to Outgoing "
                "Monitoring under the LGMED codes written in the file."
            ),
            "mapping_sheets": [
                sheet for sheet in batch.summary.get("sheets", [])
                if sheet.get("mapping")
            ],
        }


def _filter_count(counts, value):
    valid = counts.get("created", 0)
    return {
        "": counts.get("total", 0) + counts.get("ignored", 0),
        "valid": valid,
        "warning": counts.get("flagged", 0),
        "duplicate": counts.get("duplicates", 0),
        "error": counts.get("errors", 0),
        "ignored": counts.get("ignored", 0),
    }[value]


class BatchActionView(CanEncodeMixin, View):
    """A POST that acts on a batch still awaiting confirmation."""

    def get(self, request, pk):
        return redirect("datasync:batch", pk=pk)

    def get_batch(self):
        batch = get_object_or_404(SyncBatch, pk=self.kwargs["pk"])
        _require(self.request.user, batch.profile)
        if not batch.is_preview:
            messages.error(
                self.request,
                f"This file has already been {batch.get_status_display().lower()}.",
            )
            return None
        return batch


class SheetSelectionView(BatchActionView):
    """Redraw the preview for the ticked sheets and the chosen options."""

    def post(self, request, pk):
        batch = self.get_batch()
        if batch is None:
            return redirect("datasync:batch", pk=pk)
        names = [sheet["name"] for sheet in batch.summary.get("sheets", [])]
        chosen = [name for name in request.POST.getlist("sheets") if name in names]
        if not chosen:
            messages.error(request, "Choose at least one sheet to sync.")
            return redirect(batch.get_absolute_url())
        batch.sheets = [] if len(chosen) == len(names) else chosen
        if batch.profile.is_migration:
            batch.options = {"strict_types": request.POST.get("strict_types") == "1"}
        batch.save(update_fields=["sheets", "options"])
        engine.preview(batch)
        messages.success(request, "The preview was redrawn.")
        return redirect(batch.get_absolute_url())


class CommitView(BatchActionView):
    def post(self, request, pk):
        batch = self.get_batch()
        if batch is None:
            return redirect("datasync:batch", pk=pk)
        try:
            plan = engine.commit(batch, request.user)
        except engine.AlreadyCommitted:
            messages.error(request, "This file has already been committed.")
            return redirect(batch.get_absolute_url())
        except DatabaseError:
            # The transaction was rolled back: nothing from the file was saved.
            logger.exception("Commit of sync batch %s failed", batch.pk)
            messages.error(
                request,
                "The import stopped because of a database error, and nothing "
                "from this file was saved. Try again; if it happens again, "
                "report it to the system administrator.",
            )
            return redirect(batch.get_absolute_url())
        counts = plan.counts
        if plan.is_migration:
            messages.success(
                request,
                f"Migration completed: {counts['created']} imported, "
                f"{counts['duplicates']} duplicates skipped, "
                f"{counts['errors']} errors skipped.",
            )
        else:
            messages.success(
                request,
                f"{batch.original_name} was synced into {batch.profile.label}: "
                f"{counts['created']} created, {counts['updated']} updated, "
                f"{counts['skipped']} skipped.",
            )
        return redirect(batch.get_absolute_url())


class DiscardView(BatchActionView):
    def post(self, request, pk):
        batch = self.get_batch()
        if batch is None:
            return redirect("datasync:batch", pk=pk)
        batch.delete_file()
        batch.status = BatchStatus.DISCARDED
        batch.save(update_fields=["file", "status"])
        messages.success(
            request, f"{batch.original_name} was discarded. Nothing was changed."
        )
        return redirect(f"{reverse('datasync:home')}?module={batch.module}")


class ErrorReportView(CanEncodeMixin, View):
    """The rows of a migration that were not imported, as an Excel file."""

    def get(self, request, pk):
        batch = get_object_or_404(SyncBatch, pk=pk)
        _require(request.user, batch.profile)
        if not batch.profile.is_migration:
            raise PermissionDenied("Only a migration has an error report.")
        response = HttpResponse(
            report.build(batch),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = content_disposition_header(
            as_attachment=True, filename=report.filename(batch)
        )
        return response
