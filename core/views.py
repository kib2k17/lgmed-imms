import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from . import stats


# ---------------------------------------------------------------------------
# Internal system
# ---------------------------------------------------------------------------


@login_required
def dashboard(request):
    """Regional monitoring and evaluation overview, computed from the records."""
    charts = stats.charts()

    context = {
        "page_title": "LGMED-iMMS Dashboard",
        "page_subtitle": "Regional monitoring and evaluation overview",
        "breadcrumbs": [{"label": "Dashboard"}],
        "active_nav": "dashboard",
        "as_of": timezone.localtime(),
        "summary_cards": stats.summary_cards(),
        "charts": charts,
        "recent_monitoring": stats.recent_monitoring(),
        "pending_actions": stats.pending_actions(),
        "upcoming_activities": stats.upcoming_activities(request.user),
        # Series only - the accessible figure tables are rendered server side.
        "charts_json": json.dumps({c["id"]: c["data"] for c in charts}),
    }
    return render(request, "dashboard/dashboard.html", context)


@login_required
def module_placeholder(request, *, key, title, subtitle, summary, requires=None):
    """
    Renders a module that is scheduled for a later phase.

    Authorization is enforced here rather than by hiding the sidebar link, so a
    user who types the URL still receives a 403.
    """
    if requires and not getattr(request.user, requires, False):
        raise PermissionDenied

    context = {
        "page_title": title,
        "page_subtitle": subtitle,
        "breadcrumbs": [{"label": title}],
        "active_nav": key,
        "module_summary": summary,
    }
    return render(request, "dashboard/module_placeholder.html", context)


def _module(key, title, subtitle, summary, requires=None):
    """Build a named view for a module scheduled for a later phase."""

    def view(request):
        return module_placeholder(
            request,
            key=key,
            title=title,
            subtitle=subtitle,
            summary=summary,
            requires=requires,
        )

    view.__name__ = key
    return view


@login_required
def components(request):
    """Living reference of the design system's components."""
    context = {
        "page_title": "Design System",
        "page_subtitle": "Reference implementation of LGMED-iMMS interface components",
        "breadcrumbs": [{"label": "Design System"}],
        "active_nav": "components",
        "demo_filters": [
            {
                "name": "status",
                "label": "Status",
                "options": [
                    ("active", "Active"),
                    ("completed", "Completed"),
                    ("pending", "Pending"),
                    ("archived", "Archived"),
                ],
                "selected": request.GET.get("status", ""),
            },
            {
                "name": "year",
                "label": "Year",
                "options": [("2026", "2026"), ("2025", "2025"), ("2024", "2024")],
                "selected": request.GET.get("year", ""),
            },
        ],
    }
    return render(request, "dashboard/components.html", context)


# ---------------------------------------------------------------------------
# Public website
#
# Only records that have been explicitly marked for publication appear here.
# ---------------------------------------------------------------------------


def _paginate(request, queryset, per_page):
    """
    One page of a public listing.

    An out-of-range or non-numeric ?page= gives the last page rather than a
    404: a visitor who lands on a stale link should still see the library.
    """
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def public_view(view):
    """
    Honour the `public_site_enabled` system setting.

    When an administrator switches the public site off, visitors get a plain
    maintenance notice instead of a broken or half-populated page. Staff
    sign-in and the internal system are deliberately unaffected.
    """
    from functools import wraps

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from administration.models import SystemSetting

        if not SystemSetting.load().public_site_enabled:
            return render(request, "public/unavailable.html", status=503)
        return view(request, *args, **kwargs)

    return wrapper


@public_view
def home(request):
    news = list(stats.public_news(limit=6))
    lead = stats.public_featured_story() or (news[0] if news else None)
    if lead is not None:
        news = [item for item in news if item.pk != lead.pk]
    context = {
        "meta_title": "Home",
        "summary": stats.public_summary(),
        "documents": stats.public_documents(),
        "activities": stats.public_activities(),
        "services": stats.public_services(),
        # The lead story is the first featured item, falling back to the most
        # recent one, so the homepage never leads with an empty slot.
        "lead_story": lead,
        "news": news[:4],
    }
    return render(request, "public/home.html", context)


def _public_page(template, title, subtitle):
    @public_view
    def view(request):
        return render(
            request,
            template,
            {"meta_title": title, "page_title": title, "page_subtitle": subtitle},
        )

    return view


@public_view
def public_about(request):
    from lgus.models import Province

    return render(
        request,
        "public/about.html",
        {
            "meta_title": "About LGMED",
            "page_title": "About LGMED",
            "page_subtitle": "Mandate, functions and coverage of the Division",
            "provinces": Province.objects.all(),
            "summary": stats.public_summary(),
            "commendations": stats.public_commendations(),
        },
    )


