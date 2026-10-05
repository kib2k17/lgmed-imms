from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse

from programs.storage import protected_storage


class Role(models.TextChoices):
    """Authorization roles recognised by LGMED-iMMS."""

    SUPERADMIN = "SUPERADMIN", "System Administrator"
    ADMIN = "ADMIN", "Administrator"
    LGMED_STAFF = "LGMED_STAFF", "LGMED Staff"
    ENCODER = "ENCODER", "Encoder"
    VIEWER = "VIEWER", "Viewer"


class Section(models.Model):
    """
    A department, division or section of the office.

    Employees belong to one; a calendar activity records the section that owns
    it. The Chief's monitoring view filters on this, which is the whole reason
    it is a table rather than the free-text `office` field beside it: you
    cannot group a division's workload by a string people spell four ways.
    """

    name = models.CharField(max_length=120, unique=True)
    short_name = models.CharField(
        max_length=20, blank=True,
        help_text="Abbreviation used where space is tight, e.g. LGCDD.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "department / division / section"
        verbose_name_plural = "departments / divisions / sections"
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def label(self):
        return self.short_name or self.name


class User(AbstractUser):
    """
    LGMED-iMMS account.

    `role` drives both the navigation a user is offered and the permission
    checks enforced in the views. Frontend visibility is a usability layer
    only - authorization is always re-checked server side.
    """

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        help_text="Determines the modules and actions available to this account.",
    )
    position = models.CharField(
        max_length=120,
        blank=True,
        help_text="Official designation, e.g. Information Systems Analyst.",
    )
    office = models.CharField(
        max_length=120,
        blank=True,
        default="Local Government Monitoring and Evaluation Division",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="department / division / section",
        help_text=(
            "The unit this employee belongs to. Determines which team "
            "activities they see and how the Chief groups their workload."
        ),
    )
    contact_number = models.CharField(max_length=40, blank=True)
    code_initials = models.CharField(
        "initials for LGMED codes",
        max_length=10,
        blank=True,
        help_text=(
            "The initials written into an LGMED code when a document is "
            "assigned to this person, e.g. RGFJ. Leave empty to use the first "
            "letter of each part of the first and last name."
        ),
    )
    # A photograph of a person is personal information, so it lives in the
    # protected root beside internal documents and is read back only through
    # `accounts.views.user_photo`, which requires a signed-in session. Always a
    # square JPEG written by `accounts.photos`, never the file as uploaded.
    photo = models.ImageField(
        "profile photo",
        upload_to="profile_photos/",
        storage=protected_storage,
        blank=True,
    )

    class Meta:
        verbose_name = "user account"
        verbose_name_plural = "user accounts"
        ordering = ("last_name", "first_name", "username")

    def __str__(self):
        return self.get_display_name()

    def get_absolute_url(self):
        return reverse("accounts:user_detail", args=[self.pk])

    # -- presentation -------------------------------------------------

    def get_display_name(self):
        full = self.get_full_name().strip()
        return full or self.username

    def get_initials(self):
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return "".join(p[0] for p in parts).upper()[:2]
        return self.username[:2].upper()

    def get_photo_url(self):
        """
        Where the profile photo is served, or "" when there is none.

        The stored file name changes with every upload, so it doubles as the
        cache-busting version: a browser keeps a photo for as long as it likes
        and still sees a new one straight away.
        """
        if not self.photo:
            return ""
        version = self.photo.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return f"{reverse('accounts:user_photo', args=[self.pk])}?v={version}"

    def get_code_initials(self):
        """
        The initials an LGMED code carries for this person.

        The office's naming rule includes the middle initial ("RGFJ"), which
        the account does not otherwise hold, so it is set by an administrator;
        without it the initials come from every part of the name.
        """
        if self.code_initials.strip():
            return self.code_initials.strip().upper()
        words = f"{self.first_name} {self.last_name}".split()
        if words:
            return "".join(word[0] for word in words if word[0].isalnum()).upper()
        return "".join(c for c in self.username if c.isalnum())[:4].upper()

    def get_role_label(self):
        return self.get_role_display()

    # -- authorization helpers ----------------------------------------

    @property
    def can_view(self):
        """Every role may read the modules; the account must be active."""
        return self.is_active

    @property
    def is_superadmin(self):
        return self.is_superuser or self.role == Role.SUPERADMIN

    @property
    def can_administer(self):
        """Users & roles, system settings, audit logs."""
        return self.is_superadmin or self.role == Role.ADMIN

    @property
    def can_encode(self):
        """Create and edit operational records."""
        return self.can_administer or self.role in (Role.LGMED_STAFF, Role.ENCODER)

    @property
    def can_approve(self):
        """Publish reports, approve monitoring records."""
        return self.can_administer or self.role == Role.LGMED_STAFF

    @property
    def can_review_incoming(self):
        """
        Review an incoming document and decide who handles it.

        This is the Division Chief's decision, and it is deliberately narrower
        than `can_approve`: an encoder records what arrived, but naming the
        focal person is not theirs to do. Held by the Chief and by designated
        administrators, who are the ADMIN role.
        """
        return self.is_superadmin or self.role == Role.ADMIN

    @property
    def can_supervise(self):
        """
        Monitor the work of others: read every calendar activity in the office,
        whoever created it, and group it by employee or by section.

        This is a *reading* capability. The Division Chief needs to see who is
        doing what without that turning into a licence to rewrite an
        employee's own plan - the record still belongs to the person who made
        it, and an activity silently edited by someone else is worse than no
        activity at all. Changing another employee's record is
        `can_manage_any_activity`, and it is deliberately narrower.
        """
        return self.is_superadmin or self.role == Role.ADMIN

    @property
    def can_manage_any_activity(self):
        """
        Edit or delete a calendar activity belonging to another employee.

        Administrators only. Everyone else - the Chief included - reads.
        """
        return self.is_superadmin

    # -- programmes, projects and activities ---------------------------
    #
    # The PPA module separates three decisions that the rest of the system
    # treats as one, because each of them can disclose something to the public
    # that cannot be taken back:
    #
    #   encoding    - describing the work and uploading the papers behind it
    #   reviewing   - reading the security screening and clearing the content
    #   publishing  - putting the cleared content on the public website
    #
    # An encoder may never clear their own work, and a reviewer may clear
    # content without being the one who decides the public website changes.

    @property
    def can_encode_ppa(self):
        """Create programmes, projects, sub-projects, activities; upload files."""
        return self.can_encode

    @property
    def can_review_ppa(self):
        """
        Read a document's security screening and decide whether it may be
        released: approve, reject, or send it back for revision.

        Held by the Division Chief, designated administrators and LGMED staff
        assigned the reviewing role - the same people who already approve
        monitoring records and clear reports.
        """
        return self.can_approve

    @property
    def can_publish_ppa(self):
        """
        Put approved content on the public website, take it down again, and
        archive it.

        Deliberately narrower than reviewing. Approval says the content is fit
        to be seen; publication decides that it is seen, and is the act that
        actually creates the public copy of a file. Administrators only.
        """
        return self.can_administer

    # -- document management -------------------------------------------

    @property
    def can_assign_documents(self):
        """
        Name the focal person responsible for a document.

        The same reasoning as `can_review_incoming`: an encoder records a
        document, but deciding whose desk it lands on is the Division Chief's
        call. Held by the Chief and designated administrators.
        """
        return self.is_superadmin or self.role == Role.ADMIN

    @property
    def can_archive_documents(self):
        """
        Move a completed document into the archive, and bring one back.

        Archiving is a records-management act rather than an editorial one, so
        it sits with the roles that already approve and publish rather than
        with everyone who may encode.
        """
        return self.can_approve

    @property
    def can_dispose_documents(self):
        """
        Authorise the permanent disposal of an archived document.

        The one irreversible action in the module, and deliberately the
        narrowest capability in the system. Even holding it, disposal requires
        a written authority to be recorded against the document.
        """
        return self.can_administer

    @property
    def can_delete(self):
        return self.can_administer

    # -- e-SIRA: signatures, routing and approval -----------------------
    #
    # Anyone with an active account may be sent a document to sign or approve
    # - a Director who only reads the other modules still signs. Uploading a
    # document and starting a route is encoding work. Being allowed to sign a
    # particular document is decided per document by esira.permissions, never
    # by role alone: it takes being the recipient whose turn it is, and
    # holding a verified PNPKI certificate.

    @property
    def can_use_esira(self):
        """Open e-SIRA and act on documents routed to you."""
        return self.is_active

    @property
    def can_upload_esira(self):
        """Upload or scan a document into e-SIRA and route it."""
        return self.is_active and self.can_encode

    @property
    def can_oversee_esira(self):
        """Read every e-SIRA document, its trail and the office-wide figures."""
        return self.is_active and self.can_supervise

    @property
    def can_verify_signing_certificates(self):
        """
        Confirm that a registered PNPKI certificate belongs to the employee
        who registered it, or revoke one. Administrators only: a verified
        certificate is what lets an account sign in the office's name.
        """
        return self.is_active and self.can_administer

    # -- organisational scope -----------------------------------------

    @property
    def section_label(self):
        """The employee's unit, for display. Falls back to the office name."""
        if self.section_id:
            return self.section.name
        return self.office or "Not assigned"

    # -- multi-factor authentication ------------------------------------

    @property
    def mfa_required(self):
        """
        Whether this account may not sign in on a password alone.

        Administrators hold the keys to every other account, the audit log
        and the public website, so a stolen administrator password is the
        one that does the most damage. Everyone else may turn MFA on for
        themselves from My Profile.
        """
        return self.can_administer

    @property
    def mfa_enabled(self):
        device = getattr(self, "mfa_device", None)
        return device is not None and device.is_confirmed


