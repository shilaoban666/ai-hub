from fastapi import HTTPException

from agent_routes import _validate_reasoning_config_or_400


def test_claude_code_rejects_unsupported_thinking_levels():
    try:
        _validate_reasoning_config_or_400("claude_code", "off")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "不支持" in str(exc.detail)
    else:
        raise AssertionError("Claude Code must reject an unsupported off level")


if __name__ == "__main__":
    test_claude_code_rejects_unsupported_thinking_levels()
    print("agent reasoning settings tests passed")
