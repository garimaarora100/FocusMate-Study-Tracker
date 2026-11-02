-- =====================================================================
-- FocusMate - PL/SQL stored procedures (CREATE OR REPLACE: safe to re-run)
-- Error codes raised to Python:
--   -20001 study session already active     -20002 no active study session
--   -20003 invalid input                    -20004 overlaps another activity
--   -20005 activity not found               -20006 activity still running
-- Procedures never COMMIT; the Python layer owns the transaction.
-- =====================================================================

-- Shared validation used by ADD_MANUAL_ACTIVITY and UPDATE_ACTIVITY.
CREATE OR REPLACE PROCEDURE validate_activity_input (
  p_name       IN VARCHAR2,
  p_type       IN VARCHAR2,
  p_start      IN TIMESTAMP,
  p_end        IN TIMESTAMP,
  p_exclude_id IN NUMBER DEFAULT NULL
)
IS
  v_count NUMBER;
BEGIN
  IF p_name IS NULL OR LENGTH(TRIM(p_name)) = 0 OR LENGTH(TRIM(p_name)) > 100 THEN
    RAISE_APPLICATION_ERROR(-20003, 'Activity name must be 1 to 100 characters.');
  END IF;
  IF p_type IS NULL OR p_type NOT IN
     ('STUDY','SLEEP','FOOD','EXERCISE','ENTERTAINMENT','TRAVEL','OTHER') THEN
    RAISE_APPLICATION_ERROR(-20003, 'Invalid activity category.');
  END IF;
  IF p_start IS NULL OR p_end IS NULL OR p_end <= p_start THEN
    RAISE_APPLICATION_ERROR(-20003, 'End time must be after start time.');
  END IF;
  IF p_end > p_start + INTERVAL '1' DAY THEN
    RAISE_APPLICATION_ERROR(-20003, 'An activity cannot be longer than 24 hours.');
  END IF;

  -- Overlap test: two intervals overlap when each starts before the other ends.
  -- A running stopwatch session counts as ending "now".
  SELECT COUNT(*) INTO v_count
    FROM activity
   WHERE start_time < p_end
     AND NVL(end_time, CAST(SYSDATE AS TIMESTAMP)) > p_start
     AND activity_id <> NVL(p_exclude_id, -1);
  IF v_count > 0 THEN
    RAISE_APPLICATION_ERROR(-20004, 'This time range overlaps an existing activity.');
  END IF;
END validate_activity_input;
/

CREATE OR REPLACE PROCEDURE start_study_session (
  p_activity_name IN  VARCHAR2,
  p_activity_id   OUT NUMBER,
  p_start_time    OUT TIMESTAMP
)
IS
  v_name VARCHAR2(200) := NVL(TRIM(p_activity_name), 'Study Session');
BEGIN
  IF LENGTH(v_name) > 100 THEN
    RAISE_APPLICATION_ERROR(-20003, 'Activity name must be at most 100 characters.');
  END IF;
  p_start_time := CAST(SYSDATE AS TIMESTAMP);   -- database clock is the source of truth
  INSERT INTO activity (activity_name, activity_type, start_time)
  VALUES (v_name, 'STUDY', p_start_time)
  RETURNING activity_id INTO p_activity_id;
EXCEPTION
  WHEN DUP_VAL_ON_INDEX THEN   -- raised by uq_one_active_study
    RAISE_APPLICATION_ERROR(-20001, 'A study session is already active.');
END start_study_session;
/

CREATE OR REPLACE PROCEDURE stop_study_session (
  p_activity_id      OUT NUMBER,
  p_end_time         OUT TIMESTAMP,
  p_duration_minutes OUT NUMBER
)
IS
  v_start TIMESTAMP;
