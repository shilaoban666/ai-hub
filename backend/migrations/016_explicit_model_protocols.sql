-- 016: Replace legacy auto protocol detection with explicit model protocols.

UPDATE ai_models
SET api_protocol = 'anthropic-messages'
WHERE (api_protocol IS NULL OR api_protocol = '' OR api_protocol = 'auto')
  AND (
    LOWER(provider) LIKE '%anthropic%'
    OR LOWER(provider) LIKE '%claude%'
    OR LOWER(name) LIKE '%claude%'
    OR (
      LOWER(name) REGEXP '(^|[/_-])deepseek[-_]?v4($|[/_.-])'
      AND LOWER(api_proxy_url) LIKE 'https://sub2api.fancyqube.net%'
    )
  );

UPDATE ai_models
SET api_protocol = 'openai-completions'
WHERE api_protocol IS NULL OR api_protocol = '' OR api_protocol = 'auto';

ALTER TABLE ai_models
MODIFY COLUMN api_protocol VARCHAR(30) NOT NULL
DEFAULT 'openai-completions'
COMMENT 'openai-completions | anthropic-messages';
