"""
What the public website is allowed to see.

Every query the public pages run goes through this module, and every one of
them filters on publication status - not once, but at each level of the tree.
The repetition is the point. A visitor reaching a sub-project page has walked
past a published programme and a published project to get there, but they can
also have arrived by typing the address, and the page must refuse in that case
too. `visible()` therefore re-checks the whole chain rather than trusting the
route that led to it.

Two things are deliberately absent from everything this module returns:

    Database identifiers. Public addresses are built from slugs, and a record's
    primary key never appears in a URL, a form or a page.

    Internal files. `SupportingDocument.public_url` returns the address of the
    approved public copy or nothing at all, and the internal file's path exists
    nowhere in any template the public can reach.
"""

from django.db.models import Count, Q
from django.http import Http404

from .models import (
    OUTCOME_BY_SLUG,
    OUTCOME_DETAIL,
    Activity,
    DocumentStatus,
    OrganizationalOutcome,
    Program,
    Project,
    PublicationStatus,
    SubProject,
    SupportingDocument,
)

PUBLISHED = PublicationStatus.PUBLISHED


def published_documents():
    """The approved public copies, and nothing else."""
    return SupportingDocument.objects.filter(
        status=DocumentStatus.PUBLISHED
    ).exclude(public_file="")


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


def published_programs(outcome=None):
    queryset = (
        Program.objects.filter(publication_status=PUBLISHED)
        .select_related("category")
        # Every card states its coverage; counting per card is a query per card.
        .annotate(lgu_total=Count("covered_lgus", distinct=True))
    )
    if outcome:
        queryset = queryset.filter(outcome_code=outcome)
    return queryset.order_by("outcome_code", "title")


def published_projects(program):
    return program.projects.filter(publication_status=PUBLISHED).order_by("title")


def published_sub_projects(project):
    return project.sub_projects.filter(publication_status=PUBLISHED).order_by("title")


def published_activities(parent):
    return parent.activities.filter(publication_status=PUBLISHED).order_by(
        "-activity_date", "title"
    )


def outcome_summary():
    """
    The five Outcomes with a count of the published programmes under each.

    One query rather than five, and the Outcomes with nothing published under
    them are still listed - the public page names all five because all five are
    the Department's, whether or not this region has published against them yet.
    """
    counts = dict(
        published_programs()
        .values_list("outcome_code")
        .annotate(total=Count("pk"))
        .values_list("outcome_code", "total")
    )
    rows = []
    for value in OrganizationalOutcome.values:
        outcome = OrganizationalOutcome(value)
        rows.append({
            "value": value,
            "label": outcome.label,
            "detail": OUTCOME_DETAIL[outcome],
            "program_count": counts.get(value, 0),
        })
    return rows


def public_statistics():
    """
    The figures on the public programme page.

    Published records only. A count that included drafts would disclose how
    much unpublished work exists and, over time, roughly what it is - which is
    a small leak, but a free one to avoid.
    """
    return {
        "outcomes": len(OrganizationalOutcome.values),
        "programs": Program.objects.filter(publication_status=PUBLISHED).count(),
        "projects": Project.objects.filter(
            publication_status=PUBLISHED, program__publication_status=PUBLISHED
        ).count(),
        "sub_projects": SubProject.objects.filter(
            publication_status=PUBLISHED,
            project__publication_status=PUBLISHED,
            project__program__publication_status=PUBLISHED,
        ).count(),
        "activities": Activity.objects.filter(
            Q(publication_status=PUBLISHED)
            & (
                Q(project__publication_status=PUBLISHED,
                  project__program__publication_status=PUBLISHED)
                | Q(sub_project__publication_status=PUBLISHED,
                    sub_project__project__publication_status=PUBLISHED,
                    sub_project__project__program__publication_status=PUBLISHED)
            )
        ).count(),
        "documents": published_documents().count(),
    }


# ---------------------------------------------------------------------------
# Single records
# ---------------------------------------------------------------------------


def outcome_from_slug(slug):
    outcome = OUTCOME_BY_SLUG.get(slug)
    if outcome is None:
        raise Http404("No such Organizational Outcome.")
    return outcome


