/* api.js - the ONLY place that talks to the backend (Fetch API). Exposes window.FocusAPI. */
window.FocusAPI = (function () {
  "use strict";

  // Served by FastAPI (same origin) -> relative URLs. Opened from another dev server -> point at FastAPI.
  const BASE = window.FOCUSMATE_API_BASE !== undefined
    ? window.FOCUSMATE_API_BASE
    : (location.port === "8000" ? "" : "http://127.0.0.1:8000");

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function request(path, options = {}) {
    const init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    let response;
    try {
      response = await fetch(BASE + path, init);
    } catch (networkError) {
      throw new ApiError("Cannot reach the FocusMate server. Is it running?", 0);
    }
    let json = null;
    try { json = await response.json(); } catch (_) { /* non-JSON body */ }
    if (!response.ok || !json || json.success === false) {
      throw new ApiError((json && json.message) || `Request failed (${response.status})`, response.status);
    }
    return json.data;
  }

  const query = (params) => {
    const clean = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
    return clean.length ? "?" + new URLSearchParams(clean).toString() : "";
  };

  return {
    ApiError,
    health: () => request("/api/health"),
    // stopwatch
    startSession: (name) => request("/api/activity/start", { method: "POST", body: { activity_name: name } }),
    stopSession: () => request("/api/activity/stop", { method: "POST" }),
    getActive: () => request("/api/activity/active"),
    todaySummary: () => request("/api/activity/today-summary"),
    // activities
    addActivity: (payload) => request("/api/activity/add", { method: "POST", body: payload }),
    updateActivity: (id, payload) => request(`/api/activity/${id}`, { method: "PUT", body: payload }),
    deleteActivity: (id) => request(`/api/activity/${id}`, { method: "DELETE" }),
    listActivities: (params = {}) => request("/api/activity/list" + query(params)),
    daySummary: (date) => request("/api/activity/summary" + query({ date })),
    // analytics
    dailyAnalytics: (days) => request("/api/analytics/daily" + query({ days })),
    weeklyAnalytics: () => request("/api/analytics/weekly"),
    categoryAnalytics: (days) => request("/api/analytics/category-summary" + query({ days })),
    exportUrl: (kind, days) => BASE + "/api/analytics/export" + query({ kind, days }),
  };
})();
