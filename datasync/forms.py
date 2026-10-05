from django import forms
from django.core.validators import FileExtensionValidator

from core.forms_base import FILE_CLASS, SELECT_CLASS

from . import profiles

MAX_UPLOAD_MB = 25


class UploadForm(forms.Form):
    module = forms.ChoiceField(
        label="Sync into",
        help_text="Which register this workbook is.",
    )
    file = forms.FileField(
        label="Excel workbook",
        help_text=(
            f"An .xlsx file of up to {MAX_UPLOAD_MB} MB. Nothing is saved until "
            "you have seen the preview and confirmed it."
        ),
        validators=[FileExtensionValidator(["xlsx", "xlsm"])],
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only the modules this person may sync into are offered.
        self.fields["module"].choices = [
            (profile.key, f"{profile.label} - {profile.description}")
            for profile in profiles.PROFILES.values()
            if getattr(user, profile.capability, False)
        ]
        self.fields["module"].widget.attrs.update(
            {"class": SELECT_CLASS, "aria-describedby": "id_module-help"}
        )
        self.fields["file"].widget.attrs.update(
            {"class": FILE_CLASS, "accept": ".xlsx,.xlsm",
             "aria-describedby": "id_file-help"}
        )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(
                f"The file is larger than {MAX_UPLOAD_MB} MB."
            )
        return upload
