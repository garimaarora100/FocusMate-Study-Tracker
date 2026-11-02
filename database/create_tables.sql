-- =====================================================================
-- FocusMate - table and index creation
-- SAFE TO RE-RUN: nothing is dropped. "already exists" errors are ignored.
-- Every statement block ends with a line containing only "/"
-- Run order: create_tables -> functions -> procedures -> views -> (sample_data)
-- =====================================================================
DECLARE
  -- Runs one DDL statement; ignores "object already exists" style errors only.
  PROCEDURE run_ddl(p_sql IN VARCHAR2) IS
  BEGIN
    EXECUTE IMMEDIATE p_sql;
  EXCEPTION
    WHEN OTHERS THEN
      -- -955  name already used by an existing object
      -- -1408 such column list already indexed
      IF SQLCODE NOT IN (-955, -1408) THEN
        RAISE;
      END IF;
  END run_ddl;
BEGIN
  run_ddl(q'[
    CREATE TABLE activity (
      activity_id       NUMBER GENERATED ALWAYS AS IDENTITY,
      activity_name     VARCHAR2(100) NOT NULL,
      activity_type     VARCHAR2(20)  NOT NULL,
      start_time        TIMESTAMP(0)  NOT NULL,
      end_time          TIMESTAMP(0),
      duration_minutes  NUMBER(8,2),
      created_at        TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
      CONSTRAINT pk_activity PRIMARY KEY (activity_id),
      CONSTRAINT ck_activity_type CHECK (activity_type IN
        ('STUDY','SLEEP','FOOD','EXERCISE','ENTERTAINMENT','TRAVEL','OTHER')),
      CONSTRAINT ck_activity_name CHECK (LENGTH(TRIM(activity_name)) > 0),
      -- no negative / zero-length intervals (full timestamps => midnight crossing is safe)
      CONSTRAINT ck_activity_end_after_start CHECK (end_time IS NULL OR end_time > start_time),
      -- a single activity can never exceed 24 hours
      CONSTRAINT ck_activity_duration CHECK
        (duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 1440)),
      -- an activity is either open (no end, no duration) or closed (both present)
      CONSTRAINT ck_activity_closed CHECK
        ((end_time IS NULL AND duration_minutes IS NULL)
      OR (end_time IS NOT NULL AND duration_minutes IS NOT NULL)),
      -- only stopwatch (STUDY) sessions may be open
      CONSTRAINT ck_activity_open_only_study CHECK (end_time IS NOT NULL OR activity_type = 'STUDY')
    )]');

  run_ddl('CREATE INDEX idx_activity_start ON activity (start_time)');
  run_ddl('CREATE INDEX idx_activity_type_start ON activity (activity_type, start_time)');

  -- CONCURRENCY GUARD: function-based UNIQUE index. Every open STUDY row maps to the
  -- same value (1); all other rows map to NULL (not indexed). So the database itself
  -- refuses a second open study session, even under simultaneous requests.
  run_ddl(q'[CREATE UNIQUE INDEX uq_one_active_study ON activity
             (CASE WHEN activity_type = 'STUDY' AND end_time IS NULL THEN 1 END)]');
END;
/
