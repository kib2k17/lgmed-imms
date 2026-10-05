"""
Deciding what a workbook would change, and then changing it.

`build_plan` reads the workbook and compares every row with what is stored,
keyed on the profile's key column: an unknown key is a create, a known key
whose values differ is an update, and a known key whose values match is left
alone. Nothing is written. `commit` builds the plan again - so it acts on the
database as it is at that moment, not as it was when the preview was drawn -
and applies it in one transaction: either the whole file is synced or none of
it is.

A profile in "migrate" mode is planned differently (`_plan_migration`): a
known key is a duplicate and is left alone, the target checks every row and
names each problem, and each row's outcome is kept as a `SyncRow`.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from .reader import SkippedRow, read_workbook

# How many created and updated rows a summary lists by name. The counts are
# always complete; a 20,000-row first sync does not need 20,000 rows on screen.
LIST_LIMIT = 500


class AlreadyCommitted(Exception):
    """The batch was committed or discarded after the preview was drawn."""


@dataclass
class PlannedChange:
    kind: str                     # create | update | unchanged
    row: object                   # reader.ParsedRow
    fields: dict
    instance: object = None
    changes: dict = field(default_factory=dict)   # field -> (stored, incoming)


@dataclass
class Plan:
    profile: object
    target: object
    read: object                  # reader.ReadResult
    creates: list
    updates: list
    unchanged: list
    skipped: list

    @property
    def is_migration(self):
        return self.profile.is_migration

    @property
    def flagged(self):
        if self.is_migration:
            return [change.row for change in self.creates if change.row.notes]
        return self.read.flagged

    def _skipped(self, kind):
        return sum(1 for row in self.skipped if row.kind == kind)

    @property
    def counts(self):
        counts = {
            "created": len(self.creates),
            "updated": len(self.updates),
            "unchanged": len(self.unchanged),
            "skipped": len(self.skipped),
            "flagged": len(self.flagged),
            "blank": sum(sheet.blank for sheet in self.read.sheets),
            "duplicates": self._skipped("duplicate"),
            "errors": self._skipped("error"),
            "ignored": self._skipped("ignored"),
        }
        # Every row that is a record: imported, or left out as a duplicate or
        # an error. The template's sample rows and blank rows are not records.
        counts["total"] = counts["created"] + counts["duplicates"] + counts["errors"]
        return counts

    def summary(self):
        """Everything the preview and result pages show, as plain JSON."""
        if self.is_migration:
            return self._migration_summary()
        target = self.target

        def show(value):
            return value.strftime("%d %b %Y") if hasattr(value, "strftime") else (
                "" if value is None else str(value)
            )

        return {
            "counts": self.counts,
            "key_label": target.key_label,
            "sheets": [sheet.as_dict() for sheet in self.read.sheets],
            "skipped": [row.as_dict() for row in self.skipped],
            "flagged": [
                {"sheet": row.sheet, "row": row.row, "key": row.key,
                 "notes": row.notes}
                for row in self.read.flagged
            ],
            "created": [
                {"sheet": change.row.sheet, "row": change.row.row,
                 "key": change.row.key, "date": show(change.row.date),
                 "subject": change.row.values.get("subject", "")[:160]}
                for change in self.creates[:LIST_LIMIT]
            ],
            "updated": [
                {"sheet": change.row.sheet, "row": change.row.row,
                 "key": change.row.key,
                 "changes": [
                     {"field": target.field_labels.get(name, name),
                      "from": show(old)[:200], "to": show(new)[:200]}
                     for name, (old, new) in change.changes.items()
                 ]}
                for change in self.updates[:LIST_LIMIT]
            ],
            "list_limit": LIST_LIMIT,
        }

    def _migration_summary(self):
        """
        Counts and file-level findings. The rows themselves are `SyncRow`s, so
        a register of 20,000 rows is not carried in one JSON field.
        """
        types = {}
        references = matched = 0
        for change in self.creates:
            extra = change.row.extra
            name = change.fields.get("communication_type") or ""
            entry = types.setdefault(name, {
                "name": name, "count": 0,
                "recognised": bool(name) and not extra.get("type_unrecognised"),
            })
            entry["count"] += 1
            if extra.get("reference"):
                references += 1
                matched += bool(extra.get("incoming"))
        return {
            "mode": "migrate",
            "counts": self.counts,
            "key_label": self.target.key_label,
            "sheets": [sheet.as_dict() for sheet in self.read.sheets],
            "types": sorted(types.values(), key=lambda t: (-t["count"], t["name"])),
            "references": {"total": references, "matched": matched},
            "options": dict(self.target.options),
        }

    def row_records(self, created=None):
        """
        Every row as an unsaved `SyncRow`, in workbook order.

        `created` maps each imported code to its new record's key; when it is
        given, the valid rows are marked imported.
        """
        from .models import RowStatus, SyncRow

        order = {name: index for index, name in enumerate(self.read.sheet_names)}
        records = []
        for change in self.creates:
            row = change.row
            status = RowStatus.WARNING if row.notes else RowStatus.VALID
            record_id = None
            if created is not None:
                status = RowStatus.IMPORTED
                record_id = created.get(row.key)
            records.append(SyncRow(
                sheet=row.sheet[:100], row_number=row.row, status=status,
                key=row.key[:255], values=_display(row.values, row.extra),
                messages=list(row.notes), record_id=record_id,
            ))
        kinds = {"duplicate": RowStatus.DUPLICATE, "ignored": RowStatus.IGNORED}
        for row in self.skipped:
            records.append(SyncRow(
                sheet=row.sheet[:100], row_number=row.row,
                status=kinds.get(row.kind, RowStatus.ERROR),
                key=row.key[:255], values=_display(row.values, {}),
                messages=row.reason.split("; "),
            ))
        records.sort(key=lambda record: (order.get(record.sheet, 0), record.row_number))
        return records


def _display(values, extra):
    """What the preview table shows of a row: its cells, and what was found."""
    shown = {name: text[:1000] for name, text in values.items()}
    shown.update(extra)
    return shown


def build_plan(profile, source, sheets=None, options=None):
    """Read `source` (a path or file) against `profile` and plan every row."""
    read = read_workbook(source, profile, sheets=set(sheets) if sheets else None)
    target = profile.get_target()
    target.options = dict(options or {})
    if profile.is_migration:
        return _plan_migration(profile, target, read)
    existing = target.existing(row.key for row in read.rows)

    creates, updates, unchanged = [], [], []
    skipped = list(read.skipped)
    for row in read.rows:
        fields, problem = target.prepare(row)
        if problem:
            skipped.append(SkippedRow(row.sheet, row.row, row.key, problem))
            continue
        instance = existing.get(row.key.upper())
        if instance is None:
            creates.append(PlannedChange("create", row, fields))
            continue
        changes = target.diff(instance, fields)
        bucket = updates if changes else unchanged
        bucket.append(
            PlannedChange("update" if changes else "unchanged", row, fields,
                          instance, changes)
        )
    skipped.sort(key=lambda row: (read.sheet_names.index(row.sheet), row.row))
    return Plan(profile, target, read, creates, updates, unchanged, skipped)


def _plan_migration(profile, target, read):
    """
    Insert-only: a new key is imported; a known one is a duplicate, left alone.

    Duplicates are looked for first - a row already in the system is reported
    as already there, whatever else might be wrong with it - and the target
    then checks what is left.
    """
    target.prefetch(read.rows)
    creates = []
    skipped = list(read.skipped)
    for row in read.rows:
        duplicate = target.find_existing(row)
        if duplicate:
            skipped.append(SkippedRow(row.sheet, row.row, row.key, duplicate,
                                      "duplicate", row.values))
            continue
        fields, problem = target.prepare(row)
        if problem:
            skipped.append(SkippedRow(row.sheet, row.row, row.key, problem,
                                      "error", row.values))
            continue
        creates.append(PlannedChange("create", row, fields))
    skipped.sort(key=lambda row: (read.sheet_names.index(row.sheet), row.row))
    return Plan(profile, target, read, creates, [], [], skipped)


def _plan(batch):
    return build_plan(batch.profile, batch.file.path, batch.sheets, batch.options)


def _write_rows(batch, plan, created=None):
    from .models import SyncRow

    batch.rows.all().delete()
    records = plan.row_records(created)
    for record in records:
        record.batch = batch
    SyncRow.objects.bulk_create(records, batch_size=1000)


def preview(batch):
    """Plan the batch's file and keep the result on the batch."""
    plan = _plan(batch)
    batch.summary = plan.summary()
    with transaction.atomic():
        batch.save(update_fields=["summary"])
        if plan.is_migration:
            _write_rows(batch, plan)
    return plan


