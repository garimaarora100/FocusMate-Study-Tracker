"""
Integration tests: FastAPI -> python-oracledb -> real Oracle PL/SQL.

 * Nothing is mocked. If Oracle is unreachable (or the SQL scripts are not installed) the
   database tests are SKIPPED, never faked as passed.
 * Test data uses the year 2001 and is deleted afterwards, so your real data is untouched.
 * Stopwatch tests are skipped if YOU currently have a study session running (they would
   otherwise have to stop it).

Run from the project root:   python -m pytest -v
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.main import app

client = TestClient(app)
DAY, NEXT_DAY = "2001-01-01", "2001-01-02"


def _database_ready() -> bool:
    try:
        database.fetch_all("SELECT COUNT(*) AS c FROM v_daily_activity_details WHERE 1 = 0")
        database.fetch_all("SELECT COUNT(*) AS c FROM user_procedures WHERE object_name = 'START_STUDY_SESSION'")
        return True
    except Exception:
        return False


DB_READY = _database_ready()
requires_db = pytest.mark.skipif(
    not DB_READY, reason="Oracle not reachable, .env not filled in, or SQL scripts not installed")


def payload(name="Test activity", kind="STUDY", day=DAY, start="09:00", end="10:30"):
    return {"activity_name": name, "activity_type": kind,
            "activity_date": day, "start_time": start, "end_time": end}


@pytest.fixture
def created_ids():
    """Collects IDs created by a test and deletes them afterwards."""
    ids = []
    yield ids
    client.post("/api/activity/stop")  # no-op (404) unless a test left a session open
    for activity_id in ids:
        client.delete(f"/api/activity/{activity_id}")


@pytest.fixture
def stopwatch(created_ids):
    if client.get("/api/activity/active").json()["data"]["active"]:
        pytest.skip("A real study session is running; not touching it.")
    return created_ids


def add(created_ids, **kwargs):
    response = client.post("/api/activity/add", json=payload(**kwargs))
    if response.status_code == 201:
        created_ids.append(response.json()["data"]["activity_id"])
    return response


# --------------------------------------------------------------------------- health
def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["data"]["api"] == "ok"


@requires_db
def test_database_connectivity_and_plsql_function():
    assert client.get("/api/health").json()["data"]["database"] == "connected"
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            import oracledb
            from datetime import datetime
            minutes = cur.callfunc("CALCULATE_DURATION", oracledb.DB_TYPE_NUMBER,
                                   [datetime(2001, 1, 1, 9, 0), datetime(2001, 1, 1, 10, 30)])
    assert float(minutes) == 90.0


# ----------------------------------------------------------------------- stopwatch
@requires_db
def test_start_session_and_block_duplicates(stopwatch):
    first = client.post("/api/activity/start", json={"activity_name": "Test session"})
    assert first.status_code == 201
    stopwatch.append(first.json()["data"]["activity_id"])
    second = client.post("/api/activity/start")
    assert second.status_code == 409


@requires_db
def test_rapid_repeated_starts_create_exactly_one_record(stopwatch):
    codes = [client.post("/api/activity/start").status_code for _ in range(4)]
    assert codes.count(201) == 1 and codes.count(409) == 3
    active = client.get("/api/activity/active").json()["data"]
    stopwatch.append(active["activity_id"])


@requires_db
def test_active_session_retrieval(stopwatch):
    assert client.get("/api/activity/active").json()["data"]["active"] is False
    started = client.post("/api/activity/start").json()["data"]
    stopwatch.append(started["activity_id"])
    active = client.get("/api/activity/active").json()["data"]
    assert active["active"] is True
    assert active["activity_id"] == started["activity_id"]
    assert active["start_time"] == started["start_time"] and active["server_now"]


@requires_db
def test_stop_session_and_today_summary(stopwatch):
    stopwatch.append(client.post("/api/activity/start").json()["data"]["activity_id"])
    time.sleep(1.5)
    stopped = client.post("/api/activity/stop")
    assert stopped.status_code == 200
    assert stopped.json()["data"]["duration_minutes"] > 0
    assert client.post("/api/activity/stop").status_code == 404          # nothing left to stop
    assert client.get("/api/activity/active").json()["data"]["active"] is False
    summary = client.get("/api/activity/today-summary").json()["data"]
    assert summary["study_minutes"] >= stopped.json()["data"]["duration_minutes"] - 0.01


# ------------------------------------------------------------------------ activities
@requires_db
def test_manual_activity_insert_and_daily_retrieval(created_ids):
    late = add(created_ids, name="Evening", kind="FOOD", start="19:00", end="19:45")
    early = add(created_ids, name="Morning study", start="09:00", end="10:30")
    assert early.status_code == 201 and early.json()["data"]["duration_minutes"] == 90.0
    listed = client.get("/api/activity/list", params={"date": DAY}).json()["data"]
    assert [a["activity_name"] for a in listed] == ["Morning study", "Evening"]   # chronological
    assert late.status_code == 201


@requires_db
def test_overnight_activity_is_split_across_days(created_ids):
    response = add(created_ids, name="Night sleep", kind="SLEEP", start="23:00", end="06:00")
    data = response.json()["data"]
    assert data["end_time"].startswith(NEXT_DAY) and data["duration_minutes"] == 420.0
    day1 = client.get("/api/activity/summary", params={"date": DAY}).json()["data"]
    day2 = client.get("/api/activity/summary", params={"date": NEXT_DAY}).json()["data"]
    assert day1["categories"]["SLEEP"]["minutes"] == 60.0
    assert day2["categories"]["SLEEP"]["minutes"] == 360.0
    assert client.get("/api/activity/list", params={"date": NEXT_DAY}).json()["data"]  # shows on both days


@requires_db
def test_daily_summary_calculation(created_ids):
    add(created_ids, name="Maths", start="09:00", end="10:30")
    add(created_ids, name="Gym", kind="EXERCISE", start="11:00", end="12:00")
    summary = client.get("/api/activity/summary", params={"date": DAY}).json()["data"]
    assert summary["categories"]["STUDY"]["minutes"] == 90.0
    assert summary["study_minutes"] == 90.0            # value produced by PL/SQL function
    assert summary["total_minutes"] == 150.0
    assert summary["untracked_minutes"] == 1290.0
    assert summary["total_activities"] == 2


@requires_db
def test_overlap_is_rejected(created_ids):
    add(created_ids, start="09:00", end="10:00")
    assert add(created_ids, name="Clash", start="09:30", end="10:30").status_code == 409
    assert add(created_ids, name="Back to back", start="10:00", end="11:00").status_code == 201


@requires_db
def test_input_validation(created_ids):
    assert add(created_ids, kind="GAMING").status_code == 422
    assert add(created_ids, name="   ").status_code == 422
    assert add(created_ids, start="09:00", end="09:00").status_code == 400
    assert client.post("/api/activity/add", json={"activity_name": "x"}).status_code == 422


@requires_db
def test_edit_and_delete_activity(created_ids):
    activity_id = add(created_ids, name="Original").json()["data"]["activity_id"]
    edited = client.put(f"/api/activity/{activity_id}", json=payload(name="Edited", end="11:00"))
    assert edited.status_code == 200 and edited.json()["data"]["duration_minutes"] == 120.0
    assert client.get("/api/activity/list", params={"date": DAY}).json()["data"][0]["activity_name"] == "Edited"
    assert client.delete(f"/api/activity/{activity_id}").status_code == 200
    assert client.delete(f"/api/activity/{activity_id}").status_code == 404


# -------------------------------------------------------------------------- analytics
@requires_db
def test_analytics_endpoints_and_csv_export():
    for path in ("daily", "weekly", "category-summary"):
        response = client.get(f"/api/analytics/{path}")
        assert response.status_code == 200 and response.json()["success"] is True
    assert client.get("/api/analytics/daily", params={"days": 0}).status_code == 422
    for kind in ("detail", "daily", "category"):
        export = client.get("/api/analytics/export", params={"kind": kind, "days": 7})
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("text/csv")
        assert len(export.text.splitlines()) >= 1                               # at least the header
