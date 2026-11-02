/* dashboard.js - every number comes from Oracle through the API; nothing is hard-coded. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const dateInput = $("dateInput");

  const setText = (id, text) => { const node = $(id); node.textContent = text; node.classList.remove("skeleton"); };

  function renderCards(summary) {
    const c = summary.categories;
    setText("statStudy", FM.fmtMinutes(summary.study_minutes));
    setText("hintStudy", `${c.STUDY.count} session(s)`);
    setText("statSleep", FM.fmtMinutes(c.SLEEP.minutes));
    setText("statExercise", FM.fmtMinutes(c.EXERCISE.minutes));
    setText("statEntertainment", FM.fmtMinutes(c.ENTERTAINMENT.minutes));
    setText("statCount", String(summary.total_activities));
    setText("hintTracked", `${FM.fmtMinutes(summary.total_minutes)} of 24h tracked`);
  }

  function renderProductivity(summary) {
    const box = $("productivity");
    if (summary.total_activities === 0) {
      box.innerHTML = FM.emptyState("📝", "Nothing recorded for this date",
        "Start the stopwatch or add activities to your schedule to see your summary.") +
        `<div style="text-align:center"><a class="btn small" href="stopwatch.html">Open stopwatch</a> <a class="btn small secondary" href="schedule.html">Add activity</a></div>`;
      return;
    }
    const pct = Math.min(100, summary.total_minutes / 1440 * 100);
    const top = Object.entries(summary.categories).sort((a, b) => b[1].minutes - a[1].minutes)[0];
    const share = summary.study_share_of_waking_pct;
    box.innerHTML = `
      <div class="bar-row" style="grid-template-columns:110px 1fr 70px"><span>Day tracked</span>
        <div class="bar-track"><div class="bar-fill" data-w="${pct}"></div></div><span class="bar-value">${pct.toFixed(0)}%</span></div>
      <table><tbody>
        <tr><td>Tracked time</td><td><strong>${FM.fmtMinutes(summary.total_minutes)}</strong></td></tr>
        <tr><td>Not yet tracked</td><td><strong>${FM.fmtMinutes(summary.untracked_minutes)}</strong></td></tr>
        <tr><td>Study share of waking time</td><td><strong>${share === null ? "–" : share + "%"}</strong></td></tr>
        <tr><td>Biggest category</td><td><strong>${FM.CATEGORIES[top[0]].icon} ${FM.CATEGORIES[top[0]].label}</strong> (${FM.fmtMinutes(top[1].minutes)})</td></tr>
      </tbody></table>`;
  }

  function renderBreakdown(summary) {
    const box = $("breakdown");
    const rows = Object.entries(summary.categories).filter(([, v]) => v.minutes > 0).sort((a, b) => b[1].minutes - a[1].minutes);
    if (!rows.length) { box.innerHTML = FM.emptyState("📊", "No category data", "Record some activities first."); return; }
    box.innerHTML = rows.map(([type, v]) => `
      <div class="bar-row"><span>${FM.CATEGORIES[type].icon} ${FM.CATEGORIES[type].label}</span>
        <div class="bar-track"><div class="bar-fill" style="--bar:${FM.CATEGORIES[type].color}" data-w="${v.minutes / summary.total_minutes * 100}"></div></div>
        <span class="bar-value">${FM.fmtMinutes(v.minutes)}</span></div>`).join("");
  }

  function renderRecent(items) {
    const box = $("recent");
    if (!items.length) { box.innerHTML = FM.emptyState("🗒️", "No activities yet", "Your latest activities will appear here."); return; }
    box.innerHTML = `<table><thead><tr><th>Activity</th><th>Category</th><th>Started</th><th>Duration</th></tr></thead><tbody>` +
      items.map((a) => `<tr><td>${FM.esc(a.activity_name)}</td>
        <td><span class="badge ${a.activity_type}">${FM.CATEGORIES[a.activity_type].label}</span></td>
        <td>${FM.fmtDateTime(a.start_time)}</td>
        <td>${a.is_active ? "<strong style='color:var(--success)'>● Running</strong>" : FM.fmtMinutes(a.duration_minutes)}</td></tr>`).join("") +
      `</tbody></table>`;
  }

  function animateBars() {
    requestAnimationFrame(() => document.querySelectorAll(".bar-fill[data-w]").forEach((b) => { b.style.width = Math.min(100, b.dataset.w) + "%"; }));
  }

  async function load(date) {
    try {
      FM.clearError();
      const [summary, recent] = await Promise.all([FocusAPI.daySummary(date), FocusAPI.listActivities({ limit: 8 })]);
      if (!date) dateInput.value = summary.date; // first load: server's "today"
      renderCards(summary); renderProductivity(summary); renderBreakdown(summary); renderRecent(recent);
      animateBars();
    } catch (error) { FM.showError(error); }
  }

  dateInput.addEventListener("change", () => { if (dateInput.value) load(dateInput.value); });
  document.querySelectorAll(".stat .value").forEach((v) => v.classList.add("skeleton"));
  load();
})();
