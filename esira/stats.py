"""
The e-SIRA dashboard figures.

Two scopes. "Mine" - the default for everyone - counts the work waiting on
the user and what they have done. "Office" - offered to those who oversee
e-SIRA - counts the same things across every account. Each figure carries the
list link that shows exactly the documents it counted.

"Signed" counts signing acts: one person signing one document. "Routed
documents completed" counts routing steps completed without a signature -
an approval, a review or an acknowledgement. The two are the halves of the
work e-SIRA carries, and their sum is the total.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import (
    DONE_STEP_STATUSES,
    OPEN_STEP_STATUSES,
    DigitalSignature,
    DocumentStatus,
    RoutingStep,
    StepAction,
)
from .permissions import visible_documents

OUT_STATUSES = [
    DocumentStatus.OUT_FOR_SIGNATURE,
    DocumentStatus.PARTIALLY_SIGNED,
    DocumentStatus.ROUTED,
]
NON_SIGNING_DONE = [s for s in DONE_STEP_STATUSES if s != "SIGNED"]


def scope_for(user, requested):
    if requested == "office" and user.can_oversee_esira:
        return "office"
    return "mine"


def compute(user, scope="mine"):
    office = scope == "office"
    week_ago = timezone.now() - timedelta(days=7)

    open_sign_steps = RoutingStep.objects.filter(
        action=StepAction.SIGN, status__in=list(OPEN_STEP_STATUSES),
    )
    documents = visible_documents(user)
    signatures = DigitalSignature.objects.all()
    routed_done = RoutingStep.objects.exclude(action=StepAction.SIGN).filter(
        status__in=NON_SIGNING_DONE,
    )
    if not office:
        open_sign_steps = open_sign_steps.filter(recipient=user)
        documents = documents.filter(owner=user)
        signatures = signatures.filter(signer=user)
        routed_done = routed_done.filter(recipient=user)

    completed = (
        visible_documents(user) if not office else documents
    ).filter(status=DocumentStatus.COMPLETED)

    signed_total = signatures.count()
    routed_total = routed_done.count()
    signed_week = signatures.filter(signed_at__gte=week_ago).count()
    routed_week = routed_done.filter(acted_at__gte=week_ago).count()

    return {
        "awaiting_my_signature": open_sign_steps.count(),
        "out_for_signature": documents.filter(status__in=OUT_STATUSES).count(),
        "completed": completed.count(),
        "total_signed": signed_total,
        "total_routed_completed": routed_total,
        "total_signed_routed": signed_total + routed_total,
        "signed_week": signed_week,
        "routed_week": routed_week,
        "total_week": signed_week + routed_week,
    }


def cards(user, scope="mine"):
    """The figures as the dashboard shows them: label, value, link, tone."""
    figures = compute(user, scope)
    office = scope == "office"
    url = reverse("esira:list")

    def link(**params):
        if office:
            params["scope"] = "office"
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{query}" if query else url

    who = "office" if office else "me"
    items = [
        {"key": "awaiting_my_signature",
         "label": "Awaiting Signature" if office else "Awaiting My Signature",
         "meta": "Signature steps open now" if office else "Documents whose next signature is yours",
         "icon": "edit", "tone": "warning",
         "url": link(view="awaiting_signature" if office else "awaiting_me")},
        {"key": "out_for_signature", "label": "Out for Signature",
         "meta": "Documents on their route" if office else "Your documents with others",
         "icon": "mail", "tone": "info", "url": link(view="out")},
        {"key": "completed", "label": "Completed",
         "meta": "Closed with every step done", "icon": "check-circle",
         "tone": "success", "url": link(status=DocumentStatus.COMPLETED)},
        {"key": "total_signed", "label": "Total Documents Signed",
         "meta": "Signatures applied" + ("" if office else " by you"),
         "icon": "shield", "tone": "", "url": link(view=f"signed_by_{who}")},
        {"key": "total_routed_completed", "label": "Total Routed Documents Completed",
         "meta": "Approvals, reviews and acknowledgements",
         "icon": "check", "tone": "", "url": link(view=f"acted_by_{who}")},
        {"key": "total_signed_routed", "label": "Total Signed + Routed",
         "meta": "All completed e-SIRA actions", "icon": "trending-up",
         "tone": "", "url": link(view=f"handled_by_{who}")},
        {"key": "signed_week", "label": "Signed This Week",
         "meta": "Last 7 days", "icon": "shield", "tone": "success",
         "url": link(view=f"signed_by_{who}", period="week")},
        {"key": "routed_week", "label": "Routed Documents Completed This Week",
         "meta": "Last 7 days", "icon": "check", "tone": "success",
         "url": link(view=f"acted_by_{who}", period="week")},
        {"key": "total_week", "label": "Total This Week (Signed + Routed)",
         "meta": "Last 7 days", "icon": "trending-up", "tone": "success",
         "url": link(view=f"handled_by_{who}", period="week")},
    ]
    for item in items:
        item["value"] = figures[item["key"]]
    return items
