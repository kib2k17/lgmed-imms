"""
Monthly Submissions: the staff member's page and the Division Chief's.

One sidebar entry, two sides. `home` shows staff their own MMIA and DTR, and
shows the Chief everyone's. Every view re-checks the capability it needs, and
every file goes out through `SubmissionFileView`, which checks that the person
asking owns the file or manages the module - protected storage has no public
URL to fall back on.
"""

import io

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView, View

from accounts.models import User
from audit.models import Action
from audit.recording import record
from core import csv_safe
from core.files import is_pdf, send_fieldfile, serve_inline
from core.mixins import CapabilityRequiredMixin

from . import notify, services
from .forms import ReminderForm, ScheduleForm, UploadForm
from .models import (
    ALLOWED_EXTENSIONS,
    DOCUMENT_DESCRIPTIONS,
    DOCUMENT_TITLES,
    MONTH_CHOICES,
    AuditAction,
    DocumentKind,
    MonthlyStaffSubmission,
    MonthlySubmissionAuditLog,
    MonthlySubmissionNotification,
    MonthlySubmissionSchedule,
)
from .status import LABELS, SHORT_LABELS, STATUS_ORDER, TONES, standing
from .validators import max_upload_bytes

ACTIVITY_ACTIONS = (
    AuditAction.UPLOADED, AuditAction.REPLACED, AuditAction.COMPLETED,
    AuditAction.SCHEDULE_CREATED, AuditAction.DEADLINE_EXTENDED,
    AuditAction.DEADLINE_CHANGED, AuditAction.REMINDER_SENT,
)
PAGE_SIZE = 25


def _wants_json(request):
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
    )


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ModuleMixin(CapabilityRequiredMixin):
    capability = "can_use_monthly_submissions"

    def base_context(self, title, subtitle="", crumbs=None):
        return {
            "active_nav": "monthly_submissions",
            "page_title": title,
            "page_subtitle": subtitle,
            "breadcrumbs": [
                {"label": "Monthly Submissions", "url": reverse("submissions:home")},
                *(crumbs or []),
            ] if crumbs else [{"label": "Monthly Submissions"}],
            "max_upload_mb": max_upload_bytes() // (1024 * 1024),
            "accept_extensions": ",".join(f".{ext}" for ext in ALLOWED_EXTENSIONS),
            "status_labels": LABELS,
        }


# ---------------------------------------------------------------------------
# Presenting one submission
# ---------------------------------------------------------------------------


def document_cards(schedule, submission, viewer):
    """What the two document cards show, in MMIA-then-DTR order."""
    cards = []
    for kind in DocumentKind:
        has = submission is not None and submission.has(kind)
        card = {
            "kind": kind.value,
            "label": kind.label,
            "title": DOCUMENT_TITLES[kind],
            "description": DOCUMENT_DESCRIPTIONS[kind],
            "has": has,
        }
        if has:
            card.update({
                "name": submission.original_name(kind),
                "size": submission.size(kind),
                "uploaded_at": submission.uploaded_at(kind),
                "is_pdf": is_pdf(submission.file_for(kind)),
                "download_url": reverse(
                    "submissions:file", args=[submission.pk, kind.value]
                ),
                "view_url": reverse(
                    "submissions:file_view", args=[submission.pk, kind.value]
                ),
            })
        cards.append(card)
    return cards


def staff_panel_context(user, schedule, at=None):
    """The context the staff page's live parts are rendered from."""
    at = at or timezone.now()
    submission = services.submission_for(user, schedule) if schedule else None
    current = standing(schedule, submission, at) if schedule else None
    return {
        "schedule": schedule,
        "submission": submission,
        "standing": current,
        "cards": document_cards(schedule, submission, user) if schedule else [],
        "can_upload": bool(
            schedule and schedule.is_open(at) and user.must_submit_monthly
        ),
        "days_remaining": schedule.days_remaining(at) if schedule else None,
        "is_open": bool(schedule and schedule.is_open(at)),
    }


# ---------------------------------------------------------------------------
# The landing page: each role its own side
# ---------------------------------------------------------------------------


class HomeView(ModuleMixin, View):
    def get(self, request):
        if request.user.can_manage_monthly_submissions:
            return MonitorView.as_view()(request)
        return StaffDashboardView.as_view()(request)


