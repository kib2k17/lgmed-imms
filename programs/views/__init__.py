"""
The PPA workbench.

Four levels of record, one publication workflow, and a set of views that are
deliberately generic across the levels: a project and a sub-project differ in
what they mean to the office, not in how they are created, reviewed or
published, and writing the same six views four times would guarantee that the
copy governing sub-projects eventually forgets a permission check the copy
governing projects has.

The level is therefore a URL segment - `program`, `project`, `sub-project`,
`activity` - resolved through `LEVELS` below. An unknown level is a 404, not a
default, so a mistyped URL cannot land on the wrong model.

Every view that changes anything declares the capability it needs through the
mixins in `core.mixins`. The three that matter here are separate on purpose:
encoding, reviewing and publishing are three different decisions, taken by
three different people.
"""

# A package of five parts; every name is re-exported here, so programs/urls.py
# and anything importing from programs.views keep working unchanged.

from .common import (  # noqa: F401
    LEVELS,
    LEVEL_FOR_MODEL,
    PPAContextMixin,
    RecordViewMixin,
    WORKFLOW_HELP,
    WORKFLOW_PATH,
    level_of,
    level_spec,
    record_breadcrumbs,
    record_trail,
    record_url,
    workflow_states,
)
from .workbench import (  # noqa: F401
    ReviewQueueView,
    WorkbenchView,
)
from .records import (  # noqa: F401
    RecordActionMixin,
    RecordArchiveView,
    RecordCreateView,
    RecordDecisionView,
    RecordDeleteView,
    RecordDetailView,
    RecordPreviewView,
    RecordPublishView,
    RecordRestoreView,
    RecordSubmitView,
    RecordUnpublishView,
    RecordUpdateView,
)
from .documents import (  # noqa: F401
    DocumentDeleteView,
    DocumentDownloadView,
    DocumentRescreenView,
    DocumentReviewView,
    DocumentUploadView,
    PhotoArrangeView,
)
from .authority import (  # noqa: F401
    AuthorityCreateView,
    AuthorityDetailView,
    AuthorityFileView,
    AuthorityFormMixin,
    AuthorityListView,
    AuthorityUpdateView,
    DocumentAuthorityView,
    DocumentPublishView,
    DocumentWithdrawView,
)
