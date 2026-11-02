"""FocusMate FastAPI application: routes only. Logic lives in the service modules."""
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import oracledb
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import activity_service as acts
from backend import analytics_service as stats
from backend.database import DatabaseConfigError, check_connection, close_pool
from backend.schemas import ActivityRequest, StartSessionRequest

logger = logging.getLogger("focusmate")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_pool()          # release Oracle connections on shutdown


app = FastAPI(title="FocusMate API", version="1.0.0", lifespan=lifespan,
              description="Study time and daily activity tracker (FastAPI + Oracle PL/SQL + pandas)")

# Lets the pages work even if opened from another local dev server (e.g. VS Code Live Server).
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


def ok(data=None, message: str = "OK") -> dict:
    """Every successful response has the same shape."""
    return {"success": True, "message": message, "data": data}


def fail(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "message": message, "data": None})


# ------------------------------ error handlers ------------------------------
@app.exception_handler(acts.ServiceError)
async def service_error_handler(_: Request, exc: acts.ServiceError):
    return fail(exc.status_code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p not in ("body", "query"))
    return fail(422, f"{field}: {first['msg']}" if field else first["msg"])


@app.exception_handler(DatabaseConfigError)
async def config_error_handler(_: Request, exc: DatabaseConfigError):
    return fail(503, str(exc))


@app.exception_handler(oracledb.Error)
async def oracle_error_handler(_: Request, exc: oracledb.Error):
    logger.exception("Oracle error")          # details go to the log, not to the browser
    return fail(503, "Database error. Check that Oracle is running and the scripts are installed.")


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    logger.exception("Unexpected error")
    return fail(500, "Unexpected server error.")


# ------------------------------ health --------------------------------------
@app.get("/api/health", tags=["System"])
def health():
    try:
        database = "connected" if check_connection() else "unavailable"
    except Exception as exc:  # health must never crash
        logger.warning("Health check DB failure: %s", exc)
        database = "unavailable"
    return ok({"api": "ok", "database": database})


# ------------------------------ stopwatch -----------------------------------
@app.post("/api/activity/start", status_code=201, tags=["Stopwatch"])
def start_session(body: StartSessionRequest | None = None):
    name = body.activity_name if body else "Study Session"
    return ok(acts.start_study_session(name), "Study session started.")


@app.post("/api/activity/stop", tags=["Stopwatch"])
def stop_session():
    return ok(acts.stop_study_session(), "Study session stopped.")


@app.get("/api/activity/active", tags=["Stopwatch"])
def active_session():
    return ok(acts.get_active_session())


@app.get("/api/activity/today-summary", tags=["Stopwatch"])
def today_summary():
    return ok(acts.get_today_summary())


# ------------------------------ activities ----------------------------------
@app.post("/api/activity/add", status_code=201, tags=["Activities"])
def add_activity(body: ActivityRequest):
    result = acts.add_activity(body.activity_name, body.activity_type,
                               body.activity_date, body.start_time, body.end_time)
    return ok(result, "Activity added.")


@app.put("/api/activity/{activity_id}", tags=["Activities"])
def update_activity(activity_id: int, body: ActivityRequest):
    result = acts.update_activity(activity_id, body.activity_name, body.activity_type,
                                  body.activity_date, body.start_time, body.end_time)
    return ok(result, "Activity updated.")


@app.delete("/api/activity/{activity_id}", tags=["Activities"])
def delete_activity(activity_id: int):
    acts.delete_activity(activity_id)
    return ok(None, "Activity deleted.")


@app.get("/api/activity/list", tags=["Activities"])
def list_activities(date_: date | None = Query(None, alias="date"),
                    limit: int = Query(100, ge=1, le=500)):
    return ok(acts.list_activities(date_, limit))


@app.get("/api/activity/summary", tags=["Activities"])
def activity_summary(date_: date | None = Query(None, alias="date")):
    return ok(acts.get_day_summary(date_ or acts.db_today()))


# ------------------------------ analytics (pandas) --------------------------
def _range(days: int) -> tuple[date, date]:
    end = acts.db_today()
    return end - timedelta(days=days - 1), end


@app.get("/api/analytics/daily", tags=["Analytics"])
def analytics_daily(days: int = Query(30, ge=1, le=365)):
    start, end = _range(days)
    return ok(stats.daily_analysis(stats.load_activity_dataframe(start, end), start, end))


@app.get("/api/analytics/weekly", tags=["Analytics"])
def analytics_weekly():
    today = acts.db_today()
    df = stats.load_activity_dataframe(today - timedelta(days=27), today)
    return ok(stats.weekly_analysis(df, today))


@app.get("/api/analytics/category-summary", tags=["Analytics"])
def analytics_categories(days: int = Query(30, ge=1, le=365)):
    start, end = _range(days)
    result = stats.category_analysis(stats.load_activity_dataframe(start, end))
    result.update(start_date=start.isoformat(), end_date=end.isoformat())
    return ok(result)


@app.get("/api/analytics/export", tags=["Analytics"])
def analytics_export(days: int = Query(30, ge=1, le=365),
                     kind: Literal["detail", "daily", "category"] = "detail"):
    start, end = _range(days)
    path, name = stats.export_csv(stats.load_activity_dataframe(start, end), kind, start, end)
    return FileResponse(path, media_type="text/csv", filename=name)


# ------------------------------ frontend (must be last) ---------------------
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
