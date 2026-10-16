"""Forms for the Monthly Submissions module."""

from datetime import time

from django import forms
from django.utils import timezone

from core.forms_base import FILE_CLASS, SELECT_CLASS, TEXT_CLASS, TEXTAREA_CLASS

from .models import (
    ALLOWED_EXTENSIONS,
    MONTH_CHOICES,
    DocumentKind,
    MonthlySubmissionSchedule,
)
from .validators import validate_submission_file


class ScheduleForm(forms.Form):
    """
    The Chief's deadline for one reporting month.

    Creating picks the month; editing a schedule keeps its month fixed and
    changes only the deadline and the announcement - a deadline moved to
    another month is a different schedule, not an edit of this one.
    """

    reporting_month = forms.TypedChoiceField(
        label="Reporting month", choices=MONTH_CHOICES, coerce=int,
    )
    reporting_year = forms.IntegerField(
        label="Reporting year", min_value=2000, max_value=2100,
    )
    deadline_date = forms.DateField(
        label="Submission deadline date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    deadline_time = forms.TimeField(
        label="Deadline time", initial=time(17, 0),
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        help_text="Philippine Standard Time (Asia/Manila).",
    )
    announcement = forms.CharField(
        label="Announcement / instructions", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Optional. Shown to staff on their page and included in the email.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            local = instance.deadline_local
            kwargs["initial"] = {
                "reporting_month": instance.reporting_month,
                "reporting_year": instance.reporting_year,
                "deadline_date": local.date(),
                "deadline_time": local.time().replace(second=0, microsecond=0),
                "announcement": instance.announcement,
            }
        elif instance is None and "initial" not in kwargs:
            today = timezone.localdate()
            kwargs["initial"] = {
                "reporting_month": today.month,
                "reporting_year": today.year,
                "deadline_time": time(17, 0),
            }
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs["class"] = SELECT_CLASS
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = TEXTAREA_CLASS
            else:
                widget.attrs["class"] = TEXT_CLASS

        if instance is not None:
            # The month is the schedule's identity; it is shown, not edited.
            for name in ("reporting_month", "reporting_year"):
                self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        month = cleaned.get("reporting_month")
        year = cleaned.get("reporting_year")
        day = cleaned.get("deadline_date")
        at = cleaned.get("deadline_time")
        if not (month and year and day and at):
            return cleaned

        if self.instance is None and MonthlySubmissionSchedule.objects.filter(
            reporting_year=year, reporting_month=month
        ).exists():
            raise forms.ValidationError(
                "A deadline is already set for that reporting month. Open it "
                "from Deadline Management to change or extend it."
            )

        deadline = MonthlySubmissionSchedule.combine(day, at)
        if deadline <= timezone.now():
            self.add_error(
                "deadline_date", "The deadline must be later than the present time."
            )
        if day < MonthlySubmissionSchedule(
            reporting_year=year, reporting_month=month
        ).period_start:
            self.add_error(
                "deadline_date",
                "The deadline cannot fall before the reporting month begins.",
            )
        cleaned["deadline"] = deadline
        return cleaned


class UploadForm(forms.Form):
    """One file, for one of the two slots."""

    kind = forms.ChoiceField(choices=DocumentKind.choices)
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={
            "class": FILE_CLASS,
            "accept": ",".join(f".{ext}" for ext in ALLOWED_EXTENSIONS),
        }),
    )

    def clean_file(self):
        return validate_submission_file(self.cleaned_data.get("file"))


class ReminderForm(forms.Form):
    """
    The rows the Chief ticked on the monitoring table.

    Each value is "<schedule id>:<staff id>"; the view decides which of them
    still have something missing, so a ticked row that completed in the
    meantime is quietly left out rather than nagged.
    """

    selected = forms.MultipleChoiceField(required=True)
    message = forms.CharField(required=False, max_length=500)

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected"].choices = [(value, value) for value in choices]
        self.fields["selected"].error_messages["required"] = (
            "Select at least one staff member to remind."
        )

    def pairs(self):
        result = []
        for value in self.cleaned_data["selected"]:
            schedule_id, _, staff_id = value.partition(":")
            result.append((int(schedule_id), int(staff_id)))
        return result
