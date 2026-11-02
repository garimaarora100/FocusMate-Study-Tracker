# 🎯 FocusMate – Smart Study Time and Daily Activity Tracker

A study-time and 24-hour activity tracker for students.
**Stack:** HTML/CSS/Vanilla JS · Python · FastAPI · Oracle (SQL + PL/SQL) · python-oracledb · pandas

```
Browser (HTML/CSS/JS, Fetch API)
        │  JSON over HTTP
        ▼
FastAPI  backend/main.py            routes, status codes, error handlers
        │
        ├── activity_service.py     business logic ──► calls PL/SQL procedures & function
        └── analytics_service.py    pandas DataFrames, groupby, CSV
                 │
          database.py               connection pool, transactions, .env credentials
                 │  python-oracledb
                 ▼
Oracle FREEPDB1   tables · unique index · PL/SQL procedures/functions · views
```

---

## 1. Prerequisites

* Python **3.10+**
* Oracle AI Database Free running locally (service `FREEPDB1`, port 1521)
* VS Code (optional) – python-oracledb uses *thin mode*, so **no Oracle Client install is needed**

## 2. Installation

```bash
# from the FocusMate folder
python -m venv .venv
.venv\Scripts\activate          # Windows      (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

## 3. Database setup

### 3.1 Create a database user (once)

Connect as an administrator to the pluggable database (SQL Developer, SQLcl or SQL*Plus) and run:

```sql
-- sqlplus system/<your_admin_password>@localhost:1521/FREEPDB1
CREATE USER focusmate IDENTIFIED BY "ChooseAStrongPassword1";
GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE SEQUENCE TO focusmate;
ALTER USER focusmate QUOTA UNLIMITED ON USERS;
```

(Or use any existing schema that has those privileges.)

### 3.2 Create and fill in `.env`

The zip deliberately contains **no** `.env` (so it can never overwrite yours). Copy `.env.example` to `.env`, then edit it:

```
ORACLE_USER=focusmate
ORACLE_PASSWORD=ChooseAStrongPassword1
ORACLE_DSN=localhost:1521/FREEPDB1
```

`.env` is in `.gitignore`; never commit it. `.env.example` is the template.

### 3.3 Install the tables, PL/SQL and views

```bash
python -m backend.database check    # should print: Connected to Oracle.
python -m backend.database setup    # creates tables, functions, procedures, views
python -m backend.database sample   # OPTIONAL: 7 days of demo data
```

`setup` runs, in order: `create_tables.sql → functions.sql → procedures.sql → views.sql`
and then reports any PL/SQL compile errors.
You can also run the same files manually in SQL Developer / SQL*Plus (`@database/create_tables.sql`, …).

**The scripts never DROP anything** – tables/indexes use "ignore if already exists" blocks,
procedures/functions/views use `CREATE OR REPLACE`. Re-running is safe.
Remove demo data later with: `DELETE FROM activity WHERE activity_name LIKE '[Sample]%'; COMMIT;`

## 4. Run the application

```bash
uvicorn backend.main:app --reload
```

| URL | What |
|---|---|
| http://127.0.0.1:8000 | The web app (FastAPI also serves the `frontend/` folder) |
| http://127.0.0.1:8000/docs | Automatic interactive API documentation (Swagger UI) |

## 5. Run the tests

```bash
python -m pytest -v
```

* `tests/test_analytics.py` – pandas logic on a small hand-made dataset (no Oracle needed).
* `tests/test_api.py` – real FastAPI → Oracle → PL/SQL tests. **They skip (not fake-pass) if Oracle is unreachable.**
  They use dates in 2001 and delete what they create; they also refuse to run the stopwatch tests if you have a real session running.

---

## 6. Database design

**Table `ACTIVITY`**

| Column | Type | Notes |
|---|---|---|
| ACTIVITY_ID | NUMBER identity | primary key, auto-generated |
| ACTIVITY_NAME | VARCHAR2(100) | not blank |
| ACTIVITY_TYPE | VARCHAR2(20) | CHECK in STUDY, SLEEP, FOOD, EXERCISE, ENTERTAINMENT, TRAVEL, OTHER |
| START_TIME | TIMESTAMP(0) | full date + time |
| END_TIME | TIMESTAMP(0) | NULL while a stopwatch session is running |
| DURATION_MINUTES | NUMBER(8,2) | set by `CALCULATE_DURATION` |
| CREATED_AT | TIMESTAMP | default `SYSTIMESTAMP` |

Key constraints
* `end_time > start_time` → no negative / zero intervals.
* `duration_minutes` between 0 and 1440 → no activity longer than 24 h.
* Open (NULL end) rows are only allowed for `STUDY`; end and duration are NULL together or set together.
* **`uq_one_active_study`** – a *function-based unique index*:
  `CASE WHEN activity_type='STUDY' AND end_time IS NULL THEN 1 END`.
  All running study sessions map to `1`, everything else to `NULL` (not indexed) – so the **database itself** refuses a second running session, even if two requests arrive at the same instant.
* Indexes on `start_time` and `(activity_type, start_time)`.
* No foreign keys: the project has a single entity and the category list is small and fixed, so a CHECK constraint is simpler and just as safe.

**Midnight crossing:** timestamps include the date, so `23:00 → 06:30` is stored as two real timestamps on different days. The view `V_DAILY_ACTIVITY_DETAILS` then *splits* each activity per calendar day (60 min on day 1, 390 min on day 2) so daily totals are right.

**Views**
* `V_DAILY_ACTIVITY_DETAILS` – one row per activity per day it touches, with `MINUTES_IN_DAY`.
* `V_DAILY_ACTIVITY_SUMMARY` – per day and category: activity count and total minutes.

## 7. PL/SQL objects

| Object | Purpose |
|---|---|
| `START_STUDY_SESSION(name IN, id OUT, start OUT)` | Inserts an open STUDY row using the **database clock**; the unique index → error −20001 if one is already running |
| `STOP_STUDY_SESSION(id OUT, end OUT, minutes OUT)` | `SELECT … FOR UPDATE` locks the running row, sets end time, calls `CALCULATE_DURATION`; −20002 if none. Caps forgotten sessions at 24 h |
| `ADD_MANUAL_ACTIVITY(name, type, start, end, id OUT, minutes OUT)` | Validates, rejects overlaps, inserts |
| `UPDATE_ACTIVITY`, `DELETE_ACTIVITY` | Safe edit/delete (cannot touch a running session) |
| `VALIDATE_ACTIVITY_INPUT` | Shared validation: name, category, end > start, ≤ 24 h, overlap check |
| `CALCULATE_DURATION(start, end) → NUMBER` | Minutes between two timestamps (via `INTERVAL DAY TO SECOND` + `EXTRACT`) |
| `GET_DAILY_STUDY_MINUTES(date) → NUMBER` | Study minutes within one day, clipped at day boundaries; running session counts up to now |

Custom errors: `−20001` already active · `−20002` none active · `−20003` invalid input · `−20004` overlap · `−20005` not found · `−20006` still running.
`activity_service.py` translates these into HTTP **409 / 404 / 400**.
Procedures never commit – Python's `transaction()` commits on success and rolls back on any exception.

## 8. How Python calls PL/SQL (viva answer)

```python
with transaction() as conn:                         # borrow connection; COMMIT or ROLLBACK at the end
    with conn.cursor() as cur:
        out_id    = cur.var(oracledb.DB_TYPE_NUMBER)      # placeholders for OUT parameters
        out_start = cur.var(oracledb.DB_TYPE_TIMESTAMP)
        cur.callproc("START_STUDY_SESSION", [name, out_id, out_start])   # call the procedure
        new_id = out_id.getvalue()                       # read what PL/SQL returned
