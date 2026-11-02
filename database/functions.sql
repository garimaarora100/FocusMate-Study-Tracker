-- =====================================================================
-- FocusMate - PL/SQL functions (CREATE OR REPLACE: safe to re-run)
-- =====================================================================
CREATE OR REPLACE FUNCTION calculate_duration (
  p_start IN TIMESTAMP,
  p_end   IN TIMESTAMP
) RETURN NUMBER DETERMINISTIC
IS
  v_interval INTERVAL DAY TO SECOND;
BEGIN
  IF p_start IS NULL OR p_end IS NULL THEN
    RETURN NULL;
  END IF;
  IF p_end <= p_start THEN
    RAISE_APPLICATION_ERROR(-20003, 'End time must be after start time.');
  END IF;
  v_interval := p_end - p_start;   -- TIMESTAMP - TIMESTAMP = INTERVAL DAY TO SECOND
  RETURN ROUND(
      EXTRACT(DAY    FROM v_interval) * 1440
    + EXTRACT(HOUR   FROM v_interval) * 60
    + EXTRACT(MINUTE FROM v_interval)
    + EXTRACT(SECOND FROM v_interval) / 60, 2);
END calculate_duration;
/

-- Total STUDY minutes inside one calendar day. Each session is clipped to the
-- day boundaries, so a session crossing midnight is split between the two days.
-- A still-running session counts up to "now".
CREATE OR REPLACE FUNCTION get_daily_study_minutes (
  p_date IN DATE
) RETURN NUMBER
IS
  v_day_start DATE := TRUNC(p_date);
  v_day_end   DATE := TRUNC(p_date) + 1;
  v_total     NUMBER;
BEGIN
  SELECT NVL(SUM(GREATEST(0,
           (LEAST(NVL(CAST(end_time AS DATE), SYSDATE), v_day_end)
            - GREATEST(CAST(start_time AS DATE), v_day_start)) * 1440)), 0)
    INTO v_total
    FROM activity
   WHERE activity_type = 'STUDY'
     AND CAST(start_time AS DATE) < v_day_end
     AND NVL(CAST(end_time AS DATE), SYSDATE) > v_day_start;
  RETURN ROUND(v_total, 2);
END get_daily_study_minutes;
/
