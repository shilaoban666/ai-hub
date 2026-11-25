#!/usr/bin/env python3
"""端到端验证:claude -p 模式下 PreToolUse hook 是否触发。

直接在 workspace 2 里跑 claude -p,绕开后端,验证 hook 链路。
"""
import json
import os
import subprocess
import sys

WS = os.path.join(os.path.dirname(__file__), "agent_workspaces", "2")
SETTINGS = os.path.join(WS, ".claude", "settings.json")
HOOK_LOG = os.path.join(WS, "hook_permission.log")

# 1. 读取 settings.json,把 hook 命令的引号去掉(路径无空格)
with open(SETTINGS, "r", encoding="utf-8") as f:
    settings = json.load(f)

python_exe = sys.executable
quote = '"' if ' ' in python_exe else ''
for hook_type in settings.get("hooks", {}):
    for h in settings["hooks"][hook_type]:
        cmd = h["command"]
        # 替换掉引号包裹的 python 路径
        cmd = cmd.replace(f'"{python_exe}"', f"{quote}{python_exe}{quote}")
        h["command"] = cmd
        print(f"{hook_type} command: {h['command']}")

with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)

# 2. 清掉旧日志
if os.path.exists(HOOK_LOG):
    os.remove(HOOK_LOG)

# 3. 读取 env 配置
env_cfg = settings.get("env", {})
token = env_cfg.get("ANTHROPIC_AUTH_TOKEN", "")
base = env_cfg.get("ANTHROPIC_BASE_URL", "")
model = env_cfg.get("ANTHROPIC_MODEL", "")

# 4. 运行 claude -p
env = os.environ.copy()
env["CLAUDE_CONFIG_DIR"] = os.path.join(WS, ".claude")
env["ANTHROPIC_API_KEY"] = token
if base:
    env["ANTHROPIC_BASE_URL"] = base

cmd = [
    "claude", "-p", "读取 CLAUDE.md 文件并告诉我第一行内容",
    "--permission-mode", "default",
    "--model", model,
    "--output-format", "stream-json",
    "--verbose",
]
print(f"\n=== 运行: {' '.join(cmd[:3])} ... ===")
try:
    r = subprocess.run(cmd, cwd=WS, env=env, capture_output=True, text=True, timeout=90)
    print(f"exit code: {r.returncode}")
    print(f"stdout (前 500 字):\n{r.stdout[:500]}")
    if r.stderr:
        print(f"stderr (前 500 字):\n{r.stderr[:500]}")
except subprocess.TimeoutExpired:
    print("超时(90s)")

# 5. 检查 hook 日志
print(f"\n=== 检查 hook 日志: {HOOK_LOG} ===")
if os.path.exists(HOOK_LOG):
    content = open(HOOK_LOG, encoding="utf-8").read()
    print(f"✓ 日志已写入!内容:\n{content[:1000]}")
    print("\n>>> 结论:hook 触发成功!问题已解决(引号是元凶)。")
else:
    print("✗ 日志不存在 - hook 在 claude -p 模式下仍未触发")
    print(">>> 结论:hook 在 -p 模式下不运行,需改用其他方案。")