class MFADevice(models.Model):
    """
    The authenticator app an account has enrolled.

    One per account. Enrolling a new phone replaces the old one, and only
    after the new phone has proved it can produce a correct code - so a
    half-finished enrolment never locks anyone out of an account that was
    working.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="mfa_device",
    )
    # Base32, as the authenticator app holds it. Stored so the server can
    # compute the same code; never shown again after enrolment.
    secret = models.CharField(max_length=64)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # The time step of the last code accepted, so a code cannot be used twice.
    last_used_step = models.BigIntegerField(null=True, blank=True)

    # Wrong codes in a row, across sign-in attempts. A password alone lets
    # someone restart the sign-in as often as they like; counting here rather
    # than in the session is what stops each restart buying fresh guesses.
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "MFA authenticator"
        verbose_name_plural = "MFA authenticators"

    def __str__(self):
        return f"Authenticator for {self.user}"

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None


class RecoveryCode(models.Model):
    """
    A single-use code for signing in when the phone is lost or flat.

    Only a hash is kept, as with a password: the codes are shown once, at the
    moment they are made, and the account holder keeps them somewhere safe.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="mfa_recovery_codes",
    )
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "MFA recovery code"
        verbose_name_plural = "MFA recovery codes"
        ordering = ("pk",)

    def __str__(self):
        return f"Recovery code for {self.user}"



