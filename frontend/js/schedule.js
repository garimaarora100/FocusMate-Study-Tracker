/* schedule.js - 24-hour schedule: add, edit, delete, chronological timeline. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = {
    date: $("dateInput"), form: $("activityForm"), name: $("nameInput"), type: $("typeInput"),
    start: $("startInput"), end: $("endInput"), save: $("saveBtn"), cancel: $("cancelBtn"),
    title: $("formTitle"), strip: $("strip"), timeline: $("timeline"), totals: $("dayTotals"),
  };
  let editing = null; // { id, date } while editing an existing activity
  let busy = false;

  /** Part of an activity that falls inside the selected calendar day (handles overnight activities). */
  function clipToDay(item) {
    const dayStart = new Date(el.date.value + "T00:00:00");
    const dayEnd = new Date(dayStart); dayEnd.setDate(dayEnd.getDate() + 1);
    const s = FM.parseTs(item.start_time).getTime();
    const e = item.end_time ? FM.parseTs(item.end_time).getTime() : Date.now();
    const from = Math.max(s, dayStart.getTime()), to = Math.min(e, dayEnd.getTime());
    const span = dayEnd.getTime() - dayStart.getTime();
    return {
      leftPct: (from - dayStart.getTime()) / span * 100,
      widthPct: Math.max(0, to - from) / span * 100,
      minutes: Math.max(0, to - from) / 60000,
      fromPrevDay: s < dayStart.getTime(), toNextDay: e > dayEnd.getTime(),
    };
  }

  function renderStrip(items) {
    el.strip.innerHTML = items.map((item) => {
      const c = clipToDay(item);
      return `<div class="seg" title="${FM.esc(item.activity_name)}" style="left:${c.leftPct}%;width:${c.widthPct}%;background:${FM.CATEGORIES[item.activity_type].color}"></div>`;
    }).join("");
  }

  function renderTimeline(items) {
    if (!items.length) {
      el.timeline.innerHTML = FM.emptyState("🗓️", "Nothing scheduled for this day", "Use the form above to add your first activity.");
      return;
    }
    el.timeline.innerHTML = items.map((item) => {
      const c = clipToDay(item);
      const cat = FM.CATEGORIES[item.activity_type];
      const endLabel = item.end_time ? FM.fmtTime(item.end_time) : "now";
      const notes = [c.fromPrevDay ? "↩ started the previous day" : "", c.toNextDay ? "continues next day ↪" : ""].filter(Boolean).join(" · ");
      const total = item.is_active ? "Running" : FM.fmtMinutes(item.duration_minutes);
      const partial = (c.fromPrevDay || c.toNextDay) ? ` (${FM.fmtMinutes(c.minutes)} on this day)` : "";
      const actions = item.is_active
        ? `<a class="btn small secondary" href="stopwatch.html">Open stopwatch</a>`
        : `<button class="btn small secondary" data-edit="${item.activity_id}">Edit</button><button class="btn small danger" data-delete="${item.activity_id}">Delete</button>`;
      return `<div class="t-item ${item.activity_type}">
        <div class="t-time">${FM.fmtTime(item.start_time)}<small>→ ${endLabel}</small></div>
        <div><div class="t-title">${cat.icon} ${FM.esc(item.activity_name)}</div>
          <div class="t-meta"><span class="badge ${item.activity_type}">${cat.label}</span> ${total}${partial} ${notes ? "· " + notes : ""}</div></div>
        <div class="t-actions">${actions}</div></div>`;
    }).join("");
  }

  let items = [];

  async function load() {
    try {
      FM.clearError();
      items = await FocusAPI.listActivities({ date: el.date.value });
      const used = Math.min(1440, items.reduce((sum, item) => sum + clipToDay(item).minutes, 0));
      el.totals.textContent = items.length ? `· tracked ${FM.fmtMinutes(used)} · free ${FM.fmtMinutes(1440 - used)}` : "";
      renderStrip(items); renderTimeline(items);
    } catch (error) { FM.showError(error); }
  }

  function resetForm() {
    editing = null;
    el.form.reset();
    el.title.textContent = "Add an activity";
    el.save.textContent = "Add";
    el.cancel.hidden = true;
  }

  function beginEdit(id) {
    const item = items.find((a) => a.activity_id === id);
    if (!item) return;
    editing = { id, date: item.start_time.slice(0, 10) }; // the date the activity STARTED
    el.name.value = item.activity_name;
    el.type.value = item.activity_type;
    el.start.value = FM.fmtTime(item.start_time);
    el.end.value = FM.fmtTime(item.end_time);
    el.title.textContent = `Edit activity (started ${editing.date})`;
    el.save.textContent = "Save changes";
    el.cancel.hidden = false;
    el.form.scrollIntoView({ behavior: "smooth", block: "center" });
    el.name.focus();
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    busy = true; el.save.disabled = true; FM.clearError();
    const payload = {
      activity_name: el.name.value.trim(), activity_type: el.type.value,
      activity_date: editing ? editing.date : el.date.value,
      start_time: el.start.value, end_time: el.end.value,
    };
    try {
      if (editing) await FocusAPI.updateActivity(editing.id, payload); else await FocusAPI.addActivity(payload);
      FM.toast(editing ? "Activity updated." : "Activity added.", "success");
      resetForm();
      await load();
    } catch (error) { FM.showError(error); FM.toast(error.message, "error"); }
    finally { busy = false; el.save.disabled = false; }
  }

  async function onTimelineClick(event) {
    const editId = event.target.dataset.edit, deleteId = event.target.dataset.delete;
    if (editId) return beginEdit(Number(editId));
    if (deleteId && confirm("Delete this activity permanently?")) {
      try { await FocusAPI.deleteActivity(Number(deleteId)); FM.toast("Activity deleted.", "success"); if (editing && editing.id === Number(deleteId)) resetForm(); await load(); }
      catch (error) { FM.showError(error); }
    }
  }

  el.form.addEventListener("submit", onSubmit);
  el.cancel.addEventListener("click", resetForm);
  el.timeline.addEventListener("click", onTimelineClick);
  el.date.addEventListener("change", () => { if (el.date.value) load(); });
  el.date.value = FM.todayISO();
  load();
})();
