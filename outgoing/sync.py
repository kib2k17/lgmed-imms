"""
How the Outgoing register's rows become outgoing documents.

Used by `datasync`, which brings the register in as a one-time migration of
historical records (see `datasync/profiles.py` for the columns read). Every row
is checked before anything is written, and each problem is named with the
column it is in:

- errors keep the row out: no LGMED code, a code not in the office's format or
  with a date that is not a date, no subject, an Excel error value (#REF!) or a
  control character, a value too long for its field;
- warnings let it in, but are listed for a second look: an unrecognised type of
  communication, a DNS number with no incoming document behind it, a running
  number already used by another code, a code written irregularly.

The LGMED code is stored exactly as written - never reissued, never tidied.
The DNS number is kept as the record's incoming reference and matched against
Incoming Monitoring for the preview, but the record is not attached to the
incoming document: that link is made by the workflow when a focal person
acknowledges an assignment, and a historical row joined to it would pull the
incoming document back into that workflow under the wrong code.
"""

import re

from django.utils import timezone

from datasync.targets import SyncTarget, chunked

from . import codes
from .models import OutgoingDocument

_FIELDS = OutgoingDocument._meta

# The types the office's template lists, and the short forms the registers
# use for them. Any name in System Settings > Document types is recognised as
# well, so a type the office uses often can be added there.
COMMUNICATION_TYPES = (
    "Memorandum", "Regional MC", "Message for Transmission", "Advisory", "Letter",
)
TYPE_ALIASES = {
    "MEMO": "Memorandum",
    "RMC": "Regional MC",
    "REGIONALMEMORANDUMCIRCULAR": "Regional MC",
    "MFT": "Message for Transmission",
    "LETTERS": "Letter",
}

