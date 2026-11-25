"""Recover missing attachment references from matching Claude run transcripts."""

import argparse
import json
from pathlib import Path

from agent_workspace import normalize_workspace_relative_path
from database import SessionLocal, settings
from message_content import pack_user_content, unpack_user_content
from models import Agent, AgentMessage, AgentRun, AgentSession, UserWorkspace


def transcript_attachments(events, content):
    header = "[用户引用了以下工作区文件，请参考这些文件来回答问题：]"
    matches = []
    for event in events:
        if event.get("type") != "user":
            continue
        parts = event.get("message", {}).get("content", [])
        if isinstance(parts, str):
            parts = [{"type": "text", "text": parts}]
        for part in parts:
            text = part.get("text", "") if part.get("type") == "text" else ""
            if not content or not text.endswith("\n" + content):
                continue
            prefix = text[:-(len(content) + 1)]
            lines = prefix.splitlines()
            if lines.count(header) != 1:
                continue
            paths = []
            for line in lines[lines.index(header) + 1:]:
                if not line.startswith("  文件: "):
                    break
                paths.append(normalize_workspace_relative_path(line[len("  文件: "):]))
            if paths:
                matches.append(list(dict.fromkeys(paths)))
    return matches[0] if len(matches) == 1 else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--session-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires an unused --backup path")

    with SessionLocal() as db:
        changes = []
        sessions = db.query(AgentSession).filter(
            AgentSession.id.in_(args.session_id),
            AgentSession.user_id == args.user_id,
            AgentSession.is_deleted == False,
        ).all()
        if len(sessions) != len(set(args.session_id)):
            raise RuntimeError("Some requested sessions do not belong to this user")
        for session in sessions:
            agent = db.query(Agent).filter(
                Agent.id == session.agent_id, Agent.user_id == args.user_id,
                Agent.is_deleted == False,
            ).one()
            workspace = db.query(UserWorkspace).filter(
                UserWorkspace.id == agent.workspace_id, UserWorkspace.user_id == args.user_id,
            ).one()
            root = Path(workspace.storage_path or Path(settings.user_workspace_root) / workspace.workspace_key)
            files_root = (root / "files").resolve()
            runs = db.query(AgentRun).filter(
                AgentRun.session_id == session.id, AgentRun.user_id == args.user_id,
                AgentRun.assistant_message_id.isnot(None),
            ).all()
            for run in runs:
                message = db.query(AgentMessage).filter(
                    AgentMessage.session_id == session.id,
                    AgentMessage.id < run.assistant_message_id,
                ).order_by(AgentMessage.id.desc()).first()
                if message is None or message.role != "user":
                    continue
                if unpack_user_content(message.content)["attached_files"]:
                    continue
                transcripts = list((root / "sessions" / "projects").glob(f"*-runs-{run.id}-view/*.jsonl"))
                if len(transcripts) != 1:
                    continue
                with transcripts[0].open(encoding="utf-8") as handle:
                    paths = transcript_attachments((json.loads(line) for line in handle), message.content)
                if not paths:
                    continue
                for path in paths:
                    resolved = (files_root / path).resolve()
                    resolved.relative_to(files_root)
                    if not resolved.is_file():
                        raise RuntimeError(f"Missing attachment for message {message.id}: {path}")
                changes.append({
                    "id": message.id, "session_id": session.id, "run_id": run.id,
                    "before": message.content,
                    "after": pack_user_content(message.content, paths),
                    "attached_files": paths,
                })

        if args.apply and changes:
            with args.backup.open("x", encoding="utf-8") as handle:
                json.dump(changes, handle, ensure_ascii=False, indent=2)
            for change in changes:
                count = db.query(AgentMessage).filter(
                    AgentMessage.id == change["id"],
                    AgentMessage.session_id == change["session_id"],
                    AgentMessage.content == change["before"],
                ).update({AgentMessage.content: change["after"]}, synchronize_session=False)
                if count != 1:
                    raise RuntimeError("Message changed during recovery; rolled back")
            db.commit()

        print(json.dumps({
            "applied": args.apply,
            "messages": [{key: value for key, value in change.items() if key not in {"before", "after"}} for change in changes],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
