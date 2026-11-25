import json

import pytest

from agent_memory import AgentMemory, MAX_TOOL_RESULT_CHARS, estimate_tokens


def _memory_without_db() -> AgentMemory:
    return object.__new__(AgentMemory)


@pytest.mark.parametrize("aggressive", [False, True])
@pytest.mark.parametrize("field", ["s_html", "html"])
def test_tool_preview_survives_history_compaction(aggressive, field):
    html = '  <section onclick="score()">' + ("评分内容" * 4_000) + "</section>  "
    # MCP responses can wrap another JSON response in a text content block.
    result = json.dumps({"content": [{"type": "text", "text": json.dumps({
        "data": {field: html},
    }, ensure_ascii=False)}]}, ensure_ascii=False)
    original = {"type": "tool_result", "tool_use_id": "score", "content": result}

    blocks = _memory_without_db()._compact_blocks([original], aggressive=aggressive)
    stored = json.loads(_memory_without_db()._dump_payload_with_limit({"blocks": blocks}, 500_000))

    assert stored["blocks"][0]["resultHtml"] == html
    assert len(stored["blocks"][0]["content"]) < len(result)
    assert "resultHtml" not in original
    # Recompacting a saved block must retain the complete preview, too.
    assert _memory_without_db()._compact_blocks(blocks, aggressive=True)[0]["resultHtml"] == html


def test_non_html_tool_results_remain_bounded():
    blocks = _memory_without_db()._compact_blocks([{
        "type": "tool_result", "content": "log" * MAX_TOOL_RESULT_CHARS,
    }])
    assert "resultHtml" not in blocks[0]
    assert len(blocks[0]["content"]) < MAX_TOOL_RESULT_CHARS + 100


def test_oversized_tool_preview_produces_visible_summary_instead_of_partial_html():
    html = "<section>" + ("评分" * 20_000) + "</section>"
    blocks = _memory_without_db()._compact_blocks([{
        "type": "tool_result", "content": json.dumps({"html": html}),
    }], aggressive=True)
    stored = _memory_without_db()._dump_payload_with_limit({"blocks": blocks}, 60_000)
    payload = json.loads(stored)
    assert len(stored.encode("utf-8")) < 60_000
    assert payload["truncated"] is True
    assert payload["blocks"][0]["type"] == "text"
    assert "助手消息过长" in payload["blocks"][0]["content"]


def test_history_compaction_uses_readable_summary_and_preserves_recent_messages():
    memory = _memory_without_db()
    messages = []
    for index in range(10):
        messages.append({"role": "user", "content": f"request-{index} " + ("x" * 700)})
        messages.append({
            "role": "assistant",
            "content": json.dumps({
                "blocks": [
                    {"type": "thinking", "content": "private reasoning"},
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "a.txt"}},
                    {"type": "text", "content": f"answer-{index} " + ("y" * 700)},
                ]
            }),
        })

    compacted, omitted = memory._compress_history_with_stats(messages, 1_000)

    assert omitted > 0
    assert compacted[0]["role"] == "system"
    assert "较早对话摘要" in compacted[0]["content"]
    assert "private reasoning" not in compacted[0]["content"]
    assert '"blocks"' not in compacted[0]["content"]
    assert compacted[-1] == messages[-1]
    assert sum(estimate_tokens(item["content"]) for item in compacted) <= 1_150


if __name__ == "__main__":
    test_history_compaction_uses_readable_summary_and_preserves_recent_messages()
    print("agent memory tests passed")
