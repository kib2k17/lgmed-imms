"""
Automatic recording of record and account activity.

Every operational model is audited by connecting to its save and delete
signals, so a record cannot be changed through a view, the Django admin, a
management command or the shell without leaving a trail. `pre_save` reads the
stored row to produce a real field-level diff - one extra query per update,
which at this system's scale is a fair price for an audit trail an auditor can
actually use.
"""

from django.apps import apps
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Action
from .recording import diff, record, snapshot

# "app_label.ModelName" of everything that leaves a trail.
AUDITED_MODELS = [
    "lgus.LGU",
    "lgus.Province",
    "programs.Program",
    "programs.ProgramCategory",
    "monitoring.MonitoringActivity",
    "monitoring.MonitoringAttachment",
    "incoming.IncomingDocument",
    "incoming.IncomingUpdate",
    "services.FrontlineService",
    "documents.Document",
    "documents.DocumentType",
    # The authority under which documents are destroyed. Audited for the same
    # reason as roles and system settings: it does not hold records itself, it
    # decides what may be done to them.
    "documents.DisposalAuthority",
    "reports.Report",
    "activities.CalendarActivity",
    "announcements.Announcement",
    "updates.ReportingPeriod",
    "updates.DivisionUpdate",
    "updates.UpdateAttachment",
    "updates.PopsPlanUpdate",
    "updates.WayForward",
    # A standing decision about what the public may see, not a record of
    # work - audited for the same reason system settings are.
    "updates.PublicDisclosure",
    "accounts.User",
    "accounts.Section",
    "administration.SystemSetting",
    "administration.PublicSiteContent",
]

# Deliberately absent: `documents.DocumentVersion` and `documents.DocumentEvent`
# are write-once records that exist to be a trail. Auditing them would produce a
# trail of the trail, and every version upload already reaches both logs -
# `DocumentEvent` in the office's words, `Document` as a field-level diff.
# `documents.ControlNumberSequence` is an internal counter that moves on every
# registration; logging it would add a row of noise per document and tell an
# auditor nothing the control number does not already say.

_SNAPSHOT_ATTR = "_audit_snapshot"


def audited_models():
    for label in AUDITED_MODELS:
        try:
            yield apps.get_model(label)
        except LookupError:  # pragma: no cover - guards a mistyped label
            continue


def connect():
    """Wire the signal handlers. Called from AuditConfig.ready()."""
    for model in audited_models():
        pre_save.connect(remember_previous_state, sender=model, weak=False)
        post_save.connect(record_save, sender=model, weak=False)
        post_delete.connect(record_delete, sender=model, weak=False)


# ---------------------------------------------------------------------------
# Record changes
# ---------------------------------------------------------------------------


def remember_previous_state(sender, instance, **kwargs):
    """Stash the stored row so post_save can work out what actually changed."""
    if instance.pk is None:
        setattr(instance, _SNAPSHOT_ATTR, None)
        return
    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        previous = None
    setattr(instance, _SNAPSHOT_ATTR, snapshot(previous) if previous else None)


def record_save(sender, instance, created, **kwargs):
    if created:
        record(Action.CREATE, target=instance)
        return

    before = getattr(instance, _SNAPSHOT_ATTR, None)
    if before is None:
        record(Action.UPDATE, target=instance)
        return

    changes = diff(before, snapshot(instance), instance=instance)
    if not changes:
        return  # a save that changed nothing is not an event

    # An account's role and active flag are significant enough to name.
    if sender._meta.label == "accounts.User":
        if "role" in changes:
            role = changes["role"]
            record(
                Action.ROLE_CHANGE,
                target=instance,
                detail=f"Role changed from {role['from']} to {role['to']}",
                changes=changes,
            )
            return
        if "is_active" in changes:
            became_active = changes["is_active"]["to"] == "Yes"
            record(
                Action.ACTIVATION if became_active else Action.DEACTIVATION,
                target=instance,
                detail=(
                    "Account activated" if became_active else "Account deactivated"
                ),
                changes=changes,
            )
            return

    record(Action.UPDATE, target=instance, changes=changes)


def record_delete(sender, instance, **kwargs):
    record(
        Action.DELETE,
        target=instance,
        target_label=str(instance),
        detail=f"{sender._meta.verbose_name.title()} permanently deleted",
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    record(Action.LOGIN, actor=user, request=request, detail="Signed in")


@receiver(user_logged_out)
def record_logout(sender, request, user, **kwargs):
    if user is not None:
        record(Action.LOGOUT, actor=user, request=request, detail="Signed out")


@receiver(user_login_failed)
def record_login_failed(sender, credentials, request=None, **kwargs):
    """
    A failed sign-in is recorded with the username that was tried, never the
    password - Django already scrubs the credentials, and the password is on
    the redaction list besides.
    """
    username = (credentials or {}).get("username", "")
    record(
        Action.LOGIN_FAILED,
        request=request,
        detail=f"Failed sign-in attempt for '{username}'" if username
        else "Failed sign-in attempt",
    )
