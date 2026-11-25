-- New runs debit reported usage without reserving a budget. Legacy reservations
-- continue through the existing settlement path; do not refund them here.
CREATE TABLE IF NOT EXISTS model_gateway_requests (
    id VARCHAR(100) NOT NULL PRIMARY KEY,
    credential_id BIGINT NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'started',
    billed_points DECIMAL(20, 2) NOT NULL DEFAULT 0,
    charged_points DECIMAL(20, 2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_model_gateway_requests_credential_id (credential_id),
    INDEX ix_model_gateway_requests_run_id (run_id),
    FOREIGN KEY (credential_id) REFERENCES model_run_credentials(id)
);