class StaffDashboardView(ModuleMixin, TemplateView):
    """A staff member's own MMIA and DTR, this month and every month before."""

    capability = "must_submit_monthly"
    template_name = "dashboard/submissions/staff.html"

    def get_schedule(self):
        period = _int(self.request.GET.get("period"))
        if period:
            return get_object_or_404(MonthlySubmissionSchedule, pk=period)
        return services.default_schedule_for_staff()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()
        schedule = self.get_schedule()

        submissions = {
            item.schedule_id: item
            for item in MonthlyStaffSubmission.objects.filter(staff=user)
        }
        history = []
        for item in MonthlySubmissionSchedule.objects.order_by(
            "-reporting_year", "-reporting_month"
        ):
            submission = submissions.get(item.pk)
            history.append({
                "schedule": item,
                "submission": submission,
                "standing": standing(item, submission, now),
                "is_current": schedule is not None and item.pk == schedule.pk,
            })

        context.update(self.base_context(
            "Monthly Accomplishment & DTR Submission",
            "Submit your Monthly Monitoring Individual Accomplishments (MMIA) "
            "and Daily Time Record (DTR) within the prescribed submission period.",
        ))
        context.update(staff_panel_context(user, schedule, now))
        context.update({
            "open_schedules": MonthlySubmissionSchedule.objects.open(now).order_by("deadline"),
            "history": history,
            "now": now,
        })
        return context


# ---------------------------------------------------------------------------
# Uploading
# ---------------------------------------------------------------------------


class UploadView(ModuleMixin, View):
    """
    Receive one file for one slot.

    Answers JSON to the page's script, which updates the cards in place, and
    a redirect with a message to a plain form post, so the page still works
    with scripting off.
    """

    capability = "must_submit_monthly"
    http_method_names = ["post"]

    def post(self, request, pk):
        schedule = get_object_or_404(MonthlySubmissionSchedule, pk=pk)
        back = f"{reverse('submissions:home')}?period={schedule.pk}"
        form = UploadForm(request.POST, request.FILES)
        kind = request.POST.get("kind", "")

        if not schedule.is_open():
            return self.closed(request, schedule, kind, back)

        if not form.is_valid():
            errors = [str(e) for field in form.errors.values() for e in field]
            services.refuse(
                request.user, schedule, kind,
                "Refused: " + " ".join(errors), request=request,
            )
            if _wants_json(request):
                return JsonResponse({"ok": False, "errors": errors}, status=400)
            for error in errors:
                messages.error(request, error)
            return redirect(back)

        kind = DocumentKind(form.cleaned_data["kind"])
        try:
            submission, replaced, completed = services.upload(
                request.user, schedule, kind, form.cleaned_data["file"],
                request=request,
            )
        except services.UploadClosed:
            return self.closed(request, schedule, kind.value, back)

        if completed:
            message = (
                f"Both documents are in. Your {schedule.period_label} submission "
                "is complete."
            )
        else:
            message = f"Your {kind.label} was {'replaced' if replaced else 'uploaded'}."

        if _wants_json(request):
            context = staff_panel_context(request.user, schedule)
            context.update(self_context(request))
            return JsonResponse({
                "ok": True,
                "message": message,
                "completed": completed,
                "status": context["standing"].status,
                "html": {
                    "summary": render_to_string(
                        "dashboard/submissions/_staff_summary.html", context, request
                    ),
                    "cards": render_to_string(
                        "dashboard/submissions/_document_cards.html", context, request
                    ),
                },
            })
        messages.success(request, message)
        return redirect(back)

    def closed(self, request, schedule, kind, back):
        services.refuse(
            request.user, schedule, kind,
            "Refused: the submission deadline has passed.", request=request,
        )
        text = (
            "Submission Deadline Has Passed. The prescribed submission period "
            "has ended. Please coordinate with your Division Chief if you need "
            "to submit or update your documents."
        )
        if _wants_json(request):
            return JsonResponse({"ok": False, "closed": True, "errors": [text]}, status=403)
        messages.error(request, text)
        return redirect(back)


def self_context(request):
    """What the partial templates need beyond the panel itself."""
    return {
        "max_upload_mb": max_upload_bytes() // (1024 * 1024),
        "accept_extensions": ",".join(f".{ext}" for ext in ALLOWED_EXTENSIONS),
        "user": request.user,
    }


# ---------------------------------------------------------------------------
# Serving files
# ---------------------------------------------------------------------------


