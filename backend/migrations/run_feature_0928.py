"""Compatibility entry point; use run_upgrade.py for current releases."""
from run_upgrade import MIGRATIONS, apply_migrations, main, run_sql


if __name__ == "__main__":
    raise SystemExit(main())
