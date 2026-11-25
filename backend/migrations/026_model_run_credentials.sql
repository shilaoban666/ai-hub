-- 026: Short-lived per-Run credentials for the AI Hub model gateway.

CREATE TABLE IF NOT EXISTS model_run_credentials (
    id BIGINT NOT NULL AUTO_INCREMENT,
    token_hash VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    user_id INT NOT NULL,
    model_id INT NOT NULL,
    pricing_version_id BIGINT NOT NULL,
    max_points BIGINT NOT NULL,
    consumed_points BIGINT NOT NULL DEFAULT 0,
    request_count INT NOT NULL DEFAULT 0,
    request_in_flight TINYINT(1) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_model_run_credentials_token_hash (token_hash),
    UNIQUE KEY uq_model_run_credentials_run_id (run_id),
    KEY ix_model_run_credentials_user_id (user_id),
    KEY ix_model_run_credentials_model_id (model_id),
    KEY ix_model_run_credentials_status_expires (status, expires_at),
    CONSTRAINT fk_model_run_credentials_model FOREIGN KEY (model_id) REFERENCES ai_models(id),
    CONSTRAINT fk_model_run_credentials_pricing FOREIGN KEY (pricing_version_id) REFERENCES model_pricing_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
