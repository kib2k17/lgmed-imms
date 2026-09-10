"""
Event notifications, raised from model signals.

Raised here rather than in the views so that a record moved through the Django
admin, a management command or the shell notifies the same people it would
have done through the interface.
"""

from django.db.models.signals import post_save, pre_save

from audit.recording import get_request

from .models import Category, Level
from .service import approvers, notify, resolve

_PREVIOUS_STATUS = "_notify_previous_status"


def acting_user():
    """Whoever is signed in, so we do not notify someone of their own action."""
    request = get_request()
    user = getattr(request, "user", None) if request else None
    return user if user is not None and user.is_authenticated else None


def connect():
    """Wire the handlers. Called from NotificationsConfig.ready()."""
    from reports.models import Report

    pre_save.connect(remember_status, sender=Report, weak=False)
    post_save.connect(report_status_changed, sender=Report, weak=False)

    # Documents are deliberately absent. Every move a document makes goes
    # through `documents.workflow`, which raises the notice for that move
    # alongside the trail entry and the status change. A signal here would
    # raise a second, vaguer notice for the same event and could not say what
    # the move was for.


def remember_status(sender, instance, **kwargs):
    """Stash the stored status so post_save can tell a transition from a save."""
    if instance.pk is None:
        setattr(instance, _PREVIOUS_STATUS, None)
        return
    previous = sender.objects.filter(pk=instance.pk).values_list(
        "status", flat=True
    ).first()
    setattr(instance, _PREVIOUS_STATUS, previous)


def report_status_changed(sender, instance, created, **kwargs):
    from reports.models import ReportStatus

    previous = getattr(instance, _PREVIOUS_STATUS, None)
    if not created and previous == instance.status:
        return

    key = f"report:review:{instance.pk}"

    if instance.status in (ReportStatus.SUBMITTED, ReportStatus.FOR_REVIEW):
        notify(
            approvers(),
            title=f"Report awaiting review: {instance.title}",
            message=f"{instance.get_period_display()} {instance.year}",
            url=instance.get_absolute_url(),
            category=Category.REVIEW,
            level=Level.ACTION,
            dedupe_key=key,
            exclude=acting_user(),
        )
    else:
        # Approved, published or returned: the review is no longer pending.
        resolve(key)

    if instance.status == ReportStatus.RETURNED and instance.created_by:
        notify(
            [instance.created_by],
            title=f"Report returned for revision: {instance.title}",
            message=instance.review_remarks or "See the review remarks on the report.",
            url=instance.get_absolute_url(),
            category=Category.ASSIGNMENT,
            level=Level.ACTION,
            dedupe_key=f"report:returned:{instance.pk}:{instance.updated_at:%Y%m%d%H%M}",
            exclude=acting_user(),
        )
