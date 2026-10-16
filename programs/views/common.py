"""
What every PPA view shares: the four levels and how a URL names them, the
context and breadcrumb mixins, and the workflow explanations shown on pages.

Part of programs.views - see its package docstring.
"""

from django.http import Http404
from django.urls import reverse

from core.views_base import ModuleContextMixin
from ..forms import ActivityForm, ProgramForm, ProjectForm, SubProjectForm
from ..models import Activity, Program, Project, PublicationStatus, SubProject


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
