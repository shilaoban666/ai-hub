"""Convert unchanged workbench prompt copies to references.

Run through run_upgrade.py --from 054 --apply with API/workers stopped.
No configured database is touched without --apply. Edited, published, system,
unverifiable and inaccessible-source copies are retained. Converted copies are
soft-deleted, retaining their bytes and existing expert binding snapshots.
Migration 055 redirects those expert bindings to the author template.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def apply_schema(connection):
    from models import WorkspacePromptReference
    WorkspacePromptReference.__table__.create(connection, checkfirst=True)


def backfill(db):
    from models import PromptTemplate, WorkspacePromptReference, WorkspacePromptRemoval

    converted = 0
    retained = 0
    copies = db.query(PromptTemplate).filter(
        PromptTemplate.source_template_id.isnot(None),
        PromptTemplate.is_deleted == False,
        PromptTemplate.is_system == False,
    ).order_by(PromptTemplate.id).with_for_update().all()
    for copy in copies:
        canonical = json.dumps({
            key: getattr(copy, key) for key in
            ("name", "category", "content", "variables", "description", "author")
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source = db.get(PromptTemplate, copy.source_template_id)
        if (copy.is_public or not copy.imported_at or not copy.source_snapshot_hash
                or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != copy.source_snapshot_hash
                or source is None or source.is_deleted
                or not (source.is_public or source.is_system or source.user_id == copy.user_id)):
            retained += 1
            continue
        removed = db.get(WorkspacePromptRemoval, (copy.user_id, copy.id)) is not None
        key = (copy.user_id, source.id)
        # Keep explicit workbench removals; never re-enable a previously removed
        # source or overwrite an existing reference on a repeated migration.
        if (not removed and source.user_id != copy.user_id and not source.is_system
                and db.get(WorkspacePromptReference, key) is None):
            db.add(WorkspacePromptReference(user_id=copy.user_id, template_id=source.id))
        elif removed and db.get(WorkspacePromptRemoval, key) is None:
            # A legacy removal targeted the copied row. Preserve that choice
            # when the canonical source is already in the user's workspace.
            db.add(WorkspacePromptRemoval(user_id=copy.user_id, template_id=source.id))
        copy.is_deleted = True
        converted += 1
    db.flush()
    return {"converted": converted, "retained": retained}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    if not parser.parse_args().apply:
        parser.print_help()
        return
    from sqlalchemy.orm import Session
    from database import engine
    with engine.begin() as connection:
        apply_schema(connection)
    with Session(engine) as db, db.begin():
        counts = backfill(db)
    print(f"Workbench prompt references ready: {counts}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Migration failed ({type(exc).__name__}); keep writers stopped and fix the cause.", file=sys.stderr)
        raise SystemExit(1) from None
