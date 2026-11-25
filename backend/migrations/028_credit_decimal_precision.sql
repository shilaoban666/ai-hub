-- 028: Store credit balances and per-run charges with two decimal places.

ALTER TABLE agent_runs
    MODIFY COLUMN reserved_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN charged_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

SET @agent_run_message_sql = IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'assistant_message_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN assistant_message_id INT NULL AFTER runtime_version, ADD INDEX ix_agent_runs_assistant_message_id (assistant_message_id)',
    'SELECT 1'
);
PREPARE agent_run_message_stmt FROM @agent_run_message_sql;
EXECUTE agent_run_message_stmt;
DEALLOCATE PREPARE agent_run_message_stmt;

-- Backfill only unambiguous historical turns. Failed runs without an assistant
-- message remain NULL instead of being linked heuristically.
UPDATE agent_runs AS target
JOIN (
    SELECT candidates.run_id, candidates.assistant_message_id
    FROM (
        SELECT
            run_record.id AS run_id,
            MIN(message.id) AS assistant_message_id,
            COUNT(message.id) AS candidate_count
        FROM agent_runs AS run_record
        JOIN agent_messages AS message
          ON message.session_id = run_record.session_id
         AND message.role = 'assistant'
         AND message.created_at >= COALESCE(run_record.started_at, run_record.created_at)
         AND message.created_at <= DATE_ADD(
             COALESCE(run_record.finished_at, run_record.updated_at),
             INTERVAL 2 SECOND
         )
        WHERE run_record.assistant_message_id IS NULL
        GROUP BY run_record.id
    ) AS candidates
    WHERE candidates.candidate_count = 1
) AS matched ON matched.run_id = target.id
SET target.assistant_message_id = matched.assistant_message_id
WHERE target.assistant_message_id IS NULL;

ALTER TABLE platform_agent_settings
    MODIFY COLUMN initial_claim_amount DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN daily_claim_amount DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN per_run_limit DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN low_balance_threshold DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE credit_accounts
    MODIFY COLUMN available_balance DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN reserved_balance DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE credit_claim_records
    MODIFY COLUMN amount DECIMAL(20, 2) NOT NULL;

ALTER TABLE credit_ledger
    MODIFY COLUMN amount DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN available_after DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN reserved_after DECIMAL(20, 2) NOT NULL;

ALTER TABLE model_run_credentials
    MODIFY COLUMN max_points DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN consumed_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00;
