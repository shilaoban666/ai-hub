"""Split default-assistant settings from shared agent policy.

From backend: python migrations/052_split_workbench_settings.py --apply
Safe to repeat; existing workbench drafts/publications are never overwritten.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def migrate(engine):
    from models import WorkbenchSettings
    from agent_settings import seed_workbench_settings
    from sqlalchemy.orm import Session

    WorkbenchSettings.__table__.create(engine, checkfirst=True)
    with Session(engine) as db, db.begin():
        seed_workbench_settings(db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    if parser.parse_args().apply:
        from database import engine
        try:
            migrate(engine)
            print("Workbench settings migrated; shared agent policy retained")
        except Exception as exc:
            print(f"Migration failed ({type(exc).__name__})", file=sys.stderr)
            raise SystemExit(1) from None
    else:
        parser.print_help()
