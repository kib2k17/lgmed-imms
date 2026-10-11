"""
The PPA workbench.

Four levels of record, one publication workflow, and a set of views that are
deliberately generic across the levels: a project and a sub-project differ in
what they mean to the office, not in how they are created, reviewed or
published, and writing the same six views four times would guarantee that the
copy governing sub-projects eventually forgets a permission check the copy
governing projects has.

The level is therefore a URL segment - `program`, `project`, `sub-project`,
`activity` - resolved through `LEVELS` below. An unknown level is a 404, not a
default, so a mistyped URL cannot land on the wrong model.

Every view that changes anything declares the capability it needs through the
mixins in `core.mixins`. The three that matter here are separate on purpose:
encoding, reviewing and publishing are three different decisions, taken by
three different people.
"""

import mimetypes

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)
from django.views.generic.edit import FormView

from audit.models import Action
from audit.recording import record as record_audit
from core.mixins import (
    CanEncodePPAMixin,
    CanPublishPPAMixin,
    CanReviewPPAMixin,
)
from core.redirects import safe_next
from core.views_base import ModuleContextMixin

from .forms import (
    ActivityForm,
    DocumentAuthorityForm,
    DocumentDecisionForm,
    PhotoOrderForm,
    ProgramForm,
    ProjectForm,
    PublicationAuthorityForm,
    RecordDecisionForm,
    SubProjectForm,
    SupportingDocumentForm,
)
from .models import (
    AWAITING_RELEASE_STATUSES,
    OUTCOME_DETAIL,
    Activity,
    DocumentStatus,
    OrganizationalOutcome,
    Program,
    Project,
    PublicationAuthority,
    PublicationStatus,
    RiskLevel,
    SubProject,
    SupportingDocument,
)

# ---------------------------------------------------------------------------
# The four levels
# ---------------------------------------------------------------------------
#
# `parent_attr` is how a child finds the record above it; `child_levels` is
# what may be created beneath it. The workbench, the forms and the breadcrumbs
# are all driven from here rather than from four parallel sets of if-branches.

LEVELS = {
    "program": {
        "model": Program,
        "form": ProgramForm,
        "label": "Program",
        "plural": "Programs",
        "parent_attr": None,
        "child_levels": ("project",),
        "public_url_name": "core:public_program",
    },
    "project": {
        "model": Project,
        "form": ProjectForm,
        "label": "Project",
        "plural": "Projects",
        "parent_attr": "program",
        "child_levels": ("sub-project", "activity"),
        "public_url_name": "core:public_project",
    },
    "sub-project": {
        "model": SubProject,
        "form": SubProjectForm,
        "label": "Sub-Project",
        "plural": "Sub-Projects",
        "parent_attr": "project",
        "child_levels": ("activity",),
        "public_url_name": "core:public_subproject",
    },
    "activity": {
        "model": Activity,
        "form": ActivityForm,
        "label": "Activity",
        "plural": "Activities",
        # An activity hangs off a project *or* a sub-project, so its parent is
        # resolved from whichever is set rather than from one named field.
        "parent_attr": "parent",
        "child_levels": (),
        "public_url_name": "core:public_activity",
    },
}

# The URL segment for a model, for building links back the other way.
LEVEL_FOR_MODEL = {spec["model"]: key for key, spec in LEVELS.items()}


def level_spec(level):
    """The configuration for a level, or 404."""
    try:
        return LEVELS[level]
    except KeyError:
        raise Http404(f"There is no '{level}' in the programme structure.")


def level_of(record):
    return LEVEL_FOR_MODEL[type(record)]


def record_url(record, view="detail"):
    return reverse(f"programs:{view}", args=[level_of(record), record.pk])


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


class PPAContextMixin(ModuleContextMixin):
    module_key = "programs"
    module_label = "Programs"
    module_url_name = "programs:list"
    list_label = "Programs"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", "programs")
        return context


class RecordViewMixin(PPAContextMixin):
    """Resolves `self.level`, `self.spec` and the model from the URL."""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.level = kwargs.get("level", "program")
        self.spec = level_spec(self.level)
        self.model = self.spec["model"]

    def get_queryset(self):
        return self.model.objects.select_related("responsible_office")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"level": self.level, "level_spec": self.spec})
        return context


def record_breadcrumbs(record, tail=None):
    """Programme > project > sub-project, then whatever page we are on."""
    crumbs = [{"label": "Programs", "url": reverse("programs:list")}]
    for ancestor in record.ancestors:
        crumbs.append({"label": ancestor.title, "url": record_url(ancestor)})
    if tail:
        crumbs.append({"label": record.title, "url": record_url(record)})
        crumbs.append({"label": tail})
    else:
        crumbs.append({"label": record.title})
    return crumbs


# ---------------------------------------------------------------------------
# Explaining the workflow on the page
# ---------------------------------------------------------------------------
#
# The eight statuses mean something specific, and the person looking at the
# screen is a government employee who has been asked to use a new module, not
# somebody who has read the specification. So each state says in a sentence
# what it means and what happens next.

WORKFLOW_HELP = {
    PublicationStatus.DRAFT: (
        "This is a draft. Nobody outside the office can see it. Submit it for "
        "review when it is ready."
    ),
    PublicationStatus.SCREENING: (
        "The attached files are being screened for personal and confidential "
        "information."
    ),
    PublicationStatus.FOR_REVIEW: (
        "Waiting for a reviewer. The screening found nothing obvious in the "
        "attached files, which is not the same as them being safe - a reviewer "
        "still has to read them."
    ),
    PublicationStatus.REVIEW_REQUIRED: (
        "A reviewer must look at this before anything can be published. Either "
        "the screening flagged something in an attached file, or a reviewer has "
        "asked for changes."
    ),
    PublicationStatus.APPROVED: (
        "A reviewer has cleared the content. It is still not public: an "
        "administrator has to publish it, and that is what creates the public "
        "copies of any approved files."
    ),
    PublicationStatus.PUBLISHED: (
        "This is live on the public website, together with any files approved "
        "for release."
    ),
    PublicationStatus.UNPUBLISHED: (
        "This was public and has been taken down. The public copies of its "
        "files were deleted. It must be reviewed and approved again before it "
        "can go back up."
    ),
    PublicationStatus.ARCHIVED: (
        "Closed out and kept for the record. Not on the public website."
    ),
}

