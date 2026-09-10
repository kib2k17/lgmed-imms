"""
Tests for the public news feed.

What matters here is what a visitor can and cannot see: a draft, or an item
dated next week, must not appear on the public site by any route - the list,
the homepage or its own address.
"""

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Announcement, AnnouncementCategory


def make_item(title, **overrides):
    fields = {
        "title": title,
        "summary": f"{title} summary paragraph.",
        "is_published": True,
        "published_on": timezone.localdate(),
    }
    fields.update(overrides)
    return Announcement.objects.create(**fields)


class AnnouncementModelTests(TestCase):
    def test_slug_is_generated_from_the_headline(self):
        item = make_item("Regional Peace and Order Council convenes")
        self.assertEqual(item.slug, "regional-peace-and-order-council-convenes")

    def test_a_repeated_headline_still_saves(self):
        """Two activities can share a headline; the second gets a counter."""
        first = make_item("Barangay assembly day")
        second = make_item("Barangay assembly day")
        self.assertEqual(first.slug, "barangay-assembly-day")
        self.assertEqual(second.slug, "barangay-assembly-day-2")

    def test_published_excludes_drafts_and_post_dated_items(self):
        live = make_item("Published today")
        make_item("Still a draft", is_published=False)
        make_item(
            "Scheduled for next week",
            published_on=timezone.localdate() + datetime.timedelta(days=7),
        )
        self.assertEqual([a.pk for a in Announcement.objects.published()], [live.pk])

    def test_commendations_are_separated_from_the_news_feed(self):
        news = make_item("Field validation completed")
        commendation = make_item(
            "Region cited for full compliance",
            category=AnnouncementCategory.COMMENDATION,
        )
        published = Announcement.objects.published()
        self.assertEqual([a.pk for a in published.news()], [news.pk])
        self.assertEqual([a.pk for a in published.commendations()], [commendation.pk])

    def test_alt_text_falls_back_to_the_headline(self):
        item = make_item("Crisis management training held in Butuan City")
        self.assertEqual(item.alt_text, item.title)


class PublicNewsTests(TestCase):
    def test_news_page_lists_published_items_only(self):
        make_item("Anti-illegal drug advocacy caravan")
        make_item("Unreleased advisory", is_published=False)

        response = self.client.get(reverse("core:public_announcements"))
        self.assertContains(response, "Anti-illegal drug advocacy caravan")
        self.assertNotContains(response, "Unreleased advisory")

    def test_news_page_filters_by_category(self):
        make_item("Child protection orientation")
        make_item("Advisory on report deadlines", category=AnnouncementCategory.ADVISORY)

        response = self.client.get(
            reverse("core:public_announcements"), {"category": "ADVISORY"}
        )
        self.assertContains(response, "Advisory on report deadlines")
        self.assertNotContains(response, "Child protection orientation")

    def test_an_item_has_its_own_page(self):
        item = make_item("Local governance audit begins")
        response = self.client.get(item.get_public_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.summary)

    def test_a_draft_has_no_public_page(self):
        item = make_item("Draft for clearance", is_published=False)
        self.assertEqual(self.client.get(item.get_public_url()).status_code, 404)

    def test_homepage_leads_with_the_featured_item(self):
        """
        Regression: the featured item leads even when it is old enough to have
        fallen off the end of the short homepage feed.
        """
        for day in range(1, 9):
            make_item(
                f"Routine item {day}",
                published_on=timezone.localdate() - datetime.timedelta(days=day),
            )
        featured = make_item(
            "Featured item",
            is_featured=True,
            published_on=timezone.localdate() - datetime.timedelta(days=300),
        )

        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["lead_story"].pk, featured.pk)
        self.assertContains(response, "LGMED Latest News")

    def test_homepage_does_not_repeat_the_lead_story_in_the_list(self):
        featured = make_item("Featured item", is_featured=True)
        make_item("Second item")

        response = self.client.get(reverse("core:home"))
        listed = [item.pk for item in response.context["news"]]
        self.assertNotIn(featured.pk, listed)

    def test_commendations_appear_on_the_about_page(self):
        make_item(
            "Region 10 cited by the National Office",
            category=AnnouncementCategory.COMMENDATION,
        )
        response = self.client.get(reverse("core:public_about"))
        self.assertContains(response, "Region 10 cited by the National Office")
