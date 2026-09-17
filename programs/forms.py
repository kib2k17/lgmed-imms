"""
Data-entry forms for the PPA module.

Two things are worth pointing out about them.

The public-facing text fields carry a warning in their help text rather than a
validator. The module cannot tell a name that belongs in a public sentence
("attended by Mayor Dela Cruz") from one that does not, and a form that refuses
the first teaches staff to work around it. The screening and the review step
are where that judgement is made, by a person.

Neither the publication status nor any of the provenance fields appear on a
form. They are only ever set by the transition methods on the model, called
from views that check the user's role first. A status that can be typed into a
form is a status that can be typed past a reviewer.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from accounts.models import Section
from core.forms_base import GovModelForm

from .models import (
    ALLOWED_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    PUBLIC_HEADING_DEFAULTS,
    Activity,
    Program,
    ProgramCategory,
    Project,
    PublicationAuthority,
    SubProject,
    SupportingDocument,
)

PUBLIC_TEXT_WARNING = (
    "Written for the public website. Do not include names of private "
    "individuals, contact details or identification numbers."
)

# Every heading field is optional, and the per-field help text says what a
# blank box becomes. They are gathered into their own section at the foot of
# the form rather than sitting beside the content they title: an encoder
# filling in a record should be typing the work, not answering four questions
# about wording that almost every record leaves alone.
PUBLIC_HEADINGS_TITLE = "Public page headings"


class PPAFormMixin:
    """Shared behaviour of the four record forms."""

    def prepare_fields(self):
        super().prepare_fields()
        if "responsible_office" in self.fields:
            self.fields["responsible_office"].queryset = Section.objects.filter(
                is_active=True
            )
            self.fields["responsible_office"].empty_label = "Not yet assigned"
        if "description" in self.fields:
            self.fields["description"].help_text = PUBLIC_TEXT_WARNING
        # An empty heading box should say what the page will show, not sit
        # blank and leave the encoder guessing whether blank means "no
        # heading". The placeholder is the default wording itself.
        for name, field in self.fields.items():
            if not name.endswith("_heading"):
                continue
            field.widget.attrs.setdefault(
                "placeholder", PUBLIC_HEADING_DEFAULTS[name[: -len("_heading")]]
            )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error(
                "end_date", "The end date must not be earlier than the start date."
            )
        return cleaned


class ProgramForm(PPAFormMixin, GovModelForm):
    class Meta:
        model = Program
        fields = [
            "title", "outcome_code", "reference_number", "category",
            "description", "objectives",
            "start_date", "end_date", "status",
            "responsible_office", "lead_office", "focal_person", "covered_lgus",
            "about_heading", "objectives_heading", "photographs_heading",
            "projects_heading",
        ]
        widgets = {"covered_lgus": forms.SelectMultiple(attrs={"size": 8})}

    fieldsets = [
        ("Program information",
         ["title", "outcome_code", "reference_number", "category",
          "description", "objectives"]),
        ("Implementation period", ["start_date", "end_date", "status"]),
        ("Responsibility and coverage",
         ["responsible_office", "lead_office", "focal_person", "covered_lgus"]),
        (PUBLIC_HEADINGS_TITLE,
         ["about_heading", "objectives_heading", "photographs_heading",
          "projects_heading"]),
    ]
    wide_fields = ("title", "description", "objectives", "covered_lgus")

    def prepare_fields(self):
        super().prepare_fields()
        self.fields["category"].queryset = ProgramCategory.objects.filter(
            is_active=True
        )
        self.fields["outcome_code"].help_text = (
            "The Department outcome this programme reports against. The public "
            "website groups every programme by this."
        )


class ChildFormMixin(PPAFormMixin):
    """
    A form for a record below the programme level.

    The parent is fixed by the page the user came from rather than chosen from
    a list of every project in the region: the tree is how this module is
    navigated, and a dropdown of four hundred projects is how a sub-project
    ends up filed under the wrong one.

    The parent is applied in `prepare_fields()` rather than after
    `super().__init__()`, and that is not a stylistic choice. `GovModelForm`
    reads `self.errors` in its constructor so it can mark invalid inputs -
    which validates the form there and then. A parent field disabled after
    that point has already been validated as an enabled one, against POST data
    that a browser never sends for a disabled control, so every submission
    failed as "this field is required".
    """

    parent_field = ""

    def __init__(self, *args, parent=None, **kwargs):
        self.parent_object = parent
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        super().prepare_fields()
        parent = self.parent_object
        if parent is not None and self.parent_field in self.fields:
            field = self.fields[self.parent_field]
            field.disabled = True
            field.initial = parent
            field.queryset = type(parent).objects.filter(pk=parent.pk)


class ProjectForm(ChildFormMixin, GovModelForm):
    parent_field = "program"

    class Meta:
        model = Project
        fields = [
            "title", "program", "description",
            "start_date", "end_date", "status",
            "responsible_office", "focal_person",
            "about_heading", "photographs_heading",
            "sub_projects_heading", "activities_heading",
        ]

    fieldsets = [
        ("Project information", ["title", "program", "description"]),
        ("Implementation period", ["start_date", "end_date", "status"]),
        ("Responsibility", ["responsible_office", "focal_person"]),
        (PUBLIC_HEADINGS_TITLE,
         ["about_heading", "photographs_heading",
          "sub_projects_heading", "activities_heading"]),
    ]
    wide_fields = ("title", "description")


class SubProjectForm(ChildFormMixin, GovModelForm):
    parent_field = "project"

    class Meta:
        model = SubProject
        fields = [
            "title", "project", "description",
            "start_date", "end_date", "status",
            "responsible_office", "focal_person",
            "about_heading", "photographs_heading", "activities_heading",
        ]

    fieldsets = [
        ("Sub-project information", ["title", "project", "description"]),
        ("Implementation period", ["start_date", "end_date", "status"]),
        ("Responsibility", ["responsible_office", "focal_person"]),
        (PUBLIC_HEADINGS_TITLE,
         ["about_heading", "photographs_heading", "activities_heading"]),
    ]
    wide_fields = ("title", "description")


class ActivityForm(ChildFormMixin, GovModelForm):
    """
    An activity hangs off a project or a sub-project, never both.

    Which one is settled by the page the user started from, so neither foreign
    key appears on the form: offering both would offer a user the chance to
    file an activity under neither, and `Activity.clean()` would then refuse
    the record with a message about a choice they were never really given.
    """

    class Meta:
        model = Activity
        fields = [
            "title", "description", "activity_date", "location",
            "status", "accomplishment",
            "responsible_office", "focal_person",
            "about_heading", "accomplishment_heading", "photographs_heading",
        ]

    fieldsets = [
        ("Activity information",
         ["title", "description", "activity_date", "location", "status"]),
        ("Result", ["accomplishment"]),
        ("Responsibility", ["responsible_office", "focal_person"]),
        (PUBLIC_HEADINGS_TITLE,
         ["about_heading", "accomplishment_heading", "photographs_heading"]),
    ]
    wide_fields = ("title", "description", "accomplishment")

    def prepare_fields(self):
        super().prepare_fields()
        self.fields["accomplishment"].help_text = PUBLIC_TEXT_WARNING

        # Before validation, not after: `Activity.clean()` insists on exactly
        # one parent, and it runs while the form is validating itself inside
        # `GovModelForm.__init__`.
        parent = self.parent_object
        if parent is not None:
            if isinstance(parent, SubProject):
                self.instance.sub_project = parent
                self.instance.project = None
            else:
                self.instance.project = parent
                self.instance.sub_project = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class MultipleFileInput(forms.ClearableFileInput):
    """
    A file input that accepts more than one file.

    Django's own `ClearableFileInput` sets `allow_multiple_selected = False`
    and raises if `multiple` turns up in its attrs, because a *model* file
    field has room for exactly one file. That is the right default and the
    wrong thing here: the field below is not bound to a model field at all,
    and a field officer back from a validation visit has thirty photographs
    of it.
    """

    allow_multiple_selected = True

    def __init__(self, attrs=None):
        super().__init__({**(attrs or {}), "multiple": True})


class MultipleFileField(forms.FileField):
    """
    A file field whose cleaned value is a *list* of uploaded files.

    Each file is put through the ordinary `FileField` validation - extension,
    emptiness, the size ceiling - so nothing is waved through just because it
    arrived in company. The list is what the view iterates over to create one
    `SupportingDocument` per file.
    """

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single = super().clean
        if not isinstance(data, (list, tuple)):
            data = [] if data in self.empty_values else [data]
        if not data:
            # Let the base class raise "this field is required" in its own
            # words rather than inventing a second wording for the same thing.
            return [single(None, initial)] if self.required else []
        return [single(item, initial) for item in data]


class SupportingDocumentForm(GovModelForm):
    """
    Upload one supporting file, or a set of photographs, against a record.

    The confirmation checkbox is not decoration. Most disclosures at this
    office will not be a file somebody meant to publish; they will be the
    attendance sheet attached in a hurry because it was the nearest proof the
    activity happened. Asking the question at the moment of upload is the
    cheapest place in the whole workflow to stop that.

    `files` stands in for the model's own `file` on this form, and the reason
    is the office's actual habit: documents arrive one at a time, photographs
    arrive by the memory card. Each selected file still becomes its own
    `SupportingDocument` row - screened on its own, reviewed on its own,
    published or refused on its own - so nothing about the security workflow
    is loosened by uploading thirty at once. What changes is that the encoder
    stops repeating the same form thirty times.
    """

    # Which of the four foreign keys a record of each level occupies.
    OWNER_FIELDS = {
        "Program": "program",
        "Project": "project",
        "SubProject": "sub_project",
        "Activity": "activity",
    }

    # A caption per picture, supplied by the upload page's preview grid and
    # posted in the same order as the files. Not a form field: how many there
    # are depends on what the person selected, so it is read off the POST
    # data directly rather than declared.
    CAPTION_FIELD = "file_caption"

    files = MultipleFileField(
        label="File or photographs",
        # The same validator the model's own `file` field carries. It has to
        # be repeated here because `files` is declared rather than generated
        # from the model, and a declared field inherits none of the model
        # field's validators - which would have let a .exe through a form whose
        # whole purpose is to decide what may be stored.
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        help_text=(
            "PDF, Word, Excel, PowerPoint, JPG or PNG - up to 25 MB each. "
            "Several photographs can be selected at once; each one is stored, "
            "screened and reviewed separately."
        ),
    )

    acknowledge = forms.BooleanField(
        label="I have opened these files and checked what is in them",
        help_text=(
            "The files are stored internally and screened automatically. "
            "They will not appear on the public website unless a reviewer "
            "approves them and an administrator publishes them."
        ),
    )

    class Meta:
        model = SupportingDocument
        # `file` is deliberately absent: `files` above stands in its place and
        # the form writes one row per uploaded file in `documents()`.
        fields = ["title", "kind", "description"]

    fieldsets = [
        ("The file", ["files", "title", "kind", "description"]),
        ("Confirmation", ["acknowledge"]),
    ]
    wide_fields = ("files", "title", "description", "acknowledge")

    def __init__(self, *args, record=None, **kwargs):
        self.record = record
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        """
        Attach the record the file belongs to, before anything validates.

        `SupportingDocument.clean()` insists a file belongs to exactly one
        programme, project, sub-project or activity - the constraint that keeps
        an orphaned file out of every listing. `GovModelForm` validates inside
        its own constructor, so attaching the owner in the view afterwards
        meant the form rejected every upload on a rule the view was about to
        satisfy one line later.
        """
        super().prepare_fields()
        if self.record is not None:
            setattr(
                self.instance,
                self.OWNER_FIELDS[type(self.record).__name__],
                self.record,
            )
        self.fields["title"].help_text = (
            "What the file is - shown to the public if it is ever released. "
            "The uploaded filename is not published. Where several "
            "photographs are selected this names the set, and each picture "
            "keeps the caption typed under its thumbnail."
        )
        self.fields["files"].widget.attrs.update({
            "accept": ",".join(f".{extension}" for extension in ALLOWED_EXTENSIONS),
            "data-multi-upload": "true",
            "data-caption-name": self.CAPTION_FIELD,
            "data-image-extensions": ",".join(IMAGE_EXTENSIONS),
            "data-max-bytes": str(MAX_UPLOAD_BYTES),
        })

    def clean_files(self):
        uploaded = self.cleaned_data["files"]
        for item in uploaded:
            if item.size > MAX_UPLOAD_BYTES:
                raise ValidationError(
                    f"'{item.name}' is {item.size / 1048576:.1f} MB. "
                    "The limit is 25 MB per file."
                )
            if item.size == 0:
                raise ValidationError(f"'{item.name}' is empty.")
        return uploaded

    # -- what the view saves ----------------------------------------------

    def captions(self):
        """
        The per-picture captions posted alongside the selection, in its order.

        Empty when the page ran without JavaScript, which is why `documents()`
        zips defensively rather than indexing.
        """
        if not self.is_bound or not hasattr(self.data, "getlist"):
            return []
        return [
            caption.strip()[:255]
            for caption in self.data.getlist(self.CAPTION_FIELD)
        ]

    def documents(self):
        """
        One unsaved `SupportingDocument` per uploaded file, in selection order.

        The title is numbered only when there is more than one file, so the
        ordinary case - one document, one title - reads exactly as it did
        before. A picture's own caption becomes its description, which is what
        the public gallery prints beneath it.
        """
        uploaded = self.cleaned_data["files"]
        captions = self.captions()
        title = self.cleaned_data["title"]
        kind = self.cleaned_data["kind"]
        description = self.cleaned_data.get("description", "")
        total = len(uploaded)

        built = []
        for position, item in enumerate(uploaded, start=1):
            caption = captions[position - 1] if position <= len(captions) else ""
            document = SupportingDocument(
                title=title if total == 1 else f"{title} ({position})",
                kind=kind,
                description=caption or description,
                file=item,
            )
            setattr(
                document,
                self.OWNER_FIELDS[type(self.record).__name__],
                self.record,
            )
            built.append(document)
        return built


class PhotoOrderForm(forms.Form):
    """
    The new running order of one record's photographs.

    Posted as a single list of document identifiers, in the order a person
    dragged them into. Validated against the record's own pictures rather than
    against the whole table, so an identifier belonging to another programme -
    mistyped, or supplied on purpose - reorders nothing.
    """

    order = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, photographs=None, **kwargs):
        self.photographs = list(photographs or [])
        super().__init__(*args, **kwargs)

    def clean_order(self):
        raw = self.cleaned_data["order"]
        try:
            submitted = [int(token) for token in raw.split(",") if token.strip()]
        except ValueError:
            raise ValidationError("The new order could not be read.")

        allowed = {photograph.pk for photograph in self.photographs}
        if set(submitted) != allowed:
            raise ValidationError(
                "The photographs on this page have changed since it was "
                "opened. Reload and arrange them again."
            )
        return submitted


class PublicationAuthorityForm(GovModelForm):
    """
    Record the memorandum under which files may be released.

    Recorded before it is cited, never alongside a release in the same breath:
    an authority typed into the same form that publishes a file is not an
    authority, it is a second checkbox.
    """

    class Meta:
        model = PublicationAuthority
        fields = [
            "reference", "title", "approved_on", "approved_by", "scope",
            "memorandum", "effective_from", "effective_until", "is_active",
        ]

    fieldsets = [
        ("The issuance", ["reference", "title", "approved_on", "approved_by"]),
        ("What it covers", ["scope", "memorandum"]),
        ("Period of effect", ["effective_from", "effective_until", "is_active"]),
    ]
    wide_fields = ("title", "scope", "memorandum", "is_active")

    def prepare_fields(self):
        super().prepare_fields()
        self.fields["memorandum"].help_text = (
            "The signed issuance, for the record. It is stored internally and "
            "is never itself published."
        )


def authority_field(required=False, label="Published under"):
    """
    The choice of memorandum, offered wherever a release is being decided.

    Only authorities actually in force are listed. A withdrawn or expired
    memorandum stays on the record of what it already authorised, but it must
    not be selectable for something new.
    """
    return forms.ModelChoiceField(
        queryset=PublicationAuthority.objects.filter(is_active=True),
        required=required,
        label=label,
        empty_label="No memorandum recorded yet",
        help_text=(
            "The memorandum authorising this file's release. A file cannot go "
            "on the public website without one."
        ),
    )


class DocumentAuthorityForm(forms.Form):
    """Attach or change the memorandum cited against one file."""

    authority = authority_field(required=True, label="Memorandum")

    def clean_authority(self):
        authority = self.cleaned_data["authority"]
        if not authority.is_in_force():
            raise ValidationError(
                f"{authority.reference} is {authority.status_label.lower()} "
                "and cannot authorise a release."
            )
        return authority


class DocumentDecisionForm(forms.Form):
    """
    The reviewer's decision on one screened file.

    `acknowledge_risk` appears only for a high-risk file, and the view refuses
    an approval without it. Section 7 of the brief asks that a high-risk file
    not be publishable directly; an untickable-by-accident confirmation that
    the reviewer opened the file is how that is enforced without stopping a
    reviewer who has genuinely checked and found the warning to be a false
    positive.
    """

    DECISIONS = (
        ("approve", "Approve for publication"),
        ("revise", "Request revision"),
        ("reject", "Reject"),
    )

    decision = forms.ChoiceField(choices=DECISIONS, widget=forms.RadioSelect)
    authority = authority_field()
    comments = forms.CharField(
        label="Review comments",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Recorded against the file and kept in the audit trail.",
    )
    acknowledge_risk = forms.BooleanField(
        required=False,
        label=(
            "I have opened and read this file in full, and I confirm it "
            "contains nothing that should not be released."
        ),
    )

    def __init__(self, *args, document=None, **kwargs):
        self.document = document
        super().__init__(*args, **kwargs)
        if document is not None and document.authority_id:
            self.fields["authority"].initial = document.authority_id

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get("decision")

        # Offered, not demanded. The memorandum authorising a batch is often
        # issued after the files in it have been read, and refusing the
        # approval until it exists would stall the review rather than control
        # the release. The control bites at publication, where it belongs:
        # `SupportingDocument.publish()` refuses a file without one.
        authority = cleaned.get("authority")
        if authority is not None and not authority.is_in_force():
            self.add_error(
                "authority",
                f"{authority.reference} is {authority.status_label.lower()} "
                "and cannot authorise a release.",
            )

        if decision in ("revise", "reject") and not cleaned.get("comments"):
            self.add_error(
                "comments",
                "Say why, so the person who uploaded the file knows what to change.",
            )

        if (
            decision == "approve"
            and self.document is not None
            and not self.document.may_be_approved_directly
            and not cleaned.get("acknowledge_risk")
        ):
            self.add_error(
                "acknowledge_risk",
                "The screening flagged this file as high risk. It cannot be "
                "approved until you confirm you have read it.",
            )
        return cleaned


class RecordDecisionForm(forms.Form):
    """The reviewer's decision on the content of a record."""

    DECISIONS = (
        ("approve", "Approve the content"),
        ("revise", "Request revision"),
        ("reject", "Reject"),
    )

    decision = forms.ChoiceField(choices=DECISIONS, widget=forms.RadioSelect)
    comments = forms.CharField(
        label="Review comments",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") in ("revise", "reject") and not cleaned.get("comments"):
            self.add_error("comments", "Say why, so the encoder knows what to change.")
        return cleaned
