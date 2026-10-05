from django.conf import settings
from django.db import models
from django.urls import reverse


class Action(models.TextChoices):
    CREATE = "CREATE", "Created"
    UPDATE = "UPDATE", "Updated"
    DELETE = "DELETE", "Deleted"
    LOGIN = "LOGIN", "Signed in"
    LOGOUT = "LOGOUT", "Signed out"
    LOGIN_FAILED = "LOGIN_FAILED", "Failed sign-in"
    PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
    ROLE_CHANGE = "ROLE_CHANGE", "Role changed"
    ACTIVATION = "ACTIVATION", "Account activated"
    DEACTIVATION = "DEACTIVATION", "Account deactivated"
    EXPORT = "EXPORT", "Exported records"
    ACCESS_DENIED = "ACCESS_DENIED", "Access denied"

    # Publication workflow. Recorded separately from UPDATE because "who
    # approved this, and who put it on the public website" is a different
    # question from "who edited it", and an auditor asking the first one
    # should not have to read every field diff in the module to answer it.
    UPLOAD = "UPLOAD", "Uploaded a file"
    SCREEN = "SCREEN", "Screened a file"
    SUBMIT = "SUBMIT", "Submitted for review"
    APPROVE = "APPROVE", "Approved"
    REJECT = "REJECT", "Rejected"
    REQUEST_REVISION = "REQUEST_REVISION", "Requested revision"
    PUBLISH = "PUBLISH", "Published"
    UNPUBLISH = "UNPUBLISH", "Unpublished"
    ARCHIVE = "ARCHIVE", "Archived"
    RESTORE = "RESTORE", "Restored from the archive"

    # Two-step verification. Turning it off - by the holder or by an
    # administrator resetting a lost phone - and signing in with a recovery
    # code are the entries an auditor looks for after an account is misused.
    MFA_ENABLED = "MFA_ENABLED", "Two-step verification on"
    MFA_DISABLED = "MFA_DISABLED", "Two-step verification off"
    MFA_CODES_RENEWED = "MFA_CODES_RENEWED", "Renewed recovery codes"
    MFA_RECOVERY_USED = "MFA_RECOVERY_USED", "Used a recovery code"

    # The Data Privacy Act notice shown after every sign-in. Recorded so the
    # office can show that each user agreed to it, and when.
    PRIVACY_ACKNOWLEDGED = "PRIVACY_ACKNOWLEDGED", "Acknowledged the privacy notice"

    # A spreadsheet register brought into a module by Data Sync. One entry per
    # file; the batch it points to lists every row created, updated or skipped.
    SYNC = "SYNC", "Synchronised from a spreadsheet"

    # e-SIRA. A digital signature and the routing of a document for one are
    # the acts an auditor asks about first; e-SIRA keeps its own detailed
    # per-document trail and mirrors these into this log.
    SIGN = "SIGN", "Digitally signed"
    ROUTE = "ROUTE", "Routed for signature/approval"
    COMPLETE = "COMPLETE", "Completed"
    CANCEL = "CANCEL", "Cancelled"


# Actions that warrant a second look when an auditor scans the log.
NOTABLE_ACTIONS = {
    Action.DELETE,
    Action.LOGIN_FAILED,
    Action.PASSWORD_RESET,
    Action.ROLE_CHANGE,
    Action.DEACTIVATION,
    Action.ACCESS_DENIED,
    # Publication is the action that cannot be taken back by editing a row:
    # once a document has been on the public website, it has been seen.
    Action.PUBLISH,
    Action.UNPUBLISH,
    Action.MFA_DISABLED,
    Action.MFA_RECOVERY_USED,
}


class AuditEvent(models.Model):
    """
    One recorded action.

    The log is append-only: there is no edit or delete path in the interface,
    and the model deliberately denormalises the actor's name and the affected
    record's label. An audit trail that says "deleted by NULL" because the
    account was later removed is not an audit trail.
    """

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_label = models.CharField(
        max_length=150,
        help_text="The actor's name as it was at the time of the action.",
    )
    actor_role = models.CharField(max_length=40, blank=True)

    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)

    # What was acted on. Stored as plain text rather than a generic foreign key
    # so the entry survives the record and even the model being removed.
    target_model = models.CharField(max_length=100, blank=True, db_index=True)
    target_label = models.CharField(max_length=255, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_url = models.CharField(max_length=255, blank=True)

    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Field-level before and after values for an update.",
    )
    detail = models.CharField(max_length=255, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    path = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "audit event"
        ordering = ("-timestamp", "-id")
        indexes = [
            models.Index(fields=("action", "-timestamp")),
            models.Index(fields=("target_model", "-timestamp")),
        ]

    def __str__(self):
        target = self.target_label or self.target_model
        return f"{self.actor_label} {self.get_action_display().lower()} {target}".strip()

    def get_absolute_url(self):
        return reverse("audit:detail", args=[self.pk])

    # -- presentation ---------------------------------------------------

    @property
    def is_notable(self):
        return self.action in NOTABLE_ACTIONS

    @property
    def status_tone(self):
        """Maps onto the shared status vocabulary in core/status.py."""
        return {
            Action.CREATE: "active",
            Action.UPDATE: "in_progress",
            Action.DELETE: "rejected",
            Action.LOGIN: "completed",
            Action.LOGOUT: "archived",
            Action.LOGIN_FAILED: "critical",
            Action.PASSWORD_RESET: "pending",
            Action.ROLE_CHANGE: "pending",
            Action.ACTIVATION: "active",
            Action.DEACTIVATION: "critical",
            Action.EXPORT: "in_progress",
            Action.ACCESS_DENIED: "critical",
            Action.UPLOAD: "in_progress",
            Action.SCREEN: "in_progress",
            Action.SUBMIT: "pending",
            Action.APPROVE: "active",
            Action.REJECT: "rejected",
            Action.REQUEST_REVISION: "pending",
            Action.PUBLISH: "completed",
            Action.UNPUBLISH: "critical",
            Action.ARCHIVE: "archived",
            Action.RESTORE: "in_progress",
            Action.MFA_ENABLED: "active",
            Action.MFA_DISABLED: "critical",
            Action.MFA_CODES_RENEWED: "pending",
            Action.MFA_RECOVERY_USED: "pending",
            Action.SIGN: "completed",
            Action.ROUTE: "in_progress",
            Action.COMPLETE: "completed",
            Action.CANCEL: "cancelled",
        }.get(self.action, "archived")

    @property
    def change_list(self):
        """[(field, before, after)] for display in the record page."""
        rows = []
        for field, values in sorted((self.changes or {}).items()):
            if isinstance(values, dict):
                rows.append((
                    field.replace("_", " ").capitalize(),
                    values.get("from", ""),
                    values.get("to", ""),
                ))
        return rows
