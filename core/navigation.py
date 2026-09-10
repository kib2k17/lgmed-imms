"""
The LGMED-iMMS sidebar is defined once, here.

Each entry declares the permission attribute (on the user model) that gates it.
Hiding a link is a usability courtesy only - the view itself re-checks access,
so a user cannot reach a module by typing its URL.

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
            {"key": "programs", "label": "Programs", "icon": "programs",
             "url_name": "programs:list", "namespace": "programs"},
            {"key": "monitoring", "label": "Monitoring", "icon": "monitoring",
             "url_name": "monitoring:list", "namespace": "monitoring"},
            {"key": "incoming", "label": "Incoming Monitoring", "icon": "inbox",
             "url_name": "incoming:list", "namespace": "incoming"},
            {"key": "lgus", "label": "LGU Management", "icon": "lgu",
             "url_name": "lgus:list", "namespace": "lgus"},
            {"key": "services", "label": "Frontline Services", "icon": "services",
             "url_name": "services:list", "namespace": "services"},
        ],
    },
    {
        "label": "Information",
        "items": [
            {"key": "updates", "label": "Updates & Accomplishments",
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
            {"key": "settings", "label": "System Settings", "icon": "settings",
             "url_name": "administration:settings", "requires": "can_administer",
             "namespace": "administration"},
            {"key": "audit", "label": "Audit Logs", "icon": "audit",
             "url_name": "audit:list", "requires": "can_administer",
             "namespace": "audit"},
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


def _matches(item, namespace, view_name):
    if namespace and namespace == item.get("namespace"):
        return True
    return view_name in item.get("url_names", ())


def build_sidebar(user, active_key=None, resolver_match=None, current_path=""):
    """Return the sidebar sections this user may see, with the active item flagged."""
    visible = []
    for section in NAV_SECTIONS:
        if not _allowed(user, section.get("requires")):
            continue
        items = []
        for item in section["items"]:
            if not _allowed(user, item.get("requires")):
                continue
            try:
                url = reverse(item["url_name"])
            except NoReverseMatch:
                continue
            items.append({**item, "url": url, "is_active": False})
        if items:
            visible.append({"label": section["label"], "items": items})

    all_items = [item for section in visible for item in section["items"]]
    match = None

    if active_key:
        match = next((i for i in all_items if i["key"] == active_key), None)

    if match is None and resolver_match is not None:
        match = next(
            (
                item
                for item in all_items
                if _matches(item, resolver_match.namespace, resolver_match.view_name)
            ),
            None,
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
