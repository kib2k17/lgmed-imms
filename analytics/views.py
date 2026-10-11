
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView

from audit.models import Action
from audit.recording import record
from core import csv_safe
from core.safe_json import script_json

from . import metrics


class AnalyticsView(LoginRequiredMixin, TemplateView):
    """
    Regional performance analysis.

    Read-only and available to every signed-in role: the point of publishing
    performance figures internally is that everyone works from the same ones.
    """

    template_name = "dashboard/analytics/analytics.html"

    def get_year(self):
        try:
            year = int(self.request.GET.get("year", timezone.localdate().year))
        except (TypeError, ValueError):
            return timezone.localdate().year
        return year if year in metrics.available_years() else timezone.localdate().year

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            return self.export_csv(self.get_year())
        return super().get(request, *args, **kwargs)

    def export_csv(self, year):
        """
        Every figure on the page, as one file.

        Each chart's own table becomes a titled block, so the export reads the
        way the page does rather than as an undifferentiated dump.
        """
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="lgmed-imms-analytics-{year}.csv"'
        )
        response.write("\ufeff")

        writer = csv_safe.writer(response)
        writer.writerow([f"LGMED-IMMS analytics for {year}"])
        writer.writerow([
            "Generated",
            timezone.localtime().strftime("%d %B %Y, %I:%M %p"),
        ])
        writer.writerow([])

        for chart in metrics.charts(year):
            writer.writerow([chart["title"]])
            writer.writerow(chart["headers"])
            for row in chart["rows"]:
                writer.writerow(row)
            writer.writerow([])

        writer.writerow(["Least-monitored LGUs"])
        writer.writerow(["LGU", "Type", "Province", "Activities"])
        for lgu in metrics.least_monitored(year, limit=20):
            writer.writerow([
                lgu.name, lgu.get_lgu_type_display(), lgu.province.name, lgu.visits,
            ])

        record(
            Action.EXPORT,
            detail=f"Exported the {year} analytics summary",
            request=self.request,
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = self.get_year()
        charts = metrics.charts(year)

        context.update({
            "page_title": "Analytics",
            "page_subtitle": "Regional monitoring and evaluation performance",
            "breadcrumbs": [{"label": "Analytics"}],
            "active_nav": "analytics",
            "year": year,
            "years": metrics.available_years(),
            "headline": metrics.headline(year),
            "documents": metrics.document_summary(year),
            "charts": charts,
            "least_monitored": metrics.least_monitored(year),
            "charts_json": script_json({c["id"]: c["data"] for c in charts}),
        })
        return context
