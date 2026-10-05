"""
Which sidebar modules each role and each account is offered.

Stored in `RoleModuleAccess` and `UserModuleAccess`, so the System Administrator changes it from the
Menu Permissions page rather than in code. Two rules decide a module:

  1. an account's own rule, if it has one;
  2. otherwise its role's rule, if there is one;
  3. otherwise the module is open.

This can only narrow access. A module also needs the capability its sidebar
entry `requires` (core/navigation.py), and the views keep checking that
capability, so opening PPA Review Queue to Viewers here does not let a Viewer
review anything.

The same answer is used twice: by the sidebar, to leave a closed module out,
and by `ModuleAccessMiddleware`, to refuse its URLs. Hiding the link alone
would leave the module one typed address away.
"""

from .models import Role, RoleModuleAccess, UserModuleAccess

# The modules the System Administrator may open or close, in sidebar order.
# Administration (Users & Roles, System Settings, Audit Logs) and the Public
# Website page are deliberately absent: they are already limited to the roles
# that run the system, and closing them from here is how an office locks
# itself out of the page that would reopen them.
MANAGED_MODULES = (
    "dashboard",
    "programs",
    "ppa_queue",
    "ppa_authorities",
    "monitoring",
    "incoming",
    "outgoing",
    "datasync",
    "lgus",
    "services",
    "updates",
    "announcements",
    "documents",
    "analytics",
    "reports",
    "calendar",
    "activity_monitor",
    "esira",
)

_CACHE_ATTR = "_module_access_states"


def nav_items():
    """Every sidebar entry, flattened. Imported late: navigation imports us."""
    from core.navigation import NAV_SECTIONS

    return [item for section in NAV_SECTIONS for item in section["items"]]


def managed_items():
    """The managed modules' sidebar entries, in sidebar order."""
    by_key = {item["key"]: item for item in nav_items()}
    return [by_key[key] for key in MANAGED_MODULES if key in by_key]


def is_exempt(user):
    """The System Administrator always sees every module."""
    return bool(getattr(user, "is_superadmin", False))


def role_grants(role, item):
    """Whether a role's capabilities cover the module at all."""
    from .models import User

    requires = item.get("requires")
    return not requires or bool(getattr(User(role=role), requires, False))


def _states(user):
    """
    {module: allowed} for the modules this account has a rule for.

    Worked out once per request and kept on the user object, because the
    sidebar and the middleware both ask, item by item.
    """
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    states = dict(
        RoleModuleAccess.objects.filter(role=user.role)
        .values_list("module", "allowed")
    )
    states.update(
        UserModuleAccess.objects.filter(user=user)
        .values_list("module", "allowed")
    )
    setattr(user, _CACHE_ATTR, states)
    return states


def forget(user):
    """Drop the cached answer after the rules for this account changed."""
    if hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def can_access_module(user, key):
    """Whether the Menu Permissions rules leave this module open to `user`."""
    if key not in MANAGED_MODULES:
        return True
    if user is None or not user.is_authenticated:
        # Signing in is the views' business; a stored rule is not consulted.
        return True
    if is_exempt(user):
        return True
    return _states(user).get(key, True)


def module_for(resolver_match):
    """The managed module a resolved URL belongs to, or None."""
    if resolver_match is None:
        return None
    from core.navigation import _resolve_match

    item = _resolve_match(
        nav_items(), resolver_match.namespace, resolver_match.view_name
    )
    if item is None or item["key"] not in MANAGED_MODULES:
        return None
    return item["key"]


# ---------------------------------------------------------------------------
# The management page
# ---------------------------------------------------------------------------

def managed_roles():
    """Every role except the System Administrator, who is never restricted."""
    return [(value, label) for value, label in Role.choices
            if value != Role.SUPERADMIN]


def role_matrix():
    """Rows for the role page: each module with its state for every role."""
    stored = {
        (module, role): allowed
        for module, role, allowed in RoleModuleAccess.objects.values_list(
            "module", "role", "allowed"
        )
    }
    rows = []
    for item in managed_items():
        cells = []
        for value, label in managed_roles():
            grantable = role_grants(value, item)
            cells.append({
                "role": value,
                "role_label": label,
                "grantable": grantable,
                "allowed": stored.get((item["key"], value), True),
            })
        rows.append({"item": item, "cells": cells})
    return rows


def save_role_matrix(enabled, actor):
    """
    Store the role page's ticks. `enabled` is a set of (module, role) pairs.

    Only a closed module is worth a row - open is the default - but a row is
    kept rather than deleted when a module is reopened, so the page records
    who last touched it. Returns the list of changes, for the audit log.
    """
    stored = {
        (row.module, row.role): row
        for row in RoleModuleAccess.objects.all()
    }
    changes = []
    for item in managed_items():
        for value, label in managed_roles():
            if not role_grants(value, item):
                continue  # the checkbox is not offered; nothing to change
            key = (item["key"], value)
            allowed = key in enabled
            row = stored.get(key)
            if row is None:
                if allowed:
                    continue
                RoleModuleAccess.objects.create(
                    module=item["key"], role=value, allowed=False,
                    updated_by=actor,
                )
            elif row.allowed != allowed:
                row.allowed = allowed
                row.updated_by = actor
                row.save(update_fields=["allowed", "updated_by", "updated_at"])
            else:
                continue
            changes.append(
                f"{item['label']} {'opened' if allowed else 'closed'} for {label}"
            )
    return changes


INHERIT, ALLOW, DENY = "inherit", "allow", "deny"


def user_matrix(account):
    """Rows for one account: its own rule, its role's, and the outcome."""
    role_rules = dict(
        RoleModuleAccess.objects.filter(role=account.role)
        .values_list("module", "allowed")
    )
    user_rules = dict(account.module_access.values_list("module", "allowed"))
    rows = []
    for item in managed_items():
        key = item["key"]
        grantable = role_grants(account.role, item)
        role_allowed = role_rules.get(key, True)
        if key in user_rules:
            choice = ALLOW if user_rules[key] else DENY
            allowed = user_rules[key]
        else:
            choice = INHERIT
            allowed = role_allowed
        rows.append({
            "item": item,
            "grantable": grantable,
            "role_allowed": role_allowed,
            "choice": choice,
            "effective": grantable and allowed,
        })
    return rows


def save_user_matrix(account, choices, actor):
    """
    Store one account's overrides. `choices` maps module to inherit/allow/deny.

    "Inherit" removes the account's row so the role's rule applies again.
    """
    stored = {row.module: row for row in account.module_access.all()}
    changes = []
    for item in managed_items():
        key = item["key"]
        choice = choices.get(key, INHERIT)
        if choice not in (INHERIT, ALLOW, DENY):
            continue
        row = stored.get(key)
        if choice == INHERIT:
            if row is not None:
                row.delete()
                changes.append(f"{item['label']} follows the role again")
            continue
        allowed = choice == ALLOW
        if row is None:
            UserModuleAccess.objects.create(
                module=key, user=account, allowed=allowed, updated_by=actor,
            )
        elif row.allowed != allowed:
            row.allowed = allowed
            row.updated_by = actor
            row.save(update_fields=["allowed", "updated_by", "updated_at"])
        else:
            continue
        changes.append(
            f"{item['label']} {'opened' if allowed else 'closed'} for this account"
        )
    forget(account)
    return changes
