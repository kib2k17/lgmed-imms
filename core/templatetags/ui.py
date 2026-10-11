"""
Template helpers for the LGMED-IMMS design system.

Everything here is presentation-only. Authorization decisions are made in the
views and models; these tags simply avoid offering an action a user cannot take.
"""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.icons import ICONS
from core.status import STATUS_STYLES, resolve_status

register = template.Library()


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------


@register.simple_tag
def icon(name, css_class="size-4", stroke_width="1.75"):
    """
    Render an inline SVG icon.

        {% icon "monitoring" "size-5" %}

    Decorative by default (aria-hidden); pair the icon with real text so the
    interface never depends on iconography alone.
    """
    body = ICONS.get(name)
    if body is None:
        return ""
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="{}" stroke-linecap="round" '
        'stroke-linejoin="round" class="{}" aria-hidden="true" focusable="false">'
        "{}</svg>",
        stroke_width,
        css_class,
        mark_safe(body),
    )


# ---------------------------------------------------------------------------
# Status presentation
# ---------------------------------------------------------------------------


@register.simple_tag
def status_badge(value, label=None):
    """
    Render an accessible status badge.

    Status is communicated by an icon glyph *and* a text label, never by colour
    alone (WCAG 1.4.1).
    """
    key = resolve_status(value)
    style = STATUS_STYLES[key]
    text = label or (str(value).replace("_", " ").title() if value else style["label"])
    glyph = ICONS.get(style["icon"], "")
    return format_html(
        '<span class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 '
        'text-xs font-medium whitespace-nowrap {}">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.25" stroke-linecap="round" '
        'stroke-linejoin="round" class="size-3 shrink-0" aria-hidden="true">{}</svg>'
        "{}</span>",
        style["classes"],
        mark_safe(glyph),
        text,
    )


# ---------------------------------------------------------------------------
# Query-string helpers (search / filter / sort / paginate together)
# ---------------------------------------------------------------------------


@register.simple_tag(takes_context=True)
def query_string(context, **kwargs):
    """
    Rebuild the current query string with `kwargs` applied.

    Lets pagination links keep the active search and filters:

        <a href="?{% query_string page=3 %}">
    """
    request = context.get("request")
    params = request.GET.copy() if request else {}
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    params.pop("_", None)
    return params.urlencode()


@register.simple_tag(takes_context=True)
def sort_link(context, field):
    """Return the querystring that toggles sorting on `field`."""
    request = context.get("request")
    current = request.GET.get("sort", "") if request else ""
    new = f"-{field}" if current == field else field
    return query_string(context, sort=new, page=None)


@register.simple_tag(takes_context=True)
def sort_state(context, field):
    """`asc`, `desc` or empty - used for aria-sort and the header caret."""
    request = context.get("request")
    current = request.GET.get("sort", "") if request else ""
    if current == field:
        return "asc"
    if current == f"-{field}":
        return "desc"
    return ""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


@register.filter
def filesize(num_bytes):
    """Human-readable file size for the document repository."""
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


@register.filter
def is_pdf(fieldfile):
    """Whether a stored file can open in the in-system PDF viewer."""
    from core.files import is_pdf as _is_pdf

    return _is_pdf(fieldfile)


@register.filter
def field_class(bound_field, extra=""):
    """Attach design-system classes to a Django form widget from the template."""
    base = (
        "block w-full rounded-md border bg-white px-3 py-2 text-sm text-slate-900 "
        "placeholder:text-slate-400 shadow-xs focus:outline-none focus:ring-2 "
        "disabled:bg-slate-50 disabled:text-slate-500"
    )
    tone = (
        "border-red-300 focus:border-red-600 focus:ring-red-600/25"
        if bound_field.errors
        else "border-slate-300 focus:border-brand-600 focus:ring-brand-600/25"
    )
    return bound_field.as_widget(attrs={"class": f"{base} {tone} {extra}".strip()})


@register.filter
def capability(user, attribute):
    """
    Whether a user holds a named capability.

        {% if account|capability:"can_delete" %}

    Lets the permission matrix be driven by `accounts.capabilities.CAPABILITIES`
    rather than by a hand-written row per capability that drifts out of step
    with what the server actually enforces.
    """
    return bool(getattr(user, attribute, False))
