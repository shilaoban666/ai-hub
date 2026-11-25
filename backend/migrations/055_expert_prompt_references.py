"""Redirect expert bindings from unchanged legacy copies to author templates.

Run after 054 with API/workers stopped. Includes copies soft-deleted by an
earlier version of 054. No template content is edited or deleted. Historical
snapshots remain stored for recovery but are never used by current readers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def backfill(db):
    from models import Agent, PromptTemplate, agent_prompt_templates

    bindings = agent_prompt_templates
    rows = db.query(Agent.id, Agent.user_id, PromptTemplate, bindings.c.position).select_from(bindings).join(
        Agent, Agent.id == bindings.c.agent_id,
    ).join(PromptTemplate, PromptTemplate.id == bindings.c.prompt_template_id).filter(
        PromptTemplate.source_template_id.isnot(None),
        PromptTemplate.is_system == False,
    ).with_for_update().all()
    converted = 0
    retained = 0
    for agent_id, agent_user_id, copy, position in rows:
        canonical = json.dumps({key: getattr(copy, key) for key in
            ("name", "category", "content", "variables", "description", "author")
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source = db.get(PromptTemplate, copy.source_template_id)
        if (copy.is_public or not copy.imported_at or not copy.source_snapshot_hash
                or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != copy.source_snapshot_hash
                or source is None or source.id == copy.id or source.is_deleted
                or not (source.is_public or source.is_system or source.user_id == agent_user_id)):
            retained += 1
            continue
        target = db.execute(bindings.select().where(
            bindings.c.agent_id == agent_id,
            bindings.c.prompt_template_id == source.id,
        )).mappings().first()
        if target is None:
            db.execute(bindings.insert().values(
                agent_id=agent_id, prompt_template_id=source.id, position=position,
            ))
        else:
            db.execute(bindings.update().where(
                bindings.c.agent_id == agent_id,
                bindings.c.prompt_template_id == source.id,
            ).values(position=min(target['position'], position)))
        db.execute(bindings.delete().where(
            bindings.c.agent_id == agent_id, bindings.c.prompt_template_id == copy.id,
        ))
        converted += 1
    return {"converted": converted, "retained": retained}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    if not parser.parse_args().apply:
        parser.print_help()
        return
    from sqlalchemy.orm import Session
    from database import engine
    with Session(engine) as db, db.begin():
        counts = backfill(db)
    print(f"Expert prompt references ready: {counts}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Migration failed ({type(exc).__name__}); keep writers stopped and fix the cause.", file=sys.stderr)
        raise SystemExit(1) from None
