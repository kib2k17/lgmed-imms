"""
How an action gets into the audit log.

Signals fire deep inside the ORM, where there is no request and therefore no
signed-in user. A context variable set by `AuditMiddleware` carries the current
request down to the signal handlers, so an entry can say who did it and from
where. Anything saved outside a request - a management command, a migration,
the shell - is recorded with no actor rather than being attributed to whoever
happened to be signed in last.
"""

import contextvars

from django.db import models

_current_request = contextvars.ContextVar("lgmed_audit_request", default=None)

# Never written to the log, whatever model they appear on.
REDACTED_FIELDS = {"password"}

# Noise: changed on every save, or already carried by the entry itself.
IGNORED_FIELDS = {"created_at", "updated_at", "updated_by", "last_login"}

MAX_VALUE_LENGTH = 200


def set_request(request):
    return _current_request.set(request)


def reset_request(token):
    _current_request.reset(token)


def get_request():
    return _current_request.get()


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def describe(value):
    """A short, readable rendering of a field value for the log."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value)
    if len(text) > MAX_VALUE_LENGTH:
        return text[: MAX_VALUE_LENGTH - 1] + "…"
    return text


def snapshot(instance):
    """Field values of a model instance, keyed by field name."""
    data = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in REDACTED_FIELDS or name in IGNORED_FIELDS:
            continue
        if isinstance(field, models.ForeignKey):
            data[name] = getattr(instance, f"{name}_id", None)
        else:
            data[name] = getattr(instance, name, None)
    return data


def diff(before, after, instance=None):
    """
    Field-level changes between two snapshots.

    Foreign keys are resolved back to their string form so the log reads
    "Category: Governance -> Fiscal Administration", not "3 -> 5".
    """
    changes = {}
    for name, new_value in after.items():
        old_value = before.get(name)
        if old_value == new_value:
            continue

        label_from, label_to = old_value, new_value
        if instance is not None:
            try:
                field = instance._meta.get_field(name)
            except Exception:
                field = None
            if isinstance(field, models.ForeignKey):
                related = field.remote_field.model
                label_from = _resolve(related, old_value)
                label_to = _resolve(related, new_value)
            elif getattr(field, "choices", None):
                mapping = dict(field.choices)
                label_from = mapping.get(old_value, old_value)
                label_to = mapping.get(new_value, new_value)

        changes[name] = {"from": describe(label_from), "to": describe(label_to)}
    return changes


def _resolve(model, pk):
    if pk in (None, ""):
        return ""
    try:
        return str(model.objects.get(pk=pk))
    except Exception:
        return f"#{pk}"


def record(action, *, target=None, target_label="", detail="", changes=None,
           actor=None, request=None):
    """
    Write one entry. Never raises: a failure to log must not fail the action
    the user was performing, but it must be visible in the server log.
    """
    from .models import AuditEvent

    request = request or get_request()
    if actor is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            actor = candidate

    target_model = ""
    target_id = ""
    target_url = ""
    if target is not None:
        target_model = target._meta.verbose_name.title()
        target_id = str(getattr(target, "pk", "") or "")
        target_label = target_label or str(target)
        getter = getattr(target, "get_absolute_url", None)
        if callable(getter):
            try:
                target_url = getter()
            except Exception:
                target_url = ""

    try:
        return AuditEvent.objects.create(
            actor=actor,
            actor_label=(
                actor.get_display_name() if actor is not None else "System"
            ),
            actor_role=(actor.get_role_display() if actor is not None else ""),
            action=action,
            target_model=target_model,
            target_label=target_label[:255],
            target_id=target_id,
            target_url=target_url[:255],
            changes=changes or {},
            detail=detail[:255],
            ip_address=client_ip(request),
            user_agent=(
                request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""
            ),
            path=(request.path[:255] if request else ""),
        )
    except Exception:  # pragma: no cover - logging must never break a request
        import logging

        logging.getLogger("lgmed.audit").exception(
            "Failed to write audit entry for action %s", action
        )
        return None
