"""
The LGMED-IMMS sidebar is defined once, here.

Each entry declares the permission attribute (on the user model) that gates it.
On top of that, the System Administrator may close a module to a role or to one
account from Menu Permissions (accounts/menu_access.py). A closed module is left
out here and its URLs are refused by `accounts.middleware.ModuleAccessMiddleware`,
and the views still re-check their own capability, so a user cannot reach a
module by typing its URL.

The active item is resolved from the matched URL's namespace, not from the
path. Matching on the path meant that wherever a module happened to sit in the
URL tree decided which item lit up: /app/ prefixes every module, so Dashboard
lit up alongside them, and moving Users to /accounts/ would light nothing at
all. The namespace is what the item actually is.
"""

from django.urls import NoReverseMatch, reverse

NAV_SECTIONS = [
    {
        "label": "Main",
        "items": [
            {"key": "dashboard", "label": "Dashboard", "icon": "dashboard",
             "url_name": "core:dashboard", "url_names": {"core:dashboard"}},
            # `title` carries the full name for the tooltip where `label` is
            # the abbreviation the 256px column can actually show. A label
            # that has to be truncated to fit is not a label.
            {"key": "programs", "label": "Programs & Projects",
             "title": "Programs, Projects & Activities (PPAs)",
             "icon": "programs", "url_name": "programs:list",
             "namespace": "programs"},
            {"key": "ppa_queue", "label": "PPA Review Queue",
             "icon": "shield", "url_name": "programs:queue",
             "requires": "can_review_ppa",
             "url_names": {"programs:queue", "programs:document_review"}},
            {"key": "ppa_authorities", "label": "Publication Authorities",
             "icon": "lock", "url_name": "programs:authority_list",
             "requires": "can_review_ppa",
             "url_names": {
                 "programs:authority_list", "programs:authority_create",
                 "programs:authority_detail", "programs:authority_update",
             }},
            {"key": "monitoring", "label": "Monitoring", "icon": "monitoring",
             "url_name": "monitoring:list", "namespace": "monitoring"},
            {"key": "incoming", "label": "Incoming Monitoring", "icon": "inbox",
             "url_name": "incoming:list", "namespace": "incoming"},
            {"key": "outgoing", "label": "Outgoing Monitoring", "icon": "mail",
             "url_name": "outgoing:list", "namespace": "outgoing"},
            {"key": "datasync", "label": "Data Sync", "icon": "upload",
             "title": "Sync the Incoming and Outgoing registers from Excel",
             "url_name": "datasync:home", "namespace": "datasync",
             "requires": "can_encode"},
            {"key": "lgus", "label": "LGU Management", "icon": "lgu",
             "url_name": "lgus:list", "namespace": "lgus"},
            {"key": "services", "label": "Frontline Services", "icon": "services",
             "url_name": "services:list", "namespace": "services"},
        ],
    },
    {
        "label": "Information",
        "items": [
            {"key": "updates", "label": "Accomplishments",
             "title": "Updates & Accomplishments",
             "icon": "check-circle", "url_name": "updates:dashboard",
             "namespace": "updates"},
            {"key": "announcements", "label": "Announcements", "icon": "announcements",
             "url_name": "announcements:list", "namespace": "announcements"},
            {"key": "documents", "label": "Document Management",
             "icon": "documents", "url_name": "documents:list",
             "namespace": "documents"},
            {"key": "analytics", "label": "Analytics", "icon": "trending-up",
             "url_name": "analytics:index", "namespace": "analytics"},
            {"key": "reports", "label": "Reports", "icon": "reports",
             "url_name": "reports:list", "namespace": "reports"},
            {"key": "calendar", "label": "Calendar", "icon": "calendar",
             "url_name": "activities:list", "namespace": "activities"},
            {"key": "activity_monitor", "label": "Activity Monitoring",
             "icon": "monitoring", "url_name": "activities:monitor",
             "requires": "can_supervise",
             "url_names": {"activities:monitor"}},
            {"key": "public_site", "label": "Public Website", "icon": "home",
             "url_name": "administration:public_site", "requires": "can_approve",
             "url_names": {"administration:public_site"}},
        ],
    },
    {
        "label": "Administration",
        "requires": "can_administer",
        "items": [
            {"key": "users", "label": "Users & Roles", "icon": "users",
             "url_name": "accounts:user_list", "requires": "can_administer",
             "url_names": {
                 "accounts:user_list", "accounts:user_create",
                 "accounts:user_detail", "accounts:user_update",
                 "accounts:user_password", "accounts:user_activation",
                 "accounts:role_list",
             }},
            # Which of the modules above each role and account is offered.
            # The System Administrator's alone: an Administrator who could
            # close modules to other Administrators could close them to the
            # System Administrator's deputies too.
            {"key": "menu_permissions", "label": "Menu Permissions",
             "title": "Sidebar and module access by role and by account",
             "icon": "key", "url_name": "accounts:menu_permissions",
             "requires": "is_superadmin",
             "url_names": {
                 "accounts:menu_permissions", "accounts:user_menu_permissions",
             }},
            {"key": "settings", "label": "System Settings", "icon": "settings",
             "url_name": "administration:settings", "requires": "can_administer",
             "namespace": "administration"},
            {"key": "audit", "label": "Audit Logs", "icon": "audit",
             "url_name": "audit:list", "requires": "can_administer",
             "namespace": "audit"},
        ],
    },
    # Pinned below the scrolling list, at the foot of the sidebar, so the
    # Division's own innovations are one reach away from every page rather
    # than scrolled past under Administration.
    {
        "label": "LGMED Innovation Action",
        "pinned": True,
        "items": [
            {"key": "esira", "label": "e-SIRA",
             "title": "e-SIRA - Electronic Signature, Identification, Routing and Approval",
             "subtitle": "e-Signature & Routing",
             "icon": "signature", "url_name": "esira:dashboard",
             "namespace": "esira", "requires": "can_use_esira"},
        ],
    },
]

