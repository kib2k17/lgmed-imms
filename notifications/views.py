from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from administration.models import SystemSetting
from core.middleware import mark_passive
from core.views_base import ModuleListView

from .models import Category, Level, Notification


class NotificationListView(ModuleListView):
    """
    Everything addressed to the signed-in user.

    Scoped to the recipient rather than filtered by one: there is no URL that
    shows another person's notifications, so none has to be guarded.
    """

    model = Notification
    module_key = "notifications"
    module_label = "Notifications"
    list_label = "Notifications"
    module_url_name = "notifications:list"
    page_title = "Notifications"
    page_subtitle = "Work addressed to you"
    template_name = "dashboard/notifications/list.html"

    search_placeholder = "Search notifications..."
    search_fields = ("title", "message")
    sort_fields = ("created_at", "category", "level")
    default_sort = "-created_at"
    create_url_name = None
    exportable = False
    empty_icon = "bell"
    filter_fields = (
        ("category", "Category", Category.choices),
        ("level", "Priority", Level.choices),
    )

    def get_base_queryset(self):
        return Notification.objects.for_user(self.request.user).visible()

    def apply_filters(self, queryset):
        queryset = super().apply_filters(queryset)
        if self.request.GET.get("unread") == "1":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mine = Notification.objects.for_user(self.request.user).visible()
        # "Needs action" counts urgent items too: an urgent notice obviously
        # needs action, and reading "Needs action 0" beside "Urgent 7" is
        # nonsense. Urgent is the subset, shown separately for triage.
        context["summary"] = mine.aggregate(
            total=Count("pk"),
            unread=Count("pk", filter=Q(read_at__isnull=True)),
            action=Count(
                "pk",
                filter=Q(
                    level__in=(Level.ACTION, Level.URGENT), read_at__isnull=True
                ),
            ),
            urgent=Count("pk", filter=Q(level=Level.URGENT, read_at__isnull=True)),
        )
        context["unread_only"] = self.request.GET.get("unread") == "1"
        context["is_filtered"] = context["is_filtered"] or context["unread_only"]
        return context


@login_required
def open_notification(request, pk):
    """
    Mark one as read and send the user where the work is.

    Going through this view rather than linking straight to the record is what
    makes "read" mean "the recipient actually looked at it".
    """
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_read()
    return redirect(notification.url or "notifications:list")


@login_required
def dismiss_notification(request, pk):
    if request.method != "POST":
        return redirect("notifications:list")
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.dismiss()
    messages.success(request, "Notification dismissed.")
    return redirect(request.META.get("HTTP_REFERER") or "notifications:list")


@login_required
def mark_all_read(request):
    if request.method != "POST":
        return redirect("notifications:list")
    count = Notification.objects.for_user(request.user).unread().update(
        read_at=timezone.now()
    )
    messages.success(
        request,
        f"{count} notification{'s' if count != 1 else ''} marked as read."
        if count
        else "There were no unread notifications.",
    )
    return redirect(request.META.get("HTTP_REFERER") or "notifications:list")


@require_GET
def notification_status(request):
    """
    The signed-in user's unread count and newest unread items, as JSON.

    Read by the installed app (static/js/pwa.js) to keep the bell and the app
    icon's badge current and to raise a device notification for anything new.
    It is the same data the bell already draws on every page - the same
    recipient-scoped query as core.context_processors.notifications - so it
    shows nobody anything they could not already see.

    Not @login_required: a background check that has outlived its session
    must be told so, not handed the sign-in page's HTML. And it never extends
    the session (core.middleware.mark_passive): a page checking in is not the
    person using the system.
    """
    mark_passive(request)
    if not request.user.is_authenticated:
        response = JsonResponse({"authenticated": False}, status=401)
    else:
        unread = Notification.objects.for_user(request.user).unread()
        response = JsonResponse({
            "authenticated": True,
            # The system notice rides along, so a page left open all day still
            # receives an announcement made after it was loaded.
            "notice": SystemSetting.load().notice_payload(),
            "unread": unread.count(),
            "latest": [
                {
                    "id": item.pk,
                    "title": item.title,
                    "level": item.level,
                    # Through the open view, so following it marks it read.
                    "url": reverse("notifications:open", args=[item.pk]),
                }
                for item in unread[:5]
            ],
        })
    response["Cache-Control"] = "no-store, private"
    return response
