-- Legacy refresh output table, retained for upgrade replay and cleanup.
-- New Web runs use Redis and never insert/update rows here.
-- Positive sequences are legacy event rows, retained only for rolling upgrades.
-- The API background cleanup removes terminal runs' rows after 10 minutes.
CREATE TABLE IF NOT EXISTS agent_run_events (
    run_id VARCHAR(32) NOT NULL,
    sequence INT NOT NULL,
    payload LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