BEGIN
  -- FOR UPDATE locks the row: a simultaneous second STOP waits, then finds no open row.
  SELECT activity_id, start_time
    INTO p_activity_id, v_start
    FROM activity
   WHERE activity_type = 'STUDY' AND end_time IS NULL
     FOR UPDATE;

  p_end_time := CAST(SYSDATE AS TIMESTAMP);
  IF p_end_time <= v_start THEN                       -- stopped within the same second
    p_end_time := v_start + INTERVAL '1' SECOND;
  END IF;
  IF p_end_time > v_start + INTERVAL '1' DAY THEN     -- forgotten session: cap at 24 h
    p_end_time := v_start + INTERVAL '1' DAY;
  END IF;

  p_duration_minutes := calculate_duration(v_start, p_end_time);

  UPDATE activity
     SET end_time = p_end_time, duration_minutes = p_duration_minutes
   WHERE activity_id = p_activity_id;
EXCEPTION
  WHEN NO_DATA_FOUND THEN
    RAISE_APPLICATION_ERROR(-20002, 'No active study session found.');
END stop_study_session;
/

CREATE OR REPLACE PROCEDURE add_manual_activity (
  p_activity_name    IN  VARCHAR2,
  p_activity_type    IN  VARCHAR2,
  p_start_time       IN  TIMESTAMP,
  p_end_time         IN  TIMESTAMP,
  p_activity_id      OUT NUMBER,
  p_duration_minutes OUT NUMBER
)
IS
BEGIN
  -- Serialise writers so two simultaneous requests cannot both pass the overlap check.
  -- The lock is released at COMMIT/ROLLBACK (done by Python).
  LOCK TABLE activity IN SHARE ROW EXCLUSIVE MODE;
  validate_activity_input(p_activity_name, UPPER(TRIM(p_activity_type)), p_start_time, p_end_time);
  p_duration_minutes := calculate_duration(p_start_time, p_end_time);
  INSERT INTO activity (activity_name, activity_type, start_time, end_time, duration_minutes)
  VALUES (TRIM(p_activity_name), UPPER(TRIM(p_activity_type)),
          p_start_time, p_end_time, p_duration_minutes)
  RETURNING activity_id INTO p_activity_id;
END add_manual_activity;
/

CREATE OR REPLACE PROCEDURE update_activity (
  p_activity_id      IN  NUMBER,
  p_activity_name    IN  VARCHAR2,
  p_activity_type    IN  VARCHAR2,
  p_start_time       IN  TIMESTAMP,
  p_end_time         IN  TIMESTAMP,
  p_duration_minutes OUT NUMBER
)
IS
  v_end TIMESTAMP;
BEGIN
  LOCK TABLE activity IN SHARE ROW EXCLUSIVE MODE;
  BEGIN
    SELECT end_time INTO v_end FROM activity WHERE activity_id = p_activity_id FOR UPDATE;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20005, 'Activity not found.');
  END;
  IF v_end IS NULL THEN
    RAISE_APPLICATION_ERROR(-20006, 'Stop the running study session before editing it.');
  END IF;
  validate_activity_input(p_activity_name, UPPER(TRIM(p_activity_type)),
                          p_start_time, p_end_time, p_activity_id);
  p_duration_minutes := calculate_duration(p_start_time, p_end_time);
  UPDATE activity
     SET activity_name = TRIM(p_activity_name), activity_type = UPPER(TRIM(p_activity_type)),
         start_time = p_start_time, end_time = p_end_time,
         duration_minutes = p_duration_minutes
   WHERE activity_id = p_activity_id;
END update_activity;
/

CREATE OR REPLACE PROCEDURE delete_activity (
  p_activity_id IN NUMBER
)
IS
  v_end TIMESTAMP;
BEGIN
  BEGIN
    SELECT end_time INTO v_end FROM activity WHERE activity_id = p_activity_id FOR UPDATE;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20005, 'Activity not found.');
  END;
  IF v_end IS NULL THEN
    RAISE_APPLICATION_ERROR(-20006, 'Stop the running study session before deleting it.');
  END IF;
  DELETE FROM activity WHERE activity_id = p_activity_id;
END delete_activity;
/