# The path a record normally takes, for the progress strip on the detail page.
WORKFLOW_PATH = (
    PublicationStatus.DRAFT,
    PublicationStatus.FOR_REVIEW,
    PublicationStatus.APPROVED,
    PublicationStatus.PUBLISHED,
)


def workflow_states(record):
    """
    The publication path with the record's position marked.

    Off-path states - screening, review required, unpublished, archived - are
    appended rather than squeezed into the sequence, because they are not
    steps forward and drawing them as though they were would misrepresent
    where the record actually stands.
    """
    current = record.publication_status
    try:
        position = WORKFLOW_PATH.index(current)
    except ValueError:
        position = -1

    rows = [
        {
            "label": PublicationStatus(state).label,
            "active": state == current,
            "done": position >= 0 and index < position,
        }
        for index, state in enumerate(WORKFLOW_PATH)
    ]
    if position < 0:
        rows.append({
            "label": record.get_publication_status_display(),
            "active": True,
            "done": False,
        })
    return rows


def record_trail(record):
    """Who did what to this record, in the order it happened."""
    def who(user):
        return user.get_display_name() if user else "Not recorded"

    rows = [
        {"label": "Encoded by", "who": who(record.created_by), "when": record.created_at},
        {"label": "Last edited by", "who": who(record.updated_by), "when": record.updated_at},
    ]
    if record.submitted_at:
        rows.append({"label": "Submitted by", "who": who(record.submitted_by),
                     "when": record.submitted_at})
    if record.reviewed_at:
        rows.append({"label": "Reviewed by", "who": who(record.reviewed_by),
                     "when": record.reviewed_at})
    if record.approved_at:
        rows.append({"label": "Approved by", "who": who(record.approved_by),
                     "when": record.approved_at})
    if record.published_at:
        rows.append({"label": "Published by", "who": who(record.published_by),
                     "when": record.published_at})
    if record.unpublished_at:
        rows.append({"label": "Unpublished by", "who": who(record.unpublished_by),
                     "when": record.unpublished_at})
    if record.archived_at:
        rows.append({"label": "Archived by", "who": who(record.archived_by),
                     "when": record.archived_at})
    return rows


# ---------------------------------------------------------------------------
# The workbench
# ---------------------------------------------------------------------------


class WorkbenchView(LoginRequiredMixin, PPAContextMixin, TemplateView):
    """
    Every programme the Division runs, grouped under its Outcome.

    The whole tree is loaded in a handful of queries and rendered as nested
    `<details>` elements, collapsed by default. That choice does the work of a
    JavaScript tree without any of it: the sections open and close without
    scripting, they are keyboard-operable and screen-reader-legible for free,
    and a staff member who prints the page gets the part they opened.
    """

    template_name = "dashboard/ppa/workbench.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        show_archived = self.request.GET.get("archived") == "1"
        outcome_filter = self.request.GET.get("outcome") or ""

        # Each level counts its own attachments in the same query that fetches
        # it. The tree renders a few hundred rows; a count per row would be a
        # query per row.
        attached = Count("documents", distinct=True)

        activities = Activity.objects.select_related(
            "responsible_office"
        ).annotate(document_total=attached)
        sub_projects = SubProject.objects.select_related(
            "responsible_office"
        ).annotate(document_total=attached).prefetch_related(
            Prefetch("activities", queryset=activities)
        )
        projects = Project.objects.select_related(
            "responsible_office"
        ).annotate(document_total=attached).prefetch_related(
            Prefetch("sub_projects", queryset=sub_projects),
            Prefetch("activities", queryset=activities),
        )
        programs = Program.objects.select_related(
            "responsible_office", "category"
        ).annotate(document_total=attached).prefetch_related(
            Prefetch("projects", queryset=projects)
        )

        if not show_archived:
            programs = programs.open()
        if outcome_filter in OrganizationalOutcome.values:
            programs = programs.filter(outcome_code=outcome_filter)

        by_outcome = {value: [] for value in OrganizationalOutcome.values}
        for program in programs:
            by_outcome[program.outcome_code].append(program)

        document_counts = self._document_counts()
        summary = self._summary()

        context.update({
            "page_title": "Programs, Projects and Activities",
            "page_subtitle": (
                "The Division's work, grouped under the Department's five "
                "Organizational Outcomes"
            ),
            "breadcrumbs": [{"label": "Programs"}],
            "outcomes": [
                {
                    "value": value,
                    "label": OrganizationalOutcome(value).label,
                    "detail": OUTCOME_DETAIL[OrganizationalOutcome(value)],
                    "programs": by_outcome[value],
                }
                for value in OrganizationalOutcome.values
            ],
            "outcome_choices": OrganizationalOutcome.choices,
            "outcome_filter": outcome_filter,
            "show_archived": show_archived,
            "summary": summary,
            "cards": self._cards(summary, document_counts),
            "documents": document_counts,
            "can_encode": self.request.user.can_encode_ppa,
            "can_review": self.request.user.can_review_ppa,
            "can_publish": self.request.user.can_publish_ppa,
        })
        return context

    def _summary(self):
        counts = {}
        for key, spec in LEVELS.items():
            model = spec["model"]
            counts[key] = model.objects.aggregate(
                total=Count("pk", filter=~Q(publication_status=PublicationStatus.ARCHIVED)),
                published=Count("pk", filter=Q(publication_status=PublicationStatus.PUBLISHED)),
                awaiting=Count("pk", filter=Q(publication_status__in=(
                    PublicationStatus.FOR_REVIEW,
                    PublicationStatus.SCREENING,
                    PublicationStatus.REVIEW_REQUIRED,
                ))),
                approved=Count("pk", filter=Q(publication_status=PublicationStatus.APPROVED)),
            )
        return counts

    def _cards(self, summary, documents):
        """
        The four figures at the top of the workbench.

        Each says how many records exist and how many of them the public can
        actually see, because those are different numbers and the gap between
        them is what a division chief wants to know at a glance.
        """
        labels = [
            ("program", "program", "Programs", "programs"),
            ("project", "project", "Projects", "monitoring"),
            ("sub_project", "sub-project", "Sub-Projects", "reports"),
            ("activity", "activity", "Activities", "calendar"),
        ]
        cards = {}
        for context_key, level, label, icon in labels:
            counts = summary[level]
            waiting = counts["awaiting"] + counts["approved"]
            cards[context_key] = {
                "label": label,
                "value": counts["total"],
                "icon": icon,
                "meta": (
                    f"{counts['published']} published"
                    + (f", {waiting} awaiting a decision" if waiting else "")
                ),
                "tone": "warning" if waiting else None,
            }
        cards["documents"] = {
            "label": "Supporting documents",
            "value": documents["total"],
            "icon": "documents",
            "meta": f"{documents['published']} released publicly",
        }
        return cards

    def _document_counts(self):
        return SupportingDocument.objects.aggregate(
            total=Count("pk"),
            awaiting=Count("pk", filter=Q(status__in=(
                DocumentStatus.UPLOADED, DocumentStatus.SCREENING,
                DocumentStatus.SCREENED,
            ))),
            high_risk=Count("pk", filter=Q(
                risk_level=RiskLevel.HIGH,
                status__in=(DocumentStatus.SCREENED, DocumentStatus.UPLOADED),
            )),
            published=Count("pk", filter=Q(status=DocumentStatus.PUBLISHED)),
        )


