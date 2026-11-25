"""Skill sync must release admission slots without abandoning filesystem writes."""
import asyncio
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

import agent_execution_lease
import agent_routes
from database import Base
from models import Agent, UserWorkspace


class AgentSkillSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="aihub-skill-sync-test-")
        self.addCleanup(temporary.cleanup)
        self.engine = create_engine(
            "sqlite:///" + (Path(temporary.name) / "leases.db").as_posix(),
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(Agent(id=99, user_id=7, name="Agent"))
            db.add_all([
                UserWorkspace(id=1, user_id=7, workspace_key="workbench"),
                UserWorkspace(id=2, user_id=7, agent_id=99, workspace_key="agent"),
            ])
            db.commit()
        self.db = MagicMock()
        self.user = SimpleNamespace(user_id=7)
        self.agent = SimpleNamespace(id=99, user_id=7)
        self.workspace = SimpleNamespace(id=2)
        self.acquire = partial(
            agent_execution_lease.acquire_agent_execution_lease,
            session_factory=self.factory, lease_seconds=30, poll_seconds=0.05,
        )
        self.load = self.enterContext(patch.object(
            agent_routes, "load_runtime_assets", return_value={"skills": []},
        ))
        self.provider = MagicMock()
        self.provider.sync_skill_installations.return_value = ["example"]
        self.get_provider = self.enterContext(patch.object(
            agent_routes, "get_workspace_provider", return_value=self.provider,
        ))
        self.enterContext(patch.object(agent_routes, "get_usable_agent", return_value=self.agent))
        self.enterContext(patch.object(agent_routes, "bind_agent_workspace", return_value=(self.workspace, None)))
        self.enterContext(patch.object(agent_routes, "acquire_agent_execution_lease", self.acquire))
        self.enterContext(patch.object(agent_routes, "logger"))

    async def sync(self):
        return await agent_routes.sync_agent_skill_installations(99, self.db, self.user)

    async def assert_other_workspace_available(self):
        # Real admission logic: the workbench shares this user's default limit of 1.
        lease = await asyncio.wait_for(self.acquire(workspace_id=1, run_id="next-run"), 1)
        async with lease:
            self.assertTrue(await lease.is_owned())

    async def assert_other_workspace_blocked(self):
        token = await asyncio.to_thread(
            agent_execution_lease._try_acquire,
            workspace_id=1, run_id="competing-run", owner_id="test",
            lease_seconds=30, session_factory=self.factory,
        )
        self.assertIsNone(token)

    async def test_metadata_failure_releases_user_slot(self):
        self.load.side_effect = RuntimeError("missing skill archive")
        with self.assertRaises(HTTPException) as failure:
            await self.sync()
        self.assertEqual(failure.exception.status_code, 503)
        self.db.rollback.assert_called_once()
        self.provider.sync_skill_installations.assert_not_called()
        await self.assert_other_workspace_available()

    async def test_metadata_commit_failure_releases_user_slot(self):
        self.db.commit.side_effect = [None, RuntimeError("commit failed")]
        with self.assertRaises(HTTPException) as failure:
            await self.sync()
        self.assertEqual(failure.exception.status_code, 503)
        self.provider.sync_skill_installations.assert_not_called()
        await self.assert_other_workspace_available()

    async def test_cancellation_during_preparation_releases_user_slot(self):
        self.load.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.sync()
        self.provider.sync_skill_installations.assert_not_called()
        await self.assert_other_workspace_available()

    async def test_provider_failure_releases_user_slot(self):
        self.get_provider.side_effect = RuntimeError("provider unavailable")
        with self.assertRaises(HTTPException) as failure:
            await self.sync()
        self.assertEqual(failure.exception.status_code, 503)
        await self.assert_other_workspace_available()

    async def test_filesystem_failure_releases_user_slot(self):
        self.provider.sync_skill_installations.side_effect = OSError("write failed")
        with self.assertRaises(HTTPException) as failure:
            await self.sync()
        self.assertEqual(failure.exception.status_code, 503)
        await self.assert_other_workspace_available()

    async def test_success_preserves_result_and_session_thread_ownership(self):
        request_thread = threading.get_ident()
        def load(*args, **kwargs):
            self.assertEqual(threading.get_ident(), request_thread)
            return {"skills": ["example"]}
        def synchronize(agent, workspace):
            self.assertNotEqual(threading.get_ident(), request_thread)
            self.assertEqual(agent.runtime_skills, ["example"])
            return ["example"]
        self.load.side_effect = load
        self.provider.sync_skill_installations.side_effect = synchronize
        self.assertEqual(await self.sync(), {"status": "synced", "skills": ["example"]})
        await self.assert_other_workspace_available()

    async def test_busy_user_keeps_deferred_response(self):
        lease = await self.acquire(workspace_id=1, run_id="existing-run")
        async with lease:
            self.assertEqual(await self.sync(), {"status": "deferred", "reason": "workspace_busy"})
            self.load.assert_not_called()
            self.assertTrue(await lease.is_owned())
        await self.assert_other_workspace_available()

    async def test_acquisition_completing_after_timeout_releases_user_slot(self):
        # A timed-out request must also clean up an acquisition that already
        # succeeded in the database but has not returned from its worker yet.
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        acquire = agent_execution_lease._try_acquire
        def delayed_acquire(**kwargs):
            token = acquire(**kwargs)
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(timeout=5):
                raise RuntimeError("test acquisition timed out")
            return token
        with patch.object(agent_execution_lease, "_try_acquire", delayed_acquire):
            task = asyncio.create_task(self.sync())
            try:
                await asyncio.wait_for(started.wait(), 2)
                await asyncio.sleep(0.6)  # Existing endpoint acquisition timeout is 0.5s.
                self.assertFalse(task.done())
                finish.set()
                self.assertEqual(await asyncio.wait_for(task, 2), {
                    "status": "deferred", "reason": "workspace_busy",
                })
                self.load.assert_not_called()
            finally:
                finish.set()
                await asyncio.gather(task, return_exceptions=True)
        await self.assert_other_workspace_available()

    async def test_repeated_cancellation_keeps_lock_until_worker_finishes(self):
        await self.check_cancelled_worker(fail=False)

    async def test_worker_failure_after_cancellation_preserves_cancellation(self):
        await self.check_cancelled_worker(fail=True)

    async def check_cancelled_worker(self, *, fail):
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        def synchronize(*args):
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(timeout=5):
                raise RuntimeError("test worker timed out")
            if fail:
                raise OSError("write failed after cancellation")
            return []
        self.provider.sync_skill_installations.side_effect = synchronize
        task = asyncio.create_task(self.sync())
        competitor = None
        try:
            await asyncio.wait_for(started.wait(), 2)
            competitor = asyncio.create_task(self.acquire(workspace_id=1, run_id="competing-run"))
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0.05)
                self.assertFalse(task.done())
                self.assertFalse(competitor.done())
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        finally:
            finish.set()
            await asyncio.gather(task, return_exceptions=True)
            if competitor is not None:
                lease = await asyncio.wait_for(competitor, 2)
                async with lease:
                    self.assertTrue(await lease.is_owned())
        await self.assert_other_workspace_available()


if __name__ == "__main__":
    unittest.main()
