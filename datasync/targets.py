"""
Where synced rows go.

A target turns a `ParsedRow` into model field values and writes them. The
engine decides create, update or leave alone; the target knows the model. Each
module keeps its own target beside its models (`incoming/sync.py`,
`outgoing/sync.py`), because what a docket number or a remark means to a
record is that module's business, not the sync's.
"""

from django.utils import timezone

# `IN` lists are sent in chunks so a 20,000-row register does not become one
# 20,000-parameter query.
CHUNK = 500


def chunked(items, size=CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


class SyncTarget:
    model = None
    key_field = ""
    key_max_length = 0
    key_label = "Key"
    # model field -> how the preview names it
    field_labels = {}
    list_url_name = ""

    # -- reading ---------------------------------------------------------

    def existing(self, keys):
        """Records already holding these keys, by upper-cased key."""
        found = {}
        for chunk in chunked({key for key in keys}):
            for instance in self.model.objects.filter(**{f"{self.key_field}__in": chunk}):
                found[getattr(instance, self.key_field).upper()] = instance
        return found

    def prepare(self, row):
        """
        (fields, None) for a usable row, or (None, reason) to skip it.

        `fields` holds every field the sync owns, blank or not; `diff` decides
        which of them an update may touch.
        """
        key = row.key
        if self.key_max_length and len(key) > self.key_max_length:
            return None, (
                f"{self.key_label} is longer than {self.key_max_length} characters"
            )
        return self.fields_for(row), None

    def fields_for(self, row):
        raise NotImplementedError

    def diff(self, instance, fields):
        """
        {field: (stored, incoming)} for what an update would change.

        A blank cell never overwrites a stored value. The register leaves
        columns empty for reasons of its own - HUC/Province stops being filled
        in from April - and a sync should not erase what an officer entered by
        hand because the spreadsheet is silent about it.
        """
        changes = {}
        for name, value in fields.items():
            if value in ("", None):
                continue
            if getattr(instance, name) != value:
                changes[name] = (getattr(instance, name), value)
        return changes

    # -- writing ---------------------------------------------------------

    def create(self, planned, user, batch):
        """Create every planned record. `planned` is a list of PlannedChange."""
        raise NotImplementedError

    def update(self, change, user, batch):
        """
        Apply one planned update.

        Saved one at a time, not in bulk, so the audit log records a field-level
        before-and-after for each record the sync changed.
        """
        instance = change.instance
        for name, (_old, new) in change.changes.items():
            setattr(instance, name, new)
        update_fields = list(change.changes)
        if hasattr(instance, "updated_by_id"):
            instance.updated_by = user
            update_fields.append("updated_by")
        if hasattr(instance, "updated_at"):
            update_fields.append("updated_at")
        instance.save(update_fields=update_fields)
        self.after_update(change, user, batch)
        return instance

    def after_update(self, change, user, batch):
        """Hook: a module's own trail entry for an updated record."""

    # -- helpers -----------------------------------------------------------

    def stamp(self, instance, user):
        if hasattr(instance, "created_by_id"):
            instance.created_by = user
            instance.updated_by = user
        return instance

    def labels(self, names):
        return [self.field_labels.get(name, name.replace("_", " ")) for name in names]

    @staticmethod
    def now():
        return timezone.now()
