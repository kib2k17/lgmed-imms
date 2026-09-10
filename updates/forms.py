"""
The forms staff contribute through, and the ones the Chief reviews with.

There is a separate form per decision rather than one form with everything on
it, for the same reason the Document Management module has one: the audit
trail should be able to say which act a change belonged to, and a person
filling in a week's activity should not be shown the controls that publish it
to the public website.
"""

from django import forms
from django.utils import timezone

from core.forms_base import GovModelForm

from .models import (
    DivisionUpdate,
    PopsPlanUpdate,
    PublicDisclosure,
    ReportingPeriod,
    UpdateAttachment,
    WayForward,
    week_bounds,
)


class ReportingPeriodForm(GovModelForm):
    """Opens a division week. One per Monday, for everyone to contribute to."""

    class Meta:
        model = ReportingPeriod
        fields = ["start_date", "end_date", "theme", "convocation_date"]

    fieldsets = [
        ("Reporting Week", ["start_date", "end_date"]),
        ("Presentation", ["theme", "convocation_date"]),
    ]
    wide_fields = ("theme",)

    def prepare_fields(self):
        """Default to this week, which is the week somebody is nearly always opening."""
        if self.instance.pk:
            return
        monday, friday = week_bounds()
        self.fields["start_date"].initial = monday
        self.fields["end_date"].initial = friday


class DivisionUpdateForm(GovModelForm):
    """
    What a staff member contributes to the Division's week.

    Note what is *not* here: `is_major`, `convocation_order` and `is_public`.
    Selecting an accomplishment for the convocation and clearing it for the
    public website are the Chief's decisions, and they are made on the review
    form below.
    """

    class Meta:
        model = DivisionUpdate
        fields = [
            "period", "title", "category", "activity_type", "status",
            "activity_date", "end_date", "location", "lgu",
            "narrative", "remarks",
            "focal_person", "personnel_involved", "partner",
            "reference_number", "counterpart",
        ]

    fieldsets = [
        ("Reporting Period", ["period"]),
        (
            "What the Division Did",
            ["title", "category", "activity_type", "status"],
        ),
        ("When and Where", ["activity_date", "end_date", "location", "lgu"]),
        ("Details", ["narrative", "remarks"]),
        ("People", ["focal_person", "personnel_involved", "partner"]),
        ("Communications and References", ["reference_number", "counterpart"]),
    ]
    wide_fields = ("title", "narrative", "remarks", "personnel_involved")

    def prepare_fields(self):
        from accounts.models import User

        self.fields["focal_person"].queryset = User.objects.filter(is_active=True)
        self.fields["focal_person"].empty_label = "Not recorded"

        # Open weeks first, and the current one selected: contributions almost
        # always land on the week that is running.
        periods = ReportingPeriod.objects.all()
        self.fields["period"].queryset = periods
        if not self.instance.pk:
            current = ReportingPeriod.current()
            if current:
                self.fields["period"].initial = current.pk
                self.fields["activity_date"].initial = timezone.localdate()


