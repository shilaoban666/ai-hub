-- 012: Persist provider QR polling cadence and isolate pairing failures by sender.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND COLUMN_NAME = 'poll_interval_seconds') = 0,
    'ALTER TABLE channel_bind_sessions ADD COLUMN poll_interval_seconds INT NULL COMMENT ''provider minimum QR poll interval''',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS channel_pairing_attempts (
    bind_session_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sender_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (bind_session_id, sender_hash),
    CONSTRAINT fk_channel_pairing_attempts_bind_session
        FOREIGN KEY (bind_session_id) REFERENCES channel_bind_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='per-sender pairing failure counters';
