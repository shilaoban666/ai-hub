"""Real local processes for Claude deadlines, stderr pressure and cancellation."""
import asyncio
from contextlib import contextmanager
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import runtimes.claude_code as cli
from runtimes.base import RuntimeConfig
from sandbox.base import WorkspaceContext


class ClaudeRuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def processes(self, source, *, threaded=False):
        original_spawn = asyncio.create_subprocess_exec
        original_popen = subprocess.Popen
        spawned = []

        async def spawn(*args, **kwargs):
            if threaded:
                raise NotImplementedError
            proc = await original_spawn(sys.executable, "-c", source, **kwargs)
            spawned.append(proc)
            return proc

        def popen(args, **kwargs):
            proc = original_popen([sys.executable, "-c", source], **kwargs)
            spawned.append(proc)
            return proc

        with patch.object(cli.asyncio, "create_subprocess_exec", spawn):
            if threaded:
                with patch.object(cli.subprocess, "Popen", popen):
                    yield spawned
            else:
                yield spawned

    async def run_process(self, source, *, threaded=False, prompt="test", timeout=1, emit=None):
        events = []
        async def collect(event):
            events.append(event)
            if emit is not None:
                await emit(event)
        runtime = cli.ClaudeCodeRuntime()
        context = WorkspaceContext("directory", ".", ".", [], is_isolated=True)
        with self.processes(source, threaded=threaded) as spawned:
            began = time.monotonic()
            await asyncio.wait_for(runtime.run(
                RuntimeConfig(timeout_seconds=timeout), context, prompt, [], collect,
            ), timeout=6)
            elapsed = time.monotonic() - began
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].returncode)
            if threaded:
                self.assertTrue(spawned[0].stdout.closed)
                self.assertTrue(spawned[0].stderr.closed)
            return events, elapsed

    async def test_silent_process_times_out_and_is_reaped(self):
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, elapsed = await self.run_process(
                    "import sys,time; sys.stdin.read(); time.sleep(30)", threaded=threaded,
                )
                self.assertLess(elapsed, 3)
                self.assertEqual(sum(event.type == "error" for event in events), 1)
                self.assertIn("1", next(event.content for event in events if event.type == "error"))
                self.assertEqual(next(event.error_code for event in events if event.type == "error"), 'runtime_timeout')
                self.assertFalse(any(event.type == "text" for event in events))

    async def test_blocked_stdin_is_included_in_deadline(self):
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, elapsed = await self.run_process(
                    "import time; time.sleep(30)", prompt="x" * (4 * 1024 * 1024), threaded=threaded,
                )
                self.assertLess(elapsed, 3)
                self.assertEqual(sum(event.type == "error" for event in events), 1)

    async def test_stderr_flood_does_not_block_output_and_capture_is_bounded(self):
        source = (
            "import sys; sys.stdin.read(); "
            "sys.stderr.write('startup-failure: ' + 'x'*2000000); sys.stderr.flush(); "
            "print('{}', flush=True); sys.exit(7)"
        )
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, elapsed = await self.run_process(source, threaded=threaded, timeout=3)
                errors = [event.content for event in events if event.type == "error"]
                self.assertEqual(len(errors), 1)
                self.assertIn("startup-failure", errors[0])
                self.assertIn("7", errors[0])
                self.assertNotIn("3秒", errors[0])
                self.assertLessEqual(len(errors[0].encode("utf-8")), cli.STDERR_MAX_BYTES + 100)
                self.assertLess(elapsed, 3)

    async def test_invalid_output_cannot_extend_deadline(self):
        source = "import sys,time; sys.stdin.read();\nwhile True:\n print('not-json',flush=True); time.sleep(.02)"
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, elapsed = await self.run_process(source, threaded=threaded)
                self.assertLess(elapsed, 3)
                self.assertEqual(sum(event.type == "error" for event in events), 1)

    async def test_successful_output_survives_stderr_pressure(self):
        source = (
            "import sys; sys.stdin.read(); sys.stderr.write('x'*2000000); sys.stderr.flush(); "
            "print('{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"reply\"}',flush=True)"
        )
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, _ = await self.run_process(source, threaded=threaded, timeout=3)
                self.assertFalse(any(event.type == "error" for event in events))
                self.assertTrue(any(event.content == "reply" for event in events))

    async def test_catalog_warning_does_not_replace_the_upstream_failure(self):
        source = (
            "import sys,json; sys.stdin.read(); "
            "sys.stderr.write('[claude-code:unrecognized_model] {\"model\":\"claude-sonnet-5-5\"}\\n'); "
            "print(json.dumps({'type':'result','subtype':'error_during_execution',"
            "'errors':['API Error: 503 overloaded_error; request_id=req-real']}),flush=True); sys.exit(1)"
        )
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events, _ = await self.run_process(source, threaded=threaded, timeout=3)
                errors = [event.content for event in events if event.type == 'error']
                self.assertIn('API Error: 503 overloaded_error; request_id=req-real', errors)
                self.assertTrue(all('unrecognized_model' not in error for error in errors))

    async def test_resume_fallback_shares_the_original_deadline(self):
        original_spawn = asyncio.create_subprocess_exec
        processes = []
        async def spawn(*args, **kwargs):
            source = (
                "import sys,time; sys.stdin.read(); time.sleep(.7); "
                "sys.stderr.write('No conversation found'); sys.exit(1)"
                if not processes else "import sys,time; sys.stdin.read(); time.sleep(30)"
            )
            proc = await original_spawn(sys.executable, "-c", source, **kwargs)
            processes.append(proc)
            return proc
        events = []
        async def emit(event):
            events.append(event)
        with patch.object(cli.asyncio, "create_subprocess_exec", spawn):
            began = time.monotonic()
            await asyncio.wait_for(cli.ClaudeCodeRuntime().run(
                RuntimeConfig(timeout_seconds=1, extra={"resume_id": "expired"}),
                WorkspaceContext("directory", ".", ".", [], is_isolated=True),
                "test", [], emit,
            ), 3)
            self.assertLess(time.monotonic() - began, 1.6)
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(proc.returncode is not None for proc in processes))
        self.assertEqual(sum(event.type == "error" for event in events), 1)

    async def test_repeated_cancel_waits_for_process_exit(self):
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                runtime = cli.ClaudeCodeRuntime()
                started = asyncio.Event()
                async def emit(event):
                    if event.type == "info":
                        started.set()
                with self.processes("import sys,time; sys.stdin.read(); time.sleep(30)", threaded=threaded) as spawned:
                    task = asyncio.create_task(runtime.run(
                        RuntimeConfig(timeout_seconds=20),
                        WorkspaceContext("directory", ".", ".", [], is_isolated=True),
                        "test", [], emit,
                    ))
                    await asyncio.wait_for(started.wait(), 3)
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 3)
                    self.assertIsNotNone(spawned[0].returncode)

    async def test_callback_failure_also_reaps_process(self):
        async def fail(event):
            if event.type == "info":
                raise ValueError("callback failed")
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                runtime = cli.ClaudeCodeRuntime()
                with self.processes("import sys,time; sys.stdin.read(); time.sleep(30)", threaded=threaded) as spawned:
                    with self.assertRaisesRegex(ValueError, "callback failed"):
                        await asyncio.wait_for(runtime.run(
                            RuntimeConfig(timeout_seconds=20),
                            WorkspaceContext("directory", ".", ".", [], is_isolated=True),
                            "test", [], fail,
                        ), 3)
                    self.assertIsNotNone(spawned[0].returncode)

    async def test_callback_failure_drains_buffered_stdout_before_reaping(self):
        source = (
            "import sys,time; sys.stdin.read(); "
            "sys.stdout.write('{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"reply\"}\\n'+'x'*2000000); "
            "sys.stdout.flush(); time.sleep(30)"
        )
        async def fail(event):
            if event.content == "reply":
                raise ValueError("output callback failed")
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                with self.processes(source, threaded=threaded) as spawned:
                    with self.assertRaisesRegex(ValueError, "output callback failed"):
                        await asyncio.wait_for(cli.ClaudeCodeRuntime().run(
                            RuntimeConfig(timeout_seconds=20),
                            WorkspaceContext("directory", ".", ".", [], is_isolated=True),
                            "test", [], fail,
                        ), 3)
                    self.assertIsNotNone(spawned[0].returncode)


if __name__ == "__main__":
    unittest.main()
