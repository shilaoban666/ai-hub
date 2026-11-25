"""Live prompt references shared by expert configuration, chat and execution."""
from sqlalchemy import and_, or_

from models import Agent, PromptTemplate, agent_prompt_templates


def prompt_access_filter(user_id):
    return and_(
        PromptTemplate.is_deleted == False,
        or_(PromptTemplate.user_id == user_id,
            PromptTemplate.is_public == True,
            PromptTemplate.is_system == True),
    )


def load_agent_prompts(db, agent_id):
    return load_agent_prompts_many(db, [agent_id])[agent_id]


def load_agent_prompts_many(db, agent_ids):
    result = {agent_id: [] for agent_id in agent_ids}
    if not result:
        return result
    bindings = agent_prompt_templates
    rows = db.query(bindings.c.agent_id, PromptTemplate).select_from(bindings).join(
        PromptTemplate, PromptTemplate.id == bindings.c.prompt_template_id,
    ).join(Agent, Agent.id == bindings.c.agent_id).filter(
        bindings.c.agent_id.in_(agent_ids),
        prompt_access_filter(Agent.user_id),
    ).order_by(bindings.c.position, bindings.c.prompt_template_id).all()
    for agent_id, template in rows:
        result[agent_id].append(template)
    return result


def set_agent_prompts(db, agent_id, templates):
    """Replace only references, preserving the requested module order. No commit."""
    db.flush()
    bindings = agent_prompt_templates
    db.execute(bindings.delete().where(bindings.c.agent_id == agent_id))
    values = [dict(agent_id=agent_id, prompt_template_id=template.id, position=position)
              for position, template in enumerate(templates)]
    if values:
        db.execute(bindings.insert(), values)


def copy_agent_prompts(db, source_agent_id, target_agent_id):
    """Copy accessible references; never copy template contents or old snapshots."""
    db.flush()
    target = db.get(Agent, target_agent_id)
    templates = [template for template in load_agent_prompts(db, source_agent_id)
                 if template.user_id == target.user_id or template.is_public or template.is_system]
    set_agent_prompts(db, target_agent_id, templates)