# function call:
cur.callfunc("GET_DAILY_STUDY_MINUTES", oracledb.DB_TYPE_NUMBER, [some_date])
```
All SELECTs use **bind variables** (`:day_start`) – never string concatenation – so SQL injection is not possible.

## 9. How the stopwatch works

1. **Start** → `POST /api/activity/start` → Oracle stores the start timestamp (an open STUDY row).
2. The browser never counts seconds. Every 250 ms it computes `elapsed = (now + clockOffset) − startTimestamp`.
   `clockOffset` = `server_now − browser now`, measured when the page loads, so even a wrong PC clock cannot distort the timer.
3. **Refresh / reopen** → the page calls `GET /api/activity/active`; if a row is open it resumes with the correct elapsed time.
4. **Double-click safety** → the button is disabled while the request is in flight, **and** the database unique index rejects a duplicate (HTTP 409), so two clicks / two tabs can never create two sessions.
5. **Stop** → `POST /api/activity/stop` → `STOP_STUDY_SESSION` writes end time + duration.

## 10. pandas implementation (`backend/analytics_service.py`)

```
Oracle view ──fetch_all()──► list of dicts ──► pd.DataFrame
```
| Requirement | Where |
|---|---|
| DataFrame creation | `build_dataframe()` – `pd.DataFrame(rows, columns=…)`, typed with `to_datetime` / `astype` |
| Filtering | `df[df["activity_type"] == "STUDY"]` |
| `groupby()` | `study.groupby("activity_date")["minutes_in_day"].sum()` |
| `sum()`, `mean()`, `count()` | `category_frame()`: first `groupby(["activity_date","activity_type"]).sum()` (minutes per day per category), then `groupby("activity_type").agg(total=("sum"), avg per day=("mean"), days_recorded=("count"))` |
| Daily study analysis | `daily_study_series()` – `reindex(date_range, fill_value=0)` so days with no study appear as 0 |
| Weekly analysis | `weekly_analysis()` – last 7 days + 4 rolling 7-day buckets via integer division of day differences |
| Descriptive statistics | `series.describe()` (count, mean, std, min, 25 %, 50 %, 75 %, max) |
| Pivot / daily report | `df.pivot_table(index=date, columns=category, aggfunc="sum")` |
| 24 h safety cap | `.clip(upper=1440)` on daily totals |
| CSV export | `DataFrame.to_csv()` → saved in `reports/` and streamed to the browser |

Three CSV report kinds: `detail`, `daily` (one row per day, one column per category + TOTAL), `category`.
Text cells starting with `= + - @` are prefixed with `'` to prevent spreadsheet formula injection.

