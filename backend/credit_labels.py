"""Display labels from the effective platform credit settings."""

DEFAULT_CREDIT_DISPLAY_NAME = "积分"


def credit_display_name(policy) -> str:
    name = getattr(policy, "credit_display_name", None)
    return (name.strip() if isinstance(name, str) else "") or DEFAULT_CREDIT_DISPLAY_NAME
