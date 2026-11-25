CREATE TABLE IF NOT EXISTS mcp_user_headers (
    user_id INT NOT NULL,
    definition_id BIGINT NOT NULL,
    headers_encrypted LONGTEXT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, definition_id),
    CONSTRAINT fk_mcp_user_headers_definition
        FOREIGN KEY (definition_id) REFERENCES mcp_definitions(id)
);
