# Agent execution and credential rollout

This change is additive, but credential encryption should be enabled in stages so
older application instances never receive records they cannot decrypt.

1. Deploy the new code with `AGENT_CREDENTIAL_ENCRYPTION_KEY` empty.
2. Run `python _run_migration.py migrations/017_agent_execution_and_credentials.sql`.
3. Run `python _run_migration.py migrations/018_agent_control_and_mcp_overrides.sql`.
4. Configure the same 32-byte `AGENT_CREDENTIAL_ENCRYPTION_KEY` and key version on
   every API, channel Worker, and Runtime Worker instance.
5. Restart all instances, then run `python _migrate_agent_credentials.py --dry-run`.
6. Run `python _migrate_agent_credentials.py` to encrypt legacy model keys and MCP
   configs and clear their plaintext columns.

New and updated credentials remain plaintext only while the encryption key is
unset. Once encrypted data exists, a missing or wrong key fails closed instead of
falling back to stale plaintext.

Agent execution is serialized across processes through `agent_execution_leases`.
The default lease is 30 seconds and is renewed while the run is active. Tune
`AGENT_EXECUTION_LEASE_SECONDS` only if database latency can regularly approach the
default duration.

Migration 018 also creates the durable permission-request table used by every API
process and adds encrypted per-Agent MCP overrides. MCP overrides are rejected
until `AGENT_CREDENTIAL_ENCRYPTION_KEY` is configured. Run cancellation and
permission delivery use the shared MySQL database; `AGENT_RUN_CONTROL_POLL_SECONDS`
controls their polling interval and defaults to 0.5 seconds.
