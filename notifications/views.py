from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

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
