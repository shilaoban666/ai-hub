#!/usr/bin/env python3
"""PostToolUse hook: 截断过大的工具返回结果，防止 API 抛出 chunk-limit 错误。

Claude Code 在工具执行后以子进程执行本脚本，stdin 传入 JSON:
  {"tool_name": "...", "tool_input": {...}, "tool_response": "..."}

如果 tool_response 过大（字符数 > MAX_CHARS），保留前 KEEP_HEAD 字符 + 后 KEEP_TAIL 字符，
中间替换为截断提示，防止 Claude Code 向 API 发送超长 content block。

截断阈值：
- 通用上限: 200,000 字符（大幅提升以支持超大工具输出）
- 保留头部: 150,000 字符
- 保留尾部: 30,000 字符
"""

import json
import sys

# 截断阈值
MAX_CHARS = 200_000   # 提升至 200K 字符
KEEP_HEAD = 150_000   # 保留前 150K
KEEP_TAIL = 30_000    # 保留后 30K


def truncate_response(tool_name: str, response: str) -> str:
    """截断过长的工具返回结果"""
    if len(response) <= MAX_CHARS:
        return response

    head = response[:KEEP_HEAD]
    tail = response[-KEEP_TAIL:] if KEEP_TAIL > 0 else ""
    truncated = len(response) - KEEP_HEAD - KEEP_TAIL

    note = (
        f"\n\n[... 工具输出过长已自动截断，已省略 {truncated:,} 字符 "
        f"(原始长度 {len(response):,} 字符)。"
        f"如需完整内容，请缩小查询范围、限制行数或分块读取 ...]\n\n"
    )

    return head + note + tail


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_response = data.get("tool_response", "")

    # 只处理字符串类型的返回（Read/Grep/Bash/WebFetch 等）
    if isinstance(tool_response, str) and len(tool_response) > MAX_CHARS:
        data["tool_response"] = truncate_response(tool_name, tool_response)

    # 输出可能被修改的 JSON，Claude Code 使用此作为工具返回
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.exit(0)


if __name__ == "__main__":
    main()
