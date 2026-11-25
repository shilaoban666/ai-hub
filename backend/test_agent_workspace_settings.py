from types import SimpleNamespace
import re

from agent_workspace import (
    build_claude_state_json,
    build_mcp_json,
    build_settings_json,
    get_mcp_server_names,
)


def test_claude_state_trusts_each_managed_project_path() -> None:
    state = build_claude_state_json(["/srv/runs/one/view", "/srv/workspaces/current"])

    assert state == {
        "projects": {
            "/srv/runs/one/view": {"hasTrustDialogAccepted": True},
            "/srv/workspaces/current": {"hasTrustDialogAccepted": True},
        }
    }


def make_mcp(name: str, mcp_type: str, config: str, mcp_id: int = 0) -> SimpleNamespace:
    return SimpleNamespace(id=mcp_id, name=name, type=mcp_type, config=config)


def test_mcp_settings_enable_project_servers() -> None:
    agent = SimpleNamespace(id=4, mcps=[])
    model = SimpleNamespace(
        api_key="test-key",
        api_proxy_url="https://api.example.test",
        name="claude-test",
    )
    mcps = [
        make_mcp("online-mcp", "http", '{"url": "https://online-mcp.example.test/mcp"}'),
        make_mcp("funchub-mcp", "streamable_http", '{"url": "https://funchub.example.test/mcp"}'),
        make_mcp("", "http", '{"url": "https://empty-name.example.test/mcp"}'),
        make_mcp("bad-http", "http", '{"url": ""}'),
        make_mcp("bad-json", "http", "{"),
    ]

    expected_names = ["online-mcp", "funchub-mcp"]
    settings = build_settings_json(agent, model, mcps=mcps)
    allow_tools = settings["permissions"]["allow"]

    assert get_mcp_server_names(mcps) == expected_names
    assert settings["enableAllProjectMcpServers"] is True
    assert settings["enabledMcpjsonServers"] == expected_names
    assert settings["disabledMcpjsonServers"] == []
    assert "Bash" in allow_tools
    assert "mcp__*" not in allow_tools
    assert "mcp__online-mcp__*" in allow_tools
    assert "mcp__funchub-mcp__*" in allow_tools
    assert "mcp__bad-http__*" not in allow_tools
    assert "mcp__bad-json__*" not in allow_tools
    pre_hook = settings["hooks"]["PreToolUse"][0]
    post_hook = settings["hooks"]["PostToolUse"][0]
    assert pre_hook["matcher"] == ".*"
    assert pre_hook["hooks"][0]["type"] == "command"
    assert pre_hook["hooks"][0]["command"].endswith("pre_tool_use.py")
    assert post_hook["matcher"] == "Read|Grep|Bash|WebFetch|WebSearch"
    assert post_hook["hooks"][0]["type"] == "command"
    assert post_hook["hooks"][0]["command"].endswith("post_tool_use.py")


def test_mcp_settings_without_servers_does_not_allow_mcp_tools() -> None:
    agent = SimpleNamespace(id=4, mcps=[])
    model = SimpleNamespace(api_key="", api_proxy_url="", name="claude-test")

    settings = build_settings_json(agent, model, mcps=[])
    allow_tools = settings["permissions"]["allow"]

    assert settings["enabledMcpjsonServers"] == []
    assert settings["disabledMcpjsonServers"] == []
    assert "Bash" in allow_tools
    assert "mcp__*" not in allow_tools


def test_chinese_mcp_uses_the_same_ascii_namespace_for_config_and_permissions() -> None:
    service = make_mcp("合趣知识库", "streamable_http", '{"url":"https://knowledge.example.test/mcp"}')
    config, warnings = build_mcp_json([service])
    settings = build_settings_json(SimpleNamespace(id=4), None, mcps=[service])
    name, = config["mcpServers"]

    assert re.fullmatch(r"[a-zA-Z0-9_-]+", name)
    assert name != "_____"
    assert warnings == []
    assert settings["enabledMcpjsonServers"] == [name]
    assert f"mcp__{name}__*" in settings["permissions"]["allow"]
    assert "mcp__合趣知识库__*" not in settings["permissions"]["allow"]
    assert service.name == "合趣知识库"
    assert config["mcpServers"][name]["url"] == "https://knowledge.example.test/mcp"


def test_distinct_chinese_mcp_names_keep_separate_permission_scopes() -> None:
    allowed = make_mcp("合趣知识库", "http", '{"url":"https://allowed.example.test/mcp"}')
    restricted = make_mcp("百炼知识库", "http", '{"url":"https://restricted.example.test/mcp"}')
    restricted.require_confirmation = True
    config, _ = build_mcp_json([allowed, restricted])
    settings = build_settings_json(SimpleNamespace(id=4), None, mcps=[allowed, restricted])
    rules = settings["permissions"]["allow"]
    assert len(config["mcpServers"]) == 2
    for name, entry in config["mcpServers"].items():
        assert (f"mcp__{name}__*" in rules) == (entry["url"] == "https://allowed.example.test/mcp")
        assert (f"mcp__{name}__*" in settings["permissions"]["ask"]) == (entry["url"] == "https://restricted.example.test/mcp")
    assert "mcp__*" not in rules


def test_runtime_names_are_stable_and_do_not_collide_with_existing_ascii_names() -> None:
    chinese = make_mcp("合趣知识库", "http", '{"url":"https://chinese.example.test/mcp"}')
    original, _ = build_mcp_json([chinese])
    alias, = original["mcpServers"]
    ascii_service = make_mcp(alias, "http", '{"url":"https://ascii.example.test/mcp"}')
    ascii_service.require_confirmation = True
    services = [chinese, ascii_service]
    forward, _ = build_mcp_json(services)
    reverse, _ = build_mcp_json(services[::-1])

    assert forward == reverse
    assert len(forward["mcpServers"]) == 2
    assert forward["mcpServers"][alias]["url"] == "https://ascii.example.test/mcp"
    settings = build_settings_json(SimpleNamespace(id=4), None, mcps=services)
    assert f"mcp__{alias}__*" not in settings["permissions"]["allow"]
    for name in forward["mcpServers"]:
        assert (f"mcp__{name}__*" in settings["permissions"]["allow"]) == (name != alias)


def test_mcp_specific_tool_rules_match_cli_normalized_tool_names() -> None:
    service = make_mcp("Knowledge API", "http", '{"url":"https://knowledge.example.test/mcp"}')
    service.allowed_tools = ["BailianKnowledgeBaseList", "知识库.查询"]
    settings = build_settings_json(SimpleNamespace(id=4), None, mcps=[service])
    name, = get_mcp_server_names([service])
    rules = settings["permissions"]["allow"]

    assert f"mcp__{name}__BailianKnowledgeBaseList" in rules
    assert f"mcp__{name}__{'_' * 6}" in rules
    assert f"mcp__{name}__*" not in rules


def test_mcp_display_names_cannot_introduce_permission_wildcards() -> None:
    services = [
        make_mcp("*", "http", '{"url":"https://one.example.test/mcp"}'),
        make_mcp("a.b", "http", '{"url":"https://two.example.test/mcp"}'),
        make_mcp("a b", "http", '{"url":"https://three.example.test/mcp"}'),
        make_mcp("a_b", "http", '{"url":"https://four.example.test/mcp"}'),
    ]
    config, _ = build_mcp_json(services)
    settings = build_settings_json(SimpleNamespace(id=4), None, mcps=services)
    assert len(config["mcpServers"]) == 4
    assert "a_b" in config["mcpServers"]
    assert set(settings["enabledMcpjsonServers"]) == set(config["mcpServers"])
    assert "mcp__*__*" not in settings["permissions"]["allow"]


def test_native_hooks_use_explicit_runtime_workspace_root() -> None:
    agent = SimpleNamespace(id=9, mcps=[])
    model = SimpleNamespace(api_key="", api_proxy_url="", name="claude-test")

    settings = build_settings_json(
        agent,
        model,
        mcps=[],
        include_secrets=False,
        sandbox_type="native",
        runtime_workspace_root="/var/lib/aihub/user_workspaces/workspace-1/current",
    )

    pre_tool_hook = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    post_tool_hook = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert pre_tool_hook == (
        "/usr/bin/python3 "
        "/var/lib/aihub/user_workspaces/workspace-1/current/.claude/hooks/pre_tool_use.py"
    )
    assert post_tool_hook == (
        "/usr/bin/python3 "
        "/var/lib/aihub/user_workspaces/workspace-1/current/.claude/hooks/post_tool_use.py"
    )
    assert "/var/lib/aihub/agent_workspaces/9" not in pre_tool_hook


def test_agent_mcp_overrides_replace_or_remove_example_values() -> None:
    mcps = [
        make_mcp(
            "stdio",
            "stdio",
            '{"command":"tool","env":{"TOKEN":"example","REGION":"cn"}}',
            1,
        ),
        make_mcp(
            "http",
            "streamable_http",
            '{"url":"https://mcp.example.test","headers":{"Authorization":"example"}}',
            2,
        ),
    ]
    config, warnings = build_mcp_json(mcps, overrides=[
        {"mcp_id": 1, "env": {"TOKEN": "real", "REGION": ""}, "headers": {}},
        {"mcp_id": 2, "env": {}, "headers": {"Authorization": "Bearer real"}},
    ])

    assert warnings == []
    assert config["mcpServers"]["stdio"]["env"] == {"TOKEN": "real"}
    assert config["mcpServers"]["http"]["headers"] == {
        "Authorization": "Bearer real"
    }


if __name__ == "__main__":
    test_mcp_settings_enable_project_servers()
    test_mcp_settings_without_servers_does_not_allow_mcp_tools()
    test_native_hooks_use_explicit_runtime_workspace_root()
    test_agent_mcp_overrides_replace_or_remove_example_values()
