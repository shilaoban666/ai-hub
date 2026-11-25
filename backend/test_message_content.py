import json

from agent_memory import AgentMemory
from agent_routes import create_conversation_share, get_messages, get_public_conversation_share, save_messages
from auth import CurrentUser
from message_content import pack_user_content, unpack_user_content
from models import Agent, AgentSession
from schemas import AgentSessionMessagesResponse, PublicConversationShareResponse, SaveMessagesRequest
from test_agent_routes import _create_db


def test_user_content_preserves_plain_text_and_literal_json():
    for text in ["hello", "", '{"text":"literal JSON"}', '{"format":"aihub.user-message.v1"}']:
        assert pack_user_content(text) == text
        assert unpack_user_content(text) == {"content": text, "attached_files": []}
    literal = pack_user_content("image", ["image.png"])
    assert unpack_user_content(pack_user_content(literal))["content"] == literal


def test_attachments_survive_history_without_changing_text_or_public_access():
    db = _create_db()
    try:
        db.add(Agent(id=9, user_id=7, name="Agent", is_deleted=False))
        db.add(AgentSession(id=101, agent_id=9, user_id=7, is_deleted=False))
        db.commit()
        memory = AgentMemory(db, 101)
        skill = {"id": 11, "name": "Code review"}
        stored = memory.save_user_message(pack_user_content("Describe this image", ["chart.png", "notes.txt"], skill))
        assert json.loads(stored.content)["attached_files"] == ["chart.png", "notes.txt"]
        assert memory.load_history() == [{"role": "user", "content": "Describe this image"}]
        assert memory.get_first_message() == "Describe this image"

        result = get_messages(9, 101, None, 100, db, CurrentUser(7))
        message = AgentSessionMessagesResponse.model_validate(result).items[0]
        assert message.content == "Describe this image"
        assert message.attached_files == ["chart.png", "notes.txt"]
        assert message.skill.model_dump() == skill

        share = create_conversation_share(9, 101, db, CurrentUser(7))
        public = PublicConversationShareResponse.model_validate(
            get_public_conversation_share(share.token, None, 100, db)
        ).items[0]
        assert public.content == message.content
        assert public.attached_files == []
        assert public.skill is None

        literal = pack_user_content("literal JSON", ["not-an-attachment.png"])
        save_messages(9, 101, SaveMessagesRequest(messages=[{"role": "user", "content": literal}]), db, CurrentUser(7))
        saved = AgentSessionMessagesResponse.model_validate(
            get_messages(9, 101, None, 100, db, CurrentUser(7))
        ).items[-1]
        assert saved.content == literal
        assert saved.attached_files == []
    finally:
        db.close()


def test_skill_reference_round_trips_without_attachments():
    skill = {"id": 17, "name": "Saved skill name"}
    packed = pack_user_content("Review the code", skill=skill)
    skill["name"] = "Renamed later"
    assert unpack_user_content(packed) == {
        "content": "Review the code", "attached_files": [],
        "skill": {"id": 17, "name": "Saved skill name"},
    }
    assert unpack_user_content(pack_user_content(packed))["content"] == packed


def test_malformed_skill_metadata_does_not_hide_message_text_or_files():
    for skill in [{"id": "bad", "name": "Skill"}, {"id": 2, "name": None}, {"id": 2, "name": " "}]:
        assert unpack_user_content(pack_user_content("Text", ["notes.txt"], skill)) == {
            "content": "Text", "attached_files": ["notes.txt"],
        }