class ModuleAccessRule(models.Model):
    """
    Common to both kinds of Menu Permissions rule.

    The roles themselves stay in code (see accounts/capabilities.py): they
    decide what a person may *do*. These rules decide which sidebar modules a
    person is *offered*, and they can only narrow what the role already
    permits - a module a role's capabilities do not cover stays closed
    whatever is stored, because the views re-check the capability regardless.

    An account's rule overrides its role's; with neither, the module is open.
    The System Administrator is never subject to any rule. See
    accounts/menu_access.py.
    """

    module = models.CharField(max_length=40)
    allowed = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        state = "open" if self.allowed else "closed"
        return f"{self.module} {state} to {self.subject}"


class RoleModuleAccess(ModuleAccessRule):
    """Whether a sidebar module is open to every account holding a role."""

    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        verbose_name = "module access by role"
        verbose_name_plural = "module access by role"
        ordering = ("module", "role")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "role"), name="role_module_access_unique",
            ),
        ]

    @property
    def subject(self):
        return self.get_role_display()


class UserModuleAccess(ModuleAccessRule):
    """Whether a sidebar module is open to one account, whatever its role."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="module_access",
    )

    class Meta:
        verbose_name = "module access by account"
        verbose_name_plural = "module access by account"
        ordering = ("module", "user")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "user"), name="user_module_access_unique",
            ),
        ]

    @property
    def subject(self):
        return self.user
