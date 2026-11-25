-- Expand agent message content storage for long assistant block payloads.
ALTER TABLE agent_messages
    MODIFY COLUMN content LONGTEXT NULL;
