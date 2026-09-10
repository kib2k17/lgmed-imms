"""
The permission model, stated once in a form both the code and the interface use.

Roles are defined here rather than edited at runtime. They gate server-side
checks, so making them editable in the interface would mean an administrator
could silently widen access without any change passing review. What the
interface offers instead is this matrix: an honest, readable statement of what
each role may do, generated from the same properties the views enforce.
"""

from django.db.models import Count

from .models import Role, User

# (attribute on the user model, label, what it actually permits)
CAPABILITIES = [
    (
        "can_view",
        "View records",
        "Open every module and read the records it holds.",
    ),
    (
        "can_encode",
        "Encode and edit",
        "Create and change programs, monitoring records, documents and reports.",
    ),
    (
        "can_approve",
        "Approve and publish",
        "Move reports and documents to approved or published, and publish to "
        "the public website.",
    ),
    (
        "can_review_incoming",
        "Review and assign incoming documents",
        "Review an incoming document, note what it requires and assign the "
        "focal person who will act on it.",
    ),
    (
        "can_supervise",
        "Monitor employee activities",
        "Read every employee's calendar activities, and group the Division's "
        "workload by employee or by section.",
    ),
    (
        "can_manage_any_activity",
        "Change another employee's activity",
        "Edit or delete a calendar activity that belongs to someone else. "
        "Everyone else, the Chief included, may only read it.",
    ),
    (
        "can_assign_documents",
        "Assign documents to a focal person",
        "Name the personnel responsible for processing a registered document, "
        "and reassign it when the work moves.",
    ),
    (
        "can_archive_documents",
        "Archive and restore documents",
        "Move a completed document into the archive under its retention "
        "period, and restore an archived document when it is needed again.",
    ),
    (
        "can_dispose_documents",
        "Authorise document disposal",
        "Permanently dispose of an archived document that has reached the end "
        "of its retention period, against a recorded written authority.",
    ),
    (
        "can_delete",
        "Delete records",
        "Permanently remove a record. Always confirmed, always logged.",
    ),
    (
        "can_administer",
        "Administer the system",
        "Manage accounts and roles, change system settings, read the audit log.",
    ),
]

ROLE_DESCRIPTIONS = {
    Role.SUPERADMIN: (
        "Full access, including the Django administration. Reserved for ICT "
        "personnel responsible for the system itself."
    ),
    Role.ADMIN: (
        "Full access to the system's records and to account administration, "
        "the only role that may review an incoming document and assign its "
        "focal person, the role that assigns and disposes of documents in the "
        "Document Management module, and the role that monitors the calendar "
        "of every employee. Intended for the Division Chief and designated "
        "administrators. Reads every activity; does not rewrite the ones "
        "employees keep for themselves."
    ),
    Role.LGMED_STAFF: (
        "Encodes and edits records, and approves reports and documents for "
        "publication. Archives completed documents and restores them under "
        "the retention policy. Cannot assign a document's focal person, "
        "authorise disposal, administer accounts or delete records."
    ),
    Role.ENCODER: (
        "Encodes and edits records, including recording incoming documents "
        "and acting on those assigned to them. Cannot review or assign "
        "incoming documents, approve, publish, delete, or administer accounts."
    ),
    Role.VIEWER: (
        "Read-only access to the modules. Intended for personnel who consult "
        "records but do not maintain them."
    ),
}


def users_with(attribute):
    """
    The active accounts whose role grants a named capability.

    Audiences are worked out from the capability properties themselves rather
    than from a hand-written list of roles, so a role that gains a capability
    gains the audience with it and the two cannot drift apart.
    """
    from django.db.models import Q

    roles = [
        value
        for value, _label in Role.choices
        if getattr(User(role=value), attribute, False)
    ]
    return User.objects.filter(is_active=True).filter(
        Q(role__in=roles) | Q(is_superuser=True)
    ).distinct()


def role_matrix():
    """Every role with its capabilities and the number of accounts holding it."""
    counts = dict(
        User.objects.values_list("role")
        .annotate(total=Count("pk"))
        .values_list("role", "total")
    )
    active_counts = dict(
        User.objects.filter(is_active=True)
        .values_list("role")
        .annotate(total=Count("pk"))
        .values_list("role", "total")
    )

    rows = []
    for value, label in Role.choices:
        probe = User(role=value)
        rows.append(
            {
                "value": value,
                "label": label,
                "description": ROLE_DESCRIPTIONS.get(value, ""),
                "count": counts.get(value, 0),
                "active_count": active_counts.get(value, 0),
                "capabilities": [
                    {
                        "attribute": attribute,
                        "label": capability_label,
                        "granted": bool(getattr(probe, attribute, False)),
                    }
                    for attribute, capability_label, _ in CAPABILITIES
                ],
            }
        )
    return rows