class ReviewQueueView(CanReviewPPAMixin, PPAContextMixin, TemplateView):
    """
    Everything waiting on a reviewer, on one page.

    Files first and highest risk first, because that is the order in which a
    mistake here costs the most.
    """

    template_name = "dashboard/ppa/queue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        documents = list(
            SupportingDocument.objects.filter(
                status__in=(DocumentStatus.UPLOADED, DocumentStatus.SCREENING,
                            DocumentStatus.SCREENED)
            )
            .select_related("program", "project", "sub_project", "activity",
                            "uploaded_by")
            .order_by("-uploaded_at")
        )
        risk_order = {RiskLevel.HIGH: 0, RiskLevel.REVIEW_REQUIRED: 1, RiskLevel.LOW: 2}
        documents.sort(key=lambda d: risk_order.get(d.risk_level, 3))

        # The rows carry their attachment count, like the workbench's do, so
        # the list does not issue a query per row to render one number.
        attached = Count("documents", distinct=True)

        records = []
        for key, spec in LEVELS.items():
            for record in (
                spec["model"].objects.awaiting_review()
                .select_related("responsible_office", "submitted_by")
                .annotate(document_total=attached)
            ):
                records.append({"level": key, "record": record, "spec": spec})
        records.sort(key=lambda row: row["record"].submitted_at or timezone.now())

        approved = []
        if self.request.user.can_publish_ppa:
            for key, spec in LEVELS.items():
                for record in (
                    spec["model"].objects.ready_to_publish()
                    .annotate(document_total=attached)
                ):
                    approved.append({"level": key, "record": record})

        context.update({
            "page_title": "Review Queue",
            "page_subtitle": "Content and documents waiting on a decision",
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Review queue"},
            ],
            # The queue is its own sidebar entry, so it must not light up the
            # Programs item the rest of the module shares.
            "active_nav": "ppa_queue",
            "documents": documents,
            "records": records,
            "approved": approved,
            "can_publish": self.request.user.can_publish_ppa,
        })
        return context


# ---------------------------------------------------------------------------
# Records: read, create, edit, remove
# ---------------------------------------------------------------------------


class RecordDetailView(LoginRequiredMixin, RecordViewMixin, DetailView):
    template_name = "dashboard/ppa/detail.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        user = self.request.user

        # Cleared by a reviewer and not on the website at this moment: the
        # files that are approved and never yet released, and the files that
        # were released and later taken down. Both are one publisher click
        # from being public, and the panel below treats them the same way.
        releasable_documents = list(
            record.documents.filter(
                status__in=AWAITING_RELEASE_STATUSES
            ).select_related("authority")
        )

        context.update({
            "page_title": record.title,
            "page_subtitle": f"{self.spec['label']} · {record.get_publication_status_display()}",
            "breadcrumbs": record_breadcrumbs(record),
            "outcome": OUTCOME_DETAIL.get(record.outcome) if record.outcome else None,
            "children": self._children(record),
            "child_levels": [
                {"level": level, "label": LEVELS[level]["label"]}
                for level in self.spec["child_levels"]
            ],
            "documents": record.documents.select_related("uploaded_by", "reviewed_by"),
            "photograph_count": record.documents.photographs().count(),
            "can_encode": user.can_encode_ppa,
            "can_review": user.can_review_ppa,
            "can_publish": user.can_publish_ppa,
            "decision_form": RecordDecisionForm(),
            "unauthorised_documents": [
                document for document in releasable_documents
                if not document.may_be_released
            ],
            # Cleared, authorised, and attached to a record that is already
            # public: one click from a publisher and they are out.
            "ready_documents": [
                document for document in releasable_documents
                if document.is_awaiting_release
            ],
            # On the website now, so the one thing they are waiting for is a
            # publisher who wants them off it. Listed beside the files waiting
            # to go out so that both directions are a single confirmed click
            # from the record, rather than a trip through the review screen.
            "published_documents": list(
                record.documents.filter(
                    status=DocumentStatus.PUBLISHED
                ).select_related("authority")
            ),
            "workflow_states": workflow_states(record),
            "workflow_help": WORKFLOW_HELP.get(record.publication_status, ""),
            "trail": record_trail(record),
        })
        return context

    def _children(self, record):
        groups = []
        for level in self.spec["child_levels"]:
            attribute = {"project": "projects", "sub-project": "sub_projects",
                         "activity": "activities"}[level]
            queryset = (
                getattr(record, attribute)
                .select_related("responsible_office")
                .annotate(document_total=Count("documents", distinct=True))
            )
            groups.append({
                "level": level,
                "label": LEVELS[level]["plural"],
                "records": queryset,
            })
        return groups


