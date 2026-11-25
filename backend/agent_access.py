"""Separate public execution access from owner-only configuration access."""
from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload
from agent_settings import RuntimeAgent, runtime_agent
from skill_release_policy import published_release_filter
from mcp_publication import shareable_mcp_definition
from models import (Agent, Skill, SkillRelease, SkillInstallation, ExpertSkillBinding,
                    McpConnection, McpDefinition, McpRevision, ExpertMcpBinding,
                    PromptTemplate, agent_prompt_templates)


def agent_publication_errors(db: Session, agent: Agent) -> list[str]:
    errors = []
    private_skills = [
        skill.name for skill in (agent.skills or [])
        if not skill.is_deleted and not skill.is_public
    ] if agent.kind == "personal_default" else []
    private_mcps = [
        mcp.name for mcp in (agent.mcps or [])
        if not mcp.is_deleted and not mcp.is_public
    ] if agent.kind == "personal_default" else []
    private_prompts = []
    bound_skill_rows = db.query(Skill.name, Skill.is_public).select_from(
        ExpertSkillBinding,
    ).join(SkillInstallation, SkillInstallation.id == ExpertSkillBinding.installation_id).join(
        Skill, Skill.id == SkillInstallation.skill_id,
    ).join(SkillRelease, SkillRelease.id == SkillInstallation.release_id).filter(
        ExpertSkillBinding.agent_id == agent.id,
        SkillInstallation.status == "active",
        published_release_filter(),
    ).all()
    private_skills.extend(row[0] for row in bound_skill_rows if not row[1])
    bound_mcp_rows = db.query(McpDefinition.name, shareable_mcp_definition()).select_from(
        ExpertMcpBinding,
    ).join(McpConnection, McpConnection.id == ExpertMcpBinding.connection_id).join(
        McpDefinition, McpDefinition.id == McpConnection.definition_id,
    ).join(McpRevision, McpRevision.id == McpConnection.revision_id).filter(
        ExpertMcpBinding.agent_id == agent.id,
        ExpertMcpBinding.status == "active",
        McpConnection.status != "deleted",
        McpDefinition.status == "published",
        McpRevision.status == "published",
    ).all()
    private_mcps.extend(row[0] for row in bound_mcp_rows if not row[1])
    if private_skills:
        private_skills = list(dict.fromkeys(private_skills))
        errors.append(f"技能未公开: {'、'.join(private_skills)}")
    if private_mcps:
        private_mcps = list(dict.fromkeys(private_mcps))
        errors.append(f"MCP 未公开: {'、'.join(private_mcps)}")
    prompt_rows = db.query(PromptTemplate.name, PromptTemplate.is_public, PromptTemplate.is_system, PromptTemplate.is_deleted).join(
        agent_prompt_templates,
        agent_prompt_templates.c.prompt_template_id == PromptTemplate.id,
    ).filter(
        agent_prompt_templates.c.agent_id == agent.id,
    ).all()
    # Publication always follows the author's current visibility.
    private_prompts.extend(row[0] for row in prompt_rows if row[3] or not (row[1] or row[2]))
    if private_prompts:
        private_prompts = list(dict.fromkeys(private_prompts))
        errors.append(f"提示词未公开: {'、'.join(private_prompts)}")
    return errors


class PublicRuntimeAgent(RuntimeAgent):
    """Keep caller-specific runtime state off the publisher's ORM record."""
    def __setattr__(self, name, value):
        self._values[name] = value


def agent_for_user(db, agent, user_id):
    if agent.user_id == user_id:
        return agent
    if (agent.is_deleted or not agent.is_public or agent.kind != "expert"
            or agent_publication_errors(db, agent)):
        raise HTTPException(status_code=403, detail="智能体未公开或已不可用")
    resolved = runtime_agent(db, agent)
    if resolved.runtime_type != "claude_code":
        raise HTTPException(status_code=409, detail="该 Runtime 暂不支持公开使用")
    return PublicRuntimeAgent(resolved, {
        "execution_user_id": user_id, "workspace_id": None,
        "mcp_overrides": [], "mcp_overrides_encrypted": None,
    })


def get_usable_agent(db, agent_id, user_id):
    agent = db.query(Agent).options(lazyload("*")).filter(
        Agent.id == agent_id, Agent.is_deleted == False,
    ).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return agent_for_user(db, agent, user_id)