def _submission_file(request, pk, kind):
    if kind not in DocumentKind.values:
        raise Http404()
    submission = get_object_or_404(
        MonthlyStaffSubmission.objects.select_related("schedule", "staff"), pk=pk
    )
    user = request.user
    if submission.staff_id != user.pk and not user.can_manage_monthly_submissions:
        raise PermissionDenied("You may only open your own submissions.")
    fieldfile = submission.file_for(kind)
    if not fieldfile:
        raise Http404("No file has been submitted here.")
    return submission, DocumentKind(kind), fieldfile


class SubmissionFileView(ModuleMixin, View):
    """Download an MMIA or DTR, after checking it is the asker's to open."""

    def get(self, request, pk, kind):
        submission, kind, fieldfile = _submission_file(request, pk, kind)
        response = send_fieldfile(
            fieldfile, as_attachment=True,
            filename=submission.original_name(kind) or f"{kind.value}",
            content_type="application/octet-stream",
        )
        services.log(
            AuditAction.DOWNLOADED, user=request.user, schedule=submission.schedule,
            staff=submission.staff, kind=kind,
            details=f"Downloaded {kind.label} {submission.original_name(kind)}",
            request=request,
        )
        return response


@method_decorator(xframe_options_sameorigin, name="dispatch")
class SubmissionFileInlineView(ModuleMixin, View):
    """Show a PDF in the in-system viewer; anything else is downloaded."""

    def get(self, request, pk, kind):
        submission, kind, fieldfile = _submission_file(request, pk, kind)
        response = serve_inline(fieldfile)
        if response.get("Content-Disposition", "").startswith("attachment"):
            response["Content-Disposition"] = content_disposition_header(
                True, submission.original_name(kind) or kind.value
            )
        services.log(
            AuditAction.VIEWED, user=request.user, schedule=submission.schedule,
            staff=submission.staff, kind=kind,
            details=f"Opened {kind.label} {submission.original_name(kind)}",
            request=request,
        )
        return response


# ---------------------------------------------------------------------------
# The Division Chief: monitoring
# ---------------------------------------------------------------------------


def _filtered_rows(request, now):
    """
    The schedules and rows the monitoring table and the export both use.

    With no filters at all, the current reporting month is shown, so the
    Chief lands on what matters today rather than on every month at once.
    """
    params = request.GET
    year = _int(params.get("year"))
    month = _int(params.get("month"))
    explicit = any(key in params for key in ("year", "month", "q", "status"))

    schedules = MonthlySubmissionSchedule.objects.all()
    if not explicit:
        default = services.default_schedule_for_chief(now)
        if default is not None:
            year, month = default.reporting_year, default.reporting_month
    if year:
        schedules = schedules.filter(reporting_year=year)
    if month:
        schedules = schedules.filter(reporting_month=month)
    schedules = list(schedules.order_by("-reporting_year", "-reporting_month"))

    all_rows = services.monitoring_rows(schedules, now)
    summary = services.summarise(all_rows)

    rows = all_rows
    query = (params.get("q") or "").strip().lower()
    if query:
        rows = [
            row for row in rows
            if query in row.staff.get_display_name().lower()
            or query in row.staff.username.lower()
            or query in (row.staff.position or "").lower()
        ]
    status_filter = params.get("status") or ""
    if status_filter in STATUS_ORDER:
        rows = [row for row in rows if row.standing.status == status_filter]

    sort = params.get("sort") or "name"
    if sort in ("submitted", "-submitted"):
        # Completed submissions in date order; those not yet complete follow,
        # whichever way the dates run.
        done = sorted(
            (row for row in rows if row.submitted_on),
            key=lambda row: row.submitted_on, reverse=sort.startswith("-"),
        )
        rows = done + [row for row in rows if not row.submitted_on]
    elif sort == "status":
        rows = sorted(rows, key=lambda r: STATUS_ORDER.index(r.standing.status))
    else:
        sort = "name"
        rows = sorted(
            rows,
            key=lambda r: (
                -r.schedule.reporting_year, -r.schedule.reporting_month,
                (r.staff.last_name or r.staff.username).lower(),
                r.staff.first_name.lower(),
            ),
        )
    return {
        "schedules": schedules,
        "all_rows": all_rows,
        "rows": rows,
        "summary": summary,
        "year": year,
        "month": month,
        "query": params.get("q") or "",
        "status_filter": status_filter,
        "sort": sort,
    }