class RecordCreateView(CanEncodePPAMixin, RecordViewMixin, CreateView):
    template_name = "dashboard/module_form.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.parent = self._resolve_parent(kwargs)

    def _resolve_parent(self, kwargs):
        """
        The record this one will hang off, taken from the URL.

        A programme has no parent. Everything else does, and refusing to
        create one without it is what keeps orphaned projects out of the tree.
        """
        if self.level == "program":
            return None
        parent_level = kwargs.get("parent_level")
        parent_pk = kwargs.get("parent_pk")
        if not parent_level or not parent_pk:
            raise Http404("A parent record must be named.")
        parent_model = level_spec(parent_level)["model"]
        parent = get_object_or_404(parent_model, pk=parent_pk)

        allowed = level_spec(parent_level)["child_levels"]
        if self.level not in allowed:
            raise Http404(
                f"A {self.spec['label'].lower()} cannot be created under a "
                f"{level_spec(parent_level)['label'].lower()}."
            )
        return parent

    def get_form_class(self):
        return self.spec["form"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.level != "program":
            kwargs["parent"] = self.parent
        return kwargs

    def get_initial(self):
        """
        Carry the Outcome through from the workbench.

        The empty state under each Outcome offers "add a programme", and
        arriving at the form with that Outcome already chosen is the whole
        point of offering it there.
        """
        initial = super().get_initial()
        outcome = self.request.GET.get("outcome")
        if self.level == "program" and outcome in OrganizationalOutcome.values:
            initial["outcome_code"] = outcome
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"New {self.spec['label']}",
            "page_subtitle": (
                f"Under {self.parent.title}" if self.parent
                else "Complete the required fields marked with an asterisk"
            ),
            "breadcrumbs": (
                record_breadcrumbs(self.parent, f"New {self.spec['label']}")
                if self.parent else
                [{"label": "Programs", "url": reverse("programs:list")},
                 {"label": f"New {self.spec['label']}"}]
            ),
            "submit_label": "Save",
            "cancel_url": (
                record_url(self.parent) if self.parent else reverse("programs:list")
            ),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"{self.object.title} was saved as a draft. It is not on the "
            "public website; submit it for review when it is ready.",
        )
        return response

    def get_success_url(self):
        return record_url(self.object)


class RecordUpdateView(CanEncodePPAMixin, RecordViewMixin, UpdateView):
    template_name = "dashboard/module_form.html"

    def get_form_class(self):
        return self.spec["form"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.level != "program":
            kwargs["parent"] = self.object.parent
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"Edit {self.spec['label']}",
            "page_subtitle": self.object.title,
            "breadcrumbs": record_breadcrumbs(self.object, "Edit"),
            "submit_label": "Save changes",
            "cancel_url": record_url(self.object),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        was_public = self.object.is_published
        was_approved = self.object.publication_status == PublicationStatus.APPROVED
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)

        # Cleared wording must not be swapped for uncleared wording after the
        # fact. Editing approved or published content sends it back.
        self.object.touch_content(self.request.user)
        if was_public:
            messages.warning(
                self.request,
                f"{self.object.title} was taken off the public website because "
                "its content changed. Submit it for review again.",
            )
        elif was_approved:
            messages.warning(
                self.request,
                "The approval was withdrawn because the content changed. "
                "Submit it for review again.",
            )
        else:
            messages.success(self.request, f"Changes to {self.object.title} were saved.")
        return response

    def get_success_url(self):
        return record_url(self.object)


class RecordDeleteView(CanPublishPPAMixin, RecordViewMixin, DeleteView):
    """
    Removal, which is rarer than it looks.

    Archiving is what the office normally wants and what the interface
    offers; deletion is here for a record created by mistake, is restricted to
    administrators, and takes the attached files with it.
    """

    template_name = "dashboard/module_confirm_delete.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": f"Delete {self.spec['label']}",
            "page_subtitle": self.object.title,
            "breadcrumbs": record_breadcrumbs(self.object, "Delete"),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        record = self.get_object()
        parent = record.parent
        # Public copies are files on disk. Deleting the row is not enough.
        for document in record.documents.all():
            document._delete_public_copy()
        messages.success(self.request, f"{record.title} was deleted.")
        self.success_url = record_url(parent) if parent else reverse("programs:list")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# The publication workflow
# ---------------------------------------------------------------------------


