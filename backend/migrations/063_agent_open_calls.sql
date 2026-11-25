-- Credential digests only; raw keys are returned once to the owner.
CREATE TABLE IF NOT EXISTS agent_open_calls (
  agent_id INT NOT NULL,
  key_digest VARCHAR(64) NULL,
  generation VARCHAR(32) NOT NULL,
  default_prompt TEXT NULL,
  skill_ids JSON NOT NULL,
  mcp_ids JSON NOT NULL,
  PRIMARY KEY (agent_id),
  CONSTRAINT fk_agent_open_calls_agent FOREIGN KEY (agent_id) REFERENCES agents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Match agent_runs.id in both SQL-initialized and ORM-initialized databases.
SET @open_request_run_id_definition = (
  SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME, ' COLLATE ', COLLATION_NAME)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'agent_runs'
    AND COLUMN_NAME = 'id'
);

SET @open_requests_sql = CONCAT(
  'CREATE TABLE IF NOT EXISTS agent_open_requests (
  run_id ', @open_request_run_id_definition, ' NOT NULL,
  generation VARCHAR(32) NOT NULL,
  prompt TEXT NULL,
  skill_id INT NULL,
  PRIMARY KEY (run_id),
  CONSTRAINT fk_agent_open_requests_run FOREIGN KEY (run_id) REFERENCES agent_runs(id)
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
);
PREPARE open_requests_stmt FROM @open_requests_sql;
EXECUTE open_requests_stmt;
DEALLOCATE PREPARE open_requests_stmt;
