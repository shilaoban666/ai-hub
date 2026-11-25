"""Opt-in live acceptance using a disposable MySQL database, Redis and Linux user.

Run from backend with AIHUB_TEST_LIVE=1, AIHUB_TEST_LIVE_MYSQL_URL pointing
to an empty test_aihub_live_* database, and AIHUB_TEST_LIVE_REDIS_PORT pointing
to an empty dedicated Redis instance. This spends real upstream model credits.
Set AIHUB_TEST_LIVE_STOP_ONLY=1 to run only the single-Run stop scenario.
"""

import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
from tempfile import mkdtemp
import time
import unittest
from uuid import uuid4


TEST_USER_ID = 997001
MODEL_ID = 7
AGENT_ID = 997001
SESSION_IDS = (997001, 997002)
STOP_SCRIPT = "acceptance_wait.py"
STOP_COMMAND = "python3 " + STOP_SCRIPT


def _events(response):
    revision = 0
    for line in response.iter_lines():
        if line.startswith("id: "):
            revision = int(line[4:])
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[6:])
        revision = int(payload.get("revision", revision))
        for event in payload.get("events", [payload]):
            yield event, revision


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("AIHUB_TEST_LIVE") == "1",
    "Requires Linux and explicit AIHUB_TEST_LIVE=1; sends real model requests",
)
class AgentLiveAcceptanceTests(unittest.TestCase):
    def test_real_native_model_refresh_stop_and_single_settlement(self):
        import httpx
        import pwd
        from redis import Redis
        from sqlalchemy import create_engine, inspect, select
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import sessionmaker

        from database import settings
        from models import (
            AIModel, Agent, AgentMessage, AgentPermissionRequest, AgentRun, AgentSession, Base,
            CreditAccount, CreditLedger, ModelPricingVersion, ModelRunCredential,
            ModelUsageEvent, PlatformAgentSettings, WorkspaceExecutionLease,
        )
        from sandbox.native import resolve_native_claude_bin

        stop_only = os.environ.get("AIHUB_TEST_LIVE_STOP_ONLY") == "1"
        max_runs = 1 if stop_only else 2
        target_url = make_url(os.environ["AIHUB_TEST_LIVE_MYSQL_URL"])
        source_url = make_url(settings.database_url)
        self.assertTrue(target_url.drivername.startswith("mysql"))
        self.assertTrue((target_url.database or "").startswith("test_aihub_live_"))
        self.assertNotEqual(target_url.database, source_url.database)
        redis_port = int(os.environ["AIHUB_TEST_LIVE_REDIS_PORT"])
        self.assertNotEqual(
            (os.environ.get("AIHUB_TEST_LIVE_REDIS_HOST", "127.0.0.1"), redis_port),
            (settings.redis_host, settings.redis_port),
            "Live acceptance requires a separate Redis instance",
        )
        redis = Redis(
            host=os.environ.get("AIHUB_TEST_LIVE_REDIS_HOST", "127.0.0.1"),
            port=redis_port, password=os.environ.get("AIHUB_TEST_LIVE_REDIS_PASSWORD") or None,
            socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
        )
        self.addCleanup(redis.close)
        self.assertTrue(redis.ping())
        self.assertEqual(redis.dbsize(), 0, "Dedicated Redis must be empty")
        target = create_engine(target_url, hide_parameters=True, pool_pre_ping=True)
        self.addCleanup(target.dispose)
        self.assertEqual(inspect(target).get_table_names(), [], "Test database must be empty")
        self.assertEqual(inspect(target).get_view_names(), [], "Test database must have no views")

        model_fields = (
            "id", "user_id", "scope", "is_enabled", "name", "provider",
            "api_key_encrypted", "api_proxy_url", "api_protocol", "reasoning_support",
        )
        pricing_fields = (
            "id", "model_id", "version", "input_rate", "output_rate",
            "cache_read_rate", "cache_creation_rate", "rate_scale",
        )
        policy_fields = (
            "version", "initial_claim_amount", "daily_claim_amount", "per_run_limit",
            "low_balance_threshold", "claim_timezone", "max_concurrent_runs",
        )
        source = create_engine(source_url, hide_parameters=True, pool_pre_ping=True)
        try:
            with source.connect() as connection:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                model = connection.execute(select(
                    *(getattr(AIModel, name) for name in model_fields),
                ).where(
                    AIModel.id == MODEL_ID, AIModel.scope == "platform",
                    AIModel.is_enabled == True, AIModel.is_deleted == False,
                )).mappings().one()
                pricing = connection.execute(select(
                    *(getattr(ModelPricingVersion, name) for name in pricing_fields),
                ).where(
                    ModelPricingVersion.model_id == MODEL_ID,
                    ModelPricingVersion.effective_to.is_(None),
                ).order_by(ModelPricingVersion.version.desc()).limit(1)).mappings().one()
                policy = connection.execute(select(
                    *(getattr(PlatformAgentSettings, name) for name in policy_fields),
                ).where(
                    PlatformAgentSettings.status == "published",
                ).order_by(PlatformAgentSettings.version.desc()).limit(1)).mappings().one()
                model, pricing, policy = dict(model), dict(pricing), dict(policy)
        finally:
            source.dispose()
        self.assertEqual(model["api_protocol"], "anthropic-messages")
        self.assertTrue(model["api_key_encrypted"], "Model must have an encrypted credential")
        self.assertTrue(settings.agent_credential_encryption_key, "Credential key is required")
        self.assertGreater(policy["per_run_limit"], 0)
        self.assertGreaterEqual(policy["initial_claim_amount"], policy["per_run_limit"])

        suffix = uuid4().hex[:8]
        user_prefix = "aih_live_" + suffix + "_"
        username = user_prefix + str(TEST_USER_ID)
        with self.assertRaises(KeyError):
            pwd.getpwnam(username)
        privileged = [] if os.geteuid() == 0 else ["sudo", "-n"]
        subprocess.run([*privileged, "true"], check=True, capture_output=True)
        root = Path(mkdtemp(prefix="aihub-live-", dir="/tmp"))
        self.assertEqual(root.parent, Path("/tmp"))
        self.assertFalse(root.is_symlink())
        root.chmod(0o711)
        redis_prefix = "aihub-live:" + suffix + ":"
        server = None
        run_ids = []
        client = None
        factory = sessionmaker(bind=target)
        try:
            # The wrapper only bounds the real CLI's turns; it contains no secrets.
            cli = resolve_native_claude_bin(settings.claude_code_native_claude_bin)
            wrapper = root / "claude-bounded"
            wrapper.write_text(
                "#!/bin/sh\nexec " + shlex.quote(cli) + ' "$@" --max-turns 3\n',
                encoding="ascii",
            )
            wrapper.chmod(0o755)
            Base.metadata.create_all(target)
            with factory() as db, db.begin():
                db.add(AIModel(**model))
                db.flush()
                db.add(ModelPricingVersion(**pricing))
                db.add(PlatformAgentSettings(
                    **policy, status="published", created_by=TEST_USER_ID,
                    assistant_name="Live acceptance", default_model_id=MODEL_ID,
                    timeout_seconds=60, max_turns=3,
                ))
                db.add(Agent(
                    id=AGENT_ID, user_id=TEST_USER_ID, kind="expert", name="Live acceptance",
                    runtime_type="claude_code", default_model_id=MODEL_ID,
                    timeout_seconds=60, max_turns=3, system_prompt="Follow the user's test request exactly.",
                ))
                db.flush()
                for session_id in SESSION_IDS[1:]:
                    db.add(AgentSession(
                        id=session_id, agent_id=AGENT_ID, user_id=TEST_USER_ID,
                        title="Live acceptance", runtime_type="claude_code", model_id=MODEL_ID,
                        source="web", message_count=2,
                    ))
                db.flush()
                for session_id in SESSION_IDS[1:]:
                    db.add_all([
                        AgentMessage(session_id=session_id, role="user", content="Test session setup."),
                        AgentMessage(session_id=session_id, role="assistant", content="Ready."),
                    ])
            port = _free_port()
            base_url = f"http://127.0.0.1:{port}"
            environment = os.environ.copy()
            environment.update({
                "DATABASE_URL": target_url.render_as_string(hide_password=False),
                "REDIS_HOST": os.environ.get("AIHUB_TEST_LIVE_REDIS_HOST", "127.0.0.1"),
                "REDIS_PORT": str(redis_port),
                "REDIS_PASSWORD": os.environ.get("AIHUB_TEST_LIVE_REDIS_PASSWORD", ""),
                "AIHUB_REDIS_PREFIX": redis_prefix,
                "CLAUDE_CODE_SANDBOX_TYPE": "native",
                "CLAUDE_CODE_NATIVE_CLAUDE_BIN": str(wrapper),
                "CLAUDE_CODE_NATIVE_WORKSPACE_ROOT": str(root / "legacy"),
                "CLAUDE_CODE_NATIVE_USER_PREFIX": user_prefix,
                "USER_WORKSPACE_ROOT": str(root / "workspaces"),
                "USER_WORKSPACE_USER_PREFIX": user_prefix,
                "AGENT_WORKSPACE_ROOT": str(root / "agents"),
                "SKILL_RELEASE_CACHE_ROOT": str(root / "cache"),
                "AGENT_CREDENTIAL_ENCRYPTION_KEY": settings.agent_credential_encryption_key,
                "AGENT_CREDENTIAL_KEY_VERSION": settings.agent_credential_key_version,
                "MODEL_GATEWAY_BASE_URL": base_url + "/api/model-gateway",
                "MODEL_GATEWAY_REQUEST_TIMEOUT_SECONDS": "60",
                "WEIXIN_ILINK_ENABLED": "false", "DINGTALK_ENABLED": "false",
            })
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--log-level", "error", "--no-access-log"],
                cwd=Path(__file__).parent, env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            client = httpx.Client(
                base_url=base_url, headers={"x-user-id": str(TEST_USER_ID)},
                timeout=httpx.Timeout(75, connect=3), trust_env=False,
            )
            deadline = time.monotonic() + 20
            while True:
                self.assertIsNone(server.poll(), "Isolated test server exited")
                try:
                    if client.get("/").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                self.assertLess(time.monotonic(), deadline, "Test server startup timed out")
                time.sleep(0.1)

            bootstrap = client.post("/api/bootstrap")
            self.assertEqual(bootstrap.status_code, 200)
            workbench_id = bootstrap.json()["data"]["assistant_id"]
            with factory() as db, db.begin():
                self.assertEqual(db.get(Agent, workbench_id).kind, "personal_default")
                if not stop_only:
                    db.add(AgentSession(
                        id=SESSION_IDS[0], agent_id=workbench_id, user_id=TEST_USER_ID,
                        title="Live acceptance", runtime_type="claude_code", model_id=MODEL_ID,
                        source="web", message_count=2,
                    ))
                    db.flush()
                    db.add_all([
                        AgentMessage(session_id=SESSION_IDS[0], role="user", content="Test session setup."),
                        AgentMessage(session_id=SESSION_IDS[0], role="assistant", content="Ready."),
                    ])

            def submit(agent_id, session_id, prompt):
                self.assertLess(len(run_ids), max_runs, f"At most {max_runs} application runs are allowed")
                with client.stream("POST", f"/api/agents/{agent_id}/messages", json={
                    "content": prompt, "session_id": session_id, "model_id": MODEL_ID,
                }) as response:
                    self.assertEqual(response.status_code, 200)
                    for event, revision in _events(response):
                        if event["type"] in {"run_queued", "run_start"}:
                            run_ids.append((agent_id, event["run_id"]))
                            return event["run_id"], revision
                        self.assertNotEqual(event["type"], "error", "Model run failed before starting")
                self.fail("Application did not return a Run ID")

            def replay(agent_id, run_id, after=0):
                return client.stream(
                    "GET", f"/api/agents/{agent_id}/runs/{run_id}/events", params={"after": after},
                )

            def decide_permission(agent_id, run_id, event, *, allow_stop=False):
                self.assertEqual(event.get("run_id"), run_id)
                self.assertTrue(event.get("req_id"))
                allowed = (
                    allow_stop and event.get("tool_name") == "Bash"
                    and (event.get("tool_input") or {}).get("command", "").strip() == STOP_COMMAND
                )
                result = client.post(f"/api/agents/{agent_id}/permission/decide", json={
                    "run_id": run_id, "req_id": event["req_id"],
                    "decision": "allow" if allowed else "deny", "remember": False,
                })
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.json()["data"]["ok"])
                self.assertTrue(allowed, "Unexpected permission request was denied")

            def report_metrics(db, run_id, label):
                run = db.get(AgentRun, run_id)
                credential = db.query(ModelRunCredential).filter_by(run_id=run_id).one()
                total_tokens = sum(int(getattr(run, field) or 0) for field in (
                    "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
                ))
                print(f"{label}: status={run.status}, requests={credential.request_count}, "
                      f"charged_points={run.charged_points}, total_tokens={total_tokens}")

            if not stop_only:
                marker = "AIHUB_LIVE_OK_" + suffix
                first, cursor = submit(workbench_id, SESSION_IDS[0], "Reply with exactly " + marker + ". Do not call tools.")
                with replay(workbench_id, first, cursor) as response:
                    self.assertEqual(response.status_code, 200)
                    events = []
                    for event, _ in _events(response):
                        if event["type"] == "permission_request":
                            decide_permission(workbench_id, first, event)
                        self.assertNotEqual(event["type"], "tool_use", "Reply scenario must not call tools")
                        events.append(event)
                self.assertEqual(events[-1].get("status"), "succeeded")
                self.assertIn(marker, "".join(event.get("content", "") for event in events if event["type"] in {"text", "done"}))
                with factory() as db:
                    run = db.get(AgentRun, first)
                    self.assertEqual(run.status, "succeeded", run.error_code)
                    self.assertIsNotNone(run.assistant_message_id)
                    self.assertEqual(db.query(AgentMessage).filter_by(session_id=SESSION_IDS[0], role="assistant").count(), 2)
                    self.assertEqual(run.settlement_status, "settled")
                    self.assertEqual(db.query(CreditLedger).filter_by(run_id=first, entry_type="run_settlement").count(), 1)
                    # Live metering debits reported usage only; starting a Run
                    # does not create a reservation ledger entry.
                    self.assertEqual(db.query(CreditLedger).filter_by(run_id=first, entry_type="run_reservation").count(), 0)
                    credential = db.query(ModelRunCredential).filter_by(run_id=first).one()
                    self.assertGreater(credential.request_count, 0)
                    self.assertEqual(db.query(ModelUsageEvent).filter_by(run_id=first).count(), credential.request_count)
                    counts = (db.query(AgentRun).count(), db.query(AgentMessage).count(), db.query(CreditLedger).count())
                    report_metrics(db, first, "Workbench")
                with replay(workbench_id, first) as response:
                    self.assertEqual(response.status_code, 200)
                    replayed = [event for event, _ in _events(response)]
                self.assertEqual(replayed[-1].get("status"), "succeeded")
                with factory() as db:
                    self.assertEqual((db.query(AgentRun).count(), db.query(AgentMessage).count(), db.query(CreditLedger).count()), counts)
                    remaining = db.query(CreditAccount).filter_by(user_id=TEST_USER_ID).one().available_balance
                    self.assertLessEqual(remaining, policy["initial_claim_amount"])
                    self.assertGreaterEqual(remaining, 0)

            uploaded = client.post(f"/api/agents/{AGENT_ID}/files/upload", files={
                "files": (STOP_SCRIPT, b"import time\ntime.sleep(30)\n", "text/x-python"),
            })
            self.assertEqual(uploaded.status_code, 200)
            self.assertEqual(len(uploaded.json()["data"]["uploaded"]), 1)
            self.assertEqual(uploaded.json()["data"]["uploaded"][0]["name"], STOP_SCRIPT)
            second, _ = submit(AGENT_ID, SESSION_IDS[1],
                "Use Bash exactly once with command exactly " + STOP_COMMAND + ". "
                "The file is already uploaded. Then reply TEST_FINISHED. Do not call any other tools.")
            with replay(AGENT_ID, second) as response:
                self.assertEqual(response.status_code, 200)
                saw_stop = False
                for event, _ in _events(response):
                    if event["type"] == "permission_request":
                        decide_permission(AGENT_ID, second, event, allow_stop=True)
                    if event["type"] == "tool_use":
                        self.assertEqual(event.get("name"), "Bash", "Unexpected tool in stop scenario")
                        self.assertEqual((event.get("input") or {}).get("command", "").strip(), STOP_COMMAND)
                        saw_stop = True
                        break
                    self.assertNotIn(event["type"], {"error", "done", "stream_end"}, "Stop scenario ended before wait script")
            self.assertTrue(saw_stop)
            deadline = time.monotonic() + 5
            while subprocess.run([
                "pgrep", "-u", username, "-f", "-x", r"([^ ]*/)?python3 acceptance_wait[.]py",
            ], capture_output=True).returncode != 0:
                with factory() as db:
                    requests = [{
                        "run_id": row.run_id, "req_id": row.req_id,
                        "tool_name": row.tool_name, "tool_input": json.loads(row.tool_input or "{}"),
                    } for row in db.query(AgentPermissionRequest).filter_by(run_id=second, status="pending")]
                for request in requests:
                    decide_permission(AGENT_ID, second, request, allow_stop=True)
                self.assertLess(time.monotonic(), deadline, "Wait script did not start")
                time.sleep(0.1)
            response = client.post(f"/api/agents/{AGENT_ID}/runs/{second}/cancel")
            self.assertEqual(response.status_code, 200)
            with replay(AGENT_ID, second) as response:
                self.assertEqual(response.status_code, 200)
                stopped = [event for event, _ in _events(response)]
            self.assertEqual(stopped[-1].get("status"), "cancelled")
            with factory() as db:
                self.assertEqual(db.get(AgentRun, second).status, "cancelled")
                self.assertEqual(db.query(AgentRun).count(), max_runs)
                self.assertEqual(db.query(WorkspaceExecutionLease).filter(WorkspaceExecutionLease.run_id.is_not(None)).count(), 0)
                self.assertEqual(db.query(CreditLedger).filter_by(run_id=second, entry_type="run_settlement").count(), 1)
                report_metrics(db, second, "Expert stop")
            self.assertNotEqual(subprocess.run(["pgrep", "-u", username], capture_output=True).returncode, 0, "Cancelled native processes remain alive")
            if stop_only:
                print("Live acceptance verified: expert cancellation/lease release/single settlement, 1 Run")
            else:
                print("Live acceptance verified: workbench reply/replay/settlement and expert cancellation/lease release, 2 Runs")
        finally:
            if client is not None:
                for agent_id, run_id in run_ids:
                    try:
                        client.post(f"/api/agents/{agent_id}/runs/{run_id}/cancel", timeout=3)
                    except Exception:
                        pass
                client.close()
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            subprocess.run([*privileged, "pkill", "-KILL", "-u", username], capture_output=True)
            subprocess.run([*privileged, "userdel", username], capture_output=True)
            try:
                keys = list(redis.scan_iter(match=redis_prefix + "*"))
                if keys:
                    redis.delete(*keys)
            finally:
                self.assertEqual(root.parent, Path("/tmp"))
                self.assertTrue(root.name.startswith("aihub-live-"))
                subprocess.run([*privileged, "chattr", "-R", "-i", str(root)], capture_output=True)
                subprocess.run([*privileged, "rm", "-rf", "--", str(root)], check=True, capture_output=True)
                self.assertFalse(root.exists())
                with self.assertRaises(KeyError):
                    pwd.getpwnam(username)


if __name__ == "__main__":
    unittest.main()
