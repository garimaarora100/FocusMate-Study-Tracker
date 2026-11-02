/* analytics.js - shows results computed by pandas on the server. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const range = $("rangeInput"), kind = $("kindInput"), download = $("downloadBtn");
  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  /** Draw a simple column chart. points = [{label, value, title}] */
  function columnChart(container, points, { showValues = true, labelEvery = 1 } = {}) {
    const max = Math.max(...points.map((p) => p.value), 1);
    if (points.every((p) => p.value === 0)) { container.innerHTML = FM.emptyState("📉", "No study time recorded", "Use the stopwatch or schedule to add study sessions."); return; }
    container.innerHTML = `<div class="column-chart">` + points.map((p, i) => `
      <div class="col" title="${FM.esc(p.title)}">
        <span class="val">${showValues && p.value > 0 ? FM.fmtMinutes(p.value) : ""}</span>
        <div class="bar ${p.value === 0 ? "zero" : ""}" data-h="${p.value / max * 100}"></div>
        <span class="lbl">${i % labelEvery === 0 ? FM.esc(p.label) : "&nbsp;"}</span></div>`).join("") + `</div>`;
    requestAnimationFrame(() => container.querySelectorAll(".bar").forEach((b) => { b.style.height = Math.max(1, Number(b.dataset.h)) + "%"; }));
  }

  function renderKpis(daily, cat, days) {
    $("kAvg").textContent = FM.fmtMinutes(daily.average_study_minutes_per_day);
    $("kAvgHint").textContent = `per day · ${FM.fmtMinutes(daily.average_study_minutes_on_study_days)} on days you studied`;
    $("kStudy").textContent = FM.fmtMinutes(daily.total_study_minutes);
    $("kDays").textContent = `studied on ${daily.days_studied} of ${days} days`;
    const top = cat.most_time_consuming_category;
    $("kTop").textContent = top ? `${FM.CATEGORIES[top].icon} ${FM.CATEGORIES[top].label}` : "–";
    const topRow = cat.categories.find((c) => c.activity_type === top);
    $("kTopHint").textContent = topRow ? `${FM.fmtMinutes(topRow.total_minutes)} (${topRow.percentage}%)` : "no data yet";
    $("kTotal").textContent = FM.fmtMinutes(cat.total_recorded_minutes);
    $("kRecordedDays").textContent = `across ${cat.days_with_records} day(s) with records`;
  }

  function renderDaily(daily) {
    const n = daily.days.length;
    columnChart($("dailyChart"), daily.days.map((d) => {
      const date = new Date(d.date + "T00:00:00");
      return { label: `${date.getDate()}/${date.getMonth() + 1}`, value: d.minutes, title: `${d.date}: ${FM.fmtMinutes(d.minutes)}` };
    }), { showValues: n <= 14, labelEvery: Math.ceil(n / 10) });
  }

  function renderWeekly(weekly) {
    columnChart($("weeklyChart"), weekly.days.map((d) => ({
      label: WEEKDAYS[new Date(d.date + "T00:00:00").getDay()], value: d.minutes, title: `${d.date}: ${FM.fmtMinutes(d.minutes)}`,
    })));
    const max = Math.max(...weekly.weeks.map((w) => w.minutes), 1);
    $("weeksList").innerHTML = `<p style="margin:0 0 4px;color:var(--muted);font-size:.85rem">Last 7 days: <strong>${FM.fmtMinutes(weekly.weekly_total_minutes)}</strong> (avg ${FM.fmtMinutes(weekly.daily_average_minutes)}/day)</p>` +
      weekly.weeks.map((w) => `<div class="bar-row" style="grid-template-columns:150px 1fr 80px"><span title="${w.start_date} to ${w.end_date}">${FM.esc(w.label)}</span>
        <div class="bar-track"><div class="bar-fill" data-w="${w.minutes / max * 100}"></div></div><span class="bar-value">${FM.fmtMinutes(w.minutes)}</span></div>`).join("");
  }

  function renderCategories(cat) {
    const rows = cat.categories;
    if (cat.total_recorded_minutes === 0) {
      $("categoryBars").innerHTML = FM.emptyState("📊", "No activity in this period", "Record activities to see where your time goes.");
      $("categoryTable").innerHTML = "";
      return;
    }
    const max = Math.max(...rows.map((r) => r.total_minutes), 1);
    $("categoryBars").innerHTML = rows.filter((r) => r.total_minutes > 0).sort((a, b) => b.total_minutes - a.total_minutes).map((r) => `
      <div class="bar-row"><span>${FM.CATEGORIES[r.activity_type].icon} ${FM.CATEGORIES[r.activity_type].label}</span>
        <div class="bar-track"><div class="bar-fill" style="--bar:${FM.CATEGORIES[r.activity_type].color}" data-w="${r.total_minutes / max * 100}"></div></div>
        <span class="bar-value">${FM.fmtMinutes(r.total_minutes)}</span></div>`).join("");
    $("categoryTable").innerHTML = `<table><thead><tr><th>Category</th><th>Total (min)</th><th>Avg / day (min)</th><th>Days recorded</th><th>Activities</th><th>Share</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td><span class="badge ${r.activity_type}">${FM.CATEGORIES[r.activity_type].label}</span></td><td>${r.total_minutes}</td><td>${r.average_minutes_per_day}</td><td>${r.days_recorded}</td><td>${r.activity_count}</td><td>${r.percentage}%</td></tr>`).join("") + `</tbody></table>`;
  }

  function renderStats(daily) {
    const s = daily.descriptive_statistics;
    const order = [["count", "count (days)"], ["mean", "mean"], ["std", "std deviation"], ["min", "min"], ["25%", "25th percentile"], ["50%", "median"], ["75%", "75th percentile"], ["max", "max"]];
    $("stats").innerHTML = s && s.count !== undefined
      ? `<table><tbody>${order.map(([k, label]) => `<tr><td>${label}</td><td><strong>${s[k] === null || s[k] === undefined ? "–" : (k === "count" ? s[k] : s[k] + " min")}</strong></td></tr>`).join("")}</tbody></table>`
      : FM.emptyState("🧮", "No statistics yet", "Statistics appear once data exists.");
  }

  function updateDownloadLink() { download.href = FocusAPI.exportUrl(kind.value, range.value); }

  async function load() {
    const days = Number(range.value);
    updateDownloadLink();
    try {
      FM.clearError();
      const [daily, weekly, cat] = await Promise.all([FocusAPI.dailyAnalytics(days), FocusAPI.weeklyAnalytics(), FocusAPI.categoryAnalytics(days)]);
      renderKpis(daily, cat, days); renderDaily(daily); renderWeekly(weekly); renderCategories(cat); renderStats(daily);
      requestAnimationFrame(() => document.querySelectorAll(".bar-fill[data-w]").forEach((b) => { b.style.width = Math.min(100, b.dataset.w) + "%"; }));
    } catch (error) { FM.showError(error); }
  }

  range.addEventListener("change", load);
  kind.addEventListener("change", updateDownloadLink);
  load();
})();
