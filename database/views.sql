-- =====================================================================
-- FocusMate - views (CREATE OR REPLACE: safe to re-run)
-- =====================================================================

-- One row per activity PER CALENDAR DAY it touches. An activity from 23:00 to 06:30
-- yields two rows: 60 minutes on day 1 and 390 minutes on day 2. This is how
-- midnight crossing and the 24-hour daily cap are handled. Max activity length is
-- 24 h, so an activity touches at most 2 calendar days (offset n = 0 or 1).
CREATE OR REPLACE VIEW v_daily_activity_details AS
WITH bounds AS (
  SELECT a.activity_id, a.activity_name, a.activity_type, a.start_time, a.end_time,
         CAST(a.start_time AS DATE)          AS s_dt,
         NVL(CAST(a.end_time AS DATE), SYSDATE) AS e_dt
    FROM activity a
), offsets AS (
  SELECT 0 AS n FROM dual UNION ALL SELECT 1 FROM dual
)
SELECT b.activity_id, b.activity_name, b.activity_type, b.start_time, b.end_time,
       TRUNC(b.s_dt) + o.n AS activity_date,
       ROUND((LEAST(b.e_dt, TRUNC(b.s_dt) + o.n + 1)
              - GREATEST(b.s_dt, TRUNC(b.s_dt) + o.n)) * 1440, 2) AS minutes_in_day,
       CASE WHEN b.end_time IS NULL THEN 'Y' ELSE 'N' END AS is_active
  FROM bounds b
  JOIN offsets o ON TRUNC(b.s_dt) + o.n < b.e_dt
/

CREATE OR REPLACE VIEW v_daily_activity_summary AS
SELECT activity_date                       AS summary_date,
       activity_type,
       COUNT(DISTINCT activity_id)         AS activity_count,
       ROUND(SUM(minutes_in_day), 2)       AS total_minutes
  FROM v_daily_activity_details
 GROUP BY activity_date, activity_type
/
