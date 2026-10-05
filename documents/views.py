"""
Document Management.

The register, the record page, the monitoring dashboard and the retention
register are ordinary module views. The workflow actions are deliberately not:
each is a POST to its own URL, handled by a small view that validates a form
and hands the record to `documents.workflow`. Nothing here decides who may do
what - the workflow functions raise `PermissionDenied` themselves, so an action
taken through the shell or a management command is refused on the same terms as
one taken through a button.

Files are never served straight from MEDIA_URL. Every download goes through
`DocumentDownloadView`, which re-checks access and writes the download to the
document's trail; a register that logs who downloaded what, while also handing
out unguessable-but-permanent URLs that bypass the log, is only pretending to.
"""

import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView, View

from core.files import serve_inline
from core.mixins import CapabilityRequiredMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from . import workflow
from .forms import (
    ArchiveForm,
    AssignmentForm,
    CancelForm,
    DisposalForm,
    DocumentForm,
    RestoreForm,
    RetentionForm,
    ReviewForm,
    StatusNoteForm,
    VersionUploadForm,
)
from .models import (
    RETENTION_WARNING_DAYS,
    Document,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
    EventType,
    FileSource,
    RetentionDisposition,
    SupportingFile,
)

# The quick views offered beside the ordinary filters. Each is a question an
# officer actually asks of the register, expressed once here and reused by the
# dashboard's clickable figures.
QUICK_VIEWS = (
    ("mine", "Owned by me"),
    ("assigned_to_me", "Assigned to me"),
    ("involving_me", "Involving me"),
    ("unassigned", "Not yet assigned"),
    ("open", "Open (in circulation)"),
    ("overdue", "Overdue"),
    ("retention_due", "Retention review due"),
    ("retention_soon", "Retention approaching"),
    ("for_disposal", "Marked for disposal"),
    ("archived", "Archived"),
)

# The date the toolbar's from/to range applies to.
DATE_BASES = {
    "received": ("date_received", "Date received"),
    "created": ("date_created", "Date of document"),
    "registered": ("created_at__date", "Date registered"),
    "completed": ("completed_at__date", "Date completed"),
    "retention": ("retention_until", "Retention ends"),
}
DEFAULT_BASIS = "received"

# Where an entry came from. Incoming and Outgoing Monitoring register their
# documents here themselves; see incoming/register.py.
SOURCES = (
    ("incoming", "Incoming Monitoring"),
    ("outgoing", "Outgoing Monitoring"),
    ("direct", "Registered here"),
)


class DocumentModuleMixin:
    model = Document
    module_key = "documents"
    module_label = "Document"
    module_url_name = "documents:list"
    list_label = "Documents"


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def summarise(user):
    """The figures shown above the register and on the monitoring dashboard."""
    base = Document.objects.all()
    today = timezone.localdate()

    counts = base.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status=DocumentStatus.DRAFT)),
        received=Count("pk", filter=Q(status=DocumentStatus.RECEIVED)),
        for_review=Count("pk", filter=Q(status=DocumentStatus.FOR_REVIEW)),
        for_assignment=Count("pk", filter=Q(status=DocumentStatus.FOR_ASSIGNMENT)),
        assigned=Count("pk", filter=Q(status=DocumentStatus.ASSIGNED)),
        in_progress=Count("pk", filter=Q(status=DocumentStatus.IN_PROGRESS)),
        for_approval=Count("pk", filter=Q(status=DocumentStatus.FOR_APPROVAL)),
        completed=Count("pk", filter=Q(status=DocumentStatus.COMPLETED)),
        archived=Count("pk", filter=Q(status=DocumentStatus.ARCHIVED)),
        cancelled=Count("pk", filter=Q(status=DocumentStatus.CANCELLED)),
    )
    counts["open"] = base.open().count()
    counts["overdue"] = base.overdue(today).count()
    counts["retention_due"] = base.retention_due(today).count()
    counts["retention_soon"] = base.retention_approaching(today=today).count()
    counts["for_disposal"] = base.for_disposal().count()
    counts["public"] = base.public().count()
    counts["mine"] = base.owned_by(user).count() if user.is_authenticated else 0
    counts["assigned_to_me"] = (
        base.assigned_to(user).open().count() if user.is_authenticated else 0
    )
    return counts


