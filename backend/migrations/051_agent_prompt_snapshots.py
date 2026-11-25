"""After 050, stop API/channel workers and run from backend:
python migrations/051_agent_prompt_snapshots.py --apply

Idempotent schema changes; snapshot backfill is one transaction. Existing
snapshots are never refreshed on rerun. No configured database is touched
without --apply.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session


def apply_schema(connection):
    from models import UserExecutionGate
    if connection.dialect.name != 'mysql':
        raise RuntimeError('This migration requires MySQL')
    if 'snapshot_json' not in {c['name'] for c in inspect(connection).get_columns('agent_prompt_templates')}:
        connection.exec_driver_sql('ALTER TABLE agent_prompt_templates ADD COLUMN snapshot_json LONGTEXT NULL')
    UserExecutionGate.__table__.create(connection, checkfirst=True)


def backfill(db):
    from models import agent_prompt_templates
    from agent_prompt_snapshots import freeze_agent_prompts
    agent_ids = db.execute(select(agent_prompt_templates.c.agent_id).where(
        agent_prompt_templates.c.snapshot_json.is_(None),
    ).distinct()).scalars().all()
    for agent_id in agent_ids:
        freeze_agent_prompts(db, agent_id)
    return len(agent_ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    if not parser.parse_args().apply:
        parser.print_help()
        return
    from database import engine
    with engine.begin() as connection:
        apply_schema(connection)
    with Session(engine) as db, db.begin():
        count = backfill(db)
    print(f'Prompt snapshots ready for {count} agents; user execution gate ready')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Migration failed ({type(exc).__name__}); keep writers stopped and retry after fixing the cause.', file=sys.stderr)
        raise SystemExit(1) from None