@public_view
def public_programs(request):
    from programs.models import Program, ProgramStatus

    return render(
        request,
        "public/programs.html",
        {
            "meta_title": "Programs",
            "page_title": "Programs",
            "page_subtitle": "Programs and projects administered by the Division",
            "programs": Program.objects.select_related("category")
            .filter(status__in=(ProgramStatus.ACTIVE, ProgramStatus.COMPLETED))
            .order_by("-start_date"),
        },
    )


@public_view
def public_services(request):
    from services.models import FrontlineService

    return render(
        request,
        "public/services.html",
        {
            "meta_title": "Services",
            "page_title": "Frontline Services",
            "page_subtitle": "Services provided by the Division to LGUs and the public",
            "services": FrontlineService.objects.filter(is_published=True),
        },
    )


@public_view
def public_documents(request):
    """
    The document library: search, then narrow by type and year.

    A visitor arrives looking for one issuance, not for a list of everything
    the Division has ever published, so the filters are the page - the counts
    beside each type tell them whether it is worth clicking before they do.
    """
    from django.db.models import Count

    from documents.models import Document, DocumentStatus

    library = Document.objects.public().select_related("document_type")

    term = request.GET.get("q", "").strip()
    selected_type = request.GET.get("type", "").strip()
    selected_year = request.GET.get("year", "").strip()

    # The selected flag is resolved here rather than in the template: the id
    # comes back from the query string as a string, and comparing it to the
    # integer primary key in a template silently never matches.
    types = [
        {
            "id": row["document_type__id"],
            "name": row["document_type__name"],
            "total": row["total"],
            "is_selected": str(row["document_type__id"]) == selected_type,
        }
        for row in library.values("document_type__id", "document_type__name")
        .annotate(total=Count("pk"))
        .order_by("document_type__name")
    ]
    years = [
        {"year": year, "is_selected": str(year) == selected_year}
        for year in library.values_list("year", flat=True).distinct().order_by("-year")
    ]

    documents = library
    if term:
        documents = documents.filter(
            Q(title__icontains=term)
            | Q(reference_number__icontains=term)
            | Q(description__icontains=term)
        )
    if selected_type.isdigit():
        documents = documents.filter(document_type_id=selected_type)
    if selected_year.isdigit():
        documents = documents.filter(year=selected_year)

    page = _paginate(request, documents.order_by("-year", "title"), per_page=20)

    return render(
        request,
        "public/documents.html",
        {
            "meta_title": "Document Library",
            "page_title": "Document Library",
            "page_subtitle": (
                "Memoranda, circulars, advisories and other issuances "
                "released for public access"
            ),
            "page_obj": page,
            "documents": page.object_list,
            "document_types": types,
            "years": years,
            "total_count": library.count(),
            "search_term": term,
            "selected_type": selected_type,
            "selected_year": selected_year,
            "is_filtered": bool(term or selected_type or selected_year),
        },
    )


@public_view
def public_reports(request):
    from reports.models import Report, ReportStatus

    return render(
        request,
        "public/reports.html",
        {
            "meta_title": "Reports",
            "page_title": "Reports",
            "page_subtitle": "Published monitoring and evaluation reports",
            "reports": Report.objects.filter(status=ReportStatus.PUBLISHED),
        },
    )


@public_view
def public_calendar(request):
    from activities.models import ActivityStatus, CalendarActivity, Visibility

    return render(
        request,
        "public/calendar.html",
        {
            "meta_title": "Calendar",
            "page_title": "Calendar of Activities",
            "page_subtitle": "Scheduled activities of the Division",
            # Two conditions, not one. `is_published` is the intention to
            # publish; the visibility level is the owner's decision about who
            # may see the activity at all, and the public site must honour it
            # even if a record was flagged for publication through the Django
            # admin, which does not run the form's check.
            "activities": CalendarActivity.objects.select_related("lgu")
            .filter(
                is_published=True,
                visibility=Visibility.ORGANIZATION,
                start_date__gte=timezone.localdate(),
            )
            .exclude(status=ActivityStatus.CANCELLED),
        },
    )


@public_view
def public_announcements(request):
    """The news feed: everything the Division has published, newest first."""
    from announcements.models import Announcement, AnnouncementCategory

    items = Announcement.objects.published()
    category = request.GET.get("category", "").strip()
    if category in AnnouncementCategory.values:
        items = items.filter(category=category)

    page = _paginate(request, items, per_page=9)

    return render(
        request,
        "public/news.html",
        {
            "meta_title": "News",
            "page_title": "LGMED Latest News",
            "page_subtitle": (
                "Activities, advisories and issuances of the Division"
            ),
            "page_obj": page,
            "items": page.object_list,
            "categories": AnnouncementCategory.choices,
            "selected_category": category,
            "total_count": Announcement.objects.published().count(),
        },
    )


@public_view
def public_announcement(request, slug):
    from announcements.models import Announcement

    item = get_object_or_404(Announcement.objects.published(), slug=slug)
    related = (
        Announcement.objects.published()
        .filter(category=item.category)
        .exclude(pk=item.pk)[:3]
    )

    return render(
        request,
        "public/news_detail.html",
        {
            "meta_title": item.title,
            "meta_description": item.excerpt,
            "item": item,
            "related": related,
        },
    )


