"""
Programs, Projects and Activities - what the Division delivers, and what the
public is allowed to read about it.

Two ideas hold this module together.

**The work is a tree.** Every programme the Division runs answers to one of the
Department's five Organizational Outcomes; a programme is delivered through
projects, a project through sub-projects, and the visible unit of work at the
bottom of all of it is an activity. Recording it that way is not filing for its
own sake: it is the only way a regional office can say what an Outcome actually
amounted to on the ground this year.

**Nothing is public until a person says so.** The records here describe public
work, but the papers behind them - attendance sheets, validation reports,
letters - routinely carry names, addresses, government ID numbers and
signatures. So an uploaded file is internal, always, and stays internal in a
directory no web server maps to a URL. It reaches the public website only after
an automated screening has been read by an authorised reviewer, that reviewer
has approved it, and a publisher has created a *separate public copy* of it.

The automated screening is a screening, not a decision. A clean result means
nothing was found, which is not the same as nothing being there, and the code
below never treats it as an approval.
"""

# The module is a package of four parts; every name is re-exported here, so
# `from programs.models import X` - and the upload_to paths the migrations
# name, such as programs.models.internal_document_path - keep working.

from .vocabulary import (  # noqa: F401
    ALLOWED_EXTENSIONS,
    AWAITING_RELEASE_STATUSES,
    DOCUMENT_EXTENSIONS,
    DocumentKind,
    DocumentStatus,
    EDITABLE_WITHOUT_REREVIEW,
    IMAGE_EXTENSIONS,
    ImplementationStatus,
    MAX_UPLOAD_BYTES,
    OPEN_STATUSES,
    OUTCOME_BY_SLUG,
    OUTCOME_DETAIL,
    OrganizationalOutcome,
    ProgramCategory,
    ProgramStatus,
    PublicationStatus,
    RELEASABLE_STATUSES,
    REVIEWABLE_STATUSES,
    RiskLevel,
    SUBMITTABLE_STATUSES,
    outcome_detail,
)
from .records import (  # noqa: F401
    Activity,
    PPAQuerySet,
    PPARecord,
    PPA_MODELS,
    PPA_MODEL_BY_KEY,
    PUBLIC_HEADING_DEFAULTS,
    Program,
    Project,
    SubProject,
    heading_field,
)
from .authority import (  # noqa: F401
    PublicationAuthority,
    authority_path,
)
from .documents import (  # noqa: F401
    SupportingDocument,
    SupportingDocumentQuerySet,
    internal_document_path,
    public_document_path,
)
