"""
The workbench - every record in the tree at a glance - and the reviewers'
queue.

Part of programs.views - see its package docstring.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from core.mixins import CanReviewPPAMixin
from ..models import (
    OUTCOME_DETAIL,
    Activity,
    DocumentStatus,
    OrganizationalOutcome,
    Program,
    Project,
    PublicationStatus,
    RiskLevel,
    SubProject,
    SupportingDocument,
)

from .common import LEVELS, PPAContextMixin


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
