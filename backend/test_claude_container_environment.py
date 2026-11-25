"""Docker client configuration stays on the host across all runtime paths."""
import asyncio
import base64
from contextlib import nullcontext
import json
import os
import sys
import unittest
from unittest.mock import patch

import runtimes.claude_code as cli
from runtimes.base import RuntimeConfig
from sandbox.base import WorkspaceContext


HOST_ENV = {
    "HOME": "/host/backend",
    "PATH": os.defpath,
    "DOCKER_CONTEXT": "desktop-linux",
    "DOCKER_CONFIG": "/host/docker-config",
    "DOCKER_HOST": "unix:///host/docker.sock",
    "DOCKER_TLS_VERIFY": "1",
    "DOCKER_CERT_PATH": "/host/certs",
    "DATABASE_URL": "backend-only-secret",
    "AGENT_CREDENTIAL_ENCRYPTION_KEY": "backend-only-key",
}


def context():
    return WorkspaceContext(
        "container", "/workspace", "", [],
        env={"HOME": "/workspace", "AIHUB_AGENT_WORKSPACE": "/workspace", "PATH": "/usr/bin"},
        tunnel_env_via_stdin=True, is_isolated=True,
    )


class ContainerEnvironmentTests(unittest.TestCase):
    def test_docker_settings_and_agent_credentials_use_separate_environments(self):
        ctx = context()
        with patch.dict(os.environ, HOST_ENV, clear=True):
            runtime_env = cli._build_runtime_env(RuntimeConfig(api_key="model-only-key"), ctx)
            launcher = cli._build_subprocess_env(ctx, runtime_env)
            forwarded = json.loads(base64.b64decode(cli._encode_tunneled_env(ctx, runtime_env)))
        self.assertEqual(launcher["HOME"], HOST_ENV["HOME"])
        for key in ("DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            self.assertEqual(launcher[key], HOST_ENV[key])
            self.assertNotIn(key, forwarded)
        self.assertEqual(forwarded["HOME"], "/workspace")
        self.assertEqual(forwarded["PATH"], "/workspace/.venv/bin:/usr/bin")
        self.assertEqual(forwarded["VIRTUAL_ENV"], "/workspace/.venv")
        self.assertEqual(forwarded["PIP_REQUIRE_VIRTUALENV"], "true")
        self.assertEqual(forwarded["ANTHROPIC_API_KEY"], "model-only-key")
        self.assertNotIn("ANTHROPIC_API_KEY", launcher)
        for env in (launcher, runtime_env, forwarded):
            self.assertNotIn("DATABASE_URL", env)
            self.assertNotIn("AGENT_CREDENTIAL_ENCRYPTION_KEY", env)

    def test_other_sandboxes_keep_their_runtime_environment(self):
        for sandbox_type in ("native", "directory"):
            ctx = WorkspaceContext(sandbox_type, "/agent", "", [])
            runtime_env = {"HOME": "/agent", "ANTHROPIC_API_KEY": "test-key"}
            self.assertIs(cli._build_subprocess_env(ctx, runtime_env), runtime_env)


# Use real local subprocesses to check the env passed by run(), its threaded
# fallback and resume(). No Docker daemon or external model is needed here.
LAUNCHER = """
import base64, json, os, sys
assert os.environ['HOME'] == '/host/backend'
assert os.environ['DOCKER_CONTEXT'] == 'desktop-linux'
assert os.environ['DOCKER_CONFIG'] == '/host/docker-config'
assert os.environ['DOCKER_HOST'] == 'unix:///host/docker.sock'
for key in ('DATABASE_URL', 'AGENT_CREDENTIAL_ENCRYPTION_KEY', 'ANTHROPIC_API_KEY'):
    assert key not in os.environ, key
header, _, prompt = sys.stdin.buffer.read().partition(b'\\n')
env = json.loads(base64.b64decode(header))
assert env['HOME'] == '/workspace'
assert env['ANTHROPIC_API_KEY'] == 'model-only-key'
assert not any(key.startswith('DOCKER_') for key in env)
print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'launcher passed'}))
"""


class ContainerRuntimeLaunchTests(unittest.IsolatedAsyncioTestCase):
    def make_context(self):
        ctx = context()
        ctx.argv_prefix = [sys.executable, "-c", LAUNCHER]
        ctx.claude_bin = "unused-claude"
        return ctx

    async def test_run_and_threaded_fallback_preserve_docker_context(self):
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                events = []
                async def emit(event):
                    events.append(event)
                fallback = (patch.object(cli.asyncio, "create_subprocess_exec", side_effect=NotImplementedError)
                            if threaded else nullcontext())
                with patch.dict(os.environ, HOST_ENV, clear=True), fallback:
                    await asyncio.wait_for(cli.ClaudeCodeRuntime().run(
                        RuntimeConfig(api_key="model-only-key", timeout_seconds=5),
                        self.make_context(), "hi", [], emit,
                    ), timeout=8)
                self.assertFalse([event.content for event in events if event.type == "error"])
                self.assertTrue(any(event.content == "launcher passed" for event in events))

    async def test_resume_preserves_docker_context(self):
        with patch.dict(os.environ, HOST_ENV, clear=True):
            events = [event async for event in cli.ClaudeCodeRuntime().resume(
                RuntimeConfig(api_key="model-only-key"), self.make_context(), "session-1",
            )]
        self.assertTrue(any(event.content == "launcher passed" for event in events))


if __name__ == "__main__":
    unittest.main()