class MonitorView(ModuleMixin, TemplateView):
    capability = "can_manage_monthly_submissions"
    template_name = "dashboard/submissions/monitor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        data = _filtered_rows(self.request, now)
        schedules = data["schedules"]
        focus = schedules[0] if len(schedules) == 1 else None

        paginator = Paginator(data["rows"], PAGE_SIZE)
        page = paginator.get_page(self.request.GET.get("page"))

        years = sorted(
            set(MonthlySubmissionSchedule.objects.values_list("reporting_year", flat=True))
            | {now.year},
            reverse=True,
        )
        summary = data["summary"]
        total = summary["total"] or 1
        chart = [
            {"key": "completed", "label": "Completed", "count": summary["completed"],
             "tone": "success"},
            {"key": "partial", "label": "Incomplete", "count": summary["partial"],
             "tone": "warning"},
            {"key": "not_submitted", "label": "Not submitted",
             "count": summary["not_submitted"], "tone": "neutral"},
            {"key": "overdue", "label": "Overdue", "count": summary["overdue"],
             "tone": "danger"},
        ]
        for segment in chart:
            segment["percent"] = round(segment["count"] * 100 / total, 1)

        activity = MonthlySubmissionAuditLog.objects.filter(
            action__in=ACTIVITY_ACTIONS
        ).select_related("schedule", "staff")
        if schedules:
            activity = activity.filter(schedule__in=schedules)

        context.update(self.base_context(
            "Monthly Staff Submission Monitoring",
            "Monitor and manage the monthly MMIA and DTR submission compliance "
            "of LGMED personnel.",
        ))
        context.update(data)
        context.update({
            "stat_cards": [
                {"label": "Total Staff", "value": summary["total"], "icon": "users",
                 "meta": "Required to submit" + (
                     f" across {len(schedules)} months" if len(schedules) > 1 else ""
                 )},
                {"label": "Completed Submissions", "value": summary["completed"],
                 "icon": "check-circle", "tone": "success",
                 "meta": f"{summary['percent']}% complete - MMIA and DTR both in"},
                {"label": "Incomplete Submissions", "value": summary["partial"],
                 "icon": "clock", "tone": "warning",
                 "meta": "One of the two documents in"},
                {"label": "Not Submitted", "value": summary["not_submitted"],
                 "icon": "inbox", "meta": "Neither document yet"},
                {"label": "Overdue Submissions", "value": summary["overdue"],
                 "icon": "warning", "tone": "danger",
                 "meta": "Deadline passed, still incomplete"},
            ],
            "focus": focus,
            "focus_days": focus.days_remaining(now) if focus else None,
            "focus_open": focus.is_open(now) if focus else False,
            "page_obj": page,
            "page_rows": page.object_list,
            "years": years,
            "months": MONTH_CHOICES,
            "status_options": [(s, SHORT_LABELS[s]) for s in STATUS_ORDER],
            "status_tones": TONES,
            "chart": chart,
            "activity": activity[:10],
            "schedule_form": kwargs.get("schedule_form") or ScheduleForm(),
            "pending_on_page": sum(
                1 for row in page.object_list if not row.standing.is_complete
            ),
            "can_submit_too": self.request.user.must_submit_monthly,
            "now": now,
        })
        return context


class ReviewView(ModuleMixin, TemplateView):
    """One staff member's submission for one month, as the Chief sees it."""

    capability = "can_manage_monthly_submissions"
    template_name = "dashboard/submissions/review.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        schedule = get_object_or_404(MonthlySubmissionSchedule, pk=self.kwargs["schedule"])
        person = get_object_or_404(User, pk=self.kwargs["staff"])
        submission = services.submission_for(person, schedule)
        now = timezone.now()
        context.update(self.base_context(
            person.get_display_name(),
            f"{schedule.period_label} MMIA and DTR submission",
            crumbs=[{"label": person.get_display_name()}],
        ))
        context.update({
            "schedule": schedule,
            "person": person,
            "submission": submission,
            "standing": standing(schedule, submission, now),
            "cards": document_cards(schedule, submission, self.request.user),
            "trail": MonthlySubmissionAuditLog.objects.filter(
                schedule=schedule, staff=person
            ).select_related("user")[:50],
            "emails": MonthlySubmissionNotification.objects.filter(
                schedule=schedule, recipient=person
            )[:30],
            "row_key": f"{schedule.pk}:{person.pk}",
        })
        return context


