"""Historical 051 migration helpers. Runtime prompt reads use agent_prompts."""
import json

from models import PromptTemplate, agent_prompt_templates

FIELDS = ('name', 'category', 'content', 'variables', 'description', 'author',
          'source_template_id', 'is_public', 'is_system')


def prompt_snapshot(template):
    return json.dumps({key: getattr(template, key, None) for key in FIELDS}, ensure_ascii=False)


def freeze_agent_prompts(db, agent_id):
    """Fill only missing snapshots, including existing legacy bindings. No commit."""
    db.flush()
    bindings = agent_prompt_templates
    rows = db.query(PromptTemplate).join(
        bindings, bindings.c.prompt_template_id == PromptTemplate.id,
    ).filter(bindings.c.agent_id == agent_id, bindings.c.snapshot_json.is_(None)).all()
    for template in rows:
        if template.is_deleted:
            # Preserve the pre-migration effective state: deleted modules were inactive.
            db.execute(bindings.delete().where(
                bindings.c.agent_id == agent_id, bindings.c.prompt_template_id == template.id,
                bindings.c.snapshot_json.is_(None),
            ))
            continue
        db.execute(bindings.update().where(
            bindings.c.agent_id == agent_id, bindings.c.prompt_template_id == template.id,
            bindings.c.snapshot_json.is_(None),
        ).values(snapshot_json=prompt_snapshot(template)))
