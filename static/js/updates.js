/* ==========================================================================
   LGMED-IMMS division accomplishment charts

   Loaded only by the Updates & Accomplishments dashboard. Uses the palette and
   defaults declared in app.js, so this page reads as part of the same system
   as the dashboard and the analytics page rather than as a third style.

   Every series here is division-wide. None of these charts has a per-employee
   dimension, and none should acquire one: the module records what LGMED
   accomplished, not who accomplished it.
   ========================================================================== */

window.LGMED = window.LGMED || {};

window.LGMED.initUpdates = function (data) {
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

  /* -- Accomplishments by month ----------------------------------------- */
  make("accomplishmentsByMonth", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Accomplishments",
            data: series.values,
            backgroundColor: palette.brand[0],
            hoverBackgroundColor: palette.brand[1],
            borderRadius: 3,
            maxBarThickness: 34,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });

  /* -- Accomplishments by category --------------------------------------- */
  make("accomplishmentsByCategory", function (series) {
    return {
      type: "doughnut",
      data: {
        labels: series.labels,
        datasets: [
          {
            data: series.values,
            backgroundColor: [
              palette.brand[0],
              palette.brand[1],
              palette.brand[2],
              palette.brand[3],
              palette.status.success,
              palette.status.warning,
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

  /* -- Activities by type ------------------------------------------------- */
  make("activitiesByType", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Activities",
            data: series.values,
            backgroundColor: palette.brand[1],
            borderRadius: 3,
            maxBarThickness: 22,
          },
        ],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: valueAxis, y: categoryAxis },
      },
    };
  });

  /* -- Completed, ongoing, pending ---------------------------------------- */
  make("workStatus", function (series) {
    return {
      type: "doughnut",
      data: {
        labels: series.labels,
        datasets: [
          {
            data: series.values,
            backgroundColor: [
              palette.status.success,
              palette.status.info,
              palette.status.warning,
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

  /* -- Incoming against outgoing correspondence --------------------------- */
  make("communicationsFlow", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Incoming",
            data: series.incoming,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 22,
          },
          {
            label: "Outgoing",
            data: series.outgoing,
            backgroundColor: palette.brand[2],
            borderRadius: 3,
            maxBarThickness: 22,
          },
        ],
      },
      options: {
        plugins: { legend: { position: "top", align: "end" } },
        scales: { x: categoryAxis, y: valueAxis },
      },
    };
  });

  /* -- Weekly trend -------------------------------------------------------
     Accomplishments per week as bars, with the week's update completeness as
     a line on its own axis: the two answer different questions and must not
     share a scale. */
  make("weeklyTrend", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Accomplishments",
            data: series.values,
            backgroundColor: palette.brand[0],
            borderRadius: 3,
            maxBarThickness: 26,
            order: 2,
          },
          {
            type: "line",
            label: "Update completion (%)",
            data: series.completion,
            borderColor: palette.status.warning,
            backgroundColor: "transparent",
            tension: 0.3,
            pointRadius: 2,
            pointHoverRadius: 4,
            yAxisID: "percent",
            order: 1,
          },
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "top", align: "end" } },
        scales: {
          x: categoryAxis,
          y: valueAxis,
          percent: {
            position: "right",
            beginAtZero: true,
            max: 100,
            grid: { display: false },
            border: { display: false },
            ticks: { padding: 8, callback: function (v) { return v + "%"; } },
          },
        },
      },
    };
  });

  /* -- POPS Plan compliance ------------------------------------------------ */
  make("popsCompliance", function (series) {
    return {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Target",
            data: series.target,
            backgroundColor: palette.brand[3],
            borderRadius: 3,
            maxBarThickness: 22,
          },
          {
            label: "Accomplished",
            data: series.accomplished,
            backgroundColor: palette.status.success,
            borderRadius: 3,
            maxBarThickness: 22,
          },
        ],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { position: "top", align: "end" } },
        scales: { x: valueAxis, y: categoryAxis },
      },
    };
  });

  /* -- Year-to-date running total ------------------------------------------ */
  make("yearToDateTrend", function (series) {
    return {
      type: "line",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Year to date",
            data: series.values,
            borderColor: palette.brand[0],
            backgroundColor: "rgba(30, 84, 152, 0.08)",
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            pointHoverRadius: 4,
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
