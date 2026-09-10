from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SingletonModel(models.Model):
    """
    A configuration table that holds exactly one row.

    The row is enforced rather than merely intended: `pk` is forced to 1 on
    every save, so `Model.objects.create(...)` updates the single row instead
    of failing on the primary key. Callers should not have to know how many
    rows the table has.
    """

    CACHE_KEY = ""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):  # pragma: no cover - guarded, not used
        raise RuntimeError(f"The {self._meta.verbose_name} row cannot be deleted.")

    @classmethod
    def load(cls):
        """The single row, cached - this is read on every page render."""
        row = cache.get(cls.CACHE_KEY)
        if row is None:
            row, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, row, 300)
        return row


class SystemSetting(SingletonModel):
    """
    System-wide preferences, held as a single row.

    Every setting here changes something the user can see. A settings page full
    of switches that do nothing is worse than no settings page at all, so
    nothing is added to this model until it is wired up.
    """

    records_per_page = models.PositiveSmallIntegerField(
        default=15,
        validators=[MinValueValidator(5), MaxValueValidator(100)],
        help_text="Rows shown per page in every module table (5-100).",
    )
    public_site_enabled = models.BooleanField(
        "Public website available",
        default=True,
        help_text=(
            "When switched off, the public pages show a maintenance notice. "
            "Staff sign-in and the internal system are unaffected."
        ),
    )
    notice_message = models.CharField(
        "System notice",
        max_length=255,
        blank=True,
        help_text=(
            "Shown as a banner to every signed-in user, for example during "
            "scheduled maintenance. Leave empty for no banner."
        ),
    )
    notice_level = models.CharField(
        max_length=10,
        choices=[("info", "Information"), ("warning", "Warning"), ("danger", "Urgent")],
        default="info",
    )
    session_notice_minutes = models.PositiveSmallIntegerField(
        "Session warning",
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="Minutes before session expiry that a warning is shown (1-60).",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    CACHE_KEY = "lgmed:system-settings"

    class Meta:
        verbose_name = "system settings"
        verbose_name_plural = "system settings"

    def __str__(self):
        return "System settings"


class PublicSiteContent(SingletonModel):
    """
    The words on the public website that are not records.

    Everything else the public site shows - news, programs, services, reports,
    documents, the calendar - is a record in a module, encoded and published
    by the people who own it. What remained was the standing copy: the
    homepage heading, the mandate, the office's contact details, the privacy
    and accessibility statements. That copy used to be typed into templates,
    which meant a change of telephone number was a developer's job. It lives
    here instead.

    Every field ships with the text the templates carried, so an office that
    never opens this page sees exactly the site it had.
    """

    # -- Homepage ---------------------------------------------------------
    hero_heading = models.CharField(
        "homepage heading",
        max_length=200,
        default="Local Government Monitoring and Evaluation Division",
    )
    hero_lead = models.TextField(
        "homepage introduction",
        default=(
            "The Division oversees the performance of local government units "
            "across Caraga - monitoring compliance with national policy, "
            "evaluating programs and projects, and publishing the results for "
            "public scrutiny."
        ),
        help_text="The paragraph under the homepage heading.",
    )
    mandate_intro = models.CharField(
        "mandate introduction",
        max_length=255,
        default=(
            "LGMED carries out three interlocking functions on behalf of the "
            "Regional Office."
        ),
        help_text="The line above the three function cards on the homepage.",
    )

    # -- About page -------------------------------------------------------
    about_intro = models.TextField(
        "about the Division",
        default=(
            "The Local Government Monitoring and Evaluation Division is one of "
            "the operating divisions of the Department of the Interior and "
            "Local Government Regional Office XIII - Caraga. It is responsible "
            "for monitoring and evaluating the performance of local government "
            "units in the region, and for reporting the results to regional "
            "management, to the national office and to the public."
        ),
    )
    core_functions = models.TextField(
        "core functions",
        default=(
            "Monitoring the compliance of local government units with national "
            "laws, policies and issuances.\n"
            "Evaluating the implementation and results of local governance "
            "programs and projects.\n"
            "Conducting field validation and assessment activities across the "
            "region's provinces, cities and municipalities.\n"
            "Maintaining the regional record of monitoring findings, "
            "recommendations and follow-up actions.\n"
            "Preparing and publishing monitoring and evaluation reports.\n"
            "Providing technical assistance and frontline services to local "
            "government units."
        ),
        help_text="One function per line. Shown as the list on the About page.",
    )

    # -- Office details ---------------------------------------------------
    # These override the built-in identity wherever the site shows the
    # office's contact details, so a move or a new trunk line is a five-minute
    # edit rather than a code change.
    address = models.CharField(
        "office address",
        max_length=255,
        default="Purok 1-A, Brgy. Doongan, Butuan City, 8600",
    )
    telephone = models.CharField(
        max_length=120, default="(085) 975-9830 to 34"
    )
    email = models.EmailField(default="RegionalOffice@caraga.dilg.gov.ph")
    office_hours = models.CharField(
        max_length=150,
        blank=True,
        default="Monday to Thursday, 7:00 AM - 7:00 PM",
        help_text="Left empty, the office hours are not shown at all.",
    )
    facebook_url = models.URLField(
        "Facebook page",
        blank=True,
        help_text="Optional. Linked from the contact page and the footer.",
    )

    # -- Standing notices -------------------------------------------------
    privacy_notice = models.TextField(
        default=(
            "Personal information collected through this website and through "
            "LGMED-iMMS is processed in accordance with the Data Privacy Act "
            "of 2012 (Republic Act No. 10173) and is used solely for the "
            "Division's monitoring, evaluation and service delivery functions. "
            "Enquiries regarding personal data may be directed to the office "
            "contacts above."
        ),
    )
    accessibility_statement = models.TextField(
        default=(
            "This website is built to meet recognised accessibility practice: "
            "it can be operated by keyboard alone, uses text alternatives for "
            "non-text content, maintains sufficient colour contrast, and never "
            "relies on colour alone to convey status. If you encounter a "
            "barrier to using this site, please tell us using the contact "
            "details above so it can be corrected."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    CACHE_KEY = "lgmed:public-site-content"

    class Meta:
        verbose_name = "public website content"
        verbose_name_plural = "public website content"

    def __str__(self):
        return "Public website content"

    @property
    def function_list(self):
        return [line.strip() for line in self.core_functions.splitlines() if line.strip()]

    @property
    def telephone_link(self):
        """
        The telephone number as a `tel:` target.

        Office numbers are written for people - "(085) 975-9830 to 34" names a
        trunk line and its range of extensions - so only the first number is
        dialled, and a local number is given its country code. A field with
        no digits in it yields an empty string.
        """
        import re

        first = re.split(r"\s+(?:to|loc\.?|local)\s+|[/;,]", self.telephone, maxsplit=1)[0]
        digits = re.sub(r"[^\d+]", "", first)
        if not digits:
            return ""
        if digits.startswith("+"):
            return digits
        if digits.startswith("0"):
            return "+63" + digits[1:]
        return digits
