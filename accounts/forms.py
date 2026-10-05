from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm

from audit.models import Action
from audit.recording import client_ip, record
from core.forms_base import FILE_CLASS, TEXT_CLASS, GovModelForm

from . import photos, recaptcha
from .emails import generate_temporary_password
from .models import Role, User

FIELD_CLASS = TEXT_CLASS

# The dashboard's fields are deliberately dense: its forms sit beside tables and
# have many rows. The sign-in page has two fields and one job, so it gets a
# larger target. Substituted rather than appended - two conflicting utilities in
# one class attribute are resolved by stylesheet order, not by which is written
# last, so appending "py-2.5" to a class that already carries "py-2" is a
# coin toss.
SIGNIN_FIELD_CLASS = FIELD_CLASS.replace(
    "px-3 py-2 text-sm", "px-3.5 py-2.5 text-[0.9375rem]"
)


class LoginForm(AuthenticationForm):
    """Government-styled sign-in form."""

    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(
            attrs={
                "class": SIGNIN_FIELD_CLASS,
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "e.g. juan.delacruz",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                # Right padding leaves room for the show/hide button that the
                # sign-in page places inside the field.
                "class": SIGNIN_FIELD_CLASS + " pr-11",
                "autocomplete": "current-password",
            }
        ),
    )

    # Filled in by the sign-in page just before it posts. Not required at the
    # field level: an empty token is a refusal, but one phrased for the person
    # in front of the screen rather than "This field is required."
    recaptcha_token = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-recaptcha-token": ""}),
    )

    error_messages = {
        "invalid_login": (
            "The username or password you entered is incorrect. "
            "Please check your credentials and try again."
        ),
        "inactive": (
            "This account has been deactivated. "
            "Please contact the LGMED system administrator."
        ),
        "recaptcha_missing": (
            "This sign-in could not be verified. The sign-in page needs "
            "JavaScript and access to google.com - please enable it, reload "
            "the page and try again."
        ),
        "recaptcha_refused": (
            "This sign-in was blocked by the automated-access check. Reload "
            "the page and try again. If it keeps happening, contact the "
            "LGMED system administrator."
        ),
    }

    def clean(self):
        """
        The reCAPTCHA verdict is settled before the credentials are looked at.

        Order matters: AuthenticationForm.clean() is what calls authenticate(),
        so returning early here means a refused attempt never reaches the
        password hasher and cannot be used to probe for valid passwords.
        """
        self._check_recaptcha()
        return super().clean()

    def _check_recaptcha(self):
        if not recaptcha.is_enabled():
            return

        token = (self.cleaned_data.get("recaptcha_token") or "").strip()
        verdict = recaptcha.verify(
            token,
            remote_ip=client_ip(self.request),
        )
        if verdict.allowed:
            return

        # Refused attempts belong in the audit log beside the failed
        # passwords: on their own they are the shape of a scripted attack.
        # No signal fires for this one - authenticate() is never reached -
        # so it is recorded here.
        username = (self.data.get("username") or "").strip()[:150]
        record(
            Action.LOGIN_FAILED,
            request=self.request,
            detail=(
                f"Sign-in for '{username}' " if username else "Sign-in "
            ) + f"blocked by reCAPTCHA - {verdict.reason}"
            + ("" if settings.RECAPTCHA_ENFORCE else " (monitor mode: allowed)"),
        )

        if not settings.RECAPTCHA_ENFORCE:
            return

        raise forms.ValidationError(
            self.error_messages[
                "recaptcha_missing" if not token else "recaptcha_refused"
            ],
            code="recaptcha",
        )


class UserForm(GovModelForm):
    """Create or edit an account. Administrators only - the view enforces it."""

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email",
            "position", "office", "contact_number", "code_initials",
            "role", "is_active",
        ]

    fieldsets = [
        ("Account", ["username", "first_name", "last_name", "email"]),
        ("Designation", ["position", "office", "contact_number", "code_initials"]),
        ("Access", ["role", "is_active"]),
    ]

    def __init__(self, *args, **kwargs):
        self.acting_user = kwargs.pop("acting_user", None)
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = (
            "Used to sign in. Office convention is firstname.lastname."
        )
        self.fields["is_active"].help_text = (
            "Deactivate instead of deleting: the account's history stays in "
            "the audit trail, and the person can no longer sign in."
        )
        if self._editing_self():
            # Guard against an administrator locking themselves out.
            for name in ("role", "is_active"):
                self.fields[name].disabled = True
                self.fields[name].help_text = (
                    "You cannot change your own role or deactivate your own "
                    "account. Ask another administrator."
                )

    def _editing_self(self):
        return (
            self.acting_user is not None
            and self.instance.pk is not None
            and self.instance.pk == self.acting_user.pk
        )

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if email:
            clash = User.objects.filter(email__iexact=email)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(
                    "Another account already uses this email address."
                )
        return email

    def clean(self):
        cleaned = super().clean()
        if self._editing_self():
            # Disabled fields are not posted; restore the stored values.
            cleaned["role"] = self.instance.role
            cleaned["is_active"] = self.instance.is_active
        return cleaned


class UserCreateForm(UserForm):
    """
    Creating an account also sets its first password - generated here, never
    typed by the administrator, and sent to the account holder by email.
    """

    def prepare_fields(self):
        super().prepare_fields()
        self.fields["email"].required = True
        self.fields["email"].help_text = (
            "A temporary password is generated and emailed here, together "
            "with the username and role."
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        self.temporary_password = generate_temporary_password()
        user.set_password(self.temporary_password)
        if commit:
            user.save()
        return user


class AdminSetPasswordForm(SetPasswordForm):
    """Reset another user's password without knowing the old one."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = FIELD_CLASS
            field.widget.attrs["autocomplete"] = "new-password"


class ProfilePhotoForm(forms.Form):
    """
    A new profile photo for the signed-in account.

    A plain FileField rather than an ImageField: `photos.process_photo` opens
    and re-encodes the image anyway, and doing the checking there keeps the
    rules - size, format, dimensions - in one place.
    """

    photo = forms.FileField(
        label="Profile photo",
        widget=forms.ClearableFileInput(
            attrs={"class": FILE_CLASS, "accept": photos.ACCEPT}
        ),
        help_text="JPEG, PNG or WebP, up to 5 MB. It is cropped to a square.",
    )

    def clean_photo(self):
        upload = self.cleaned_data["photo"]
        self.processed = photos.process_photo(upload)
        return upload


class MFACodeForm(forms.Form):
    """
    One code: six digits from the authenticator app, or a recovery code.

    The field asks the phone for a numeric keypad unless the page is asking
    for a recovery code, which has letters in it.
    """

    code = forms.CharField(
        label="Authentication code",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "class": SIGNIN_FIELD_CLASS + " font-mono tracking-[0.2em]",
                "autocomplete": "one-time-code",
                "autofocus": True,
                "spellcheck": "false",
                "autocapitalize": "off",
            }
        ),
    )

    def __init__(self, *args, recovery=False, dense=False, **kwargs):
        super().__init__(*args, **kwargs)
        attrs = self.fields["code"].widget.attrs
        if dense:
            attrs["class"] = FIELD_CLASS + " font-mono tracking-[0.2em]"
        if recovery:
            self.fields["code"].label = "Recovery code"
            attrs["placeholder"] = "xxxxx-xxxxx"
            attrs["autocomplete"] = "off"
        else:
            attrs["inputmode"] = "numeric"
            attrs["placeholder"] = "123456"