@public_view
def public_updates(request):
    """
    What the Division has accomplished - the same statistics the office works
    from, published.

    The Division is the subject throughout: the figures are LGMEDD's, the
    accomplishments are LGMEDD's, and no individual's record appears here.

    The figures cover the weeks the Chief has **published** *and* left inside
    the disclosure window, so nothing reaches this page before it has been
    reviewed, and the Division decides how far back the public record runs.
    Within those weeks the counts are the Division's real totals, while the
    lists - the weeks, the ways forward, what is coming - carry only what was
    cleared item by item.
    """
    import json

    from updates.models import PublicDisclosure, public_periods
    from updates.stats import Scope, available_years

    from updates import stats as update_stats

    years = available_years(published_only=True)
    try:
        year = int(request.GET.get("year", years[0] if years else 0))
    except (TypeError, ValueError):
        year = years[0] if years else 0
    if year not in years:
        year = years[0] if years else timezone.localdate().year

    scope = Scope.for_public(year)
    figures = update_stats.division_statistics(scope=scope)
    charts = update_stats.charts(scope=scope)

    periods = public_periods().filter(start_date__year=year)
    page = _paginate(request, periods, per_page=8)

    return render(
        request,
        "public/updates.html",
        {
            "meta_title": "Accomplishments",
            "page_title": "LGMEDD Updates & Accomplishments",
            "page_subtitle": (
                "What the Local Government Monitoring and Evaluation Division "
                "accomplished, week by week"
            ),
            "disclosure": PublicDisclosure.load(),
            "year": year,
            "years": years,
            "stats": figures,
            "cards": update_stats.headline_cards(figures),
            "figures": update_stats.breakdown_figures(figures),
            "charts": charts,
            "charts_json": json.dumps({c["id"]: c["data"] for c in charts}),
            "upcoming": update_stats.upcoming_activities(scope=scope),
            "ways_forward": update_stats.open_ways_forward(scope=scope),
            "page_obj": page,
            "weeks": [
                {
                    "period": week,
                    "entries": week.updates.published().order_by("-activity_date")[:6],
                    "entry_count": week.updates.published().count(),
                    "photos": week.photos.filter(is_public=True)[:4],
                }
                for week in page.object_list
            ],
            "total_count": public_periods().count(),
        },
    )


@public_view
def public_update_week(request, pk):
    """
    One published division week, presented as it is at the convocation.

    The figures are the Division's own for that week - counts of activities and
    correspondence, which is exactly the kind of aggregate a government office
    publishes about itself. What is *listed* underneath them is narrower: only
    the entries, photographs, POPS Plan figures and ways forward the Chief
    cleared one at a time. So the page can honestly say the Division did
    fourteen things while publishing the six it chose to publish, and no
    internal note or individual's record leaves the system either way.
    """
    from django.db.models import Sum

    from updates.models import public_periods
    from updates.stats import division_statistics, headline_cards

    period = get_object_or_404(public_periods(), pk=pk)
    figures = division_statistics(period=period)
    entries = period.updates.published().order_by("-activity_date")
    pops_updates = period.pops_updates.filter(is_public=True)

    # Compliance is computed from the published rows alone, so the headline
    # percentage always adds up to the table printed beneath it.
    totals = pops_updates.aggregate(target=Sum("target"), done=Sum("accomplished"))
    target = totals["target"] or 0
    accomplished = totals["done"] or 0

    return render(
        request,
        "public/update_week.html",
        {
            "meta_title": f"Accomplishments, {period.label}",
            "meta_description": (
                f"What the Local Government Monitoring and Evaluation Division "
                f"accomplished during {period.label}."
            ),
            "page_title": "LGMEDD Updates & Accomplishments",
            "page_subtitle": period.label,
            "period": period,
            "stats": figures,
            "cards": headline_cards(figures),
            "entries": entries,
            "major": entries.filter(is_major=True).order_by(
                "convocation_order", "-activity_date"
            ),
            "photos": period.photos.filter(is_public=True),
            "pops_updates": pops_updates,
            "pops_compliance": {
                "target": target,
                "accomplished": accomplished,
                "percent": round(accomplished * 100 / target) if target else 0,
            },
            "ways_forward": period.ways_forward.filter(is_public=True),
            "upcoming": period.upcoming.filter(is_public=True),
        },
    )


@public_view
def public_statistics(request):
    """Regional figures, published as they stand in the records."""
    return render(
        request,
        "public/statistics.html",
        {
            "meta_title": "Statistics",
            "page_title": "Statistics",
            "page_subtitle": (
                "Coverage, monitoring and publication figures for Region XIII"
            ),
            "summary": stats.public_summary(),
            "figures": stats.public_statistics(),
        },
    )


public_contact = _public_page(
    "public/contact.html",
    "Contact",
    "Reach the Local Government Monitoring and Evaluation Division",
)
