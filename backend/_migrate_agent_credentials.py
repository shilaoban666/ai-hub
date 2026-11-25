"""Idempotently move legacy model/MCP plaintext into encrypted columns."""

from __future__ import annotations

import argparse

from credential_crypto import AgentCredentialCrypto
from database import SessionLocal, settings
from models import AIModel, McpService


def migrate(*, dry_run: bool = False) -> tuple[int, int]:
    if AgentCredentialCrypto.from_settings(settings) is None:
        raise RuntimeError("AGENT_CREDENTIAL_ENCRYPTION_KEY must be configured first")

    db = SessionLocal()
    model_count = 0
    mcp_count = 0
    try:
        models = db.query(AIModel).filter(
            AIModel.api_key_encrypted.is_(None),
            AIModel._api_key_plaintext != "",
        ).all()
        mcps = db.query(McpService).filter(
            McpService.config_encrypted.is_(None),
            McpService._config_plaintext.isnot(None),
        ).all()

        model_count = len(models)
        mcp_count = len(mcps)
        if dry_run:
            db.rollback()
            return model_count, mcp_count

        for model in models:
            model.store_api_key(model._api_key_plaintext)
        for mcp in mcps:
            mcp.store_config(mcp._config_plaintext)
        db.commit()
        return model_count, mcp_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    encrypted_models, encrypted_mcps = migrate(dry_run=args.dry_run)
    action = "would encrypt" if args.dry_run else "encrypted"
    print(f"{action}: {encrypted_models} model keys, {encrypted_mcps} MCP configs")