class SendReminderView(ModuleMixin, View):
    """Email and notify the ticked staff who still have something missing."""

    capability = "can_manage_monthly_submissions"
    http_method_names = ["post"]

    def post(self, request):
        back = request.POST.get("next") or reverse("submissions:home")
        if not url_has_allowed_host_and_scheme(
            back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            back = reverse("submissions:home")

        posted = request.POST.getlist("selected")
        schedule_ids = {_int(value.partition(":")[0]) for value in posted} - {None}
        schedules = MonthlySubmissionSchedule.objects.filter(pk__in=schedule_ids)
        pending = {
            row.key: row
            for row in services.monitoring_rows(schedules)
            if not row.standing.is_complete
        }
        form = ReminderForm(request.POST, choices=pending.keys())
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(
                        request,
                        "Select staff whose submission is still incomplete."
                        if "valid choice" in str(error) else error,
                    )
            return redirect(back)

        rows = [pending[value] for value in form.cleaned_data["selected"]]
        note = form.cleaned_data.get("message", "").strip()
        count = notify.manual_reminders(
            rows, request.user, note=note, base_url=services.base_url_of(request)
        )
        for row in rows:
            services.log(
                AuditAction.REMINDER_SENT, user=request.user, schedule=row.schedule,
                staff=row.staff,
                details=f"Reminder sent for {row.schedule.period_label} "
                        f"(missing: {', '.join(row.standing.missing_labels)})",
                request=request,
            )
        messages.success(
            request,
            f"Reminder sent to {count} staff member{'s' if count != 1 else ''} "
            "by email and in-system notification.",
        )
        return redirect(back)


class ExportView(ModuleMixin, View):
    """The monthly compliance report, as a CSV for Excel."""

    capability = "can_manage_monthly_submissions"

    def get(self, request):
        now = timezone.now()
        data = _filtered_rows(request, now)
        summary = data["summary"]
        buffer = io.StringIO()
        writer = csv_safe.writer(buffer)

        periods = ", ".join(s.period_label for s in data["schedules"]) or "None"
        writer.writerow(["LGMED-iMMS Monthly Compliance Report (MMIA and DTR)"])
        writer.writerow(["Reporting month(s)", periods])
        writer.writerow(["Generated", timezone.localtime(now).strftime("%Y-%m-%d %H:%M PST")])
        writer.writerow(["Total staff", summary["total"]])
        writer.writerow(["Completed submissions", summary["completed"]])
        writer.writerow(["Incomplete submissions", summary["partial"]])
        writer.writerow(["Not submitted", summary["not_submitted"]])
        writer.writerow(["Overdue submissions", summary["overdue"]])
        writer.writerow(["Completion percentage", f"{summary['percent']}%"])
        writer.writerow([])
        writer.writerow([
            "Staff name", "Username", "Position", "Reporting month", "Deadline",
            "MMIA", "MMIA uploaded", "DTR", "DTR uploaded", "Status",
            "Date completed",
        ])

        def stamp(value):
            return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""

        for row in data["rows"]:
            sub = row.submission
            writer.writerow([
                row.staff.get_display_name(), row.staff.username,
                row.staff.position, row.schedule.period_label,
                timezone.localtime(row.schedule.deadline).strftime("%Y-%m-%d %H:%M"),
                "Submitted" if row.has_mmia else "Pending",
                stamp(sub.mmia_uploaded_at) if sub else "",
                "Submitted" if row.has_dtr else "Pending",
                stamp(sub.dtr_uploaded_at) if sub else "",
                row.standing.short_label,
                stamp(row.submitted_on),
            ])

        services.log(
            AuditAction.EXPORTED, user=request.user,
            schedule=data["schedules"][0] if len(data["schedules"]) == 1 else None,
            details=f"Compliance report exported: {periods}", request=request,
        )
        record(Action.EXPORT, actor=request.user, request=request,
               target_label="Monthly submissions compliance report",
               detail=f"Reporting month(s): {periods}"[:255])

        label = (
            f"{data['schedules'][0].reporting_year}-{data['schedules'][0].reporting_month:02d}"
            if len(data["schedules"]) == 1 else "all"
        )
        response = HttpResponse(
            "﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="mmia-dtr-compliance-{label}.csv"'
        )
        return response


# ---------------------------------------------------------------------------
# The Division Chief: deadlines
# ---------------------------------------------------------------------------


class ScheduleListView(ModuleMixin, TemplateView):
    capability = "can_manage_monthly_submissions"
    template_name = "dashboard/submissions/schedules.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        schedules = list(MonthlySubmissionSchedule.objects.select_related(
            "created_by", "updated_by"
        ))
        rows = services.monitoring_rows(schedules, now)
        by_schedule = {}
        for row in rows:
            by_schedule.setdefault(row.schedule.pk, []).append(row)
        items = [
            {
                "schedule": item,
                "summary": services.summarise(by_schedule.get(item.pk, [])),
                "is_open": item.is_open(now),
                "days": item.days_remaining(now),
            }
            for item in schedules
        ]
        context.update(self.base_context(
            "Submission Deadline Management",
            "Set, change and extend the MMIA and DTR deadline for each reporting "
            "month. Deadlines are in Philippine Standard Time.",
            crumbs=[{"label": "Deadline Management"}],
        ))
        context.update({
            "items": items,
            "schedule_form": kwargs.get("schedule_form") or ScheduleForm(),
            "open_dialog": kwargs.get("open_dialog", False),
            "trail": MonthlySubmissionAuditLog.objects.filter(action__in=(
                AuditAction.SCHEDULE_CREATED, AuditAction.DEADLINE_CHANGED,
                AuditAction.DEADLINE_EXTENDED, AuditAction.ANNOUNCEMENT_UPDATED,
            )).select_related("schedule")[:15],
        })
        return context