def visible(record):
    """
    Whether a visitor may see this record.

    Walks the whole chain to the programme. A published activity under an
    unpublished project is not public, however it was reached.
    """
    node = record
    while node is not None:
        if node.publication_status != PUBLISHED:
            return False
        node = node.parent
    return True


def get_public(model, slug):
    """Fetch a record by slug, or 404 if the public may not see it."""
    try:
        record = model.objects.select_related("responsible_office").get(slug=slug)
    except model.DoesNotExist:
        raise Http404("No such record.")
    if not visible(record):
        # Deliberately the same 404 a missing record gets. A "this exists but
        # is not published" response would confirm that unpublished work by
        # that name exists, which is itself a disclosure.
        raise Http404("No such record.")
    return record


def public_detail_context(record, preview=False):
    """
    Everything a public detail page needs, for any level of the tree.

    `preview` lets an authorised member of staff see the page before it is
    published. It relaxes the publication filter on the record itself and on
    its children, and on nothing else: the documents shown in a preview are
    still only those a reviewer has approved, because a preview that displayed
    a file the public will never receive would be lying about the thing it
    exists to show.
    """
    from .models import Program as ProgramModel

    outcome = record.outcome
    documents = record.documents.filter(status=DocumentStatus.PUBLISHED)
    if preview:
        documents = record.documents.filter(
            status__in=(DocumentStatus.APPROVED, DocumentStatus.PUBLISHED)
        )
    documents = documents.select_related("authority")

    # The gallery is ordered, the document list is not reordered.
    #
    # Pictures come out in the order somebody arranged them on the record's
    # arrange page, because a visitor reads a gallery as a sequence - the
    # ceremony, then the work, then the turnover - and a grid in whatever
    # order a memory card happened to hand over says nothing. The papers below
    # keep the module's own ordering, which is newest first, because a
    # document list is a reference and the newest issuance is the one somebody
    # came for.
    gallery = list(documents.filter(is_image=True).order_by(
        "display_order", "uploaded_at", "pk"
    ))

    # In a preview, a child counts if it has been cleared - not if it merely
    # exists. Showing drafts would promise the reviewer a page the public is
    # never going to get, which defeats the point of previewing it.
    def children_of(manager, published):
        if not preview:
            return list(published)
        return list(
            manager.filter(
                publication_status__in=(
                    PublicationStatus.APPROVED, PublicationStatus.PUBLISHED,
                )
            ).order_by("title")
        )

    # Each list is headed by whatever the record calls it. `public_heading()`
    # falls back to the default wording, so a record that has never been near
    # the heading fields reads exactly as it did before they existed.
    children = []
    if isinstance(record, ProgramModel):
        children.append({
            "label": record.public_heading("projects"),
            "records": children_of(record.projects, published_projects(record)),
        })
    elif isinstance(record, Project):
        children.append({
            "label": record.public_heading("sub_projects"),
            "records": children_of(record.sub_projects,
                                   published_sub_projects(record)),
        })
        children.append({
            "label": record.public_heading("activities"),
            "records": children_of(record.activities,
                                   published_activities(record)),
        })
    elif isinstance(record, SubProject):
        children.append({
            "label": record.public_heading("activities"),
            "records": children_of(record.activities,
                                   published_activities(record)),
        })

    return {
        "record": record,
        "record_level": record.level_label,
        # The prose and gallery headings. Passed as a dict because a Django
        # template cannot call a method with an argument, and a dict keeps the
        # fallback in one place rather than repeating `|default:"About"` in
        # the template where a typo would go unnoticed.
        "headings": {
            "about": record.public_heading("about"),
            "objectives": record.public_heading("objectives"),
            "accomplishment": record.public_heading("accomplishment"),
            "photographs": record.public_heading("photographs"),
        },
        "outcome": OUTCOME_DETAIL.get(outcome) if outcome else None,
        "outcome_label": (
            OrganizationalOutcome(outcome).label if outcome else ""
        ),
        "ancestors": record.ancestors,
        "children": [group for group in children if group["records"]],
        "documents": documents,
        "images": gallery,
        "files": [document for document in documents if not document.is_image],
        "meta_title": record.title,
        "page_title": record.title,
    }
