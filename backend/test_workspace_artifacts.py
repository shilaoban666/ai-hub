import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent_service
from agent_memory import AgentMemory
from agent_stream import StreamSnapshot, _completed_snapshot
from runtimes.base import RuntimeEvent
from sandbox.base import WorkspaceContext
from sandbox.directory import DirectorySandbox
from sandbox.native import NativeSandbox
from workspace_artifacts import changed_artifacts, snapshot_execution_files
from test_agent_service import _DB, _Memory, _Runtime, _agent, _execution_dependencies, _model, _session


def context(root):
    return WorkspaceContext(
        sandbox_type="directory", workspace_root=str(root),
        host_workspace_path=str(root), execution_view_path=str(root), argv_prefix=[],
    )


def test_snapshot_only_returns_new_or_updated_user_files(tmp_path):
    ctx = context(tmp_path)
    for name in ["uploaded.csv", "unchanged.txt", "updated.txt", "deleted.txt"]:
        (tmp_path / name).write_text("before")
    before = snapshot_execution_files(ctx, "claude_code")
    for name in [".claude/skills/pkg.txt", "node_modules/pkg/file.js", "tmp/scratch.txt", "__pycache__/x.pyc"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ignore")
    (tmp_path / "CLAUDE.md").write_text("managed")
    (tmp_path / "report.tmp").write_text("temporary")
    (tmp_path / "updated.txt").write_text("changed")
    (tmp_path / "deleted.txt").unlink()
    (tmp_path / "output").mkdir()
    (tmp_path / "output/report.csv").write_text("sku,count\nx,2")
    (tmp_path / "output/chart.png").write_bytes(b"image")
    (tmp_path / "output/report.pdf").write_bytes(b"pdf")
    (tmp_path / "output/data.xlsx").write_bytes(b"xlsx")
    (tmp_path / "output/empty.txt").touch()
    (tmp_path / "external").symlink_to(tmp_path.parent, target_is_directory=True)
    (tmp_path / "link.csv").symlink_to(tmp_path / "uploaded.csv")
    artifacts = changed_artifacts(before, snapshot_execution_files(ctx, "claude_code"))
    by_path = {item["path"]: item for item in artifacts}
    assert set(by_path) == {"updated.txt", "output/report.csv", "output/chart.png", "output/report.pdf", "output/data.xlsx", "output/empty.txt"}
    assert by_path["output/empty.txt"]["size"] == 0
    assert by_path["output/report.csv"]["is_previewable"] is True
    assert by_path["output/chart.png"]["is_previewable"] is True
    assert by_path["output/report.pdf"]["is_previewable"] is True
    assert by_path["output/data.xlsx"]["is_previewable"] is False


def test_native_snapshot_uses_same_scanner_with_privileged_reader(tmp_path):
    (tmp_path / "result.txt").write_text("data")
    ctx = context(tmp_path)
    ctx.handle = {"user_root": str(tmp_path)}
    provider = NativeSandbox.__new__(NativeSandbox)
    def run(*args):
        assert args[0] == "python3"
        assert args[1].endswith("sandbox/artifact_scan.py")
        return subprocess.run([sys.executable, *args[1:]], capture_output=True, text=True, check=True)
    with patch.object(provider, "_assert_user_workspace_path"), patch.object(provider, "_run_root", side_effect=run) as reader:
        actual = provider.snapshot_execution_files(ctx, "claude_code")
    assert actual == snapshot_execution_files(ctx, "claude_code")
    reader.assert_called_once()


@pytest.mark.parametrize("cleanup_fails,committed,cancelled", [(False, True, False), (True, True, False), (False, False, False), (False, True, True)])
def test_turn_only_publishes_committed_artifacts_and_saves_history(tmp_path, cleanup_fails, committed, cancelled):
    class Provider(DirectorySandbox):
        def prepare_execution(self, *args, **kwargs):
            return context(tmp_path)

        def cleanup(self, ctx):
            if cleanup_fails:
                raise RuntimeError("writeback failed")

    class Runtime(_Runtime):
        async def run(self, **kwargs):
            (tmp_path / "result.csv").write_text("a,b\n1,2")
            if cancelled:
                raise asyncio.CancelledError
            await kwargs["on_event"](RuntimeEvent(type="text", content="文件已生成"))
            await kwargs["on_event"](RuntimeEvent(type="done"))

    events = []
    async def emit(evt):
        events.append(evt)
    def commit(operation):
        # Preparation is also protected by the lease.
        if not committed and (tmp_path / "result.csv").exists():
            return False
        operation()
        return True
    with (_execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory),
          patch.object(agent_service, "get_workspace_provider", return_value=Provider()),
          patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
          patch.object(agent_service, "get_runtime", return_value=Runtime())):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(), user_input="生成文件", session_id=11, user_id=7,
            db=_DB(_session(), _model()), on_event=emit, workspace_commit=commit,
        ))
    artifact_events = [event for event in events if event.type == "artifacts"]
    artifact_blocks = [block for block in result.blocks if block["type"] == "artifacts"]
    if committed and not cleanup_fails:
        assert len(artifact_events) == len(artifact_blocks) == 1
        assert artifact_blocks[0]["files"][0]["path"] == "result.csv"
        assert _Memory.saved_blocks == result.blocks
        assert json.loads(artifact_events[0].to_sse()[6:])["metadata"]["files"] == artifact_blocks[0]["files"]
    else:
        assert artifact_events == artifact_blocks == []


def test_artifacts_survive_compaction_live_snapshots_and_completed_replay():
    files = [{"name": "result.csv", "path": "output/result.csv", "size": 12, "is_previewable": True}]
    block = {"type": "artifacts", "files": files}
    memory = AgentMemory.__new__(AgentMemory)
    for aggressive in (False, True):
        assert memory._compact_blocks([block], aggressive=aggressive) == [block]
    compacted = json.loads(memory._dump_payload_with_limit({"blocks": [{"type": "text", "content": "a" * 10000}, block]}, 1000))
    assert block in compacted["blocks"]
    many_files = {"type": "artifacts", "files": [dict(files[0], path=f"output/{index}.csv") for index in range(1000)]}
    assert len(memory._dump_payload_with_limit({"blocks": [many_files]}, 1000).encode("utf-8")) <= 1000
    snapshot = StreamSnapshot()
    snapshot.consume(RuntimeEvent(type="artifacts", metadata={"files": files}).to_sse())
    assert snapshot.payload()["events"][0]["metadata"]["files"] == files
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(content=json.dumps({"blocks": [block]})))
    run = SimpleNamespace(id="run", session_id=11, assistant_message_id=102, usage_detail=None,
                          duration_ms=10, charged_points=None, settlement_status="none",
                          status="succeeded", error_message=None, error_code=None)
    assert block in _completed_snapshot(db, run, 0)["events"]