class UpdateAttachmentForm(forms.ModelForm):
    """
    A photograph or a supporting document against one entry.

    A plain ModelForm rather than a `GovModelForm`: this is rendered inline on
    the record page beside the files already filed, not as a sectioned form of
    its own.
    """

    class Meta:
        model = UpdateAttachment
        fields = ["kind", "file", "caption", "is_public"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.forms_base import CHECKBOX_CLASS, FILE_CLASS, SELECT_CLASS, TEXT_CLASS

        self.fields["kind"].widget.attrs["class"] = SELECT_CLASS
        self.fields["file"].widget.attrs["class"] = FILE_CLASS
        self.fields["caption"].widget.attrs["class"] = TEXT_CLASS
        self.fields["is_public"].widget.attrs["class"] = CHECKBOX_CLASS


class PopsPlanUpdateForm(GovModelForm):
    class Meta:
        model = PopsPlanUpdate
        fields = ["commitment", "target", "accomplished", "remarks", "is_public"]

    fieldsets = [
        ("Commitment", ["commitment"]),
        ("Progress", ["target", "accomplished"]),
        ("Notes", ["remarks", "is_public"]),
    ]
    wide_fields = ("commitment", "remarks")


class WayForwardForm(GovModelForm):
    class Meta:
        model = WayForward
        fields = ["description", "detail", "target_date", "status", "is_public"]

    fieldsets = [
        ("Next Step", ["description", "detail"]),
        ("Tracking", ["target_date", "status", "is_public"]),
    ]
    wide_fields = ("description", "detail")


class PeriodReviewForm(GovModelForm):
    """
    The Division Chief's review of a week.

    Kept to the three things the review actually decides - the remarks that
    open the convocation, the week's state, and whether it goes to the public
    website - so the audit trail records a review as a review.
    """

    class Meta:
        model = ReportingPeriod
        fields = ["theme", "chief_remarks", "is_public"]

    fieldsets = [
        ("Convocation", ["theme", "chief_remarks"]),
        ("Publication", ["is_public"]),
    ]
    wide_fields = ("theme", "chief_remarks")
    textarea_rows = 6


class ConvocationSelectionForm(forms.Form):
    """
    Which accomplishments the Chief will present on Monday.

    A single multiple-choice field over the week's own entries: the selection
    is a property of the week, and posting it as one form means the Chief's
    choices are saved together or not at all.
    """

    selected = forms.ModelMultipleChoiceField(
        queryset=DivisionUpdate.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Major accomplishments to present",
    )

    def __init__(self, period, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.period = period
        self.fields["selected"].queryset = period.accomplishments.order_by(
            "-activity_date"
        )
        if not self.is_bound:
            self.fields["selected"].initial = period.updates.filter(
                is_major=True
            ).values_list("pk", flat=True)

    def save(self):
        """Apply the selection, and number the chosen items in date order."""
        chosen = list(self.cleaned_data["selected"])
        self.period.updates.update(is_major=False, convocation_order=0)
        for order, update in enumerate(
            sorted(chosen, key=lambda u: u.activity_date), start=1
        ):
            DivisionUpdate.objects.filter(pk=update.pk).update(
                is_major=True, convocation_order=order
            )
        return chosen


class PublicClearanceForm(forms.Form):
    """
    Which of a week's entries and photographs the public may see.

    Separate from the convocation selection on purpose: presenting something
    internally and disclosing it publicly are different decisions, and running
    them through one checkbox would mean the Chief could only ever do both.
    """

    entries = forms.ModelMultipleChoiceField(
        queryset=DivisionUpdate.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Entries cleared for the public website",
    )
    photos = forms.ModelMultipleChoiceField(
        queryset=UpdateAttachment.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Photographs cleared for the public website",
    )

    def __init__(self, period, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.period = period
        self.fields["entries"].queryset = period.updates.order_by("-activity_date")
        self.fields["photos"].queryset = period.photos
        if not self.is_bound:
            self.fields["entries"].initial = period.updates.filter(
                is_public=True
            ).values_list("pk", flat=True)
            self.fields["photos"].initial = period.photos.filter(
                is_public=True
            ).values_list("pk", flat=True)

    def save(self):
        entries = self.cleaned_data["entries"]
        photos = self.cleaned_data["photos"]

        self.period.updates.update(is_public=False)
        if entries:
            DivisionUpdate.objects.filter(
                pk__in=[entry.pk for entry in entries]
            ).update(is_public=True)

        UpdateAttachment.objects.filter(update__period=self.period).update(
            is_public=False
        )
        if photos:
            UpdateAttachment.objects.filter(
                pk__in=[photo.pk for photo in photos]
            ).update(is_public=True)
        return entries, photos


class PublicDisclosureForm(GovModelForm):
    """
    The Chief's control over what the public website is showing.

    Only weeks that have been reviewed and published are ever eligible, so
    nothing on this form can disclose something the Chief has not already
    approved - it decides how much of the approved record is on the site now.
    """

    class Meta:
        model = PublicDisclosure
        fields = [
            "window",
            "weeks_shown",
            "months_shown",
            "range_start",
            "range_end",
            "include_current_week",
        ]

    fieldsets = [
        ("What the Public Website Shows", ["window"]),
        ("A Rolling Window", ["weeks_shown", "months_shown"]),
        ("A Fixed Range", ["range_start", "range_end"]),
        ("The Week in Progress", ["include_current_week"]),
    ]