@transaction.atomic
def commit(batch, user):
    """Apply the batch's file. All of it, or - if anything fails - none of it."""
    from audit.models import Action
    from audit.recording import record

    from .models import BatchStatus, SyncBatch

    # Locked, so a double-clicked Commit cannot apply the same file twice.
    locked = SyncBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status != BatchStatus.PREVIEW:
        raise AlreadyCommitted(batch)

    plan = _plan(batch)
    created = plan.target.create(plan.creates, user, batch)
    for change in plan.updates:
        plan.target.update(change, user, batch)

    batch.summary = plan.summary()
    batch.status = BatchStatus.COMMITTED
    batch.committed_by = user
    batch.committed_at = timezone.now()
    batch.save(update_fields=["summary", "status", "committed_by", "committed_at"])

    counts = plan.counts
    if plan.is_migration:
        _write_rows(batch, plan, created if isinstance(created, dict) else {})
        record(
            Action.SYNC,
            target=batch,
            actor=user,
            detail=(
                f"Migrated {batch.original_name} into {batch.profile.label}: "
                f"{counts['created']} imported, {counts['duplicates']} duplicates "
                f"skipped, {counts['errors']} errors skipped "
                f"(of {counts['total']} records)"
            ),
            changes={
                name: {"from": "", "to": str(value)}
                for name, value in (
                    ("file_name", batch.original_name),
                    ("records_in_file", counts["total"]),
                    ("imported", counts["created"]),
                    ("duplicates_skipped", counts["duplicates"]),
                    ("errors_skipped", counts["errors"]),
                )
            },
        )
        return plan

    # One entry for the whole file. Updates have each left a field-level
    # entry of their own; creates are listed, with sheet and row, on the batch.
    record(
        Action.SYNC,
        target=batch,
        actor=user,
        detail=(
            f"Synced {batch.original_name} into {batch.profile.label}: "
            f"{counts['created']} created, {counts['updated']} updated, "
            f"{counts['skipped']} skipped"
        ),
    )
    return plan
