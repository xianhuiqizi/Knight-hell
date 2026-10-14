-- FlowRemote - checks for the first slice.
-- Run these in any SQLite client, or use:
--   python src\flowremote\devtools\seed.py --verify

-- 1. The batch that was loaded.
SELECT outcome, COUNT(*) AS records
FROM source_records
WHERE task_id = 'TASK-1001'
GROUP BY outcome;

-- 2. Exceptions by review status.
SELECT status, COUNT(*) AS exceptions
FROM exceptions
WHERE task_id = 'TASK-1001'
GROUP BY status;

-- 3. The three cases from the storyboard.
SELECT record_id, issue, suggestion, confidence, status
FROM exceptions
WHERE record_id IN ('ORD-052', 'ORD-081', 'ORD-099')
ORDER BY record_id;

-- 4. The gate: approval is only allowed when unresolved reaches zero.
SELECT
  (SELECT batch_size FROM tasks WHERE id = 'TASK-1001') AS batch_size,
  (SELECT COUNT(*) FROM exceptions
    WHERE task_id = 'TASK-1001' AND status = 'unresolved') AS unresolved;

-- 5. Nothing has been approved or decided yet.
SELECT
  (SELECT COUNT(*) FROM decisions WHERE exception_id IN (
     SELECT id FROM exceptions WHERE task_id = 'TASK-1001')) AS decisions,
  (SELECT COUNT(*) FROM approvals WHERE task_id = 'TASK-1001') AS approvals;
