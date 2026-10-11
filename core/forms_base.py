"""
Form foundations.

`GovModelForm` applies the design system's input styling to every widget
automatically, and lets a form declare `fieldsets` so a long government form
renders as titled sections rather than one intimidating column of inputs
(section 12 of the design system).
"""

from django import forms

TEXT_CLASS = (
    "block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-900 shadow-xs transition-colors placeholder:text-slate-400 "
    "focus:border-brand-600 focus:ring-2 focus:ring-brand-600/25 focus:outline-none "
    "disabled:bg-slate-50 disabled:text-slate-500"
)
SELECT_CLASS = TEXT_CLASS + " appearance-none pr-9 form-select"
TEXTAREA_CLASS = TEXT_CLASS + " min-h-24 leading-relaxed"
CHECKBOX_CLASS = (
    "size-4 rounded border-slate-300 text-brand-600 "
    "focus:ring-2 focus:ring-brand-600/25 focus:ring-offset-0"
)
FILE_CLASS = (
    "block w-full rounded-md border border-slate-300 bg-white text-sm text-slate-700 "
    "shadow-xs file:mr-3 file:border-0 file:border-r file:border-slate-200 "
    "file:bg-slate-50 file:px-3 file:py-2 file:text-sm file:font-medium "
    "file:text-slate-700 hover:file:bg-slate-100 focus:border-brand-600 "
    "focus:ring-2 focus:ring-brand-600/25 focus:outline-none"
)
ERROR_CLASS = "border-red-300 focus:border-red-600 focus:ring-red-600/25"


class GovModelForm(forms.ModelForm):
    """A ModelForm that already looks like an official data-entry form.

    Declare `fieldsets` to group fields into titled sections:

        fieldsets = [
            ("Program Information", ["title", "category", "description"]),
            ("Implementation Period", ["start_date", "end_date", "status"]),
        ]

    Fields listed in `wide_fields` span the full width of the two-column grid.
    """

    fieldsets = None
    wide_fields = ()
    textarea_rows = 4

    def __init__(self, *args, **kwargs):
        # A view's last word on which fields this person may set (see
        # ModuleFormMixin.approval_fields). Applied before anything reads
        # `self.errors`, for the reason prepare_fields() gives below.
        restrict_fields = kwargs.pop("restrict_fields", None)
        super().__init__(*args, **kwargs)
        self.prepare_fields()
        if restrict_fields is not None:
            restrict_fields(self)
        for name, field in self.fields.items():
            widget = field.widget
            attrs = widget.attrs

            if isinstance(widget, forms.CheckboxInput):
                attrs["class"] = CHECKBOX_CLASS
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                attrs["class"] = SELECT_CLASS
            elif isinstance(widget, forms.Textarea):
                attrs["class"] = TEXTAREA_CLASS
                # Django's Textarea always ships rows=10/cols=40, so setdefault
                # would never apply. Four rows suits these forms; a form that
                # needs more can set rows after calling super().__init__().
                attrs["rows"] = self.textarea_rows
                attrs.pop("cols", None)
            elif isinstance(widget, (forms.FileInput, forms.ClearableFileInput)):
                attrs["class"] = FILE_CLASS
            else:
                attrs["class"] = TEXT_CLASS

            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            if isinstance(widget, forms.TimeInput):
                widget.input_type = "time"

            if field.required:
                attrs["aria-required"] = "true"
            if self.is_bound and self.errors.get(name):
                attrs["class"] += " " + ERROR_CLASS
                attrs["aria-invalid"] = "true"

            describedby = []
            if field.help_text:
                describedby.append(f"id_{name}-help")
            if self.is_bound and self.errors.get(name):
                describedby.append(f"id_{name}-error")
            if describedby:
                attrs["aria-describedby"] = " ".join(describedby)

    def prepare_fields(self):
        """
        Add, remove or re-point fields, before anything else looks at them.

        Subclasses that change which fields exist must do it here rather than
        after calling `super().__init__()`. The styling loop above reads
        `self.errors` so it can mark invalid inputs, and reading `errors`
        validates the form - so a field removed afterwards has already been
        cleaned, and a required field the person was never shown can leave a
        "This field is required" error on a form with nothing to correct.
        """

    def _bound(self, name):
        """A BoundField tagged with whether it spans both form columns."""
        bound_field = self[name]
        bound_field.is_wide = name in self.wide_fields or isinstance(
            bound_field.field.widget, forms.Textarea
        )
        return bound_field

    def get_sections(self):
        """Yield (title, [BoundField, ...]) for the template to render."""
        if not self.fieldsets:
            return [(None, [self._bound(name) for name in self.fields])]

        assigned = {name for _title, names in self.fieldsets for name in names}
        sections = [
            (title, [self._bound(name) for name in names if name in self.fields])
            for title, names in self.fieldsets
        ]
        leftovers = [
            self._bound(name) for name in self.fields if name not in assigned
        ]
        if leftovers:
            sections.append(("Other details", leftovers))
        return sections