# What Excel shows in a cell whose formula failed.
EXCEL_ERRORS = {
    "#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!",
    "#SPILL!", "#CALC!", "#GETTING_DATA",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# "DMS No: " is the template's placeholder; "DMS No: 2026-01-05-119" a label
# written in front of the number.
_REFERENCE_LABEL = re.compile(r"^\s*D[MN]S\s*(?:No|Number)?\.?\s*:?\s*", re.I)
# Written in a DNS column to say there is no incoming document.
NO_REFERENCE = {"NONE", "N/A", "NA", "NIL", "-", "--", "---"}

CODE_FORMAT = "LGMED-13 - INITIALS - YYYY-MM-DD-NNNN"


def _fold(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _limit(name):
    return _FIELDS.get_field(name).max_length


class OutgoingTarget(SyncTarget):
    model = OutgoingDocument
    key_field = "control_code"
    key_label = "LGMED Code"
    key_max_length = _limit("control_code")
    list_url_name = "outgoing:list"
    field_labels = {
        "date_sent": "Date",
        "incoming_reference": "DNS Number (Incoming)",
        "communication_type": "Type of Communication / Documents",
        "subject": "Subject / Title",
        "sent_to": "Sent To",
        "sent_via": "Sent Via",
        "remarks": "Remarks",
        "dms_number": "DNS Number (Outgoing)",
    }

    def __init__(self):
        self.options = {}
        self._codes = {}          # canonical code -> where it is already used
        self._numbers = {}        # (year, number, suffix) -> the code using it
        self._dockets = {}        # upper-cased DNS number -> (pk, docket)
        self._types = {}          # folded type name -> the name it is stored as

    @property
    def strict_types(self):
        return bool(self.options.get("strict_types"))

    # -- what is already stored -----------------------------------------------

    def prefetch(self, rows):
        """Load what every row is checked against, in a few queries."""
        from documents.models import DocumentType
        from incoming.models import IncomingDocument

        self._types = {_fold(name): name for name in COMMUNICATION_TYPES}
        self._types.update(TYPE_ALIASES)
        for name in DocumentType.objects.values_list("name", flat=True):
            self._types.setdefault(_fold(name), name)

        stored = [
            (code, f"already in Outgoing Monitoring as {code}")
            for code in OutgoingDocument.objects.values_list("control_code", flat=True)
        ] + [
            (code, f"already issued to incoming document {docket}")
            for code, docket in IncomingDocument.objects.exclude(
                lgmed_code__isnull=True
            ).values_list("lgmed_code", "docket_number")
        ]
        self._codes, self._numbers = {}, {}
        for code, where in stored:
            self._codes.setdefault(codes.canonical(code), where)
            self._note_number(code)

        references = {
            self.clean_reference(row.values.get("incoming_reference", ""))
            for row in rows
        } - {""}
        self._dockets = {}
        for chunk in chunked(references):
            for pk, docket in IncomingDocument.objects.filter(
                docket_number__in=chunk
            ).values_list("pk", "docket_number"):
                self._dockets[docket.upper()] = (pk, docket)

    def _note_number(self, code):
        parsed = codes.parse(code)
        if parsed is not None:
            self._numbers.setdefault((parsed.year, parsed.number, parsed.suffix), code)
        return parsed

    def find_existing(self, row):
        """Why this row is a duplicate of a stored record, or None."""
        where = self._codes.get(codes.canonical(row.key))
        if where is None:
            return None
        return f"Duplicate {self.key_label} - {where}"

    # -- checking a row ---------------------------------------------------------

    @staticmethod
    def clean_reference(text):
        """A DNS number without its "DMS No:" label; "None" and the like are blank."""
        text = _REFERENCE_LABEL.sub("", text or "").strip()
        return "" if text.upper() in NO_REFERENCE else text

    def prepare(self, row):
        errors, warnings = [], []
        values = row.values
        extra = row.extra

        # The code.
        parsed = codes.parse(row.key)
        date_sent = None
        if len(row.key) > self.key_max_length:
            errors.append(
                f"{self.key_label}: longer than {self.key_max_length} characters"
            )
        elif parsed is None:
            errors.append(
                f"{self.key_label}: {row.key[:80]!r} is not in the LGMED code "
                f"format ({CODE_FORMAT})"
            )
        elif parsed.issued_on is None:
            errors.append(
                f"{self.key_label}: the date written in the code is not a real date"
            )
        else:
            date_sent = parsed.issued_on
            if parsed.issued_on > timezone.localdate():
                warnings.append(f"{self.key_label}: the date in the code is in the future")
            if parsed.irregularities:
                warnings.append(
                    f"{self.key_label}: written irregularly - "
                    + ", ".join(parsed.irregularities)
                )
            other = self._numbers.get((parsed.year, parsed.number, parsed.suffix))
            if other is not None:
                warnings.append(
                    f"{self.key_label}: running number "
                    f"{parsed.number:04d}{parsed.suffix} of {parsed.year} is also on "
                    f"{other}"
                )
            else:
                self._numbers[(parsed.year, parsed.number, parsed.suffix)] = row.key

        # Every cell: nothing Excel failed to calculate, nothing unprintable.
        for name, text in values.items():
            label = self.field_labels.get(name, self.key_label)
            if text.strip().upper() in EXCEL_ERRORS:
                errors.append(f"{label}: holds the Excel error {text.strip()}")
            elif _CONTROL.search(text):
                errors.append(f"{label}: contains a control character")
            elif "�" in text:
                warnings.append(f"{label}: contains a character that could not be read (�)")

        # Required.
        if not values.get("subject"):
            errors.append(f"{self.field_labels['subject']}: Missing")

        # Type of communication.
        written = values.get("communication_type", "")
        label = self.field_labels["communication_type"]
        communication_type = written
        if not written:
            warnings.append(f"{label}: Missing")
        else:
            known = self._types.get(_fold(written))
            if known:
                communication_type = known
                if known != written:
                    extra["type_written"] = written
            elif self.strict_types:
                errors.append(f"{label}: Unknown document type {written[:60]!r}")
            else:
                warnings.append(f"{label}: Unrecognised type {written[:60]!r}, kept as written")
                extra["type_unrecognised"] = True
        extra["type"] = communication_type

        # The incoming document it answers.
        reference = self.clean_reference(values.get("incoming_reference", ""))
        label = self.field_labels["incoming_reference"]
        if reference:
            if row.raw_kinds.get("incoming_reference") in ("date", "number"):
                warnings.append(
                    f"{label}: Excel stored this as a "
                    f"{row.raw_kinds['incoming_reference']}, not text - check it "
                    "reads as written in the register"
                )
            elif not re.search(r"\d", reference):
                warnings.append(f"{label}: {reference[:40]!r} does not look like a DNS number")
            match = self._dockets.get(reference.upper())
            if match:
                extra["incoming"] = {"pk": match[0], "docket": match[1]}
        extra["reference"] = reference

        fields = {
            "date_sent": date_sent or row.date,
            "incoming_reference": reference,
            "communication_type": communication_type,
            "subject": values.get("subject", ""),
            "sent_to": values.get("sent_to", ""),
            "sent_via": values.get("sent_via", ""),
            "remarks": values.get("remarks", ""),
            "dms_number": self.clean_reference(values.get("dms_number", "")),
        }
        # A value cut short is a different value: too long is an error, not a trim.
        for name, value in fields.items():
            limit = _limit(name) if name != "date_sent" else None
            if limit and value and len(value) > limit:
                errors.append(
                    f"{self.field_labels[name]}: longer than {limit} characters "
                    f"({len(value)})"
                )

        row.notes.extend(warnings)
        if errors:
            return None, "; ".join(errors)
        return fields, None

    # -- writing ----------------------------------------------------------------

    def create(self, planned, user, batch):
        documents = [
            self.stamp(
                OutgoingDocument(control_code=change.row.key, **change.fields), user
            )
            for change in planned
        ]
        OutgoingDocument.objects.bulk_create(documents, batch_size=500)

        # MySQL does not hand back the new keys from a bulk insert, so they are
        # found by code - for the result page, and for the Documents register,
        # where every communication belongs.
        from incoming.register import sync_all_outgoing

        created = {}
        for chunk in chunked(change.row.key for change in planned):
            queryset = OutgoingDocument.objects.filter(control_code__in=chunk)
            created.update(queryset.values_list("control_code", "pk"))
            sync_all_outgoing(queryset)
        return created

    def after_update(self, change, user, batch):
        from incoming.register import sync_outgoing

        sync_outgoing(change.instance, user)
