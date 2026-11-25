"""Safe diagnostics shared by runtime errors and the model gateway."""

import re


def strip_model_diagnostics(value: str) -> str:
    """The CLI's unknown-catalog warning is telemetry, not an API failure."""
    return re.sub(
        r'\[claude-code:unrecognized_model\]\s*\{[^\r\n]*?\}',
        '', value,
    ).strip()


def safe_error_detail(value: str) -> str:
    value = strip_model_diagnostics(value)
    value = re.sub(r'\b(?:sk-[\w-]+|ahr_[\w-]+)\b', '[redacted]', value)
    value = re.sub(r'(?i)\bBearer\s+[^\s\"\']+', 'Bearer [redacted]', value)
    value = re.sub(
        r'(?i)((?:api[_-]?key|authorization|access_token)[\"\']?\s*[:=]\s*[\"\']?)[^\s\"\',}]+',
        r'\1[redacted]', value,
    )
    return value[:8000]
