-- =====================================================================
-- FocusMate - OPTIONAL demo data for the last 7 days (idempotent).
-- Inserted through ADD_MANUAL_ACTIVITY, so all validation rules apply.
-- Every row is named "[Sample] ..." and the script does nothing if such rows exist.
-- To remove later:  DELETE FROM activity WHERE activity_name LIKE '[Sample]%';
-- =====================================================================
DECLARE
  v_exists NUMBER;
  v_id     NUMBER;
  v_dur    NUMBER;

  -- timestamp for "d days ago at minute-of-day m" (exact: no fractional-day maths)
  FUNCTION ts(p_days IN NUMBER, p_min IN NUMBER) RETURN TIMESTAMP IS
  BEGIN
    RETURN CAST(TRUNC(SYSDATE) AS TIMESTAMP)
           - NUMTODSINTERVAL(p_days, 'DAY') + NUMTODSINTERVAL(p_min, 'MINUTE');
  END ts;

  PROCEDURE act(p_name VARCHAR2, p_type VARCHAR2, p_s TIMESTAMP, p_e TIMESTAMP) IS
  BEGIN
    add_manual_activity('[Sample] ' || p_name, p_type, p_s, p_e, v_id, v_dur);
  END act;
BEGIN
  SELECT COUNT(*) INTO v_exists FROM activity WHERE activity_name LIKE '[Sample]%';
  IF v_exists > 0 THEN
    DBMS_OUTPUT.PUT_LINE('Sample data already present - nothing inserted.');
    RETURN;
  END IF;

  FOR d IN 0 .. 6 LOOP
    act('Night sleep',  'SLEEP',         ts(d + 1, 1380), ts(d, 390));            -- 23:00 -> 06:30 (crosses midnight)
    act('Morning run',  'EXERCISE',      ts(d, 420),      ts(d, 420 + 30 + MOD(d * 7, 20)));
    act('Breakfast',    'FOOD',          ts(d, 480),      ts(d, 510));
    act('Study block',  'STUDY',         ts(d, 540),      ts(d, 540 + 60 + MOD(d * 37, 90)));
    act('Lunch',        'FOOD',          ts(d, 780),      ts(d, 825));
    act('Commute',      'TRAVEL',        ts(d, 840),      ts(d, 880));
    act('Revision',     'STUDY',         ts(d, 900),      ts(d, 900 + 45 + MOD(d * 23, 60)));
    act('Series',       'ENTERTAINMENT', ts(d, 1200),     ts(d, 1200 + 40 + MOD(d * 11, 40)));
    act('Errands',      'OTHER',         ts(d, 1020),     ts(d, 1050));
  END LOOP;
  DBMS_OUTPUT.PUT_LINE('Sample data inserted.');
END;
/
