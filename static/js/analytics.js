/* ==========================================================================
   LGMED-IMMS analytics charts

   Loaded only by the analytics page. Uses the palette and defaults declared in
   app.js, so the two pages read as one system rather than two.
   ========================================================================== */

window.LGMED = window.LGMED || {};

window.LGMED.initAnalytics = function (data) {
  if (typeof Chart === "undefined" || !data) return;

  var palette = window.LGMED.chartPalette;
  window.LGMED.applyChartDefaults();

  var valueAxis = {
    grid: { color: palette.grid, drawTicks: false },
    border: { display: false },
    ticks: { padding: 8, precision: 0 },
    beginAtZero: true,
  };
  var categoryAxis = {
    grid: { display: false },
    border: { color: palette.grid },
    ticks: { padding: 6 },
  };

  function make(id, build) {
    var canvas = document.getElementById(id);
    if (canvas && data[id]) new Chart(canvas, build(data[id]));
  }

  /* -- Monitoring by province ------------------------------------------ */
  make("monitoringByProvince", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Activities conducted",
            data: series.conducted,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 30,
          },
          {
            label: "LGUs reached",
            data: series.covered,
            backgroundColor: palette.brand[2],
            borderRadius: 3,
            maxBarThickness: 30,
          },
        ],
      },
      options: {
        plugins: { legend: { position: "top", align: "end" } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });

  /* -- Compliance breakdown --------------------------------------------- */
  make("complianceBreakdown", function (series) {
    return {
      type: "doughnut",
      data: {
        labels: series.labels,
        datasets: [
          {
            data: series.values,
            backgroundColor: [
              palette.status.success,
              palette.status.warning,
              palette.status.danger,
              palette.status.neutral,
            ],
            borderColor: "#ffffff",
            borderWidth: 2,
          },
        ],
      },
      options: { cutout: "62%", plugins: { legend: { position: "right" } } },
    };
  });

  /* -- Year-on-year monitoring trend ------------------------------------ */
  make("monitoringTrend", function (series) {
    return {
      type: "line",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: series.currentLabel,
            data: series.current,
            borderColor: palette.brand[0],
            backgroundColor: "rgba(30, 84, 152, 0.08)",
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: series.previousLabel,
            data: series.previous,
            borderColor: palette.muted,
            backgroundColor: "transparent",
            borderDash: [5, 4],
            tension: 0.3,
            pointRadius: 2,
            pointHoverRadius: 4,
          },
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "top", align: "end" } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });

  /* -- Coverage by LGU type ---------------------------------------------- */
  make("lguTypeCoverage", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Reached",
            data: series.covered,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 34,
          },
          {
            label: "Registered",
            data: series.total,
            backgroundColor: palette.brand[2],
            borderRadius: 3,
            maxBarThickness: 34,
          },
        ],
      },
      options: {
        plugins: { legend: { position: "top", align: "end" } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });

  /* -- Programs by category ---------------------------------------------
     Horizontal: category names are long, and reading them along the y axis
     beats rotating them under a vertical bar.                             */
  make("programsByCategory", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Active",
            data: series.active,
            backgroundColor: palette.status.success,
            borderRadius: 3,
          },
          {
            label: "Other",
            data: series.other,
            backgroundColor: palette.status.neutral,
            borderRadius: 3,
          },
        ],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { position: "top", align: "end" } },
        scales: {
          x: Object.assign({}, valueAxis, { stacked: true }),
          y: Object.assign({}, categoryAxis, { stacked: true }),
        },
      },
    };
  });

  /* -- Report pipeline ---------------------------------------------------- */
  make("reportPipeline", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Reports",
            data: series.values,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 40,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });
};
