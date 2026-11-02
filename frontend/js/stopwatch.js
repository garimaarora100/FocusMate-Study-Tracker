/* stopwatch.js - study stopwatch. The DATABASE is the source of truth:
   elapsed = (browser now + clock offset) - start timestamp stored in Oracle.
   Nothing is "counted up", so a refresh, a sleeping laptop or a throttled tab cannot drift. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CIRCUMFERENCE = 628.3; // 2 * PI * r (r = 100)
  const el = {
    card: $("watchCard"), clock: $("clock"), ring: $("ring"), startedAt: $("startedAt"), status: $("statusText"),
    start: $("startBtn"), stop: $("stopBtn"), name: $("sessionName"), notice: $("doneNotice"), today: $("todayTotal"),
  };

  let startMs = null;      // session start (ms), from Oracle
  let clockOffset = 0;     // (server clock - browser clock) in ms
  let tickTimer = null;
  let todayTimer = null;
  let busy = false;        // blocks double clicks while a request is in flight

  function setBusy(value) {
    busy = value;
    el.start.disabled = value;
    el.stop.disabled = value;
  }

  const elapsedSeconds = () => (Date.now() + clockOffset - startMs) / 1000;

  function tick() {
    const seconds = elapsedSeconds();
    el.clock.textContent = FM.fmtClock(seconds);
    el.ring.style.strokeDashoffset = String(CIRCUMFERENCE * (1 - (Math.max(seconds, 0) % 60) / 60));
    document.title = `${FM.fmtClock(seconds)} · FocusMate`;
  }

  function showRunning(session) {
    startMs = FM.parseTs(session.start_time).getTime();
    clockOffset = FM.parseTs(session.server_now).getTime() - Date.now();
    el.card.classList.add("running");
    el.status.textContent = "Study session in progress";
    el.startedAt.textContent = `Started ${FM.fmtDateTime(session.start_time)}`;
    el.name.value = session.activity_name;
    el.name.disabled = true;
    el.start.hidden = true;
    el.stop.hidden = false;
    clearInterval(tickTimer);
    tick();
    tickTimer = setInterval(tick, 250);
    clearInterval(todayTimer);
    todayTimer = setInterval(refreshToday, 30000); // keep "today" fresh while running
  }

  function showIdle() {
    startMs = null;
    clearInterval(tickTimer);
    clearInterval(todayTimer);
    el.card.classList.remove("running");
    el.status.textContent = "Idle";
    el.clock.textContent = "00:00:00";
    el.ring.style.strokeDashoffset = String(CIRCUMFERENCE);
    el.startedAt.textContent = "Not started";
    el.name.disabled = false;
    el.start.hidden = false;
    el.stop.hidden = true;
    document.title = "Study Stopwatch · FocusMate";
  }

  async function refreshToday() {
    try {
      const summary = await FocusAPI.todaySummary();
      el.today.textContent = FM.fmtMinutes(summary.study_minutes);
    } catch (error) { /* non-critical */ }
  }

  /** Ask the server what is happening and make the screen match. Used on load, refresh, after errors. */
  async function syncWithServer() {
    const session = await FocusAPI.getActive();
    if (session.active) showRunning(session); else showIdle();
    return session.active;
  }

  async function onStart() {
    if (busy) return;
    setBusy(true);
    FM.clearError();
    el.notice.style.display = "none";
    try {
      await FocusAPI.startSession(el.name.value.trim() || "Study Session");
      await syncWithServer();
      FM.toast("Study session started. Good luck! 📚", "success");
    } catch (error) {
      if (error.status === 409) { FM.toast("A session is already running; resuming it.", "info"); await syncWithServer().catch(() => {}); }
      else FM.showError(error);
    } finally { setBusy(false); refreshToday(); }
  }

  async function onStop() {
    if (busy) return;
    setBusy(true);
    FM.clearError();
    try {
      const result = await FocusAPI.stopSession();
      showIdle();
      el.notice.textContent = `✅ Session complete! You studied for ${FM.fmtMinutes(result.duration_minutes)} (${result.duration_minutes} min). It has been saved.`;
      el.notice.style.display = "block";
    } catch (error) {
      if (error.status === 404) { await syncWithServer().catch(() => {}); FM.toast("That session was already stopped.", "info"); }
      else FM.showError(error);
    } finally { setBusy(false); refreshToday(); }
  }

  el.start.addEventListener("click", onStart);
  el.stop.addEventListener("click", onStop);
  // Re-sync when the tab becomes visible again (e.g. session stopped from another tab).
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !busy) syncWithServer().catch(() => {}); });

  (async function init() {
    try { await syncWithServer(); } catch (error) { FM.showError(error); }
    refreshToday();
  })();
})();
