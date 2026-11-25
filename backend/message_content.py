"""User message text and attachment references stored in the content column."""

import json


USER_MESSAGE_FORMAT = "aihub.user-message.v1"


def unpack_user_content(content: str | None) -> dict:
    try:
        payload = json.loads(content or "")
    except (ValueError, TypeError):
        payload = None
    if (
        isinstance(payload, dict)
        and payload.get("format") == USER_MESSAGE_FORMAT
        and isinstance(payload.get("text"), str)
        and isinstance(payload.get("attached_files"), list)
        and all(isinstance(path, str) for path in payload["attached_files"])
    ):
        result = {"content": payload["text"], "attached_files": payload["attached_files"]}
        skill = payload.get("skill")
        if (isinstance(skill, dict) and type(skill.get("id")) is int
                and isinstance(skill.get("name"), str) and skill["name"].strip()):
            result["skill"] = {"id": skill["id"], "name": skill["name"]}
        return result
    return {"content": content, "attached_files": []}


def pack_user_content(content: str, attached_files: list[str] | None = None, skill: dict | None = None) -> str:
    # Escape literal envelope-shaped text so it still round-trips as user text.
    if not attached_files and not skill and unpack_user_content(content)["content"] == content:
        return content
    return json.dumps({
        "format": USER_MESSAGE_FORMAT,
        "text": content,
        "attached_files": list(dict.fromkeys(attached_files or [])),
        **({"skill": skill} if skill else {}),
    }, ensure_ascii=False)