class ScheduleCreateView(ScheduleListView):
    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        return redirect("submissions:schedules")

    def post(self, request, *args, **kwargs):
        form = ScheduleForm(request.POST)
        if form.is_valid():
            schedule = services.create_schedule(form.cleaned_data, request.user, request)
            messages.success(
                request,
                f"The {schedule.period_label} deadline is set to "
                f"{services.format_deadline(schedule.deadline)}. Staff are being "
                "notified by email and in the system.",
            )
            return redirect(f"{reverse('submissions:home')}?year="
                            f"{schedule.reporting_year}&month={schedule.reporting_month}")
        messages.error(request, "The deadline was not saved. Check the form below.")
        return self.render_to_response(
            self.get_context_data(schedule_form=form, open_dialog=True)
        )


class ScheduleUpdateView(ModuleMixin, TemplateView):
    capability = "can_manage_monthly_submissions"
    template_name = "dashboard/submissions/schedule_form.html"

    def get_schedule(self):
        return get_object_or_404(MonthlySubmissionSchedule, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        schedule = kwargs.get("schedule") or self.get_schedule()
        now = timezone.now()
        context.update(self.base_context(
            f"{schedule.period_label} Deadline",
            "Change or extend the deadline. Staff who have not completed are "
            "notified of the new deadline by email and in the system.",
            crumbs=[
                {"label": "Deadline Management", "url": reverse("submissions:schedules")},
                {"label": schedule.period_label},
            ],
        ))
        context.update({
            "schedule": schedule,
            "form": kwargs.get("form") or ScheduleForm(instance=schedule),
            "is_open": schedule.is_open(now),
            "summary": services.summarise(services.monitoring_rows([schedule], now)),
            "trail": MonthlySubmissionAuditLog.objects.filter(
                schedule=schedule, action__in=(
                    AuditAction.SCHEDULE_CREATED, AuditAction.DEADLINE_CHANGED,
                    AuditAction.DEADLINE_EXTENDED, AuditAction.ANNOUNCEMENT_UPDATED,
                ),
            ),
        })
        return context

    def post(self, request, pk):
        schedule = self.get_schedule()
        form = ScheduleForm(request.POST, instance=schedule)
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(schedule=schedule, form=form)
            )
        schedule, change = services.update_schedule(
            schedule, form.cleaned_data, request.user, request
        )
        if change:
            messages.success(
                request,
                f"The {schedule.period_label} deadline was {change} to "
                f"{services.format_deadline(schedule.deadline)}. Staff who have not "
                "completed are being notified.",
            )
        else:
            messages.success(request, f"The {schedule.period_label} schedule was saved.")
        return redirect("submissions:schedules")
