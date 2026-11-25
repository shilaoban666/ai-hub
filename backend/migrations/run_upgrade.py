"""AI Hub full incremental upgrade from master b663a72 (043) through 063.

Preview is offline by default; --check is read-only; only --apply writes.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import hashlib


MIGRATION_DIR = Path(__file__).resolve().parent
BACKEND_DIR = MIGRATION_DIR.parent
MIGRATIONS = (
    "044_expert_agent_prompt_modules.sql",
    "045_agent_scoped_workspaces.sql",
    "046_agent_workspace_uniqueness.sql",
    "047_workspace_scope_keys.sql",
    "048_agent_mcp_binding_status.sql",
    "049_agent_asset_scopes.py",
    "050_assistant_reasoning_settings.sql",
    "051_agent_prompt_snapshots.py",
    "052_split_workbench_settings.py",
    "053_web_run_hardening.sql",
    "054_workspace_prompt_references.py",
    "055_expert_prompt_references.py",
    "056_claude_runtime.py",
    "057_noun_highlight.sql",
    "058_skill_conversation_examples.sql",
    "059_realtime_model_billing.sql",
    "060_skill_development_mode.sql",
    "061_feedback_processing_details.sql",
    "062_global_runtime_environment.sql",
    "063_agent_open_calls.sql",
    "063_knowledge_base.sql",
)


def run_sql(engine, path):
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            # Keep PREPARE/session variables together; never split SQL on ';'.
            cursor.execute(path.read_text(encoding="utf-8-sig"))
            while cursor.nextset():
                pass
    finally:
        connection.close()


def configured_engine():
    """Import configuration only for explicit online check/apply modes."""
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))
    from pymysql.constants import CLIENT
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from database import settings, _configure_database_timezone

    url = make_url(settings.database_url)
    if url.get_backend_name() != "mysql" or url.get_driver_name() != "pymysql":
        raise RuntimeError("Requires mysql+pymysql DATABASE_URL")
    engine = create_engine(
        url, isolation_level="AUTOCOMMIT",
        connect_args={"client_flag": CLIENT.MULTI_STATEMENTS},
    )
    _configure_database_timezone(engine)
    return engine


def verify(engine, *, baseline=False):
    from upgrade_checks import schema_problems, data_problems
    with engine.connect() as connection:
        problems = schema_problems(connection, baseline=baseline)
        if not baseline and not problems:
            problems.extend(data_problems(connection))
    for problem in problems:
        print(f"NOT READY: {problem}", flush=True)
    if not problems:
        print("Baseline prerequisites: OK" if baseline else "Upgrade schema and backfills: OK", flush=True)
    return not problems


def check_upgrade():
    engine = None
    try:
        engine = configured_engine()
        return 0 if verify(engine) else 1
    except Exception as exc:
        print(f"CHECK FAILED ({type(exc).__name__}); no migrations applied.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def apply_migrations(paths):
    engine = None
    current = None
    try:
        engine = configured_engine()
        if not verify(engine, baseline=True):
            print("Baseline is incomplete; no migrations executed. Restore the 043 prerequisites first.", file=sys.stderr)
            return 1
        for path in paths:
            current = path
            print(f"RUN {path.name}", flush=True)
            if path.suffix == ".sql":
                run_sql(engine, path)
            else:
                subprocess.run(
                    [sys.executable, str(path), "--apply"],
                    cwd=str(BACKEND_DIR),
                    check=True,
                )
            print(f"OK  {path.name}", flush=True)
        current = None
        if not verify(engine):
            print("Post-check failed. Keep writers stopped; inspect the reported objects/backfills before resuming.", file=sys.stderr)
            return 1
    except Exception as exc:
        # Driver errors can contain credentials or data; report only the step/type.
        step = current.name if current else "configuration/check"
        print(f"FAILED {step} ({type(exc).__name__}).", file=sys.stderr)
        print(
            "Stopped. MySQL DDL may already be committed. Keep writers stopped, "
            "fix the cause, and retry the failed step.",
            file=sys.stderr,
        )
        if current:
            print(
                f"Resume from repository root: python backend/migrations/run_upgrade.py "
                f"--from {current.name[:3]} --apply",
                file=sys.stderr,
            )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print("Complete: all selected migrations applied and upgrade checks passed.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="Apply to the backend's configured database"
    )
    mode.add_argument("--check", action="store_true", help="Read-only schema/backfill verification against the configured MySQL database")
    parser.add_argument(
        "--from", dest="start", choices=list(dict.fromkeys(name[:3] for name in MIGRATIONS)),
        default=None, help="Start at this migration, inclusive (default: 044)",
    )
    args = parser.parse_args(argv)
    if args.check and args.start is not None:
        parser.error("--check validates the complete upgrade; do not combine it with --from")
    start = next(i for i, name in enumerate(MIGRATIONS) if name.startswith(args.start or '044'))
    paths = [MIGRATION_DIR / name for name in MIGRATIONS[start:]]
    missing = [name for name in MIGRATIONS if not (MIGRATION_DIR / name).is_file()]
    if missing:
        parser.error("Missing migration files: " + ", ".join(missing))
    print("AI Hub master b663a72: all migrations 044-063 (master already includes 043)")
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(f"  {path.name}  sha256={digest}")
    if args.check:
        return check_upgrade()
    if not args.apply:
        print("Preview only; no database configuration loaded or connection opened.")
        print("After backup and stopping API/workers, add --apply to execute.")
        return 0
    return apply_migrations(paths)


if __name__ == "__main__":
    raise SystemExit(main())
