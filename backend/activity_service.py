"""
Activity business logic. Every write goes through a PL/SQL stored procedure, and the
daily study total comes from the PL/SQL function GET_DAILY_STUDY_MINUTES.

How a PL/SQL call works from Python (python-oracledb):
    out_id = cur.var(oracledb.DB_TYPE_NUMBER)      # placeholder for an OUT parameter
    cur.callproc("START_STUDY_SESSION", [name, out_id, out_ts])
    new_id = out_id.getvalue()                     # read the value PL/SQL produced
    cur.callfunc("GET_DAILY_STUDY_MINUTES", oracledb.DB_TYPE_NUMBER, [day])   # function
"""
import functools
import re
from datetime import date, datetime, time, timedelta

import oracledb

from backend.database import fetch_all, transaction
from backend.schemas import CATEGORIES

MINUTES_PER_DAY = 1440


# ----------------------------- exceptions -----------------------------------
class ServiceError(Exception):
    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BadRequestError(ServiceError):
    status_code = 400


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    status_code = 409


# Custom PL/SQL error numbers (RAISE_APPLICATION_ERROR) -> HTTP-friendly exceptions
_ORACLE_ERROR_MAP = {
    20001: ConflictError,    # study session already active
    20002: NotFoundError,    # no active study session
    20003: BadRequestError,  # invalid input
    20004: ConflictError,    # overlapping activity
    20005: NotFoundError,    # activity not found
    20006: BadRequestError,  # activity still running
    1: ConflictError,        # ORA-00001 unique constraint (race condition safety net)
}