def stat_links(counts):
    """
    The dashboard's figures, each one a link to the documents behind it.

    A figure an officer cannot click through to is a figure they have to take
    on trust; every one of these opens the register already filtered.
    """
    url = reverse("documents:list")

    def link(**params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{url}?{query}" if query else url

    return [
        {"label": "Total documents", "value": counts["total"], "url": link(),
         "tone": "", "icon": "documents"},
        {"label": "Newly received", "value": counts["received"],
         "url": link(status=DocumentStatus.RECEIVED), "tone": "", "icon": "inbox"},
        {"label": "For review", "value": counts["for_review"],
         "url": link(status=DocumentStatus.FOR_REVIEW), "tone": "warning",
         "icon": "clock"},
        {"label": "For assignment", "value": counts["for_assignment"],
         "url": link(status=DocumentStatus.FOR_ASSIGNMENT), "tone": "warning",
         "icon": "users"},
        {"label": "Assigned", "value": counts["assigned"],
         "url": link(status=DocumentStatus.ASSIGNED), "tone": "", "icon": "users"},
        {"label": "In progress", "value": counts["in_progress"],
         "url": link(status=DocumentStatus.IN_PROGRESS), "tone": "",
         "icon": "monitoring"},
        {"label": "For approval", "value": counts["for_approval"],
         "url": link(status=DocumentStatus.FOR_APPROVAL), "tone": "warning",
         "icon": "check"},
        {"label": "Overdue", "value": counts["overdue"], "url": link(view="overdue"),
         "tone": "danger", "icon": "warning"},
        {"label": "Completed", "value": counts["completed"],
         "url": link(status=DocumentStatus.COMPLETED), "tone": "success",
         "icon": "check-circle"},
        {"label": "Archived", "value": counts["archived"],
         "url": link(status=DocumentStatus.ARCHIVED), "tone": "", "icon": "lock"},
        {"label": "Retention approaching", "value": counts["retention_soon"],
         "url": link(view="retention_soon"), "tone": "warning", "icon": "clock"},
        {"label": "Retention review due", "value": counts["retention_due"],
         "url": link(view="retention_due"), "tone": "danger", "icon": "warning"},
    ]


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------


class DocumentListView(DocumentModuleMixin, ModuleListView):
    page_title = "Document Management"
    page_subtitle = (
        "Every document received, created, submitted or processed by the Division"
    )
    module_label = "Documents"
    template_name = "dashboard/documents/list.html"
    search_placeholder = "Search control number, title, subject, sender..."
    search_fields = (
        "reference_number", "title", "subject", "sender", "description",
        "remarks", "office",
    )
    sort_fields = (
        "reference_number", "title", "document_type__name", "year", "status",
        "date_received", "date_created", "due_date", "owner__last_name",
        "assigned_to__last_name", "retention_until", "created_at",
    )
    default_sort = "-created_at"
    create_url_name = "documents:create"
    create_label = "Register Document"
    empty_icon = "documents"
    virtual_filters = ("view", "basis", "source")
    export_columns = (
        ("Control number", "reference_number"),
        ("Source", "source_label"),
        ("Title", "title"),
        ("Subject", "subject"),
        ("Type", "document_type.name"),
        ("Sender / source", "sender"),
        ("Date received", "date_received"),
        ("Date of document", "date_created"),
        ("Division / unit", "unit_label"),
        ("Owner", "owner_label"),
        ("Assigned personnel", "assignee_label"),
        ("Status", "display_status_label"),
        ("Versions", "version_count"),
        ("Retention", "retention_summary"),
        ("Registered by", "created_by.get_display_name"),
        ("Registered", "created_at"),
    )

    # -- the date the from/to range applies to ---------------------------

    @property
    def date_basis(self):
        basis = self.request.GET.get("basis", DEFAULT_BASIS)
        return basis if basis in DATE_BASES else DEFAULT_BASIS

    @property
    def date_field(self):
        return DATE_BASES[self.date_basis][0]

    @property
    def date_field_label(self):
        return DATE_BASES[self.date_basis][1]

    @property
    def filter_fields(self):
        years = (
            Document.objects.values_list("year", flat=True)
            .distinct()
            .order_by("-year")
        )
        return (
            ("view", "View", QUICK_VIEWS),
            ("source", "Source", SOURCES),
            ("status", "Status", DocumentStatus.choices),
            ("document_type", "Type",
             [(str(t.pk), t.name) for t in DocumentType.objects.filter(is_active=True)]),
            ("owner", "Owner",
             [(str(u.pk), u.get_display_name()) for u in workflow.focal_persons()]),
            ("assigned_to", "Assigned personnel",
             [(str(u.pk), u.get_display_name()) for u in workflow.focal_persons()]),
            ("unit", "Division / unit",
             [(str(s.pk), s.name) for s in _active_sections()]),
            ("retention_disposition", "Retention", RetentionDisposition.choices),
            ("year", "Year", [(y, y) for y in years]),
            ("basis", "Date range applies to",
             [(key, label) for key, (_field, label) in DATE_BASES.items()]),
        )

    def get_base_queryset(self):
        """
        The archive is not part of the working register.

        Someone who may read the archive still does not want it mixed into
        every search of live documents, so it is left out unless the archive
        is what was asked for - by the quick view, by the status filter, or on
        the retention register.
        """
        queryset = Document.objects.select_related(
            "document_type", "owner", "assigned_to", "unit", "created_by"
        ).visible_to(self.request.user)

        if not self.wants_archive:
            queryset = queryset.live()
        return queryset

    @property
    def wants_archive(self):
        return (
            self.request.GET.get("view") in ("archived", "retention_due",
                                             "retention_soon", "for_disposal")
            or DocumentStatus.ARCHIVED in self.request.GET.getlist("status")
            or self.request.GET.get("retention_disposition", "")
        )

    def apply_extra_filters(self, queryset):
        """The quick views: questions about the record, not values in a column."""
        queryset = _filter_source(queryset, self.request.GET.get("source", "").strip())
        view = self.request.GET.get("view", "").strip()
        user = self.request.user
        if view == "mine":
            return queryset.owned_by(user)
        if view == "assigned_to_me":
            return queryset.assigned_to(user)
        if view == "involving_me":
            return queryset.involving(user)
        if view == "unassigned":
            return queryset.filter(assigned_to__isnull=True)
        if view == "open":
            return queryset.open()
        if view == "overdue":
            return queryset.overdue()
        if view == "retention_due":
            return queryset.retention_due()
        if view == "retention_soon":
            return queryset.retention_approaching()
        if view == "for_disposal":
            return queryset.for_disposal()
        if view == "archived":
            return queryset.archived()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["summary"] = summarise(self.request.user)
        context["active_view"] = self.request.GET.get("view", "")
        context["tab"] = "list"
        return context


def _filter_source(queryset, source):
    if source == "incoming":
        return queryset.filter(incoming__isnull=False)
    if source == "outgoing":
        return queryset.filter(outgoing__isnull=False)
    if source == "direct":
        return queryset.filter(incoming__isnull=True, outgoing__isnull=True)
    return queryset


def _active_sections():
    from accounts.models import Section

    return Section.objects.filter(is_active=True)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


class DocumentDetailView(DocumentModuleMixin, ModuleDetailView):
    template_name = "dashboard/documents/detail.html"

    def get_queryset(self):
        return Document.objects.select_related(
            "document_type", "owner", "assigned_to", "assigned_by", "unit",
            "reviewed_by", "approved_by", "archived_by", "disposed_by",
            "disposal_authority", "created_by", "updated_by",
            "incoming__outgoing_record", "outgoing",
        ).prefetch_related(
            "versions__uploaded_by", "events__actor", "supporting_files__uploaded_by"
        )

    def get_object(self, queryset=None):
        document = super().get_object(queryset)
        document.require_viewable_by(self.request.user)
        return document

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Recorded only once `get_object` has run and `require_viewable_by`
        # has let the request through, so an attempt to open an archived
        # document never leaves a "viewed" entry behind.
        workflow.record_view(self.object, request.user, request=request)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.object
        user = self.request.user

        context["page_title"] = document.reference_number or document.title
        context["page_subtitle"] = document.title
        context.update(
            {
                "can_edit": document.may_be_edited_by(user),
                "can_download": document.may_be_downloaded_by(user),
                "can_upload_version": document.may_upload_version_by(user),
                "can_assign": document.may_be_assigned_by(user),
                "can_archive": document.may_be_archived_by(user),
                "can_restore": document.may_be_restored_by(user),
                "can_dispose": document.may_be_disposed_by(user),
                "can_set_retention": user.can_archive_documents,
                "can_approve": user.can_approve and not document.is_synced,
                "is_responsible": document.is_responsible(user),
                "versions": document.versions.all(),
                "supporting_files": document.supporting_files.all(),
                "events": document.events.all()[:200],
                "retention_warning_days": RETENTION_WARNING_DAYS,
                "review_form": ReviewForm(
                    initial={"notes": document.review_notes}
                ),
                "assignment_form": AssignmentForm(
                    initial={
                        "assigned_to": document.assigned_to_id,
                        "assignment_remarks": document.assignment_remarks,
                        "due_date": document.due_date,
                    }
                ),
                "version_form": VersionUploadForm(),
                "status_form": StatusNoteForm(),
                "cancel_form": CancelForm(),
                "retention_form": RetentionForm(
                    initial={
                        "retention_until": document.retention_until,
                        "retention_disposition": document.retention_disposition,
                        "notes": document.retention_notes,
                    }
                ),
                "archive_form": ArchiveForm(),
                "restore_form": RestoreForm(),
                "disposal_form": DisposalForm(),
            }
        )
        return context


class DocumentCreateView(DocumentModuleMixin, ModuleCreateView):
    """
    Register a document.

    The owner defaults to whoever is registering it, and the document comes
    into being as a draft or as received - never further along, because a
    status nobody moved it to is a status nobody is answerable for.
    """

    form_class = DocumentForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Register Document"
        context["page_subtitle"] = (
            "Records the document and issues its control number. Review, "
            "assignment and approval follow on the record itself."
        )
        return context

    def form_valid(self, form):
        # A document that arrived is "Received"; one the Division is drafting
        # for itself is a "Draft". The date received is what tells them apart.
        form.instance.status = (
            DocumentStatus.RECEIVED
            if form.cleaned_data.get("date_received")
            else DocumentStatus.DRAFT
        )
        response = super().form_valid(form)
        workflow.register(self.object, self.request.user, request=self.request)
        messages.success(
            self.request,
            f"{self.object.reference_number} was registered and is owned by "
            f"{self.object.owner_label}.",
        )
        return response


class DocumentUpdateView(DocumentModuleMixin, ModuleUpdateView):
    """
    Correct the details of a registered document.

    Replacing the file here is not an overwrite: the form's `file` field
    creates a new version, exactly as the upload action on the record does.
    """

    form_class = DocumentForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        document = super().get_object(queryset)
        if not document.may_be_edited_by(self.request.user):
            raise PermissionDenied(
                "This document is not yours to edit. Its owner, its focal "
                "person or a records officer may amend it."
            )
        return document

    def form_valid(self, form):
        replaced = "file" in form.changed_data and form.cleaned_data.get("file")
        response = super().form_valid(form)

        if replaced:
            workflow.upload_version(
                self.object,
                self.request.user,
                adopt=True,
                reason="Replaced from the document edit form",
                request=self.request,
            )
        changed = ", ".join(
            str(form.fields[name].label or name.replace("_", " "))
            for name in form.changed_data
        )
        workflow.amend(
            self.object,
            self.request.user,
            changes=f"Amended: {changed}" if changed else "",
            request=self.request,
        )
        return response


class DocumentDeleteView(DocumentModuleMixin, ModuleDeleteView):
    """
    Administrative removal.

    This is not the ordinary way a document leaves the register - archiving
    is - and it stays behind `can_delete` for the cases nothing else covers: a
    record entered twice, or one registered against the wrong office.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = str(self.object)
        context["extra_warning"] = (
            "Deleting removes the document, every version of it and its whole "
            "trail. To take a document out of circulation while keeping all of "
            "that, archive it instead."
        )
        return context


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _serve(document, fieldfile, request, user, version=None):
    """
    Hand a stored file to the browser, and note that it left the system.

    A file the database knows about but storage does not is a real operational
    state - a database restored without its media, a file moved by hand - and
    it must read as "this file is not here" rather than as a server fault. The
    download is recorded only once the file has actually been opened, so the
    trail never claims a download that did not happen.
    """
    try:
        handle = fieldfile.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404(
            "The file recorded for this document is not present in storage. "
            "Report this to the system administrator."
        )

    workflow.record_download(document, user, version=version, request=request)
    return FileResponse(
        handle, as_attachment=True, filename=os.path.basename(fieldfile.name)
    )


class DocumentDownloadView(CapabilityRequiredMixin, View):
    """
    Serve a document's current file, and record that it left the system.

    Access is re-checked here rather than trusted to the URL: an archived
    document's file must not be reachable simply because someone kept a link
    to it from before it was archived.
    """

    capability = "can_view"

    def get(self, request, pk):
        document = get_object_or_404(Document, pk=pk)
        if not document.may_be_downloaded_by(request.user):
            if document.is_disposed:
                raise Http404(
                    "This document has been disposed of; its file no longer exists."
                )
            raise PermissionDenied(
                "You do not have access to this document's file."
            )
        return _serve(document, document.file, request, request.user)


class VersionDownloadView(CapabilityRequiredMixin, View):
    """Serve one earlier version, under the same checks as the current file."""

    capability = "can_view"

    def get(self, request, pk, version_pk):
        document = get_object_or_404(Document, pk=pk)
        version = get_object_or_404(DocumentVersion, pk=version_pk, document=document)

        if not document.may_be_viewed_by(request.user) or document.is_disposed:
            raise PermissionDenied("You do not have access to this document.")
        if not version.file:
            raise Http404("This version's file is no longer held.")

        return _serve(document, version.file, request, request.user, version=version)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class DocumentFileView(CapabilityRequiredMixin, View):
    """
    Show the current file in the PDF viewer.

    Checked exactly as a download is, and written to the trail: reading a file
    on screen is still the file leaving the register.
    """

    capability = "can_view"

    def get(self, request, pk):
        document = get_object_or_404(Document, pk=pk)
        if not document.may_be_downloaded_by(request.user):
            if document.is_disposed:
                raise Http404(
                    "This document has been disposed of; its file no longer exists."
                )
            raise PermissionDenied("You do not have access to this document's file.")
        response = serve_inline(document.file)
        workflow.log(
            document, request.user, EventType.VIEWED,
            detail=f"Opened {document.file_name} in the viewer", request=request,
        )
        return response


@method_decorator(xframe_options_sameorigin, name="dispatch")
class VersionFileView(CapabilityRequiredMixin, View):
    """Show one earlier version in the PDF viewer, under the download's checks."""

    capability = "can_view"

    def get(self, request, pk, version_pk):
        document = get_object_or_404(Document, pk=pk)
        version = get_object_or_404(DocumentVersion, pk=version_pk, document=document)
        if not document.may_be_viewed_by(request.user) or document.is_disposed:
            raise PermissionDenied("You do not have access to this document.")
        response = serve_inline(version.file)
        workflow.log(
            document, request.user, EventType.VIEWED,
            detail=f"Opened version {version.version_number} ({version.file_name}) "
                   "in the viewer",
            request=request,
        )
        return response


def _supporting_file(request, pk, file_pk):
    """A captured file, under the same checks as the document's own file."""
    document = get_object_or_404(Document, pk=pk)
    supporting = get_object_or_404(SupportingFile, pk=file_pk, document=document)
    if not document.may_be_viewed_by(request.user) or document.is_disposed:
        raise PermissionDenied("You do not have access to this document.")
    if not supporting.file:
        raise Http404("This file is no longer held.")
    return document, supporting


class SupportingFileDownloadView(CapabilityRequiredMixin, View):
    """Download a file captured from Incoming or Outgoing Monitoring."""

    capability = "can_view"

    def get(self, request, pk, file_pk):
        document, supporting = _supporting_file(request, pk, file_pk)
        try:
            handle = supporting.file.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            raise Http404(
                "The file recorded here is not present in storage. Report this "
                "to the system administrator."
            )
        workflow.log(
            document, request.user, EventType.DOWNLOADED,
            detail=f"Downloaded supporting file {supporting.file_name}", request=request,
        )
        return FileResponse(handle, as_attachment=True, filename=supporting.file_name)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class SupportingFileView(CapabilityRequiredMixin, View):
    """Show a captured file in the PDF viewer."""

    capability = "can_view"

    def get(self, request, pk, file_pk):
        document, supporting = _supporting_file(request, pk, file_pk)
        response = serve_inline(supporting.file)
        workflow.log(
            document, request.user, EventType.VIEWED,
            detail=f"Opened supporting file {supporting.file_name} in the viewer",
            request=request,
        )
        return response


# ---------------------------------------------------------------------------
# Every file in the register
# ---------------------------------------------------------------------------

FILE_SOURCES = (
    ("incoming", "Incoming document"),
    ("update", "Focal person's update"),
    ("outgoing", "Outgoing communication"),
    ("direct", "Registered here"),
)


class FileLibraryView(CapabilityRequiredMixin, TemplateView):
    """
    Every file the register holds, in one list.

    A document's own file and each earlier version, and every file captured
    from Incoming and Outgoing Monitoring: whatever was uploaded to the system
    for a document can be found here, searched, opened and downloaded - under
    the same access rules as the document it belongs to.
    """

    capability = "can_view"
    template_name = "dashboard/documents/files.html"
    paginate_by = 30

    def rows(self):
        params = self.request.GET
        term = params.get("q", "").strip()
        source = params.get("source", "").strip()

        visible = (
            Document.objects.visible_to(self.request.user)
            .exclude(retention_disposition=RetentionDisposition.DISPOSED)
        )
        versions = (
            DocumentVersion.objects.filter(document__in=visible)
            .exclude(file="")
            .select_related("document", "uploaded_by")
        )
        supporting = (
            SupportingFile.objects.filter(document__in=visible)
            .exclude(file="")
            .select_related("document", "uploaded_by")
        )

        if source == "incoming":
            versions = versions.filter(document__incoming__isnull=False)
            supporting = supporting.none()
        elif source == "update":
            versions = versions.none()
            supporting = supporting.filter(source=FileSource.UPDATE)
        elif source == "outgoing":
            versions = versions.filter(document__outgoing__isnull=False)
            supporting = supporting.filter(source=FileSource.OUTGOING)
        elif source == "direct":
            versions = versions.filter(
                document__incoming__isnull=True, document__outgoing__isnull=True
            )
            supporting = supporting.none()

        if term:
            match = (
                Q(file__icontains=term)
                | Q(document__reference_number__icontains=term)
                | Q(document__title__icontains=term)
            )
            versions = versions.filter(match)
            supporting = supporting.filter(match | Q(title__icontains=term))

        rows = []
        for version in versions:
            document = version.document
            rows.append({
                "when": version.uploaded_at,
                "file": version.file,
                "file_name": version.file_name,
                "file_type": version.file_type,
                "label": f"Document file - {version.label.lower()}",
                "source": (
                    "Incoming document" if document.incoming_id
                    else "Outgoing communication" if document.outgoing_id
                    else "Registered here"
                ),
                "document": document,
                "uploader": version.uploader_label,
                "view_url": reverse("documents:version_view", args=[document.pk, version.pk]),
                "download_url": reverse(
                    "documents:version_download", args=[document.pk, version.pk]
                ),
            })
        for item in supporting:
            document = item.document
            rows.append({
                "when": item.uploaded_at,
                "file": item.file,
                "file_name": item.file_name,
                "file_type": item.file_type,
                "label": item.title,
                "source": item.get_source_display(),
                "document": document,
                "uploader": item.uploader_label,
                "view_url": reverse(
                    "documents:supporting_view", args=[document.pk, item.pk]
                ),
                "download_url": reverse(
                    "documents:supporting_download", args=[document.pk, item.pk]
                ),
            })
        rows.sort(key=lambda row: row["when"], reverse=True)
        return rows

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator

        context = super().get_context_data(**kwargs)
        page_obj = Paginator(self.rows(), self.paginate_by).get_page(
            self.request.GET.get("page")
        )
        context.update({
            "page_title": "Document Files",
            "page_subtitle": (
                "Every file held in the register - registered here or uploaded in "
                "Incoming and Outgoing Monitoring"
            ),
            "breadcrumbs": [
                {"label": "Documents", "url": reverse("documents:list")},
                {"label": "Files"},
            ],
            "active_nav": "documents",
            "tab": "files",
            "page_obj": page_obj,
            "file_sources": FILE_SOURCES,
            "selected": {
                "q": self.request.GET.get("q", ""),
                "source": self.request.GET.get("source", ""),
            },
        })
        return context


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------


class WorkflowActionView(CapabilityRequiredMixin, View):
    """A POST that moves one document along. GET simply returns to the record."""

    capability = "can_view"

    def get_document(self):
        return get_object_or_404(Document, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return redirect("documents:detail", pk=pk)

    def failure(self, request, document, form):
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(document.get_absolute_url())


class ReviewView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = ReviewForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.review(
            document, request.user, notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was reviewed and is now awaiting "
            "assignment.",
        )
        return redirect(document.get_absolute_url())


class AssignView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = AssignmentForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.assign(
            document,
            request.user,
            assignee=form.cleaned_data["assigned_to"],
            remarks=form.cleaned_data["assignment_remarks"],
            due_date=form.cleaned_data["due_date"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was assigned to "
            f"{document.assignee_label}.",
        )
        return redirect(document.get_absolute_url())


class StartProcessingView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = StatusNoteForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.start_processing(
            document, request.user, notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request, f"{document.reference_number} is now in progress."
        )
        return redirect(document.get_absolute_url())


class SubmitForApprovalView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = StatusNoteForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.submit_for_approval(
            document, request.user, notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was submitted for approval.",
        )
        return redirect(document.get_absolute_url())


class SubmitForReviewView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = StatusNoteForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.submit_for_review(
            document, request.user, notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request, f"{document.reference_number} was submitted for review."
        )
        return redirect(document.get_absolute_url())


class CompleteView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = StatusNoteForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.complete(
            document, request.user, notes=form.cleaned_data["notes"],
            request=request,
        )
        if document.retention_until:
            messages.success(
                request,
                f"{document.reference_number} was approved and completed. It "
                f"is retained until "
                f"{document.retention_until.strftime('%d %b %Y')}.",
            )
        else:
            messages.warning(
                request,
                f"{document.reference_number} was approved and completed. No "
                "retention period is set for this document type - set one on "
                "the record, or add it to the type in System Settings.",
            )
        return redirect(document.get_absolute_url())


class CancelView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = CancelForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.cancel(
            document, request.user, reason=form.cleaned_data["reason"],
            request=request,
        )
        messages.success(request, f"{document.reference_number} was cancelled.")
        return redirect(document.get_absolute_url())


class UploadVersionView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = VersionUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.failure(request, document, form)
        version = workflow.upload_version(
            document,
            request.user,
            uploaded_file=form.cleaned_data["file"],
            reason=form.cleaned_data["reason"],
            request=request,
        )
        messages.success(
            request,
            f"Version {version.version_number} was uploaded. Version "
            f"{version.version_number - 1} is kept in the history."
            if version.version_number > 1
            else "Version 1 was uploaded.",
        )
        return redirect(document.get_absolute_url())


# ---------------------------------------------------------------------------
# Retention, archiving and disposal
# ---------------------------------------------------------------------------


class SetRetentionView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = RetentionForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.set_retention(
            document,
            request.user,
            retention_until=form.cleaned_data["retention_until"],
            disposition=form.cleaned_data["retention_disposition"],
            notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request,
            f"The retention decision for {document.reference_number} is now "
            f"'{document.get_retention_disposition_display()}'.",
        )
        return redirect(document.get_absolute_url())


class ArchiveView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = ArchiveForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.archive(
            document, request.user, reason=form.cleaned_data["reason"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was archived. Its metadata, "
            "versions and trail are all kept.",
        )
        return redirect(document.get_absolute_url())


class RestoreView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = RestoreForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.restore(
            document, request.user, reason=form.cleaned_data["reason"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was restored from the archive.",
        )
        return redirect(document.get_absolute_url())


class DisposeView(WorkflowActionView):
    def post(self, request, pk):
        document = self.get_document()
        form = DisposalForm(request.POST)
        if not form.is_valid():
            return self.failure(request, document, form)
        workflow.dispose(
            document,
            request.user,
            authority=form.cleaned_data["authority"],
            notes=form.cleaned_data["notes"],
            request=request,
        )
        messages.success(
            request,
            f"{document.reference_number} was disposed of under "
            f"{document.disposal_authority.reference}. Its record and trail "
            "are kept.",
        )
        return redirect(document.get_absolute_url())


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


class DocumentDashboardView(CapabilityRequiredMixin, TemplateView):
    """
    The Division Chief's view of the register.

    Every figure links to the documents behind it, and the tables beneath show
    the work that is actually waiting on someone.
    """

    capability = "can_view"
    template_name = "dashboard/documents/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        counts = summarise(user)

        visible = Document.objects.visible_to(user).select_related(
            "document_type", "owner", "assigned_to", "unit"
        )

        context.update(
            {
                "active_nav": "documents",
                "page_title": "Document Monitoring",
                "page_subtitle": (
                    "Where every document in the Division currently stands"
                ),
                "breadcrumbs": [
                    {"label": "Documents", "url": reverse("documents:list")},
                    {"label": "Monitoring"},
                ],
                "tab": "dashboard",
                "summary": counts,
                "stats": stat_links(counts),
                "by_status": self.status_breakdown(counts),
                "by_type": self.type_breakdown(),
                "by_owner": self.owner_breakdown(),
                "overdue": visible.overdue(today)[:10],
                "awaiting_action": visible.filter(
                    status__in=(
                        DocumentStatus.FOR_REVIEW,
                        DocumentStatus.FOR_ASSIGNMENT,
                        DocumentStatus.FOR_APPROVAL,
                    )
                ).order_by("created_at")[:10],
                "retention_watch": visible.retention_approaching(today=today)
                .order_by("retention_until")[:10],
                "retention_due": visible.retention_due(today)
                .order_by("retention_until")[:10],
                "recent": visible.order_by("-created_at")[:8],
                "retention_warning_days": RETENTION_WARNING_DAYS,
            }
        )
        return context

    def status_breakdown(self, counts):
        """Every lifecycle status with its share, for the chart."""
        keys = [
            ("draft", DocumentStatus.DRAFT),
            ("received", DocumentStatus.RECEIVED),
            ("for_review", DocumentStatus.FOR_REVIEW),
            ("for_assignment", DocumentStatus.FOR_ASSIGNMENT),
            ("assigned", DocumentStatus.ASSIGNED),
            ("in_progress", DocumentStatus.IN_PROGRESS),
            ("for_approval", DocumentStatus.FOR_APPROVAL),
            ("completed", DocumentStatus.COMPLETED),
            ("archived", DocumentStatus.ARCHIVED),
            ("cancelled", DocumentStatus.CANCELLED),
        ]
        total = counts["total"] or 1
        return [
            {
                "value": status,
                "label": DocumentStatus(status).label,
                "count": counts[key],
                "percent": round(counts[key] * 100 / total),
            }
            for key, status in keys
        ]

    def type_breakdown(self):
        return (
            DocumentType.objects.filter(is_active=True)
            .annotate(total=Count("documents"))
            .filter(total__gt=0)
            .order_by("-total")[:10]
        )

    def owner_breakdown(self):
        """Who is carrying how much, and how much of it is still open."""
        from accounts.models import User

        return (
            User.objects.filter(is_active=True, documents_owned__isnull=False)
            .annotate(
                total=Count("documents_owned", distinct=True),
                open_count=Count(
                    "documents_owned",
                    filter=Q(documents_owned__status__in=(
                        DocumentStatus.DRAFT,
                        DocumentStatus.RECEIVED,
                        DocumentStatus.FOR_REVIEW,
                        DocumentStatus.FOR_ASSIGNMENT,
                        DocumentStatus.ASSIGNED,
                        DocumentStatus.IN_PROGRESS,
                        DocumentStatus.FOR_APPROVAL,
                    )),
                    distinct=True,
                ),
            )
            .order_by("-total")[:12]
        )


class RetentionRegisterView(CapabilityRequiredMixin, TemplateView):
    """
    The records officer's working list.

    Kept separate from the register because it is a different job: not "find
    me this document" but "what falls due, and what have we decided about it".
    """

    capability = "can_archive_documents"
    template_name = "dashboard/documents/retention.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        base = Document.objects.select_related(
            "document_type", "owner", "disposal_authority"
        )

        context.update(
            {
                "active_nav": "documents",
                "page_title": "Retention and Archive",
                "page_subtitle": (
                    "Completed documents held under the Division's retention "
                    "policy, and what is to become of them"
                ),
                "breadcrumbs": [
                    {"label": "Documents", "url": reverse("documents:list")},
                    {"label": "Retention and Archive"},
                ],
                "tab": "retention",
                "due": base.retention_due(today).order_by("retention_until"),
                "approaching": base.retention_approaching(today=today)
                .order_by("retention_until"),
                "for_disposal": base.for_disposal().order_by("retention_until"),
                "permanent": base.filter(
                    retention_disposition=RetentionDisposition.PERMANENT
                ).order_by("-completed_at")[:25],
                "disposed": base.filter(
                    retention_disposition=RetentionDisposition.DISPOSED
                ).order_by("-disposed_at")[:25],
                "archived_total": base.archived().count(),
                "no_policy": base.completed()
                .filter(retention_until__isnull=True)
                .order_by("-completed_at")[:25],
                "retention_warning_days": RETENTION_WARNING_DAYS,
                "types": DocumentType.objects.filter(is_active=True),
            }
        )
        return context
