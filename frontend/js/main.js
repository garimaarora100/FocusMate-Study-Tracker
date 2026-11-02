/* main.js - shared helpers + sidebar. Exposes window.FM. Loaded on every inner page. */
window.FM = (function () {
  "use strict";

  const CATEGORIES = {
    STUDY: { label: "Study", color: "var(--c-study)", icon: "📚" },
    SLEEP: { label: "Sleep", color: "var(--c-sleep)", icon: "😴" },
    FOOD: { label: "Food", color: "var(--c-food)", icon: "🍽️" },
    EXERCISE: { label: "Exercise", color: "var(--c-exercise)", icon: "🏃" },
    ENTERTAINMENT: { label: "Entertainment", color: "var(--c-entertainment)", icon: "🎬" },
    TRAVEL: { label: "Travel", color: "var(--c-travel)", icon: "🚌" },
    OTHER: { label: "Other", color: "var(--c-other)", icon: "📌" },
  };

  const PAGES = [
    { id: "dashboard", href: "dashboard.html", icon: "📊", label: "Dashboard" },
    { id: "stopwatch", href: "stopwatch.html", icon: "⏱️", label: "Study Stopwatch" },
    { id: "schedule", href: "schedule.html", icon: "🗓️", label: "Daily Schedule" },
    { id: "analytics", href: "analytics.html", icon: "📈", label: "Analytics" },
  ];

  const pad = (n) => String(n).padStart(2, "0");

  /** 135 -> "2h 15m", 45 -> "45m", 0 -> "0m" */
  function fmtMinutes(minutes) {
    const total = Math.round(Number(minutes) || 0);
    const h = Math.floor(total / 60), m = total % 60;
    return h ? `${h}h ${pad(m)}m` : `${m}m`;
  }

  /** seconds -> "HH:MM:SS" */
  function fmtClock(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds));
    return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  }

  /** Server timestamps have no timezone ("2026-01-05T09:30:00"); the Date constructor reads them as local time. */
  const parseTs = (iso) => new Date(iso);
  const fmtTime = (iso) => { const d = parseTs(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const fmtDateTime = (iso) => parseTs(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const toISODate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const todayISO = () => toISODate(new Date());

  /** Escape text before putting it in innerHTML (prevents XSS from activity names). */
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function toast(message, type = "info") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  function showError(error, boxId = "errorBox") {
    const box = document.getElementById(boxId);
    if (box) { box.textContent = error.message || String(error); box.style.display = "block"; }
    else toast(error.message || String(error), "error");
  }
  function clearError(boxId = "errorBox") {
    const box = document.getElementById(boxId);
    if (box) box.style.display = "none";
  }

  function emptyState(icon, title, text) {
    return `<div class="empty"><span class="icon">${icon}</span><strong>${esc(title)}</strong><div>${esc(text)}</div></div>`;
  }

  function renderSidebar() {
    const host = document.getElementById("sidebar");
    if (!host) return;
    const current = document.body.dataset.page;
    host.className = "sidebar";
    host.innerHTML =
      `<a class="brand" href="index.html"><span class="brand-mark">🎯</span>FocusMate</a>` +
      PAGES.map((p) => `<a class="nav-link ${p.id === current ? "active" : ""}" href="${p.href}"><span>${p.icon}</span>${p.label}</a>`).join("") +
      `<div class="sidebar-foot">Hi, ${esc(localStorage.getItem("focusmate_name") || "Student")} 👋<br>Oracle · FastAPI · pandas</div>`;
    const button = document.createElement("button");
    button.className = "menu-btn";
    button.setAttribute("aria-label", "Toggle menu");
    button.textContent = "☰";
    button.onclick = () => host.classList.toggle("open");
    document.body.appendChild(button);
  }

  document.addEventListener("DOMContentLoaded", renderSidebar);

  return { CATEGORIES, pad, fmtMinutes, fmtClock, parseTs, fmtTime, fmtDateTime, toISODate, todayISO, esc, toast, showError, clearError, emptyState };
})();
