from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm

from audit.models import Action
from audit.recording import client_ip, record
from core.forms_base import TEXT_CLASS, GovModelForm

from . import recaptcha
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
                "placeholder": "juan.delacruz",
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
                "placeholder": "Enter your password",
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
            "position", "office", "contact_number",
            "role", "is_active",
        ]

    fieldsets = [
        ("Account", ["username", "first_name", "last_name", "email"]),
        ("Designation", ["position", "office", "contact_number"]),
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
    """Creating an account also sets its first password."""

    password1 = forms.CharField(
        label="Temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="The account holder should change this at first sign-in.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    fieldsets = [
        ("Account", ["username", "first_name", "last_name", "email"]),
        ("Designation", ["position", "office", "contact_number"]),
        ("Access", ["role", "is_active"]),
        ("Password", ["password1", "password2"]),
    ]

    def clean_password2(self):
        from django.contrib.auth.password_validation import validate_password

        first = self.cleaned_data.get("password1")
        second = self.cleaned_data.get("password2")
        if first and second and first != second:
            raise forms.ValidationError("The two passwords do not match.")
        if second:
            validate_password(second)
        return second

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password2"])
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
