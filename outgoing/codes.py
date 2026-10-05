"""
The LGMED code: the Division's own tracking number for a document it acts on.

    LGMED-13 - RGFJ - 2023-01-03-0001
    |          |      |          |
    region     focal  date the   running number,
               person code was   restarting each
                      issued     year

An incoming document has no LGMED code when it is recorded. One is issued,
once, when the Division Chief assigns the document to a focal person
(`incoming.workflow.assign`), and from then on it is the document's primary
tracking number. When the focal person acknowledges the assignment, the
document moves to Outgoing Monitoring under the same code, and all further
action happens there. The DMS/docket number stays with the document as a
secondary reference.

The running number is shared with the outgoing register, whose rows carry codes
issued by hand before this system existed (written then as "LGMED-13 - (DBA) -
..."), so a code issued here never repeats one already in the register.
"""

import datetime
import re
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ControlCodeCounter, OutgoingDocument

# The date and running number at the end of a code, however it is spaced.
_TAIL = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d+)\s*$")

# Every dash the registers have been typed with: Word turns " - " into an en
# dash, and a code copied from a letter can carry any of the others.
DASHES = "-‐‑‒–—―−"

# A whole code as the office writes it, from the system's own
# "LGMED-13 - JD - 2026-09-29-0001" to the register's
# "LGMED-13 – (DR JRRL) – 2023-1-03-3553" and "LGMED-13-(DBA)-2022-01-17-4001".
# A copy of a communication sent more than once is numbered with a letter:
# "...-1948-A", "...-2537A".
_D = f"[{DASHES}]"
_CODE = re.compile(
    rf"^LGMED\s*{_D}?\s*(?P<region>\d{{1,3}})\s*{_D}\s*"
    rf"(?P<open>\(*)\s*(?P<initials>[A-Za-z][A-Za-z.\s]*?)?\s*(?P<close>\)*)"
    rf"(?P<before_date>\s*{_D}\s*|\s+)"
    rf"(?P<year>\d{{4}})\s*{_D}\s*(?P<month>\d{{1,3}})\s*{_D}\s*(?P<day>\d{{1,3}})"
    rf"(?P<before_number>\s*{_D}\s*|\s+)"
    rf"(?P<number>\d{{1,5}})(?:\s*{_D}?\s*(?P<suffix>[A-Za-z]))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCode:
    region: str
    initials: str
    issued_on: datetime.date | None    # None when the date written is not a date
    year: int
    number: int
    suffix: str
    # Written in a way that is readable but not the office's pattern - a
    # doubled parenthesis, a three-digit day - so worth pointing out.
    irregularities: tuple

    @property
    def canonical(self):
        date = (
            self.issued_on.isoformat() if self.issued_on
            else f"{self.year}-?-?"
        )
        return (
            f"LGMED-{int(self.region)}-{self.initials}-{date}-"
            f"{self.number:04d}{self.suffix}"
        )


def parse(code):
    """A code's parts, or None when the text is not an LGMED code at all."""
    text = " ".join(str(code or "").split())
    match = _CODE.match(text)
    if not match:
        return None
    parts = match.groupdict()
    irregular = []
    if len(parts["open"]) != len(parts["close"]) or len(parts["open"]) > 1:
        irregular.append("parentheses round the initials do not match")
    initials = re.sub(r"[^A-Z]", "", (parts["initials"] or "").upper())
    if not initials:
        irregular.append("no initials")
    if not all(re.search(_D, parts[name]) for name in ("before_date", "before_number")):
        irregular.append("a space where a dash belongs")
    if len(parts["month"]) != 2 or len(parts["day"]) != 2:
        irregular.append("month and day are not written as two digits each")
    year = int(parts["year"])
    try:
        issued_on = datetime.date(year, int(parts["month"]), int(parts["day"]))
    except ValueError:
        issued_on = None
    return ParsedCode(
        region=parts["region"],
        initials=initials,
        issued_on=issued_on,
        year=year,
        number=int(parts["number"]),
        suffix=(parts["suffix"] or "").upper(),
        irregularities=tuple(irregular),
    )


def canonical(code):
    """
    The form two spellings of one code share, for telling duplicates apart.

    Never stored or shown: a code is kept exactly as it was written. Text that
    is not a code at all is folded to upper case without spaces, so a repeated
    stray note is still recognised as repeated.
    """
    parsed = parse(code)
    if parsed is not None:
        return parsed.canonical
    return re.sub(r"\s+", "", str(code or "")).upper()


def format_code(initials, issued_on, number, prefix=None):
    prefix = prefix or settings.LGMED_CODE_PREFIX
    return f"{prefix} - {initials} - {issued_on:%Y-%m-%d}-{number:04d}"


def parse_number(code):
    """The (year, running number) a code carries, or None if it carries none."""
    match = _TAIL.search(code or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(4))


def _highest_in_use(year):
    """The highest running number already written on a code for `year`."""
    from incoming.models import IncomingDocument

    codes = list(
        OutgoingDocument.objects.filter(control_code__contains=f"{year}-")
        .values_list("control_code", flat=True)
    ) + list(
        IncomingDocument.objects.filter(lgmed_code__contains=f"{year}-")
        .values_list("lgmed_code", flat=True)
    )
    numbers = [
        parsed[1]
        for parsed in map(parse_number, codes)
        if parsed and parsed[0] == year
    ]
    return max(numbers, default=0)


@transaction.atomic
def issue_code(assignee, issued_on=None):
    """
    Issue the next LGMED code for a document assigned to `assignee`.

    The year's counter row is locked while the number is taken, so two
    assignments made at the same moment cannot be given the same number.
    """
    issued_on = issued_on or timezone.localdate()
    year = issued_on.year
    ControlCodeCounter.objects.get_or_create(year=year)
    counter = ControlCodeCounter.objects.select_for_update().get(year=year)
    number = max(counter.last_number, _highest_in_use(year)) + 1
    counter.last_number = number
    counter.save(update_fields=["last_number"])
    return format_code(assignee.get_code_initials(), issued_on, number)