PUBLIC_NAV = [
    {"label": "Home", "url_name": "core:home"},
    {"label": "News", "url_name": "core:public_announcements"},
    {"label": "Accomplishments", "url_name": "core:public_updates"},
    {"label": "Programs", "url_name": "core:public_programs"},
    {"label": "Frontline Services", "url_name": "core:public_services"},
    {"label": "Statistics", "url_name": "core:public_statistics"},
    {"label": "Reports", "url_name": "core:public_reports"},
    {"label": "Document Library", "url_name": "core:public_documents"},
    {"label": "Calendar", "url_name": "core:public_calendar"},
    {"label": "About", "url_name": "core:public_about"},
    {"label": "Contact", "url_name": "core:public_contact"},
]


def _allowed(user, requires):
    if not requires:
        return True
    if not user or not user.is_authenticated:
        return False
    return bool(getattr(user, requires, False))


def _resolve_match(items, namespace, view_name):
    """Pick the item a resolved URL belongs to, most specific claim first.

    An item that names the exact view wins over one that claims the whole
    namespace. Both PPA Review Queue and Publication Authorities live under
    the programs namespace, so a namespace-first match lit up Programs,
    Projects & Activities on every one of their pages.
    """
    exact = next(
        (i for i in items if view_name in i.get("url_names", ())), None
    )
    if exact is not None:
        return exact
    if not namespace:
        return None
    return next((i for i in items if namespace == i.get("namespace")), None)


def build_sidebar(user, active_key=None, resolver_match=None, current_path=""):
    """Return the sidebar sections this user may see, with the active item flagged."""
    from accounts.menu_access import can_access_module

    visible = []
    for section in NAV_SECTIONS:
        if not _allowed(user, section.get("requires")):
            continue
        items = []
        for item in section["items"]:
            if not _allowed(user, item.get("requires")):
                continue
            if not can_access_module(user, item["key"]):
                continue
            try:
                url = reverse(item["url_name"])
            except NoReverseMatch:
                continue
            items.append({**item, "url": url, "is_active": False})
        if items:
            visible.append({
                "label": section["label"],
                "items": items,
                "pinned": section.get("pinned", False),
            })

    all_items = [item for section in visible for item in section["items"]]
    match = None

    if active_key:
        match = next((i for i in all_items if i["key"] == active_key), None)

    if match is None and resolver_match is not None:
        match = _resolve_match(
            all_items, resolver_match.namespace, resolver_match.view_name
        )

    if match is None and resolver_match is None and current_path:
        # Only for a page reached without a named URL. If a named URL resolved
        # and no item claimed it, that page simply is not in the sidebar -
        # Notifications, for one - and nothing should light up. Falling through
        # to a path match here would light Dashboard, because /app/ prefixes
        # every module.
        candidates = [i for i in all_items if current_path.startswith(i["url"])]
        match = max(candidates, key=lambda i: len(i["url"]), default=None)

    if match:
        match["is_active"] = True
    return visible


def build_public_nav(current_path=""):
    links = []
    for item in PUBLIC_NAV:
        try:
            url = reverse(item["url_name"])
        except NoReverseMatch:
            continue
        is_active = current_path == url if url == "/" else current_path.startswith(url)
        links.append({"label": item["label"], "url": url, "is_active": is_active})
    return links
