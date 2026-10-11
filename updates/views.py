"""
Updates and Accomplishments.

The module has four faces onto the same records, and they are deliberately
different pages rather than one page with tabs:

    the division dashboard   what LGMED has accomplished, in figures
    the reporting weeks      one consolidated record per week
    the Chief's review       what to present, and what may be published
    the convocation view     the Monday slide, projected as it stands

Everything below reads from the period. No view in this module groups,
filters or totals by employee.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, TemplateView, UpdateView

from audit.models import Action
from audit.recording import record
from core import csv_safe
from core.mixins import CanApproveMixin, CanEncodeMixin
from core.safe_json import script_json
from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from . import stats
from .forms import (
    ConvocationSelectionForm,
    DivisionUpdateForm,
    PeriodReviewForm,
    PopsPlanUpdateForm,
    PublicClearanceForm,
    PublicDisclosureForm,
    ReportingPeriodForm,
    UpdateAttachmentForm,
    WayForwardForm,
)
from .models import (
    ActivityType,
    DivisionUpdate,
    PeriodStatus,
    PopsPlanUpdate,
    PublicDisclosure,
    ReportingPeriod,
    UpdateAttachment,
    UpdateCategory,
    UpdateStatus,
    WayForward,
    public_periods,
)

# ---------------------------------------------------------------------------
# The division dashboard
# ---------------------------------------------------------------------------


class DivisionDashboardView(LoginRequiredMixin, TemplateView):
    """
    What has LGMED accomplished, how active is the Division, what is still
    open, and what is next - answered for the Division as a whole.

    Read-only and open to every signed-in role, on the same reasoning as the
    analytics page: figures the office works from should be the same figures
    for everybody who works there.
    """

    template_name = "dashboard/updates/dashboard.html"

    def get_year(self):
        years = stats.available_years()
        try:
            year = int(self.request.GET.get("year", timezone.localdate().year))
        except (TypeError, ValueError):
            return timezone.localdate().year
        return year if year in years else timezone.localdate().year

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            return self.export_csv(self.get_year())
        return super().get(request, *args, **kwargs)

    def export_csv(self, year):
        """Every division figure on the page, as one file."""
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="lgme-accomplishments-{year}.csv"'
        )
        response.write("﻿")

        writer = csv_safe.writer(response)
        writer.writerow([f"LGMED division accomplishments, {year}"])
        writer.writerow(
            ["Generated", timezone.localtime().strftime("%d %B %Y, %I:%M %p")]
        )
        writer.writerow([])

        writer.writerow(["Division statistics"])
        writer.writerow(["Figure", "Value"])
        for figure in stats.breakdown_figures(stats.division_statistics(year=year)):
            writer.writerow([figure["label"], figure["value"]])
        writer.writerow([])

        for chart in stats.charts(year):
            writer.writerow([chart["title"]])
            writer.writerow(chart["headers"])
            for row in chart["rows"]:
                writer.writerow(row)
            writer.writerow([])

        record(
            Action.EXPORT,
            detail=f"Exported the {year} division accomplishment statistics",
            request=self.request,
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = self.get_year()
        figures = stats.division_statistics(year=year)
        charts = stats.charts(year)

        context.update(
            {
                "page_title": "Updates & Accomplishments",
                "page_subtitle": (
                    "What the Local Government Monitoring and Evaluation "
                    "Division has accomplished"
                ),
                "breadcrumbs": [{"label": "Updates & Accomplishments"}],
                "active_nav": "updates",
                "year": year,
                "years": stats.available_years(),
                "stats": figures,
                "cards": stats.headline_cards(figures),
                "figures": stats.breakdown_figures(figures),
                "charts": charts,
                "charts_json": script_json({c["id"]: c["data"] for c in charts}),
                "current_period": ReportingPeriod.current(),
                "upcoming": stats.upcoming_activities(),
                "ways_forward": stats.open_ways_forward(),
                "attention": stats.weeks_needing_attention(),
            }
        )
        return context


# ---------------------------------------------------------------------------
# The reporting weeks
# ---------------------------------------------------------------------------


class PeriodModuleMixin:
    model = ReportingPeriod
    module_key = "updates"
    module_label = "Reporting Period"
    module_url_name = "updates:period_list"
    list_label = "Reporting Weeks"


class PeriodListView(PeriodModuleMixin, ModuleListView):
    page_title = "Reporting Weeks"
    page_subtitle = "One consolidated division record per week"
    template_name = "dashboard/updates/period_list.html"
    search_placeholder = "Search reporting weeks..."
    search_fields = ("theme", "chief_remarks")
    sort_fields = ("start_date", "status")
    default_sort = "-start_date"
    date_field = "start_date"
    date_field_label = "Week beginning"
    create_url_name = "updates:period_create"
    create_label = "Open a Week"
    empty_icon = "calendar"
    filter_fields = (("status", "Status", PeriodStatus.choices),)
    export_columns = (
        ("Week", "label"),
        ("Week beginning", "start_date"),
        ("Week ending", "end_date"),
        ("Theme", "theme"),
        ("Status", "get_status_display"),
        ("Update completion", "completion_percent"),
        ("Published", "is_public"),
    )


class PeriodDetailView(PeriodModuleMixin, ModuleDetailView):
    """
    The consolidated LGMED weekly accomplishment summary.

    Everything several people contributed, gathered into one record: the
    entries, the photographs, the POPS Plan movement, the ways forward, what
    is coming, and which parts of the week are still blank.
    """

    template_name = "dashboard/updates/period_detail.html"

    def get_queryset(self):
        return ReportingPeriod.objects.select_related("reviewed_by", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.object
        figures = stats.division_statistics(period=period)

        context.update(
            {
                "page_title": "LGMED Weekly Updates & Accomplishments",
                "page_subtitle": period.label,
                "stats": figures,
                "cards": stats.headline_cards(figures),
                "figures": stats.breakdown_figures(figures),
                "updates": period.updates.with_related().order_by(
                    "category", "-activity_date"
                ),
                "major": period.major_accomplishments,
                "photos": period.photos,
                "documents": period.supporting_documents,
                "pops_updates": period.pops_updates.all(),
                "pops_compliance": period.pops_compliance,
                "ways_forward": period.ways_forward.all(),
                "upcoming": period.upcoming,
                "components": period.component_state,
                "missing": period.missing_components,
                "without_mov": period.accomplishments.filter(
                    attachments__isnull=True
                ).order_by("-activity_date"),
                "can_review": self.request.user.can_approve,
            }
        )
        return context


class PeriodCreateView(PeriodModuleMixin, ModuleCreateView):
    form_class = ReportingPeriodForm


class PeriodUpdateView(PeriodModuleMixin, ModuleUpdateView):
    form_class = ReportingPeriodForm


class PeriodDeleteView(PeriodModuleMixin, ModuleDeleteView):
    pass


# ---------------------------------------------------------------------------
# The entries staff contribute
# ---------------------------------------------------------------------------


class UpdateModuleMixin:
    model = DivisionUpdate
    module_key = "updates"
    module_label = "Division Update"
    module_url_name = "updates:list"
    list_label = "Division Updates"


class DivisionUpdateListView(UpdateModuleMixin, ModuleListView):
    page_title = "Division Updates"
    page_subtitle = "Every accomplishment contributed to the Division's record"
    template_name = "dashboard/updates/list.html"
    search_placeholder = "Search accomplishments..."
    search_fields = (
        "title", "narrative", "remarks", "location", "counterpart",
        "reference_number", "personnel_involved", "partner",
    )
    sort_fields = ("title", "category", "activity_date", "status")
    default_sort = "-activity_date"
    date_field = "activity_date"
    date_field_label = "Date"
    create_url_name = "updates:create"
    create_label = "Add Update"
    empty_icon = "check-circle"
    filter_fields = (
        ("category", "Category", UpdateCategory.choices),
        ("activity_type", "Activity type", ActivityType.choices),
        ("status", "Status", UpdateStatus.choices),
        ("period", "Reporting week", ()),
    )
    export_columns = (
        ("Title", "title"),
        ("Category", "get_category_display"),
        ("Activity type", "get_activity_type_display"),
        ("Status", "get_status_display"),
        ("Date", "activity_date"),
        ("Reporting week", "period.label"),
        ("LGU", "lgu.name"),
        ("Location", "location"),
        ("Focal person", "focal_person_label"),
        ("Means of verification", "mov_count"),
        ("Presented at convocation", "is_major"),
        ("Published", "is_public"),
    )

    def get_base_queryset(self):
        return DivisionUpdate.objects.with_related()

    def get_filters_context(self):
        """The week filter is a live list of periods, newest first."""
        filters = super().get_filters_context()
        weeks = [
            (str(period.pk), period.label)
            for period in ReportingPeriod.objects.order_by("-start_date")[:52]
        ]
        for entry in filters:
            if entry["name"] == "period":
                entry["options"] = weeks
        return filters


class DivisionUpdateDetailView(UpdateModuleMixin, ModuleDetailView):
    template_name = "dashboard/updates/detail.html"

    def get_queryset(self):
        return DivisionUpdate.objects.with_related()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = "{} &middot; {}".format(
            self.object.get_category_display(), self.object.date_label
        )
        context["attachment_form"] = UpdateAttachmentForm()
        return context


class DivisionUpdateCreateView(UpdateModuleMixin, ModuleCreateView):
    form_class = DivisionUpdateForm


class DivisionUpdateUpdateView(UpdateModuleMixin, ModuleUpdateView):
    form_class = DivisionUpdateForm


class DivisionUpdateDeleteView(UpdateModuleMixin, ModuleDeleteView):
    pass


# ---------------------------------------------------------------------------
# Photographs and supporting documents
# ---------------------------------------------------------------------------


class AttachmentCreateView(CanEncodeMixin, FormView):
    """Files a means of verification against one accomplishment."""

    form_class = UpdateAttachmentForm
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        self.update = get_object_or_404(DivisionUpdate, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        attachment = form.save(commit=False)
        attachment.update = self.update
        attachment.uploaded_by = self.request.user
        attachment.save()
        messages.success(
            self.request,
            f"{attachment.get_mov_type_display()} filed against "
            f"{self.update.title}.",
        )
        return redirect(self.update.get_absolute_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            "The evidence could not be filed: "
            + "; ".join(
                error for errors in form.errors.values() for error in errors
            ),
        )
        return redirect(self.update.get_absolute_url())


class AttachmentDeleteView(ModuleDeleteView):
    model = UpdateAttachment
    module_key = "updates"
    module_label = "Means of Verification"
    module_url_name = "updates:list"
    list_label = "Division Updates"
    template_name = "dashboard/module_confirm_delete.html"

    # Removing a file the office filed is not the same act as deleting the
    # accomplishment it evidences: whoever may encode the entry may take a
    # wrongly filed photograph off it again.
    capability = "can_encode"

    def get_success_url(self):
        return self.object.update.get_absolute_url()

    def get_list_url(self):
        return self.object.update.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.object.update.get_absolute_url()
        return context


# ---------------------------------------------------------------------------
# Records that belong to the week rather than to one entry
# ---------------------------------------------------------------------------


class PeriodChildMixin:
    """
    Shared wiring for the POPS Plan entries and the ways forward.

    Both hang off a week rather than off the module list, so the breadcrumbs,
    the cancel link and the redirect after saving all point back at the week.
    """

    module_key = "updates"
    module_url_name = "updates:period_list"
    list_label = "Reporting Weeks"

    def get_period(self):
        raise NotImplementedError

    def get_list_url(self):
        return self.get_period().get_absolute_url()

    def get_success_url(self):
        return self.get_period().get_absolute_url()

    def get_breadcrumbs(self):
        period = self.get_period()
        return [
            {"label": self.list_label, "url": reverse("updates:period_list")},
            {"label": period.label, "url": period.get_absolute_url()},
            {"label": self.module_label},
        ]


class PeriodChildCreateView(PeriodChildMixin, ModuleCreateView):
    def get_period(self):
        if not hasattr(self, "_period"):
            self._period = get_object_or_404(ReportingPeriod, pk=self.kwargs["pk"])
        return self._period

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = self.get_period().label
        return context

    def form_valid(self, form):
        form.instance.period = self.get_period()
        form.instance.recorded_by = self.request.user
        return super().form_valid(form)


class PeriodChildUpdateView(PeriodChildMixin, ModuleUpdateView):
    # `recorded_by` is who first filed the figure; an edit does not rewrite
    # it, and the audit trail already carries who changed what.

    def get_period(self):
        return self.object.period


class PeriodChildDeleteView(PeriodChildMixin, ModuleDeleteView):
    def get_period(self):
        return self.object.period


class PopsCreateView(PeriodChildCreateView):
    model = PopsPlanUpdate
    form_class = PopsPlanUpdateForm
    module_label = "POPS Plan Update"


class PopsUpdateView(PeriodChildUpdateView):
    model = PopsPlanUpdate
    form_class = PopsPlanUpdateForm
    module_label = "POPS Plan Update"


class PopsDeleteView(PeriodChildDeleteView):
    model = PopsPlanUpdate
    module_label = "POPS Plan Update"


class WayForwardCreateView(PeriodChildCreateView):
    model = WayForward
    form_class = WayForwardForm
    module_label = "Way Forward"


class WayForwardUpdateView(PeriodChildUpdateView):
    model = WayForward
    form_class = WayForwardForm
    module_label = "Way Forward"


class WayForwardDeleteView(PeriodChildDeleteView):
    model = WayForward
    module_label = "Way Forward"


# ---------------------------------------------------------------------------
# The Division Chief's review
# ---------------------------------------------------------------------------


class PeriodReviewView(CanApproveMixin, TemplateView):
    """
    Everything the Chief does to a week, on one page.

    Three forms rather than one: the remarks, the convocation selection and
    the public clearance are three separate decisions, and each posts under
    its own name so the audit trail can say which was taken.
    """

    template_name = "dashboard/updates/review.html"

    def dispatch(self, request, *args, **kwargs):
        self.period = get_object_or_404(ReportingPeriod, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.period
        figures = stats.division_statistics(period=period)

        context.update(
            {
                "page_title": "Review the Division's Week",
                "page_subtitle": period.label,
                "breadcrumbs": [
                    {"label": "Reporting Weeks", "url": reverse("updates:period_list")},
                    {"label": period.label, "url": period.get_absolute_url()},
                    {"label": "Review"},
                ],
                "active_nav": "updates",
                "period": period,
                "stats": figures,
                "cards": stats.headline_cards(figures),
                "missing": period.missing_components,
                # What the Chief would be presenting without evidence behind
                # it. Shown, not blocked: an officer records the activity on
                # the day and files the photograph when it reaches them.
                "selected_without_mov": period.updates.filter(
                    is_major=True, attachments__isnull=True
                ).order_by("convocation_order", "-activity_date"),
                "without_mov": period.accomplishments.filter(
                    attachments__isnull=True
                ).order_by("-activity_date"),
                "review_form": kwargs.get("review_form") or PeriodReviewForm(
                    instance=period
                ),
                "selection_form": kwargs.get("selection_form")
                or ConvocationSelectionForm(period),
                "clearance_form": kwargs.get("clearance_form")
                or PublicClearanceForm(period),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        handler = {
            "remarks": self.save_remarks,
            "selection": self.save_selection,
            "clearance": self.save_clearance,
            "submit": self.submit_for_review,
            "reviewed": self.mark_reviewed,
            "publish": self.publish,
            "reopen": self.reopen,
        }.get(action)

        if handler is None:
            messages.error(request, "That action is not recognised.")
            return redirect(self.period.get_absolute_url())
        return handler(request)

    # -- the three forms --------------------------------------------------

    def save_remarks(self, request):
        form = PeriodReviewForm(request.POST, instance=self.period)
        if not form.is_valid():
            messages.error(request, "The review could not be saved.")
            return self.render_to_response(
                self.get_context_data(review_form=form)
            )
        period = form.save(commit=False)
        period.updated_by = request.user
        period.save()
        messages.success(request, "The Chief's remarks were saved.")
        return redirect(self.review_url())

    def save_selection(self, request):
        form = ConvocationSelectionForm(self.period, request.POST)
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(selection_form=form)
            )
        chosen = form.save()
        record(
            Action.UPDATE,
            detail=(
                f"Selected {len(chosen)} accomplishment"
                f"{'' if len(chosen) == 1 else 's'} for the convocation of "
                f"{self.period.label}"
            ),
            request=request,
        )
        messages.success(
            request,
            f"{len(chosen)} accomplishment{'' if len(chosen) == 1 else 's'} "
            "will be presented at the convocation.",
        )
        return redirect(self.review_url())

    def save_clearance(self, request):
        form = PublicClearanceForm(self.period, request.POST)
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(clearance_form=form)
            )
        entries, photos = form.save()
        record(
            Action.UPDATE,
            detail=(
                f"Cleared {len(entries)} entries and {len(photos)} photographs "
                f"of {self.period.label} for the public website"
            ),
            request=request,
        )
        messages.success(request, "The public clearance was saved.")
        return redirect(self.review_url())

    # -- the transitions --------------------------------------------------

    def submit_for_review(self, request):
        self.period.submit_for_review(request.user)
        messages.success(
            request, "The week was submitted for the Division Chief's review."
        )
        return redirect(self.period.get_absolute_url())

    def mark_reviewed(self, request):
        self.period.mark_reviewed(request.user)
        messages.success(request, "The week is marked as reviewed.")
        return redirect(self.review_url())

    def publish(self, request):
        if not self.period.updates.filter(is_public=True).exists():
            messages.error(
                request,
                "Nothing has been cleared for the public website yet. Clear at "
                "least one entry before publishing the week.",
            )
            return redirect(self.review_url())
        self.period.publish(request.user)
        record(
            Action.UPDATE,
            detail=f"Published the division summary for {self.period.label}",
            request=request,
        )
        messages.success(
            request, "The division summary is published to the public website."
        )
        return redirect(self.review_url())

    def reopen(self, request):
        self.period.reopen(request.user)
        messages.success(
            request,
            "The week is open for contributions again and has been withdrawn "
            "from the public website.",
        )
        return redirect(self.review_url())

    def review_url(self):
        return reverse("updates:review", args=[self.period.pk])


class PeriodSubmitView(CanEncodeMixin, TemplateView):
    """
    Hands the week to the Chief.

    Separated from the review page because this is the contributors' act, not
    the Chief's: anyone who may encode may say the Division's week is ready.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        period = get_object_or_404(ReportingPeriod, pk=kwargs["pk"])
        period.submit_for_review(request.user)
        messages.success(
            request,
            f"{period.label} was submitted for the Division Chief's review.",
        )
        return redirect(period.get_absolute_url())


