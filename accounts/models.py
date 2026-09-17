from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse


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

    # -- organisational scope -----------------------------------------

    @property
    def section_label(self):
        """The employee's unit, for display. Falls back to the office name."""
        if self.section_id:
            return self.section.name
        return self.office or "Not assigned"
