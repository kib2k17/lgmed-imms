"""
The reference lists an administrator maintains.

Program categories, document types and provinces are ordinary lookup tables.
Rather than three near-identical modules, they are described once here and
driven by one set of views - the same reasoning as the shared module layer in
`core.views_base`.
"""

from django import forms

from accounts.models import Section
from core.forms_base import GovModelForm
from documents.forms import DisposalAuthorityForm
from documents.models import DisposalAuthority, DocumentType
from lgus.models import Province
from programs.models import ProgramCategory


class ProgramCategoryForm(GovModelForm):
    class Meta:
        model = ProgramCategory
        fields = ["name", "description", "is_active"]


class DocumentTypeForm(GovModelForm):
    """
    A document type, and the retention period every document of that type
    inherits when it is completed.

    The period lives on the type rather than on each document because that is
    how a records schedule works: the office decides once that memoranda are
    kept for five years.
    """

    class Meta:
        model = DocumentType
        fields = [
            "name", "code", "description", "retention_years",
            "retention_action", "is_active",
        ]

    fieldsets = [
        ("Document Type", ["name", "code", "description"]),
        ("Retention Policy", ["retention_years", "retention_action"]),
        ("Availability", ["is_active"]),
    ]

    def prepare_fields(self):
        # The action at the end of a retention period only means anything once
        # a period has been set, so it is not demanded of an administrator who
        # is simply adding a type. Left blank, the model's own default applies.
        self.fields["retention_action"].required = False

    def clean_retention_action(self):
        from documents.models import RetentionAction

        return self.cleaned_data.get("retention_action") or RetentionAction.REVIEW


class SectionForm(GovModelForm):
    class Meta:
        model = Section
        fields = ["name", "short_name", "is_active"]


class ProvinceForm(GovModelForm):
    class Meta:
        model = Province
        fields = ["name", "capital"]


REFERENCE_LISTS = {
    "program-categories": {
        "model": ProgramCategory,
        "form": ProgramCategoryForm,
        "label": "Program category",
        "plural": "Program categories",
        "icon": "programs",
        "description": "Used to classify programs and projects.",
        "columns": ["Category", "Description", "Programs", "Status"],
        "usage": "programs",
    },
    "document-types": {
        "model": DocumentType,
        "form": DocumentTypeForm,
        "label": "Document type",
        "plural": "Document types",
        "icon": "documents",
        "description": (
            "Used to classify every document in the register, and to set how "
            "long a completed document of each type is kept."
        ),
        "columns": ["Type", "Retention", "Records", "Status"],
        # Two relations, because a document type classifies both the
        # repository and the incoming register. Counting only one would show
        # "0 records" beside a type the database then refuses to let go of.
        "usage": ("documents", "incoming_documents"),
    },
    "sections": {
        "model": Section,
        "form": SectionForm,
        "label": "Department / division / section",
        "plural": "Departments, divisions and sections",
        "icon": "building",
        "description": (
            "The units of the office. Employees belong to one, and the "
            "calendar groups the Division's workload by it."
        ),
        "columns": ["Section", "Abbreviation", "Employees", "Status"],
        "usage": "members",
    },
    "disposal-authorities": {
        "model": DisposalAuthority,
        "form": DisposalAuthorityForm,
        "label": "Disposal authority",
        "plural": "Disposal authorities",
        "icon": "shield",
        "description": (
            "The written authorities under which archived documents may be "
            "permanently disposed of. A disposal must cite one, so an "
            "authority that has been used cannot be removed."
        ),
        "columns": ["Authority", "Approved", "Disposals", "Status"],
        "usage": "disposals",
    },
    "provinces": {
        "model": Province,
        "form": ProvinceForm,
        "label": "Province",
        "plural": "Provinces",
        "icon": "map-pin",
        "description": (
            "The provinces of Region XIII. LGUs are grouped by these, so a "
            "province in use cannot be removed."
        ),
        "columns": ["Province", "Capital", "LGUs"],
        "usage": "lgus",
    },
}


def get_list(slug):
    """The reference list for a URL slug, or None."""
    return REFERENCE_LISTS.get(slug)


def summarise():
    """Every reference list with its rows and usage counts, for the index page."""
    from django.db.models import Count

    summary = []
    for slug, spec in REFERENCE_LISTS.items():
        relations = spec["usage"]
        if isinstance(relations, str):
            relations = (relations,)
        # Counted with distinct=True and summed: a plain Count across two
        # joins multiplies the rows of one by the rows of the other.
        total = None
        for relation in relations:
            term = Count(relation, distinct=True)
            total = term if total is None else total + term
        rows = spec["model"].objects.annotate(usage_count=total)
        summary.append({**spec, "slug": slug, "rows": rows, "count": rows.count()})
    return summary
