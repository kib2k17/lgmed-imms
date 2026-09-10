"""
The calendar's forms.

The activity form is built for the person filling it in, and the person filling
it in is usually an ordinary employee recording their own week. They are not
shown an owner field at all - the activity is theirs, and offering a menu of
colleagues would only invite the mistake of filing work under someone else's
name. Supervisors, who legitimately record activities on behalf of others, are.

Nothing here is a security boundary. The form narrows what is *offered*; the
view re-checks what is *permitted* before it saves.
"""

from django import forms

from accounts.models import Section, User
from core.forms_base import GovModelForm

from .models import ActivityStatus, CalendarActivity, Visibility


def assignable_users():
    """Active accounts an activity may be owned by or assigned to."""
    return User.objects.filter(is_active=True).select_related("section")


class CalendarActivityForm(GovModelForm):
    """
    Create or edit an activity.

    Pass the signed-in user as `user`. Whether the owner field appears, and
    whose activity a save may end up as, both follow from it.
    """

    class Meta:
        model = CalendarActivity
        fields = [
            "title", "activity_type", "description",
            "owner", "assigned_to", "section",
            "start_date", "end_date", "start_time", "end_time",
            "location", "lgu", "participants",
            "priority", "status", "visibility", "remarks", "is_published",
        ]

    fieldsets = [
        ("Activity", ["title", "activity_type", "description"]),
        ("Ownership", ["owner", "assigned_to", "section"]),
        ("Schedule", ["start_date", "end_date", "start_time", "end_time"]),
        ("Venue and Participants", ["location", "lgu", "participants"]),
        ("Tracking", ["priority", "status", "remarks"]),
        ("Visibility", ["visibility", "is_published"]),
    ]
    wide_fields = ("title", "location", "participants")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        """
        Which fields this user gets. See `GovModelForm.prepare_fields`.

        Written so that every field is optional to begin with: `QuickActivityForm`
        narrows `Meta.fields` to the handful the calendar's day dialog asks for,
        and this must apply the same rules to whichever of them survive rather
        than raising on the ones that did not.
        """
        user = self.user

        if "assigned_to" in self.fields:
            self.fields["assigned_to"].queryset = assignable_users()
            self.fields["assigned_to"].empty_label = "Nobody - the owner does it"
        if "section" in self.fields:
            self.fields["section"].queryset = Section.objects.filter(is_active=True)
            self.fields["section"].empty_label = "Use the owner's section"

        if self.can_choose_owner():
            if "owner" in self.fields:
                self.fields["owner"].queryset = assignable_users()
                self.fields["owner"].required = True
                self.fields["owner"].empty_label = None
                if not self.instance.pk and user is not None:
                    self.fields["owner"].initial = user.pk
        else:
            # An employee records their own work. The field is removed rather
            # than disabled: a disabled field still arrives in the POST body,
            # and a field that is not there cannot be re-enabled in a browser's
            # developer tools and posted back.
            self.fields.pop("owner", None)

        if not self.can_publish():
            self.fields.pop("is_published", None)

    # -- what this user is offered ---------------------------------------

    def can_choose_owner(self):
        """Only a supervisor may file an activity under another employee's name."""
        return bool(self.user and getattr(self.user, "can_supervise", False))

    def can_publish(self):
        """Publishing to the public website is the approving roles' decision."""
        return bool(self.user and getattr(self.user, "can_approve", False))

    # -- validation --------------------------------------------------------

    def clean_end_date(self):
        end = self.cleaned_data.get("end_date")
        start = self.cleaned_data.get("start_date")
        if start and end and end < start:
            raise forms.ValidationError(
                "The end date must not be earlier than the start date."
            )
        return end

    def clean(self):
        cleaned = super().clean()

        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        end_date = cleaned.get("end_date")
        start_date = cleaned.get("start_date")
        single_day = not end_date or end_date == start_date
        if start_time and end_time and single_day and end_time <= start_time:
            self.add_error(
                "end_time", "The end time must be later than the start time."
            )
        if end_time and not start_time:
            self.add_error(
                "end_time",
                "Record a start time as well, or leave both empty for a "
                "whole-day activity.",
            )

        # A private activity on a public website is a contradiction, and the
        # kind that is only noticed after it has been published. Refuse it here
        # rather than quietly publishing something the owner marked private.
        if cleaned.get("is_published") and cleaned.get("visibility") != (
            Visibility.ORGANIZATION
        ):
            self.add_error(
                "is_published",
                "Only an office-wide activity may be shown on the public "
                "calendar. Set the visibility to “Everyone in the "
                "office” first.",
            )

        assigned = cleaned.get("assigned_to")
        if (
            assigned
            and cleaned.get("visibility") == Visibility.PRIVATE
        ):
            self.add_error(
                "visibility",
                "This activity is assigned to another employee, who would not "
                "be able to see it. Choose “Assigned users” or wider.",
            )

        return cleaned


class QuickActivityForm(CalendarActivityForm):
    """
    The short form the calendar's day dialog opens.

    Eight fields rather than eighteen, because the dialog is for the thing
    people actually do at a calendar: put something on a day. It inherits its
    validation and its ownership rules from the full form rather than
    restating them - a quick way in must not be a way around them - so an
    employee still cannot file an activity under a colleague's name here, and
    the assignee-must-be-able-to-see-it rule still applies.

    What is left out is what can wait: the LGU, the participants, the remarks,
    the status of work that has not started, and publication to the public
    website. "More options" on the dialog opens the full form with the same
    date already filled in.
    """

    class Meta(CalendarActivityForm.Meta):
        fields = [
            "title", "activity_type", "description",
            "owner", "assigned_to",
            "start_date", "end_date", "start_time", "end_time",
            "location", "priority", "visibility",
        ]

    fieldsets = [
        (None, [
            "title", "activity_type", "owner", "assigned_to",
            "start_date", "end_date", "start_time", "end_time",
            "location", "priority", "visibility", "description",
        ]),
    ]
    wide_fields = ("title", "location", "visibility")
    textarea_rows = 2


class ActivityProgressForm(forms.ModelForm):
    """
    The short form the responsible employee uses to report where things stand.

    Deliberately two fields. The employee doing the work should be able to say
    "done, with these remarks" without being handed the whole record to edit -
    that is the owner's, and an assignee quietly changing the date or the
    venue is exactly the sort of thing this module exists to prevent.
    """

    class Meta:
        model = CalendarActivity
        fields = ["status", "remarks"]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        from core.forms_base import SELECT_CLASS, TEXTAREA_CLASS

        super().__init__(*args, **kwargs)
        self.fields["status"].choices = ActivityStatus.choices
        self.fields["status"].widget.attrs["class"] = SELECT_CLASS
        self.fields["remarks"].widget.attrs["class"] = TEXTAREA_CLASS
        self.fields["remarks"].required = False
        self.fields["remarks"].label = "Remarks"
