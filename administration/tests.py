"""
Tests for System Settings.

The point of these is that the settings page is not decorative: each test
changes a setting and then checks that the thing it claims to control actually
changed.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from administration.models import PublicSiteContent, SystemSetting
from lgus.models import LGU, LGUType, Province
from programs.models import Program, ProgramCategory, ProgramStatus


class SystemSettingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    def setUp(self):
        cache.clear()

    def test_only_administrators_reach_the_settings_page(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("administration:settings")).status_code, 403
        )

    def test_the_settings_row_is_a_singleton(self):
        SystemSetting.objects.all().delete()
        first = SystemSetting.load()
        SystemSetting.objects.create(records_per_page=50)
        self.assertEqual(SystemSetting.objects.count(), 1)
        self.assertEqual(first.pk, 1)

    def test_records_per_page_drives_module_pagination(self):
        province = Province.objects.create(name="Agusan del Norte")
        for index in range(12):
            LGU.objects.create(
                name=f"LGU {index}", lgu_type=LGUType.MUNICIPALITY, province=province
            )

        settings_row = SystemSetting.load()
        settings_row.records_per_page = 5
        settings_row.save()

        self.client.force_login(self.staff)
        response = self.client.get(reverse("lgus:list"))
        self.assertEqual(len(response.context["records"]), 5)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 3)

    def test_the_notice_banner_appears_when_set(self):
        settings_row = SystemSetting.load()
        settings_row.notice_message = "Scheduled maintenance on Friday evening."
        settings_row.save()

        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Scheduled maintenance on Friday evening.")

    def test_no_banner_is_rendered_when_the_notice_is_empty(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        self.assertNotContains(response, "System notice:")

    def test_switching_the_public_site_off_takes_the_public_pages_offline(self):
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)

        settings_row = SystemSetting.load()
        settings_row.public_site_enabled = False
        settings_row.save()

        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response, "temporarily unavailable", status_code=503
        )

        # Staff sign-in and the internal system stay available.
        self.assertEqual(
            self.client.get(reverse("accounts:login")).status_code, 200
        )

    def test_saving_the_form_records_who_changed_it(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration:settings"),
            {
                "records_per_page": 25,
                "session_notice_minutes": 10,
                "notice_message": "",
                "notice_level": "info",
                "public_site_enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        settings_row = SystemSetting.load()
        self.assertEqual(settings_row.records_per_page, 25)
        self.assertEqual(settings_row.updated_by, self.admin)

    def test_an_out_of_range_page_size_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration:settings"),
            {
                "records_per_page": 5000,
                "session_notice_minutes": 5,
                "notice_message": "",
                "notice_level": "info",
                "public_site_enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(SystemSetting.load().records_per_page, 5000)


class ReferenceDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )
        cls.category = ProgramCategory.objects.create(name="Governance")

    def setUp(self):
        cache.clear()

    def test_non_administrators_cannot_change_reference_data(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("administration:reference_delete",
                    args=["program-categories", self.category.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ProgramCategory.objects.filter(pk=self.category.pk).exists())

    def test_an_unknown_reference_list_is_a_404(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("administration:reference_create", args=["not-a-list"])
        )
        self.assertEqual(response.status_code, 404)

    def test_an_administrator_can_add_an_entry(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration:reference_create", args=["document-types"]),
            {"name": "Special Order", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        from documents.models import DocumentType

        self.assertTrue(DocumentType.objects.filter(name="Special Order").exists())

    def test_an_unused_entry_can_be_removed(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration:reference_delete",
                    args=["program-categories", self.category.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProgramCategory.objects.filter(pk=self.category.pk).exists())

    def test_an_entry_in_use_is_protected_and_the_refusal_is_explained(self):
        """The database refuses; the user gets an explanation, not a 500."""
        import datetime

        Program.objects.create(
            title="Seal of Good Local Governance",
            category=self.category,
            start_date=datetime.date(2026, 1, 15),
            status=ProgramStatus.ACTIVE,
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration:reference_delete",
                    args=["program-categories", self.category.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProgramCategory.objects.filter(pk=self.category.pk).exists())
        self.assertContains(response, "cannot be removed because records still refer")


class PublicSiteBackendTests(TestCase):
    """
    The page an officer uses to run the public website.

    Each test here asks the same question the page implicitly promises: does
    changing something on this form change what a visitor sees?
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="site.admin", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="site.staff", password="pw", role=Role.LGMED_STAFF
        )
        cls.encoder = User.objects.create_user(
            username="site.encoder", password="pw", role=Role.ENCODER
        )
        cls.viewer = User.objects.create_user(
            username="site.viewer", password="pw", role=Role.VIEWER
        )
        cls.url = reverse("administration:public_site")

    def setUp(self):
        cache.clear()

    def form_data(self, **overrides):
        from administration.views import PublicSiteContentForm

        row = PublicSiteContent.load()
        data = {name: getattr(row, name) for name in PublicSiteContentForm.Meta.fields}
        data.update(overrides)
        return data

    # -- access --------------------------------------------------------

    def test_administrators_and_staff_may_manage_the_site(self):
        for user in (self.admin, self.staff):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_encoders_and_viewers_are_refused(self):
        for user in (self.encoder, self.viewer):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_an_encoder_cannot_post_the_form_either(self):
        """The refusal is the view's, not the hidden sidebar link's."""
        self.client.force_login(self.encoder)
        response = self.client.post(
            self.url, self.form_data(hero_heading="Changed by an encoder")
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(PublicSiteContent.load().hero_heading, "Changed by an encoder")

    def test_signing_in_is_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    # -- editing -------------------------------------------------------

    def test_saved_text_appears_on_the_public_homepage(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            self.url,
            self.form_data(
                hero_heading="LGMED Caraga",
                hero_lead="What the Division does, in one paragraph.",
            ),
        )
        self.assertEqual(response.status_code, 302)

        home = self.client.get(reverse("core:home"))
        self.assertContains(home, "LGMED Caraga")
        self.assertContains(home, "What the Division does, in one paragraph.")

    def test_core_functions_are_published_one_per_line(self):
        self.client.force_login(self.staff)
        self.client.post(
            self.url,
            self.form_data(core_functions="First function\n\nSecond function\n"),
        )
        response = self.client.get(reverse("core:public_about"))
        self.assertContains(response, "<li>First function</li>", html=True)
        self.assertContains(response, "<li>Second function</li>", html=True)

    def test_new_contact_details_reach_every_page_that_shows_them(self):
        self.client.force_login(self.admin)
        self.client.post(
            self.url,
            self.form_data(
                address="New Capitol Compound, Butuan City",
                telephone="(085) 342-1234 to 36",
                email="lgmed@caraga.dilg.gov.ph",
            ),
        )
        for name in ("core:home", "core:public_contact"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "New Capitol Compound, Butuan City")
                self.assertContains(response, "lgmed@caraga.dilg.gov.ph")

    def test_the_dialling_link_is_built_from_the_recorded_number(self):
        """A number written for people - "to 36" is a range, not a digit."""
        row = PublicSiteContent.load()
        row.telephone = "(085) 342-1234 to 36"
        row.save()
        self.assertEqual(row.telephone_link, "+63853421234")

        response = self.client.get(reverse("core:public_contact"))
        self.assertContains(response, "tel:+63853421234")

    def test_office_hours_are_omitted_when_left_empty(self):
        row = PublicSiteContent.load()
        row.office_hours = ""
        row.save()
        response = self.client.get(reverse("core:public_contact"))
        self.assertNotContains(response, "Office hours")

    def test_saving_records_who_changed_it(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, self.form_data(hero_heading="Edited"))
        self.assertEqual(PublicSiteContent.load().updated_by, self.staff)

    def test_the_content_row_is_a_singleton(self):
        PublicSiteContent.objects.all().delete()
        first = PublicSiteContent.load()
        PublicSiteContent.objects.create(hero_heading="Second row?")
        self.assertEqual(PublicSiteContent.objects.count(), 1)
        self.assertEqual(first.pk, 1)

    # -- what is published ---------------------------------------------

    def test_the_page_counts_what_the_public_can_actually_see(self):
        from announcements.models import Announcement

        Announcement.objects.create(
            title="Published item", summary="Live.", is_published=True
        )
        Announcement.objects.create(
            title="Draft item", summary="Not live.", is_published=False
        )

        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        news = next(
            row for row in response.context["published_content"]
            if row["label"] == "News items"
        )
        self.assertEqual(news["public"], 1)
        self.assertEqual(news["total"], 2)

    def test_the_page_warns_when_the_public_site_is_switched_off(self):
        settings_row = SystemSetting.load()
        settings_row.public_site_enabled = False
        settings_row.save()

        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, "The public website is switched off")