class RecordActionMixin(RecordViewMixin, View):
    """Base for the POST-only endpoints that move a record through the workflow."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        record = get_object_or_404(self.model, pk=kwargs["pk"])
        try:
            self.perform(record, request)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        return redirect(safe_next(request, request.POST.get("next"), record_url(record)))

    def perform(self, record, request):
        raise NotImplementedError


class RecordSubmitView(CanEncodePPAMixin, RecordActionMixin):
    """Hand a record to a reviewer. Screens the attached files on the way."""

    def perform(self, record, request):
        if not record.can_be_submitted:
            raise ValidationError(
                f"{record.title} is {record.get_publication_status_display().lower()} "
                "and cannot be submitted."
            )
        outcome = record.submit_for_review(request.user)
        flagged = record.documents.exclude(risk_level=RiskLevel.LOW).count()

        record_audit(
            Action.SUBMIT, target=record, request=request,
            detail=(
                f"Submitted for review; {record.documents.count()} file(s) "
                f"screened, {flagged} flagged."
            ),
        )
        if outcome == PublicationStatus.REVIEW_REQUIRED:
            messages.warning(
                request,
                f"{record.title} was submitted. The automated screening flagged "
                f"{flagged} file(s) - a reviewer must look at them before "
                "anything is published.",
            )
        else:
            messages.success(
                request,
                f"{record.title} was submitted for review. Nothing is public yet.",
            )


class RecordDecisionView(CanReviewPPAMixin, RecordActionMixin):
    """A reviewer approves the content, sends it back, or refuses it."""

    def perform(self, record, request):
        if not record.can_be_reviewed:
            raise ValidationError(f"{record.title} is not awaiting review.")

        form = RecordDecisionForm(request.POST)
        if not form.is_valid():
            raise ValidationError(
                [error for errors in form.errors.values() for error in errors]
            )

        decision = form.cleaned_data["decision"]
        comments = form.cleaned_data["comments"]

        if decision == "approve":
            record.approve(request.user, comments)
            record_audit(Action.APPROVE, target=record, request=request,
                         detail=f"Content approved. {comments}"[:255])
            messages.success(
                request,
                f"{record.title} was approved. It is not public until an "
                "administrator publishes it.",
            )
        elif decision == "revise":
            record.request_revision(request.user, comments)
            record_audit(Action.REQUEST_REVISION, target=record, request=request,
                         detail=comments[:255])
            messages.info(request, f"{record.title} was sent back for revision.")
        else:
            record.reject(request.user, comments)
            record_audit(Action.REJECT, target=record, request=request,
                         detail=comments[:255])
            messages.info(request, f"{record.title} was rejected and returned to draft.")


class RecordPublishView(CanPublishPPAMixin, RecordActionMixin):
    """
    Put approved content on the public website.

    This is the only view in the module that causes a file to be written into
    a served directory, and it refuses anything that is not approved.
    """

    def perform(self, record, request):
        outcome = record.publish(request.user)
        released, held = outcome["released"], outcome["held"]

        authorities = sorted({
            document.authority.reference for document in released
            if document.authority_id
        })
        record_audit(
            Action.PUBLISH, target=record, request=request,
            detail=(
                f"Published to the public website with {len(released)} file(s)"
                + (f" under {', '.join(authorities)}" if authorities else "")
                + (f"; {len(held)} file(s) held back for want of an authority."
                   if held else ".")
            )[:255],
        )

        messages.success(
            request,
            f"{record.title} is now on the public website"
            + (f", with {len(released)} approved file(s)." if released else "."),
        )
        if held:
            # Named rather than counted: "two files were held back" sends the
            # publisher hunting, and the whole point of the control is that
            # the missing memorandum is obvious.
            messages.warning(
                request,
                "These files were NOT published, because no memorandum "
                "authorises their release: "
                + "; ".join(f"'{d.title}' - {d.release_blocker}" for d in held),
            )


class RecordUnpublishView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        if not record.is_published:
            raise ValidationError(f"{record.title} is not published.")
        record.unpublish(request.user)
        record_audit(
            Action.UNPUBLISH, target=record, request=request,
            detail="Withdrawn from the public website; public file copies deleted.",
        )
        messages.success(
            request,
            f"{record.title} was taken off the public website, along with "
            "anything published beneath it. The public copies of its files "
            "have been deleted.",
        )


class RecordArchiveView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        record.archive(request.user)
        record_audit(Action.ARCHIVE, target=record, request=request,
                     detail="Archived.")
        messages.success(request, f"{record.title} was archived.")


class RecordRestoreView(CanPublishPPAMixin, RecordActionMixin):
    def perform(self, record, request):
        if not record.is_archived:
            raise ValidationError(f"{record.title} is not archived.")
        record.restore(request.user)
        record_audit(Action.RESTORE, target=record, request=request,
                     detail="Restored from the archive as a draft.")
        messages.success(
            request,
            f"{record.title} was restored as a draft. It must be reviewed and "
            "approved again before it can be published.",
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentUploadView(CanEncodePPAMixin, PPAContextMixin, CreateView):
    """
    Attach one file, or a set of photographs, to a record.

    Every file is written to the protected directory and screened immediately,
    so the person who uploaded it sees the result while they still remember
    what is in it. Each is screened again on submission, against whatever the
    rules are by then.

    A batch is not a shortcut around any of that. Thirty photographs become
    thirty rows, thirty screenings and thirty review decisions; what the batch
    saves is the encoder filling in the same form thirty times, and the page
    reports the worst result it found so a flagged picture cannot hide inside
    a good-news message about the other twenty-nine.
    """

    template_name = "dashboard/ppa/document_upload.html"
    form_class = SupportingDocumentForm
    model = SupportingDocument

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.level = kwargs["level"]
        self.spec = level_spec(self.level)
        self.record = get_object_or_404(self.spec["model"], pk=kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["record"] = self.record
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Upload supporting documents",
            "page_subtitle": f"{self.spec['label']}: {self.record.title}",
            "breadcrumbs": record_breadcrumbs(self.record, "Upload documents"),
            "submit_label": "Upload and screen",
            "cancel_url": record_url(self.record),
            "list_url": reverse("programs:list"),
            "record": self.record,
            "level": self.level,
            "photograph_count": self.record.documents.photographs().count(),
            "arrange_url": reverse(
                "programs:photo_arrange", args=[self.level, self.record.pk]
            ),
            "form_note": (
                "Files are stored internally and are not published by "
                "uploading them. Each is screened for personal and "
                "confidential information, and a reviewer decides what happens "
                "next. Several photographs can be selected at once - the order "
                "you arrange them in below is the order the public gallery "
                "uses."
            ),
        })
        return context

    def form_valid(self, form):
        from . import screening

        # The owner was attached to each document by the form, before
        # validation - see SupportingDocumentForm.documents().
        documents = form.documents()
        worst = RiskLevel.LOW
        severity = {RiskLevel.LOW: 0, RiskLevel.REVIEW_REQUIRED: 1, RiskLevel.HIGH: 2}

        for document in documents:
            document.uploaded_by = self.request.user
            document.save()

            record_audit(
                Action.UPLOAD, target=document, request=self.request,
                detail=f"Uploaded against {self.record.level_label.lower()} "
                       f"'{self.record.title}'.",
            )

            screening.screen_document(document)
            record_audit(
                Action.SCREEN, target=document, request=self.request,
                detail=f"Automated screening: {document.get_risk_level_display()}, "
                       f"{document.finding_count} finding(s).",
            )
            if severity[document.risk_level] > severity[worst]:
                worst = document.risk_level

        self.object = documents[-1]
        self.report(documents, worst)

        # One file still lands on its own review screen, because that is where
        # the person who uploaded it needs to be. A batch goes back to the
        # record, where the whole set is listed with its screening results -
        # sending them to the last picture's review page would hide the other
        # twenty-nine behind a back button.
        if len(documents) == 1:
            return redirect(
                reverse("programs:document_review", args=[documents[0].pk])
            )
        if any(document.is_image for document in documents):
            return redirect(
                reverse("programs:photo_arrange", args=[self.level, self.record.pk])
            )
        return redirect(record_url(self.record))

    def report(self, documents, worst):
        """Say what was stored, leading with the worst screening result."""
        total = len(documents)
        if total == 1:
            subject = f"'{documents[0].title}'"
            verb = "was"
        else:
            subject = f"{total} files"
            verb = "were"

        if worst == RiskLevel.HIGH:
            flagged = sum(1 for d in documents if d.risk_level == RiskLevel.HIGH)
            messages.error(
                self.request,
                f"{subject} {verb} stored internally. The screening flagged "
                f"{'it' if total == 1 else f'{flagged} of them'} as HIGH RISK "
                f"- {'it' if total == 1 and flagged == 1 else 'they'} cannot be "
                "published until a reviewer reads "
                f"{'it' if total == 1 and flagged == 1 else 'them'} and says "
                "otherwise.",
            )
        elif worst == RiskLevel.REVIEW_REQUIRED:
            messages.warning(
                self.request,
                f"{subject} {verb} stored internally. The screening found "
                "something a reviewer needs to look at.",
            )
        else:
            messages.success(
                self.request,
                f"{subject} {verb} stored internally. The screening found "
                "nothing obvious, which is not the same as the files being "
                "safe - a reviewer still has to clear them.",
            )


class PhotoArrangeView(CanEncodePPAMixin, PPAContextMixin, FormView):
    """
    Put one record's photographs in the order the public will see them.

    A gallery whose order nobody chose is a gallery in upload order, and
    upload order is whatever a camera named its files that morning. This page
    is where somebody decides that the opening shot comes first and the group
    photograph comes last - before publication, and afterwards without
    republishing anything, because the order lives on the row rather than in
    the copy served to the public.

    It moves pictures and nothing else. No status changes here, no approvals,
    no publishing: rearranging a gallery is an editorial act, not a release
    decision, and the two must not share a button.
    """

    template_name = "dashboard/ppa/photo_arrange.html"
    form_class = PhotoOrderForm

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.level = kwargs["level"]
        self.spec = level_spec(self.level)
        self.record = get_object_or_404(self.spec["model"], pk=kwargs["pk"])

    def photographs(self):
        return list(
            self.record.documents.photographs().select_related("uploaded_by")
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["photographs"] = self.photographs()
        return kwargs

    def get_initial(self):
        """
        The hidden field starts out holding the order already on the record.

        So the page submitted without JavaScript saves the order it was shown,
        which is a no-op, rather than failing validation on an empty field and
        telling somebody their photographs had changed underneath them.
        """
        initial = super().get_initial()
        initial["order"] = ",".join(
            str(photograph.pk) for photograph in self.photographs()
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        photographs = self.photographs()
        context.update({
            "page_title": "Arrange photographs",
            "page_subtitle": f"{self.spec['label']}: {self.record.title}",
            "breadcrumbs": record_breadcrumbs(self.record, "Arrange photographs"),
            "record": self.record,
            "level": self.level,
            "photographs": photographs,
            "published_count": sum(
                1 for photograph in photographs
                if photograph.status == DocumentStatus.PUBLISHED
            ),
            "cancel_url": record_url(self.record),
            "upload_url": reverse(
                "programs:document_upload", args=[self.level, self.record.pk]
            ),
            "list_url": reverse("programs:list"),
        })
        return context

    def form_valid(self, form):
        order = form.cleaned_data["order"]
        by_pk = {photograph.pk: photograph for photograph in self.photographs()}

        moved = []
        for position, pk in enumerate(order, start=1):
            photograph = by_pk[pk]
            if photograph.display_order != position:
                photograph.display_order = position
                moved.append(photograph)

        if moved:
            SupportingDocument.objects.bulk_update(moved, ["display_order"])
            record_audit(
                Action.UPDATE, target=self.record, request=self.request,
                detail=f"Reordered the gallery: {len(moved)} photograph(s) moved.",
            )
            messages.success(
                self.request,
                f"The gallery order was saved. {len(moved)} photograph"
                f"{'' if len(moved) == 1 else 's'} moved.",
            )
        else:
            messages.info(self.request, "The photographs were already in that order.")
        return redirect(
            reverse("programs:photo_arrange", args=[self.level, self.record.pk])
        )

    def form_invalid(self, form):
        for error in form.errors.get("order", []):
            messages.error(self.request, error)
        return redirect(
            reverse("programs:photo_arrange", args=[self.level, self.record.pk])
        )


class DocumentReviewView(LoginRequiredMixin, PPAContextMixin, DetailView):
    """
    The dedicated review screen for one file.

    Shows what the file is, what it is attached to, who uploaded it and when,
    what the screening found, and what the scanner could not do - then offers
    the decision. Everything a reviewer needs is on this page so that the
    decision is never taken from a list view where only the risk badge is
    visible.
    """

    template_name = "dashboard/ppa/document_review.html"
    context_object_name = "document"
    model = SupportingDocument

    def get_queryset(self):
        return SupportingDocument.objects.select_related(
            "program", "project", "sub_project", "activity",
            "uploaded_by", "reviewed_by", "published_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.object
        owner = document.owner
        context.update({
            "page_title": "Document Review",
            "page_subtitle": document.title,
            "breadcrumbs": record_breadcrumbs(owner, "Document review") if owner else [],
            "record": owner,
            "record_level": level_of(owner) if owner else None,
            "findings": document.screening_findings or [],
            "high_findings": [
                f for f in (document.screening_findings or []) if f["severity"] == "HIGH"
            ],
            "decision_form": kwargs.get("decision_form")
            or DocumentDecisionForm(document=document),
            "authority_form": DocumentAuthorityForm(
                initial={"authority": document.authority_id}
            ),
            "can_review": self.request.user.can_review_ppa,
            "can_publish": self.request.user.can_publish_ppa,
            "can_encode": self.request.user.can_encode_ppa,
        })
        return context

    def post(self, request, *args, **kwargs):
        """The decision itself. Reviewers only, re-checked here."""
        if not request.user.can_review_ppa:
            raise PermissionDenied("Your role does not permit reviewing documents.")

        self.object = self.get_object()
        document = self.object
        form = DocumentDecisionForm(request.POST, document=document)
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(decision_form=form)
            )

        decision = form.cleaned_data["decision"]
        comments = form.cleaned_data["comments"]
        acknowledged = form.cleaned_data.get("acknowledge_risk")
        authority = form.cleaned_data.get("authority")

        if authority is not None and authority != document.authority:
            document.authority = authority
            record_audit(
                Action.UPDATE, target=document, request=request,
                detail=f"Publication authority set to {authority.reference}.",
            )

        if decision == "approve":
            document.approve(request.user, comments)
            record_audit(
                Action.APPROVE, target=document, request=request,
                detail=(
                    f"Approved for publication. Screening said "
                    f"{document.get_risk_level_display()}"
                    + ("; reviewer confirmed they read the file in full." if acknowledged else "")
                )[:255],
            )
            if document.authority_id:
                messages.success(
                    request,
                    f"'{document.title}' was approved under "
                    f"{document.authority.reference}. It becomes public when "
                    "the record it belongs to is published.",
                )
            else:
                messages.warning(
                    request,
                    f"'{document.title}' was approved, but no memorandum "
                    "authorising its release has been recorded - so it will "
                    "not be published until one is.",
                )
        elif decision == "revise":
            document.request_revision(request.user, comments)
            record_audit(Action.REQUEST_REVISION, target=document,
                         request=request, detail=comments[:255])
            messages.info(request, f"A revision of '{document.title}' was requested.")
        else:
            document.reject(request.user, comments)
            record_audit(Action.REJECT, target=document, request=request,
                         detail=comments[:255])
            messages.info(
                request,
                f"'{document.title}' was rejected. It stays in the internal "
                "record and will not be published.",
            )

        owner = document.owner
        return redirect(record_url(owner) if owner else reverse("programs:list"))


class DocumentRescreenView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """Run the screening again - after the rules change, or a re-upload."""

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        from . import screening

        document = self.get_object()
        screening.screen_document(document)
        record_audit(
            Action.SCREEN, target=document, request=request,
            detail=f"Re-screened: {document.get_risk_level_display()}, "
                   f"{document.finding_count} finding(s).",
        )
        messages.info(
            request,
            f"'{document.title}' was screened again: "
            f"{document.get_risk_level_display()}.",
        )
        return redirect(reverse("programs:document_review", args=[document.pk]))


class DocumentDeleteView(CanEncodePPAMixin, PPAContextMixin, DeleteView):
    template_name = "dashboard/module_confirm_delete.html"
    context_object_name = "record"
    model = SupportingDocument

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Delete document",
            "page_subtitle": self.object.title,
            "list_url": reverse("programs:list"),
        })
        return context

    def dispatch(self, request, *args, **kwargs):
        """
        Deleting is for a file uploaded by mistake, not for taking one down.

        A published file is withdrawn by unpublishing the record it belongs
        to, which is an administrator's decision and leaves a trail that says
        so. Allowing an encoder to reach the same outcome by deleting the row
        would route a publication decision around the person who holds it.
        """
        if request.method == "POST" or request.method == "GET":
            document = self.get_object()
            if document.status == DocumentStatus.PUBLISHED:
                if not request.user.is_authenticated or not request.user.can_publish_ppa:
                    raise PermissionDenied(
                        "This file is on the public website. It must be "
                        "withdrawn by an administrator before it can be deleted."
                    )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        document = self.get_object()
        owner = document.owner
        document._delete_public_copy()
        record_audit(
            Action.DELETE, target=document, request=self.request,
            detail=f"Internal file deleted from {document.owner_label}.",
        )
        messages.success(self.request, f"'{document.title}' was deleted.")
        self.success_url = record_url(owner) if owner else reverse("programs:list")
        return super().form_valid(form)


class DocumentDownloadView(LoginRequiredMixin, DetailView):
    """
    Serve an internal document to a signed-in member of staff.

    This view is the entire reason the protected directory exists. The file it
    streams is never reachable by URL: there is no route to it, the storage is
    configured without a base URL, and the only way to the bytes is through
    this method - which runs after Django has authenticated the session and
    checked the role.
    """

    model = SupportingDocument

    def get(self, request, *args, **kwargs):
        if not request.user.can_encode_ppa and not request.user.can_review_ppa:
            raise PermissionDenied(
                "Your role does not permit access to internal documents."
            )

        document = self.get_object()
        if not document.file:
            raise Http404("The file is missing from storage.")

        record_audit(
            Action.EXPORT, target=document, request=request,
            detail=f"Opened the internal copy of '{document.title}'.",
        )

        content_type = (
            mimetypes.guess_type(document.original_name or document.filename)[0]
            or "application/octet-stream"
        )
        response = FileResponse(
            document.file.open("rb"),
            content_type=content_type,
            # Inline so the reviewer can read a PDF without downloading it;
            # the review screen embeds this URL in an object element.
            as_attachment=request.GET.get("download") == "1",
            filename=document.original_name or document.filename,
        )
        # Belt and braces: an internal document must not sit in a shared cache.
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class RecordPreviewView(CanEncodePPAMixin, RecordViewMixin, DetailView):
    """
    The public page, exactly as a visitor would see it, before it is public.

    Rendered through the *same template* the public site uses rather than an
    imitation of it, because the point of a preview is to be able to trust it.
    A banner across the top says it is a preview, and the publish button on it
    is the real one.
    """

    context_object_name = "record"
    template_name = "public/ppa_detail.html"

    def get_context_data(self, **kwargs):
        from .public import public_detail_context

        context = super().get_context_data(**kwargs)
        context.update(public_detail_context(self.object, preview=True))
        context.update({
            "preview": True,
            "preview_back_url": record_url(self.object),
            "can_publish": self.request.user.can_publish_ppa,
            "level": self.level,
        })
        return context


# ---------------------------------------------------------------------------
# The authority to publish
# ---------------------------------------------------------------------------
#
# Recorded on its own pages, ahead of any release that cites it. That
# separation is the control: an authority created inside the same form that
# publishes a file would be a second checkbox wearing a memorandum's name.


class AuthorityListView(CanReviewPPAMixin, PPAContextMixin, ListView):
    """Every memorandum the office has recorded, in force or not."""

    template_name = "dashboard/ppa/authority_list.html"
    context_object_name = "authorities"
    model = PublicationAuthority

    def get_queryset(self):
        return PublicationAuthority.objects.annotate(
            released=Count(
                "documents",
                filter=Q(documents__status=DocumentStatus.PUBLISHED),
            )
        ).order_by("-approved_on", "reference")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Publication Authorities",
            "page_subtitle": (
                "The memoranda under which files may be released to the public"
            ),
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities"},
            ],
            "active_nav": "ppa_authorities",
            "awaiting": SupportingDocument.objects.filter(
                status=DocumentStatus.APPROVED, authority__isnull=True
            ).count(),
        })
        return context


class AuthorityDetailView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """One memorandum, and every file released under it."""

    template_name = "dashboard/ppa/authority_detail.html"
    context_object_name = "authority"
    model = PublicationAuthority

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        authority = self.object
        context.update({
            "page_title": authority.reference,
            "page_subtitle": authority.title,
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": authority.reference},
            ],
            "active_nav": "ppa_authorities",
            "documents": authority.documents.select_related(
                "program", "project", "sub_project", "activity", "uploaded_by",
            ).order_by("-published_at", "-uploaded_at"),
        })
        return context


class AuthorityFormMixin(PPAContextMixin):
    template_name = "dashboard/module_form.html"
    form_class = PublicationAuthorityForm
    model = PublicationAuthority

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "active_nav": "ppa_authorities",
            "list_url": reverse("programs:authority_list"),
            "cancel_url": (
                self.object.get_absolute_url() if getattr(self, "object", None)
                else reverse("programs:authority_list")
            ),
            "form_note": (
                "Record the memorandum here first. It can then be cited "
                "against the files it authorises - and a file cannot be "
                "published unless one is."
            ),
        })
        return context


class AuthorityCreateView(CanReviewPPAMixin, AuthorityFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Record a Publication Authority",
            "page_subtitle": "The memorandum authorising a public release",
            "submit_label": "Record the memorandum",
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": "New"},
            ],
        })
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"{self.object.reference} was recorded. Files may now be released "
            "under it.",
        )
        return response


class AuthorityUpdateView(CanReviewPPAMixin, AuthorityFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": "Edit Publication Authority",
            "page_subtitle": str(self.object),
            "submit_label": "Save changes",
            "breadcrumbs": [
                {"label": "Programs", "url": reverse("programs:list")},
                {"label": "Publication authorities",
                 "url": reverse("programs:authority_list")},
                {"label": self.object.reference,
                 "url": self.object.get_absolute_url()},
                {"label": "Edit"},
            ],
        })
        return context

    def form_valid(self, form):
        was_in_force = self.get_object().is_in_force()
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)

        # Withdrawing an authority stops it authorising anything further, but
        # it does not reach back and unpublish what it already released. That
        # is a separate decision and it belongs to whoever holds it, so the
        # page says plainly what is still out there rather than acting alone.
        if was_in_force and not self.object.is_in_force():
            live = self.object.documents.filter(
                status=DocumentStatus.PUBLISHED
            ).count()
            record_audit(
                Action.UPDATE, target=self.object, request=self.request,
                detail=f"Authority withdrawn; {live} file(s) remain published.",
            )
            if live:
                messages.warning(
                    self.request,
                    f"{self.object.reference} no longer authorises new "
                    f"releases. {live} file(s) already published under it are "
                    "still on the public website - unpublish the records they "
                    "belong to if they should come down.",
                )
                return response
        messages.success(
            self.request, f"Changes to {self.object.reference} were saved."
        )
        return response


class DocumentAuthorityView(CanReviewPPAMixin, PPAContextMixin, DetailView):
    """Cite a memorandum against one file that has already been approved."""

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        form = DocumentAuthorityForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(e for errors in form.errors.values() for e in errors),
            )
        else:
            authority = form.cleaned_data["authority"]
            document.authority = authority
            document.save(update_fields=["authority"])
            record_audit(
                Action.UPDATE, target=document, request=request,
                detail=f"Publication authority set to {authority.reference}.",
            )
            messages.success(
                request,
                f"'{document.title}' is now cited against {authority.reference}.",
            )
        return redirect(reverse("programs:document_review", args=[document.pk]))


class AuthorityFileView(CanReviewPPAMixin, DetailView):
    """
    Stream the scanned memorandum to a reviewer.

    The issuance is evidence behind a release, not a thing being released, so
    it lives in the protected root like every other internal file and is
    reachable only through here.
    """

    model = PublicationAuthority

    def get(self, request, *args, **kwargs):
        authority = self.get_object()
        if not authority.memorandum:
            raise Http404("No memorandum has been attached to this authority.")

        record_audit(
            Action.EXPORT, target=authority, request=request,
            detail=f"Opened the memorandum for {authority.reference}.",
        )
        name = authority.memorandum.name.rsplit("/", 1)[-1]
        response = FileResponse(
            authority.memorandum.open("rb"),
            content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            as_attachment=request.GET.get("download") == "1",
            filename=name,
        )
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response


class DocumentPublishView(CanPublishPPAMixin, PPAContextMixin, DetailView):
    """
    Put one already-cleared file on the public website.

    Needed because a programme is published once and then added to for months.
    Releasing a photograph filed today should not mean unpublishing the whole
    programme and putting it back - that takes everything else offline for the
    sake of one picture, and an office that has to do it will stop publishing
    evidence at all.

    Nothing is relaxed to make this possible. The same four conditions apply as
    when the record was published: a reviewer has approved the file, a
    memorandum authorises its release, the record carrying it is public, and
    the person clicking is a publisher. A file that was published and then
    withdrawn still satisfies the first of those - the approval never went
    away - so putting it back is this one action and not a second review.
    """

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        # A second POST of the same button - an impatient click, a refreshed
        # tab, a browser replaying the request - must not rewrite the public
        # copy or write a second PUBLISH line into the audit log. The state
        # already says what the person was asking for, so say so and stop.
        if document.status == DocumentStatus.PUBLISHED:
            messages.info(
                request,
                f"'{document.title}' is already on the public website.",
            )
            return redirect(safe_next(request, self.request.POST.get("next"),
                            reverse("programs:document_review",
                                       args=[document.pk])))
        was_withdrawn = document.status == DocumentStatus.WITHDRAWN
        try:
            document.publish(request.user)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            record_audit(
                Action.PUBLISH, target=document, request=request,
                detail=(
                    ("Put back on the public website under "
                     if was_withdrawn else "Released on its own under ")
                    + f"{document.authority.reference}, to the "
                    f"already-published {document.owner_label}."
                )[:255],
            )
            messages.success(
                request,
                f"'{document.title}' is "
                + ("back on" if was_withdrawn else "now on")
                + f" the public website, under {document.authority.reference}.",
            )
        return redirect(safe_next(request, self.request.POST.get("next"),
                        reverse("programs:document_review", args=[document.pk])))


class DocumentWithdrawView(CanPublishPPAMixin, PPAContextMixin, DetailView):
    """
    Take one file off the public website, leaving the record published.

    The counterpart of releasing one file on its own: an office that spots a
    face in a photograph needs that photograph gone now, not the whole
    programme page.
    """

    http_method_names = ["post"]
    model = SupportingDocument

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        if document.status == DocumentStatus.WITHDRAWN:
            # Already down, most likely because this is the same click twice.
            # Nothing to do and nothing to warn about.
            messages.info(
                request,
                f"'{document.title}' is already off the public website. The "
                "file itself is still here.",
            )
        elif document.status != DocumentStatus.PUBLISHED:
            messages.error(request, f"'{document.title}' is not published.")
        else:
            document.withdraw(request.user)
            record_audit(
                Action.UNPUBLISH, target=document, request=request,
                detail="Withdrawn from the public website; public copy deleted.",
            )
            messages.success(
                request,
                f"'{document.title}' was taken off the public website and its "
                "public copy deleted. The file itself is untouched, and you "
                "can publish it again from this page. The record it belongs "
                "to is still published.",
            )
        return redirect(safe_next(request, self.request.POST.get("next"),
                        reverse("programs:document_review", args=[document.pk])))
