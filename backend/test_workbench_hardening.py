"""Regression checks for fenced filesystem writes and bounded agent reads."""
import asyncio
import io
import json
import threading
import unittest
from datetime import timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker, lazyload

import agent_execution_lease as leases
import agent_routes
import agent_service
from agent_workspace import build_claude_md, build_settings_json
from database import Base, settings
from models import (Agent, AgentRun, AgentSession, AIModel, UserWorkspace,
                    WorkspaceExecutionLease, PromptTemplate, agent_prompt_templates,
                    Skill, SkillInstallation, SkillRelease, ExpertSkillBinding,
                    McpDefinition, McpRevision, McpConnection, ExpertMcpBinding,
                    RuntimeCell, WorkspaceRunView)
from enterprise_workspace import finish_run_view
from sandbox.base import WorkspaceContext
from sandbox.container import ContainerSandbox
from sandbox.native import NativeSandbox
from test_agent_service import (_agent, _model, _session, _DB, _Memory, _Sandbox,
                                _Runtime, _CancelledRuntime, _PartialCancelledRuntime,
                                _execution_dependencies)
from runtimes.base import RuntimeEvent
from workspace_provider import agent_workspace_snapshot, workspace_snapshot, workspace_model_snapshot


class WorkspaceHardeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="aihub-hardening-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_engine("sqlite:///" + (self.root / "leases.db").as_posix(),
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(Agent(id=1, user_id=7, name="Expert", kind="expert"))
            db.add(UserWorkspace(id=1, user_id=7, agent_id=1, workspace_key="expert"))
            db.commit()
        self.acquire = partial(leases.acquire_agent_execution_lease,
                               session_factory=self.factory, lease_seconds=5, poll_seconds=0.05)

    async def test_upload_and_delete_reject_busy_workspace_then_preserve_changes(self):
        provider = ContainerSandbox()
        user_root = self.root / "expert"
        files = user_root / "files"
        view = user_root / "runs" / "first" / "view"
        files.mkdir(parents=True)
        view.mkdir(parents=True)
        (files / "delete.txt").write_text("old")
        (view / "delete.txt").write_text("old")
        (view / "result.txt").write_text("new result")
        context = WorkspaceContext("container", str(view), str(view), [], run_id="first", handle={
            "view_root": str(view), "files_root": str(files), "user_root": str(user_root),
            "run_root": str(view.parent),
        })
        with self.factory() as db:
            workspace = db.get(UserWorkspace, 1)
            user = SimpleNamespace(user_id=7)
            with (patch.object(settings, "user_workspace_root", str(self.root)),
                  patch.object(agent_routes, "bind_agent_workspace", return_value=(workspace, None)),
                  patch.object(agent_routes, "get_workspace_provider", return_value=provider),
                  patch.object(agent_routes, "acquire_agent_execution_lease", self.acquire)):
                lease = await self.acquire(workspace_id=1, run_id="first")
                async with lease:
                    for operation in (
                        agent_routes.upload_workspace_files(1, [UploadFile(io.BytesIO(b"upload"), filename="upload.txt")], db, user),
                        agent_routes.delete_workspace_file(1, "delete.txt", db, user),
                    ):
                        with self.assertRaises(HTTPException) as failure:
                            await operation
                        self.assertEqual(failure.exception.status_code, 409)
                    self.assertFalse((files / "upload.txt").exists())
                    self.assertTrue((files / "delete.txt").exists())
                    self.assertTrue(await asyncio.to_thread(lease.commit_workspace, lambda: provider.cleanup(context)))
                result = await agent_routes.upload_workspace_files(
                    1, [UploadFile(io.BytesIO(b"upload"), filename="upload.txt")], db, user,
                )
                self.assertEqual(result["uploaded"][0]["path"], "upload.txt")
                await agent_routes.delete_workspace_file(1, "delete.txt", db, user)
        self.assertEqual((files / "upload.txt").read_bytes(), b"upload")
        self.assertEqual((files / "result.txt").read_text(), "new result")
        self.assertFalse((files / "delete.txt").exists())

    async def test_expired_and_replaced_owner_cannot_commit(self):
        old = await self.acquire(workspace_id=1, run_id="old")
        with self.factory() as db:
            db.get(WorkspaceExecutionLease, 1).lease_until = leases.utcnow() - timedelta(seconds=1)
            db.commit()
        calls = []
        self.assertFalse(await asyncio.to_thread(old.commit_workspace, lambda: calls.append("expired")))
        new = await self.acquire(workspace_id=1, run_id="new")
        async with new:
            self.assertFalse(await asyncio.to_thread(old.commit_workspace, lambda: calls.append("stale")))
            self.assertTrue(await asyncio.to_thread(new.commit_workspace, lambda: calls.append("new")))
        self.assertEqual(calls, ["new"])

    async def test_takeover_waits_for_write_even_if_expiry_passes_mid_copy(self):
        old = await self.acquire(workspace_id=1, run_id="old")
        with self.factory() as db:
            db.get(WorkspaceExecutionLease, 1).lease_until = leases.utcnow() + timedelta(seconds=0.15)
            db.commit()
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        def write():
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(3):
                raise RuntimeError("writer timed out")
        writer = asyncio.create_task(leases._run_sync_atomic(old.commit_workspace, write))
        competitor = None
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.sleep(0.2)
            competitor = asyncio.create_task(self.acquire(workspace_id=1, run_id="new"))
            await asyncio.sleep(0.1)
            self.assertFalse(competitor.done())
            finish.set()
            self.assertTrue(await writer)
            self.assertFalse(competitor.done())
            await leases._run_sync_atomic(old._release)
            new = await asyncio.wait_for(competitor, 2)
            async with new:
                self.assertTrue(await new.is_owned())
        finally:
            finish.set()
            await asyncio.gather(writer, return_exceptions=True)
            if competitor is not None and not competitor.done():
                competitor.cancel()
                await asyncio.gather(competitor, return_exceptions=True)

    async def test_repeated_cancelled_acquisition_releases_abandoned_lease(self):
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        acquire = leases._try_acquire
        def delayed(**kwargs):
            token = acquire(**kwargs)
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(3):
                raise RuntimeError("acquisition timed out")
            return token
        with patch.object(leases, "_try_acquire", delayed):
            task = asyncio.create_task(self.acquire(workspace_id=1, run_id="cancelled"))
            try:
                await asyncio.wait_for(started.wait(), 1)
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0.02)
                    self.assertFalse(task.done())
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                finish.set()
                await asyncio.gather(task, return_exceptions=True)
        new = await asyncio.wait_for(self.acquire(workspace_id=1, run_id="next"), 1)
        async with new:
            self.assertTrue(await new.is_owned())

    async def test_expired_orm_inputs_do_not_query_from_filesystem_thread(self):
        queries = []
        event.listen(self.engine, "before_cursor_execute",
                     lambda *args: queries.append(threading.get_ident()))
        with self.factory() as db:
            agent = db.query(Agent).options(lazyload("*")).first()
            workspace = db.get(UserWorkspace, 1)
            model = AIModel(id=1, user_id=7, name="test", provider="anthropic", api_key="test-key")
            db.add(model)
            db.commit()
            self.assertTrue(inspect(agent).expired_attributes)
            agent.runtime_skills = []
            agent.runtime_mcps = []
            snapshot = agent_workspace_snapshot(agent)
            workspace_values = workspace_snapshot(workspace)
            model_values = workspace_model_snapshot(model)
            queries.clear()
            def build():
                self.assertEqual(workspace_values.workspace_key, "expert")
                self.assertEqual(model_values.api_key, "test-key")
                build_claude_md(snapshot, [])
                build_settings_json(snapshot, model_values, mcps=[])
            await asyncio.to_thread(build)
            self.assertEqual(queries, [])

    async def test_expired_workspace_snapshot_supports_native_prepare_and_skill_sync(self):
        queries = []
        event.listen(self.engine, "before_cursor_execute",
                     lambda *args: queries.append(threading.get_ident()))
        with self.factory() as db:
            agent = db.query(Agent).options(lazyload("*")).first()
            workspace = db.get(UserWorkspace, 1)
            db.commit()
            self.assertTrue(inspect(workspace).expired_attributes)
            agent.runtime_skills = []
            agent.runtime_mcps = []
            agent_values = agent_workspace_snapshot(agent)
            workspace_values = workspace_snapshot(workspace)
            self.assertEqual(workspace_values.user_id, 7)
            queries.clear()
            with (patch("sandbox.native.sys.platform", "linux"),
                  patch.object(settings, "user_workspace_root", str(self.root)),
                  patch.object(NativeSandbox, "_run_root", return_value=SimpleNamespace(
                      returncode=0, stdout="", stderr="")),
                  patch.object(NativeSandbox, "_ensure_user") as ensure_user,
                  patch.object(NativeSandbox, "_ensure_venv"),
                  patch.object(NativeSandbox, "_apply_permissions"),
                  patch.object(NativeSandbox, "_sync_managed_files")):
                provider = NativeSandbox()
                context = await asyncio.to_thread(
                    provider.prepare_execution, agent_values, None,
                    run_id="snapshot-native", workspace=workspace_values,
                )
                self.assertEqual(context.handle["username"], settings.user_workspace_user_prefix + "7")
                self.assertEqual(await asyncio.to_thread(
                    provider.sync_skill_installations, agent_values, workspace_values,
                ), [])
                self.assertEqual(ensure_user.call_count, 2)
                ensure_user.assert_called_with(settings.user_workspace_user_prefix + "7", str(self.root / "expert"))
                self.assertEqual(queries, [])

    async def test_stale_native_discard_does_not_unlink_current(self):
        provider = object.__new__(NativeSandbox)
        context = WorkspaceContext("native", "/view", "/view", [], run_id="old", handle={
            "view_root": "/root/runs/old/view", "run_root": "/root/runs/old", "user_root": "/root",
        })
        with (patch.object(provider, "_assert_user_workspace_path"),
              patch.object(provider, "_unlock_managed"), patch.object(provider, "_run_root") as run):
            provider.discard_execution(context)
            run.assert_called_once_with("rm", "-rf", "/root/runs/old", check=False)

    async def test_skill_sync_with_expired_real_orm_queries_only_on_owner_thread(self):
        owner = threading.get_ident()
        queries = []
        event.listen(self.engine, "before_cursor_execute",
                     lambda conn, cursor, sql, *args: queries.append((sql, threading.get_ident())))
        provider = SimpleNamespace()
        def synchronize(agent, workspace):
            self.assertNotEqual(threading.get_ident(), owner)
            self.assertEqual(agent.id, 1)
            self.assertEqual(agent.name, "Expert")
            self.assertEqual(workspace.workspace_key, "expert")
            self.assertEqual(agent.runtime_skills, [])
            return []
        provider.sync_skill_installations = synchronize
        with self.factory() as db:
            agent = db.query(Agent).options(lazyload("*")).first()
            workspace = db.get(UserWorkspace, 1)
            with (patch.object(agent_routes, "_get_agent_or_404", return_value=agent),
                  patch.object(agent_routes, "bind_agent_workspace", return_value=(workspace, None)),
                  patch.object(agent_routes, "load_runtime_assets", return_value={"skills": []}),
                  patch.object(agent_routes, "get_workspace_provider", return_value=provider),
                  patch.object(agent_routes, "acquire_agent_execution_lease", self.acquire)):
                self.assertEqual(await agent_routes.sync_agent_skill_installations(
                    1, db, SimpleNamespace(user_id=7),
                ), {"status": "synced", "skills": []})
        # Lease sessions are intentionally worker-owned. Record only SQL that
        # mentions the Agent inputs to distinguish them from lease queries.
        input_queries = [(sql, thread) for sql, thread in queries
                         if "FROM agents" in sql or "user_workspaces.workspace_key" in sql]
        self.assertTrue(input_queries)
        self.assertTrue(all(thread == owner for _, thread in input_queries))

    async def test_old_run_audit_does_not_change_new_owner_cell(self):
        new = await self.acquire(workspace_id=1, run_id="new")
        with self.factory() as db:
            db.add(RuntimeCell(id=1, workspace_id=1, user_id=7, status="running", runtime_type="claude_code"))
            db.add(WorkspaceRunView(id=1, workspace_id=1, agent_id=1, run_id="old", status="running"))
            db.commit()
            finish_run_view(db, "old", success=False, error="lease lost")
            self.assertEqual(db.get(RuntimeCell, 1).status, "running")
            self.assertEqual(db.get(WorkspaceRunView, 1).cleanup_status, "failed")
        async with new:
            self.assertTrue(await new.is_owned())


class AgentListHardeningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.statements = []
        event.listen(self.engine, "before_cursor_execute",
                     lambda conn, cursor, sql, *args: self.statements.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)

    def test_personal_page_queries_do_not_grow_with_items_or_history(self):
        self.db.add_all([Agent(id=i, user_id=7, kind="expert", name=f"Agent {i}") for i in range(1, 11)])
        self.db.add(AIModel(id=1, user_id=7, name="model", provider="anthropic"))
        self.db.add_all([AgentSession(id=i, agent_id=1, user_id=7) for i in range(1, 1001)])
        self.db.commit()
        counts = []
        for limit in (1, 10):
            self.db.expunge_all()
            self.statements.clear()
            result = agent_routes.list_agents(0, limit, None, self.db, SimpleNamespace(user_id=7))
            self.assertEqual(result.total, 10)
            self.assertEqual(len(result.items), limit)
            self.assertFalse(any("FROM agent_sessions" in sql and "count(" not in sql.lower() for sql in self.statements))
            counts.append(len(self.statements))
        self.assertEqual(counts[0], counts[1])
        self.assertLessEqual(counts[1], 8)
        self.assertEqual(sum(item.session_count for item in result.items), 1000)

    def test_public_page_uses_live_visibility_before_pagination(self):
        self.db.add_all([Agent(id=i, user_id=7, kind="expert", name=f"Agent {i}", is_public=True)
                         for i in range(1, 101)])
        for agent_id, snapshot_public, source_public, source_system, deleted in (
            (1, False, True, False, False), (2, True, False, False, False),
            (3, True, True, False, True), (4, True, False, True, False),
        ):
            self.db.add(PromptTemplate(id=agent_id, user_id=7, name=f"Prompt {agent_id}",
                                      content="prompt", is_public=source_public,
                                      is_system=source_system, is_deleted=deleted))
            self.db.execute(agent_prompt_templates.insert().values(
                agent_id=agent_id, prompt_template_id=agent_id,
                snapshot_json=json.dumps({"name": "snapshot", "is_public": snapshot_public, "is_system": False}),
            ))
        self.db.add_all([
            Skill(id=1, user_id=7, name="private", version="1", is_public=False),
            SkillRelease(id=1, skill_id=1, version="1", status="published", file_path="unused", file_url=""),
            SkillInstallation(id=1, user_id=7, workspace_id=1, scope_agent_id=5, skill_id=1, release_id=1),
            ExpertSkillBinding(agent_id=5, installation_id=1),
            McpDefinition(id=1, owner_user_id=7, name="private", scope="user", status="published", transport_type="http"),
            McpRevision(id=1, definition_id=1, version=1, status="published", config_json="{}", content_sha256="test", created_by=7),
            McpConnection(id=1, user_id=7, name="private", workspace_id=1, scope_agent_id=6, definition_id=1, revision_id=1),
            ExpertMcpBinding(agent_id=6, connection_id=1, status="active"),
        ])
        self.db.commit()
        expected = [a.id for a in self.db.query(Agent).options(lazyload("*")).order_by(
            Agent.updated_at.desc(), Agent.id.desc(),
        ).all() if not agent_routes._agent_publication_errors(self.db, a)]
        self.assertEqual(len(expected), 96)
        self.db.expunge_all()
        self.statements.clear()
        result = agent_routes.list_public_agents("", 85, 10, self.db)
        self.assertEqual(result["total"], 96)
        self.assertEqual([item["id"] for item in result["items"]], expected[85:95])
        self.assertEqual(len(self.statements), 5)
        self.assertTrue(all("agent_sessions" not in sql for sql in self.statements))


class ExecutionWritebackTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_failure_reports_failure_and_preserves_reply_for_web_and_channel(self):
        for source in ("web", "channel"):
            with self.subTest(source=source), TemporaryDirectory(prefix="aihub-writeback-") as temporary:
                root = Path(temporary)
                user_root = root / "expert"
                files = user_root / "files"
                view = user_root / "runs" / "quota-run" / "view"
                files.mkdir(parents=True)
                view.mkdir(parents=True)
                (files / "previous.txt").write_text("saved")
                (view / "generated.txt").write_text("larger than the quota")
                context = WorkspaceContext("native", str(view), str(view), [], run_id="quota-run", handle={
                    "view_root": str(view), "files_root": str(files), "user_root": str(user_root),
                    "run_root": str(view.parent), "quota_bytes": 1,
                })
                provider = _Sandbox()
                events = []
                async def emit(evt):
                    events.append(evt)
                db = _DB(_session(), _model())
                if source == "channel":
                    db.run = AgentRun(id="quota-run", user_id=7, agent_id=1, session_id=11, config_snapshot="{}")
                with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
                      patch.object(agent_service, "get_workspace_provider", return_value=provider),
                      patch.object(agent_service, "get_runtime", return_value=_Runtime()),
                      patch.object(provider, "prepare_execution", return_value=context),
                      patch.object(provider, "cleanup", wraps=ContainerSandbox().cleanup) as write,
                      patch.object(provider, "discard_execution") as discard,
                      patch.object(settings, "user_workspace_root", str(root)),
                      patch.object(agent_service, "finish_run_view") as finish_view,
                      patch.object(agent_service, "settle_platform_run") as settle):
                    result = await agent_service.execute_agent_turn(
                        agent=_agent(), user_input="test", session_id=11, user_id=7,
                        db=db, source=source, run_id="quota-run", manage_run_record=source == "web", on_event=emit,
                    )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.final_text, "result")
                self.assertEqual(result.assistant_message_id, 102)
                self.assertEqual(result.usage, {"input_tokens": 1, "output_tokens": 2})
                self.assertTrue(any(block.get("content") == "result" for block in _Memory.saved_blocks))
                self.assertIn("文件保存失败", result.error)
                self.assertEqual(events[-1].type, "error")
                self.assertEqual(events[-1].error_code, "workspace_writeback_failed")
                self.assertEqual(events[-1].content, result.error)
                self.assertEqual(finish_view.call_args.kwargs, {"success": False, "error": "workspace quota exceeded"})
                write.assert_called_once()
                discard.assert_not_called()
                self.assertEqual((files / "previous.txt").read_text(), "saved")
                self.assertFalse((files / "generated.txt").exists())
                self.assertTrue(view.exists())
                self.assertEqual(db.run.assistant_message_id, 102)
                if source == "web":
                    self.assertEqual(db.run.status, "failed")
                    self.assertEqual(db.run.error_code, "workspace_writeback_failed")
                    self.assertEqual(db.run.error_message, result.error)
                    settle.assert_called_once_with(db, db.run, "failed")
                else:
                    settle.assert_not_called()

    async def test_writeback_failure_keeps_primary_runtime_error_and_hides_internal_details(self):
        class FailingRuntime(_Runtime):
            async def run(self, **kwargs):
                await super().run(**kwargs)
                await kwargs["on_event"](RuntimeEvent(
                    type="error", content="模型服务失败", error_code="model_error",
                ))
        provider = _Sandbox()
        events = []
        async def emit(evt):
            events.append(evt)
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=provider),
              patch.object(agent_service, "get_runtime", return_value=FailingRuntime()),
              patch.object(provider, "cleanup", side_effect=OSError("cannot write /internal/workspace"))):
            db = _DB(_session(), _model())
            result = await agent_service.execute_agent_turn(
                agent=_agent(), user_input="test", session_id=11, user_id=7, db=db, on_event=emit,
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.final_text, "result")
        self.assertTrue(result.error.startswith("模型服务失败"))
        self.assertIn("文件保存失败", result.error)
        self.assertNotIn("/internal/workspace", result.error)
        self.assertEqual(db.run.error_code, "model_error")
        self.assertEqual(events[-1].error_code, "model_error")

    async def test_writeback_failure_preserves_cancellation_status_and_event(self):
        provider = _Sandbox()
        events = []
        async def emit(evt):
            events.append(evt)
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=provider),
              patch.object(agent_service, "get_runtime", return_value=_PartialCancelledRuntime()),
              patch.object(provider, "cleanup", side_effect=OSError("write failed"))):
            db = _DB(_session(), _model())
            result = await agent_service.execute_agent_turn(
                agent=_agent(), user_input="test", session_id=11, user_id=7, db=db, on_event=emit,
            )
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.final_text, "partial result")
        self.assertEqual(db.run.status, "cancelled")
        self.assertEqual(db.run.error_code, "cancelled")
        self.assertIn("文件保存失败", db.run.error_message)
        self.assertEqual(events[-1].type, "cancelled")
        self.assertFalse(any(evt.type == "error" for evt in events))

    async def test_audit_failure_does_not_report_successful_writeback_as_failed(self):
        provider = _Sandbox()
        events = []
        async def emit(evt):
            events.append(evt)
        db = _DB(_session(), _model())
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=provider),
              patch.object(agent_service, "get_runtime", return_value=_Runtime()),
              patch.object(provider, "cleanup") as write,
              patch.object(agent_service, "finish_run_view", side_effect=RuntimeError("audit failed")),
              patch.object(db, "rollback", create=True) as rollback):
            result = await agent_service.execute_agent_turn(
                agent=_agent(), user_input="test", session_id=11, user_id=7, db=db, on_event=emit,
            )
        write.assert_called_once()
        rollback.assert_called_once()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(db.run.status, "succeeded")
        self.assertFalse(any(evt.type == "error" for evt in events))

    async def test_failure_event_delivery_does_not_prevent_reply_persistence(self):
        provider = _Sandbox()
        async def emit(evt):
            if evt.type == "error":
                raise OSError("transport failed")
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=provider),
              patch.object(agent_service, "get_runtime", return_value=_Runtime()),
              patch.object(provider, "cleanup", side_effect=OSError("write failed"))):
            db = _DB(_session(), _model())
            result = await agent_service.execute_agent_turn(
                agent=_agent(), user_input="test", session_id=11, user_id=7, db=db, on_event=emit,
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.assistant_message_id, 102)
        self.assertEqual(result.final_text, "result")
        self.assertEqual(db.run.status, "failed")


class ExecutionCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lease_loss_discards_without_writeback(self):
        provider = _Sandbox()
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=provider),
              patch.object(agent_service, "get_runtime", return_value=_CancelledRuntime()),
              patch.object(provider, "cleanup") as write,
              patch.object(provider, "discard_execution") as discard):
            guard = AsyncMock(side_effect=[True, False, False])
            with self.assertRaises(asyncio.CancelledError):
                await agent_service.execute_agent_turn(
                    agent=_agent(), user_input="test", session_id=11, user_id=7,
                    db=_DB(_session(), _model()), run_guard=guard,
                )
            write.assert_not_called()
            discard.assert_called_once()

    async def test_prepare_and_cleanup_drain_through_repeated_cancellation(self):
        for phase in ("prepare", "cleanup"):
            with self.subTest(phase=phase):
                started = asyncio.Event()
                finish = threading.Event()
                loop = asyncio.get_running_loop()
                provider = _Sandbox()
                original_prepare = provider.prepare_execution
                def blocking(*args, **kwargs):
                    loop.call_soon_threadsafe(started.set)
                    if not finish.wait(3):
                        raise RuntimeError("worker timed out")
                    if phase == "prepare":
                        return original_prepare(*args, **kwargs)
                with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
                      patch.object(agent_service, "get_workspace_provider", return_value=provider),
                      patch.object(agent_service, "get_runtime", return_value=_Runtime()),
                      patch.object(provider, "prepare_execution" if phase == "prepare" else "cleanup", side_effect=blocking) as worker,
                      patch.object(provider, "discard_execution") as discard):
                    guard = (AsyncMock(return_value=True) if phase == "cleanup"
                             else AsyncMock(side_effect=[True, False, False]))
                    task = asyncio.create_task(agent_service.execute_agent_turn(
                        agent=_agent(), user_input="test", session_id=11, user_id=7,
                        db=_DB(_session(), _model()), run_guard=guard,
                    ))
                    try:
                        await asyncio.wait_for(started.wait(), 1)
                        for _ in range(3):
                            task.cancel()
                            await asyncio.sleep(0.02)
                            self.assertFalse(task.done())
                        finish.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        worker.assert_called_once()
                        if phase == "prepare":
                            discard.assert_called_once()
                    finally:
                        finish.set()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_channel_platform_run_requires_matching_ownership(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as records:
            agent = _agent()
            agent.default_model_id = None
            model = _model()
            model.scope = "platform"
            class FilteredDB(_DB):
                def query(self, model_type):
                    if model_type is AgentRun:
                        return records.query(AgentRun)
                    return super().query(model_type)
            with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
                  patch.object(agent_service, "prepare_platform_run") as billing):
                for field, value in (("agent_id", 2), ("user_id", 8), ("session_id", 12), ("id", "another-run")):
                    with self.subTest(field=field):
                        records.query(AgentRun).delete()
                        values = dict(id="channel-run", user_id=7, agent_id=1, session_id=11, config_snapshot="{}")
                        values[field] = value
                        records.add(AgentRun(**values))
                        records.commit()
                        result = await agent_service.execute_agent_turn(
                            agent=agent, user_input="test", session_id=11, user_id=7,
                            db=FilteredDB(_session(), model), manage_run_record=False,
                            run_id="channel-run", source="channel",
                        )
                        self.assertEqual(result.status, "failed")
                        self.assertIn("Run", result.error)
                billing.assert_not_called()

    async def test_channel_dynamic_platform_model_reuses_existing_run(self):
        agent = _agent()
        agent.default_model_id = None
        model = _model()
        model.scope = "platform"
        db = _DB(_session(), model)
        db.run = AgentRun(id="channel-run", user_id=7, agent_id=1, session_id=11, config_snapshot="{}")
        existing = db.run
        with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
              patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
              patch.object(agent_service, "get_runtime", return_value=_Runtime()),
              patch.object(agent_service, "prepare_platform_run", return_value=("token", "http://gateway")) as billing,
              patch.object(agent_service, "settle_platform_run"),
              patch.object(agent_service, "_ensure_run_record") as create):
            result = await agent_service.execute_agent_turn(
                agent=agent, user_input="test", session_id=11, user_id=7, db=db,
                manage_run_record=False, run_id="channel-run", source="channel",
            )
            self.assertEqual(result.status, "succeeded")
            self.assertIs(billing.call_args.args[1], existing)
            create.assert_not_called()