## 11. API reference

All responses: `{"success": true|false, "message": "...", "data": ...}`

| Method | Endpoint | Description | Codes |
|---|---|---|---|
| GET | `/api/health` | API + database status | 200 |
| POST | `/api/activity/start` | Start study session `{activity_name?}` | 201, 409 already running |
| POST | `/api/activity/stop` | Stop running session | 200, 404 none running |
| GET | `/api/activity/active` | Running session (+ `server_now`) or `active:false` | 200 |
| GET | `/api/activity/today-summary` | Today's study minutes (PL/SQL function) | 200 |
| POST | `/api/activity/add` | Manual activity `{activity_name, activity_type, activity_date, start_time, end_time}` | 201, 400, 409 overlap, 422 |
| PUT | `/api/activity/{id}` | Edit (same body) | 200, 404, 400, 409 |
| DELETE | `/api/activity/{id}` | Delete | 200, 404, 400 |
| GET | `/api/activity/list?date=&limit=` | Activities of a day (chronological) or recent ones | 200 |
| GET | `/api/activity/summary?date=` | Minutes per category for a day | 200 |
| GET | `/api/analytics/daily?days=30` | Daily study series, average, descriptive stats | 200, 422 |
| GET | `/api/analytics/weekly` | Last 7 days + 4 weekly totals | 200 |
| GET | `/api/analytics/category-summary?days=30` | Category sum/mean/count, top category | 200 |
| GET | `/api/analytics/export?days=30&kind=detail\|daily\|category` | Download CSV | 200 |

Example – overnight activity: `end_time` earlier than `start_time` means "next day":
```json
{"activity_name":"Night sleep","activity_type":"SLEEP","activity_date":"2026-03-01","start_time":"23:00","end_time":"06:30"}
```

## 12. Project structure

```
FocusMate/
├── frontend/   index, dashboard, stopwatch, schedule, analytics (.html) + css/style.css + js/*.js
├── backend/    main.py · database.py · activity_service.py · analytics_service.py · schemas.py
├── database/   create_tables.sql · functions.sql · procedures.sql · views.sql · sample_data.sql
├── reports/    generated CSV files
├── tests/      test_api.py · test_analytics.py
├── .env  .env.example  .gitignore  requirements.txt  README.md
```

## 13. Known limitations

* No authentication: one shared dataset for everyone using the server (planned for a later version).
* The stopwatch does not check overlap with manual activities when it starts (the schedule form does check). Analytics cap each day at 1440 minutes as a safety net.
* Table-level lock (`SHARE ROW EXCLUSIVE`) serialises manual adds/edits to guarantee overlap-safety – ideal for a single-user app, not for thousands of concurrent users.
* A stopwatch session left running for more than 24 h is capped at 24 h when stopped.
* "Today" and all clocks use the database server's time zone.
* Charts are built with plain HTML/CSS (no chart library) by design.