def translate_oracle_errors(func):
    """Turn known Oracle errors into clean service exceptions; re-raise anything else."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except oracledb.DatabaseError as exc:
            error = exc.args[0] if exc.args else None
            code = getattr(error, "code", None)
            if code in _ORACLE_ERROR_MAP:
                first_line = str(getattr(error, "message", exc)).splitlines()[0]
                text = re.sub(r"^ORA-\d+:\s*", "", first_line)
                if code == 1:
                    text = "A study session is already active."
                raise _ORACLE_ERROR_MAP[code](text) from exc
            raise

    return wrapper


# ----------------------------- helpers --------------------------------------
def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _to_float(value) -> float | None:
    return None if value is None else round(float(value), 2)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def resolve_times(day: date, start_t: time, end_t: time) -> tuple[datetime, datetime]:
    """Build full timestamps. If the end clock time is earlier than the start, the activity
    runs past midnight and ends on the next day (e.g. 23:00 -> 06:30)."""
    if start_t == end_t:
        raise BadRequestError("Start and end time must be different.")
    start_dt = datetime.combine(day, start_t.replace(second=0, microsecond=0))
    end_dt = datetime.combine(day, end_t.replace(second=0, microsecond=0))
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _serialise(row: dict) -> dict:
    return {
        "activity_id": int(row["activity_id"]),
        "activity_name": row["activity_name"],
        "activity_type": row["activity_type"],
        "start_time": _iso(row["start_time"]),
        "end_time": _iso(row["end_time"]),
        "duration_minutes": _to_float(row["duration_minutes"]),
        "is_active": row["end_time"] is None,
    }


def db_now() -> datetime:
    return fetch_all("SELECT CAST(SYSDATE AS TIMESTAMP) AS now_ts FROM dual")[0]["now_ts"]


def db_today() -> date:
    return fetch_all("SELECT TRUNC(SYSDATE) AS today FROM dual")[0]["today"].date()


# ----------------------------- stopwatch ------------------------------------
@translate_oracle_errors
def start_study_session(name: str) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            out_id = cur.var(oracledb.DB_TYPE_NUMBER)
            out_start = cur.var(oracledb.DB_TYPE_TIMESTAMP)
            cur.callproc("START_STUDY_SESSION", [name, out_id, out_start])
            return {
                "activity_id": int(out_id.getvalue()),
                "activity_name": name,
                "start_time": _iso(out_start.getvalue()),
            }


@translate_oracle_errors
def stop_study_session() -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            out_id = cur.var(oracledb.DB_TYPE_NUMBER)
            out_end = cur.var(oracledb.DB_TYPE_TIMESTAMP)
            out_minutes = cur.var(oracledb.DB_TYPE_NUMBER)
            cur.callproc("STOP_STUDY_SESSION", [out_id, out_end, out_minutes])
            return {
                "activity_id": int(out_id.getvalue()),
                "end_time": _iso(out_end.getvalue()),
                "duration_minutes": _to_float(out_minutes.getvalue()),
            }


def get_active_session() -> dict:
    """The database is the source of truth, so a refreshed browser can recover its timer.
    server_now lets the browser correct for any difference between its clock and the DB."""
    rows = fetch_all(
        """SELECT activity_id, activity_name, start_time,
                  CAST(SYSDATE AS TIMESTAMP) AS server_now
             FROM activity
            WHERE activity_type = 'STUDY' AND end_time IS NULL"""
    )
    if not rows:
        return {"active": False, "server_now": _iso(db_now())}
    row = rows[0]
    return {
        "active": True,
        "activity_id": int(row["activity_id"]),
        "activity_name": row["activity_name"],
        "start_time": _iso(row["start_time"]),
        "server_now": _iso(row["server_now"]),
    }


def get_study_minutes(day: date) -> float:
    """Call the PL/SQL FUNCTION GET_DAILY_STUDY_MINUTES."""
    with transaction() as conn:
        with conn.cursor() as cur:
            value = cur.callfunc(
                "GET_DAILY_STUDY_MINUTES",
                oracledb.DB_TYPE_NUMBER,
                [datetime.combine(day, time.min)],
            )
            return round(float(value or 0), 2)


def get_today_summary() -> dict:
    today = db_today()
    active = get_active_session()
    return {
        "date": today.isoformat(),
        "study_minutes": get_study_minutes(today),
        "session_active": active["active"],
    }


# ----------------------------- activities -----------------------------------
@translate_oracle_errors
def add_activity(name: str, activity_type: str, day: date, start_t: time, end_t: time) -> dict:
    start_dt, end_dt = resolve_times(day, start_t, end_t)
    with transaction() as conn:
        with conn.cursor() as cur:
            out_id = cur.var(oracledb.DB_TYPE_NUMBER)
            out_minutes = cur.var(oracledb.DB_TYPE_NUMBER)
            cur.callproc(
                "ADD_MANUAL_ACTIVITY",
                [name, activity_type, start_dt, end_dt, out_id, out_minutes],
            )
            return {
                "activity_id": int(out_id.getvalue()),
                "start_time": _iso(start_dt),
                "end_time": _iso(end_dt),
                "duration_minutes": _to_float(out_minutes.getvalue()),
            }


@translate_oracle_errors
def update_activity(activity_id: int, name: str, activity_type: str,
                    day: date, start_t: time, end_t: time) -> dict:
    start_dt, end_dt = resolve_times(day, start_t, end_t)
    with transaction() as conn:
        with conn.cursor() as cur:
            out_minutes = cur.var(oracledb.DB_TYPE_NUMBER)
            cur.callproc(
                "UPDATE_ACTIVITY",
                [activity_id, name, activity_type, start_dt, end_dt, out_minutes],
            )
            return {
                "activity_id": activity_id,
                "start_time": _iso(start_dt),
                "end_time": _iso(end_dt),
                "duration_minutes": _to_float(out_minutes.getvalue()),
            }


@translate_oracle_errors
def delete_activity(activity_id: int) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.callproc("DELETE_ACTIVITY", [activity_id])


def list_activities(day: date | None = None, limit: int = 100) -> list[dict]:
    """With a date: every activity touching that day, in time order (incl. overnight ones).
    Without a date: the most recent activities first."""
    if day is not None:
        day_start, day_end = _day_bounds(day)
        rows = fetch_all(
            """SELECT activity_id, activity_name, activity_type, start_time, end_time, duration_minutes
                 FROM activity
                WHERE start_time < :day_end
                  AND NVL(end_time, CAST(SYSDATE AS TIMESTAMP)) > :day_start
                ORDER BY start_time""",
            {"day_start": day_start, "day_end": day_end},
        )
    else:
        rows = fetch_all(
            """SELECT activity_id, activity_name, activity_type, start_time, end_time, duration_minutes
                 FROM activity
                ORDER BY start_time DESC
                FETCH FIRST :max_rows ROWS ONLY""",
            {"max_rows": limit},
        )
    return [_serialise(r) for r in rows]


def get_day_summary(day: date) -> dict:
    """Minutes per category for one day (from the view) plus the PL/SQL study total."""
    rows = fetch_all(
        """SELECT activity_type, activity_count, total_minutes
             FROM v_daily_activity_summary
            WHERE summary_date = :day""",
        {"day": datetime.combine(day, time.min)},
    )
    categories = {c: {"minutes": 0.0, "count": 0} for c in CATEGORIES}
    for row in rows:
        categories[row["activity_type"]] = {
            "minutes": round(float(row["total_minutes"]), 2),
            "count": int(row["activity_count"]),
        }
    total = min(sum(c["minutes"] for c in categories.values()), MINUTES_PER_DAY)  # 24 h cap
    waking = max(total - categories["SLEEP"]["minutes"], 0)
    study = get_study_minutes(day)
    return {
        "date": day.isoformat(),
        "categories": categories,
        "total_minutes": round(total, 2),
        "untracked_minutes": round(MINUTES_PER_DAY - total, 2),
        "total_activities": sum(c["count"] for c in categories.values()),
        "study_minutes": study,
        "study_share_of_waking_pct": round(study / waking * 100, 1) if waking > 0 else None,
    }
