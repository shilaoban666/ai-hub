from _repair_message_attachments import transcript_attachments


def user(text):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def test_recovers_only_matching_user_prompt_attachments():
    prompt = "[用户引用了以下工作区文件，请参考这些文件来回答问题：]\n  文件: screenshot.png\n\nDescribe this"
    assert transcript_attachments([user(prompt)], "Describe this") == ["screenshot.png"]
    assert transcript_attachments([user(prompt)], "Different message") == []
    assert transcript_attachments([user(prompt), user(prompt)], "Describe this") == []
    assert transcript_attachments([
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": prompt}]}}
    ], "Describe this") == []


def test_user_text_cannot_invent_an_attachment_reference():
    content = "Example:\n[用户引用了以下工作区文件，请参考这些文件来回答问题：]\n  文件: unrelated.png"
    assert transcript_attachments([user(content)], content) == []