# ---------------------------------------------------------------------------
# The Monday convocation
# ---------------------------------------------------------------------------


class ConvocationView(LoginRequiredMixin, TemplateView):
    """
    The week as it is presented on Monday morning.

    Deliberately a projection surface rather than a working page: division
    figures, the major accomplishments the Chief selected, the photographs,
    the POPS Plan position, the ways forward and what is coming - and no
    controls that could be clicked by accident in front of the office.
    """

    template_name = "dashboard/updates/convocation.html"

    def get_period(self):
        if "pk" in self.kwargs:
            return get_object_or_404(ReportingPeriod, pk=self.kwargs["pk"])
        return (
            ReportingPeriod.objects.exclude(status=PeriodStatus.OPEN)
            .order_by("-start_date")
            .first()
            or ReportingPeriod.objects.order_by("-start_date").first()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.get_period()
        context.update(
            {
                "page_title": "Monday Convocation",
                "active_nav": "updates",
                "period": period,
            }
        )
        if period is None:
            return context

        figures = stats.division_statistics(period=period)
        context.update(
            {
                "page_subtitle": period.label,
                "breadcrumbs": [
                    {"label": "Reporting Weeks", "url": reverse("updates:period_list")},
                    {"label": period.label, "url": period.get_absolute_url()},
                    {"label": "Convocation"},
                ],
                "stats": figures,
                "cards": stats.headline_cards(figures),
                "major": period.major_accomplishments.prefetch_related("attachments"),
                "photos": period.photos,
                "pops_updates": period.pops_updates.all(),
                "pops_compliance": period.pops_compliance,
                "ways_forward": period.ways_forward.all(),
                "upcoming": period.upcoming,
            }
        )
        return context


class PublicDisclosureView(CanApproveMixin, UpdateView):
    """
    How much of the published record the public website is showing.

    A separate page from the weekly review because it is a standing decision
    rather than a decision about one week: the Chief sets it once and it
    governs the public site until it is changed. The page shows exactly which
    weeks the current setting selects, so the answer to "what are we showing"
    is on the same screen as the control that decides it.
    """

    form_class = PublicDisclosureForm
    template_name = "dashboard/updates/disclosure.html"

    def get_object(self, queryset=None):
        # Deliberately not `load()`: that returns a cached row, and an edit
        # form must start from what is actually stored.
        disclosure, _ = PublicDisclosure.objects.get_or_create(pk=1)
        return disclosure

    def get_success_url(self):
        return reverse("updates:disclosure")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        showing = list(public_periods()[:20])
        context.update(
            {
                "page_title": "Public Disclosure Window",
                "page_subtitle": (
                    "What the public website shows of the Division's published "
                    "record"
                ),
                "breadcrumbs": [
                    {"label": "Reporting Weeks", "url": reverse("updates:period_list")},
                    {"label": "Public Disclosure"},
                ],
                "active_nav": "updates",
                "disclosure": self.object,
                "showing": showing,
                "published_count": ReportingPeriod.objects.published().count(),
                "submit_label": "Save",
                "cancel_url": reverse("updates:period_list"),
            }
        )
        return context

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        record(
            Action.UPDATE,
            detail=f"Set the public disclosure window: {self.object.describe()}",
            request=self.request,
        )
        messages.success(self.request, self.object.describe())
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "The disclosure window could not be saved. Correct the "
            "highlighted fields and try again.",
        )
        return super().form_invalid(form)
