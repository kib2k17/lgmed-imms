"""
Where a "go back to where you were" redirect may lead.

A `next` field in a form post, or the Referer header, is supplied by the
browser - so by whoever built the request. Followed blindly, it turns this
site into a link that bounces a signed-in colleague to a look-alike sign-in
page elsewhere. Only an address on this site, over the scheme the request came
in on, is followed; anything else falls back to a page the view chooses.
"""

from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, candidate, fallback):
    candidate = (candidate or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback
