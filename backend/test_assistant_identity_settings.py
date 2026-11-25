from types import SimpleNamespace

from agent_workspace import build_claude_md
from enterprise_schemas import AssistantSettingsDraft, BootstrapResponse
from models import PlatformAgentSettings


def test_assistant_identity_defaults_are_backwards_compatible():
    draft = AssistantSettingsDraft()

    assert draft.assistant_name == "AI 助手"
    assert draft.assistant_icon == "H"
    assert PlatformAgentSettings.assistant_icon.property.columns[0].default.arg == "H"


def test_bootstrap_exposes_published_assistant_identity():
    response = BootstrapResponse(
        assistant_id=1,
        assistant_name="研发助手",
        assistant_icon="研",
        settings_version=2,
        default_model_id=3,
        runtime_type="claude_code",
        workspace_status="ready",
        workspace={},
        assistant={
            "id": 1, "name": "研发助手", "icon": "研",
            "default_model_id": 3, "runtime_type": "claude_code",
            "skills": [
                {"id": 10, "name": "系统技能"},
                {"id": 11, "name": "个人技能"},
            ],
        },
        credit={
            "available_balance": "10.00",
            "reserved_balance": "0.00",
            "status": "active",
            "version": 1,
            "display_name": "算点",
            "display_name_en": "Credits",
            "daily_claim_amount": "2.00",
            "today": "2026-09-07",
            "claimed_today": True,
            "low_balance_threshold": "1.00",
        },
    )

    assert response.assistant_name == "研发助手"
    assert response.assistant_icon == "研"
    assert response.model_dump(mode="json")["assistant"]["skills"] == [
        {"id": 10, "name": "系统技能"},
        {"id": 11, "name": "个人技能"},
    ]


def test_custom_agent_identity_is_explicit_without_replacing_business_prompts():
    main_prompt = "你是 Online 助手，查询业务数据时优先使用 online-mcp。"
    agent = SimpleNamespace(
        name="精品运营", description="负责精品业务的运营分析",
        system_prompt=main_prompt, effective_system_prompt=main_prompt,
    )

    instructions = build_claude_md(agent, ["inventory-analysis"])

    assert "你的名字是：精品运营。" in instructions
    assert "你的简介与职责：负责精品业务的运营分析" in instructions
    assert "名称冲突时以上述当前智能体名称为准" in instructions
    assert main_prompt in instructions
    assert "# 主提示词\n" in instructions
    assert "- inventory-analysis" in instructions


def test_workbench_identity_uses_current_configuration_on_each_build():
    agent = SimpleNamespace(name="小趣", description=None, system_prompt=None)
    assert "你的名字是：小趣。" in build_claude_md(agent)

    agent.name = "研发助手"
    agent.description = "帮助排查研发问题"
    instructions = build_claude_md(agent)
    assert "你的名字是：研发助手。" in instructions
    assert "你的简介与职责：帮助排查研发问题" in instructions
    assert "小趣" not in instructions


if __name__ == "__main__":
    test_assistant_identity_defaults_are_backwards_compatible()
    test_bootstrap_exposes_published_assistant_identity()
    test_custom_agent_identity_is_explicit_without_replacing_business_prompts()
    test_workbench_identity_uses_current_configuration_on_each_build()
    print("assistant identity settings tests passed")
