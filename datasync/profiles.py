"""
What each module's spreadsheet looks like, and where its rows go.

This is the one place to edit when a register's layout changes. A profile
names the columns the sync reads - by every header the office has been known
to write for them - and leaves every other column alone. Header text is
compared with case, spaces and punctuation ignored, first exactly and then as a
prefix, so `Assigned Focal/Rmearks` is found by the alias `Assigned Focal`.

To teach a profile a new header, add it to that column's `aliases`; the first
alias is the header the office's template is expected to use, and a column
found under any other alias is pointed out in the preview. To sync a new
module, add a profile here and a target class beside the module's models (see
`incoming/sync.py`).

A profile runs in one of two modes. "sync" keeps a module in step with a
register kept alongside it: a known key is updated. "migrate" brings historical
records in once: a known key is a duplicate and is left alone, every row gets a
status the person can page through, and the rows not imported can be
downloaded with their reasons (see `outgoing/sync.py`).
"""

from dataclasses import dataclass
from functools import cached_property

from django.utils.module_loading import import_string

from .reader import normalise_header


@dataclass(frozen=True)
class Column:
    name: str                          # the key the target reads the value by
    label: str                         # how the preview and summary name it
    aliases: tuple                     # header texts this column has appeared under
    multiline: bool = False            # keep line breaks (remarks), else collapse
    blank_header_fallback: bool = False
    append_unlabelled: bool = False    # fold following blank-header columns in

    @cached_property
    def normalised_aliases(self):
        return tuple(normalise_header(alias) for alias in self.aliases)


@dataclass(frozen=True)
class SyncProfile:
    key: str
    label: str
    description: str
    target: str                        # dotted path to the SyncTarget class
    capability: str                    # user capability needed to commit a sync
    columns: tuple
    key_column: str
    date_column: str | None = None
    # Where text found in the date column is kept, so a note written there by
    # mistake is not lost.
    remarks_column: str | None = None
    date_required: bool = False
    carry_date_forward: bool = False   # blank date = the date of the row above
    date_from_key: str | None = None   # regex with (year)(month)(day) groups
    ignore_key_pattern: str | None = None
    header_scan_rows: int = 1          # how far down to look for the header row
    min_header_matches: int = 2        # named fields a row needs to be the header
    mode: str = "sync"                 # sync | migrate - see the module docstring
    # Columns a sheet must have, besides the key, for its rows to be read.
    required_columns: tuple = ()
    # Dotted path to a function that folds a key for duplicate detection, so
    # two spellings of one key are recognised as the same. Default: upper case.
    key_normaliser: str | None = None
    # Fold what a repeated key adds into its first row (the Incoming register
    # repeats a docket with a newer remark) rather than just reporting it.
    merge_duplicates: bool = True

    @property
    def is_migration(self):
        return self.mode == "migrate"

    def column(self, name):
        return next(column for column in self.columns if column.name == name)

    def get_key_normaliser(self):
        if self.key_normaliser:
            return import_string(self.key_normaliser)
        return str.upper

    def get_target(self):
        return import_string(self.target)()


INCOMING = SyncProfile(
    key="incoming",
    label="Incoming",
    description="The Incoming Monitoring register - one sheet per month.",
    target="incoming.sync.IncomingTarget",
    capability="can_review_incoming",
    key_column="docket_number",
    date_column="date",
    remarks_column="remarks",
    date_required=True,
    # The date is written on the first entry of each day only.
    carry_date_forward=True,
    # "Read column headers from row 1."
    header_scan_rows=1,
    columns=(
        # Blank in January and from June onward; found by position then.
        Column("date", "Date", ("Date", "Date Received"), blank_header_fallback=True),
        # January to March only. Blank from April.
        Column("source", "HUC/Province", ("HUC/Province", "HUC", "Province",
                                          "Source/Office", "Source")),
        Column("docket_number", "Docket Number", ("Docket Number", "Docket No",
                                                  "Docket", "DNS Number",
                                                  "DNS No", "DNS")),
        # "Subject" to March, "Description" from April.
        Column("subject", "Subject", ("Subject", "Description")),
        # "Assigned Focal/Remarks" to March, "Concern Person" from April. Some
        # early rows carry a second, unlabelled remark in the next column.
        Column("remarks", "Assigned Focal/Remarks",
               ("Assigned Focal/Remarks", "Assigned Focal", "Concern Person",
                "Remarks"),
               multiline=True, append_unlabelled=True),
    ),
)


OUTGOING = SyncProfile(
    key="outgoing",
    label="Outgoing",
    description="The Outgoing Monitoring register - one sheet per year.",
    target="outgoing.sync.OutgoingTarget",
    capability="can_encode",
    key_column="control_code",
    # Historical records are brought in once. The LGMED code already written
    # on each row is kept as written; one already in the system is a duplicate,
    # never overwritten and never issued again.
    mode="migrate",
    required_columns=("subject",),
    # "LGMED-13 - (DBA) - 2026-01-05-0001" and "LGMED-13-DBA-2026-01-05-0001"
    # are one code: dashes, spaces and parentheses are not what tells codes apart.
    key_normaliser="outgoing.codes.canonical",
    merge_duplicates=False,
    # The register has no date column: each control code carries its date,
    # as in "LGMED-13 - (DBA) - 2026-01-05-0001".
    date_from_key=r"(\d{4})-(\d{1,2})-(\d{1,2})-\d+",
    # Every sheet repeats the template's example row under its header.
    ignore_key_pattern=r"^\s*sample",
    # Older sheets put a title block above the header, which is on row 3.
    header_scan_rows=6,
    min_header_matches=3,
    # The first alias of each column is the header the migration template
    # uses; the others are what the yearly registers have been written with.
    columns=(
        # The 2026 sheet left this header cell blank.
        Column("control_code", "LGMED Code", ("LGMED CODE",
                                              "Control Code", "Control No",
                                              "Control Number"),
               blank_header_fallback=True),
        Column("incoming_reference", "DNS Number (Incoming)",
               ("DNS NUMBER (INCOMING)", "DNS No (Incoming)",
                "DMS Number (Incoming)", "DMS No (Incoming)")),
        Column("communication_type", "Type of Communication / Documents",
               ("TYPE OF COMMUNICATION/ DOCUMENTS", "Type of Communication",
                "Type of Document", "Type")),
        Column("subject", "Subject / Title", ("Subject/ Title", "Subject", "Title",
                                              "Description")),
        Column("sent_to", "Sent To", ("Sent to", "Recipient", "Addressee")),
        Column("sent_via", "Sent Via", ("Sent Via", "Mode of Transmittal")),
        # Not in the migration template, but kept when a register has them.
        Column("remarks", "Remarks", ("Remarks",), multiline=True),
        Column("dms_number", "DNS Number (Outgoing)",
               ("DNS NUMBER (OUTGOING)", "DNS No (Outgoing)",
                "DMS Number (Outgoing)", "DMS No (Outgoing)")),
    ),
)


PROFILES = {profile.key: profile for profile in (INCOMING, OUTGOING)}


def get_profile(key):
    return PROFILES[key]


def choices():
    return [(profile.key, profile.label) for profile in PROFILES.values()]
