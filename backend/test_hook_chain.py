#!/usr/bin/env python3
"""端到端自测:验证 hook 脚本能运行 + 日志能写入 + MCP 默认放行。

运行: python test_hook_chain.py
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

HOOK_SCRIPT = os.path.join(os.path.dirname(__file__), "agent_hooks", "pre_tool_use.py")

print("=" * 60)
print("测试 1: Python 路径")
print("=" * 60)
print(f"sys.executable = {sys.executable}")
print(f"含空格: {' ' in sys.executable}")

print()
print("=" * 60)
print("测试 2: hook 脚本语法检查")
print("=" * 60)
r = subprocess.run([sys.executable, "-c", f"import py_compile; py_compile.compile(r'{HOOK_SCRIPT}', doraise=True)"],
                   capture_output=True, text=True)
if r.returncode == 0:
    print("[OK] 语法正确")
else:
    print("[FAIL] 语法错误:", r.stderr)

print()
print("=" * 60)
print("测试 3: hook 脚本能否运行(安全工具 Read,应自动放行)")
print("=" * 60)
# 模拟 Claude Code 调用 hook:stdin 传 JSON,设置 CLAUDE_CONFIG_DIR
with tempfile.TemporaryDirectory() as tmpdir:
    claude_dir = os.path.join(tmpdir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = claude_dir
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "test.txt"}})
    r = subprocess.run([sys.executable, HOOK_SCRIPT],
                       input=payload, env=env, capture_output=True, text=True, timeout=10)
    print(f"exit code: {r.returncode} (期望 0=放行)")
    print(f"stderr: {r.stderr[:200] if r.stderr else '(空)'}")

    log_path = os.path.join(tmpdir, "hook_permission.log")
    if os.path.exists(log_path):
        print(f"[OK] 日志已写入: {open(log_path, encoding='utf-8').read()[:300]}")
    else:
        print("[FAIL] 日志未写入 - hook 没有执行到 main()!")

print()
print("=" * 60)
print("测试 4: hook 脚本运行(MCP 工具,应直接 allow)")
print("=" * 60)
with tempfile.TemporaryDirectory() as tmpdir:
    claude_dir = os.path.join(tmpdir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = claude_dir
    payload = json.dumps({"tool_name": "mcp__online-mcp__test_tool", "tool_input": {}})
    r = subprocess.run([sys.executable, HOOK_SCRIPT],
                       input=payload, env=env, capture_output=True, text=True, timeout=10)
    print(f"exit code: {r.returncode} (期望 0,MCP 绑定即授权)")
    print(f"stderr: {r.stderr[:200] if r.stderr else '(空)'}")

print()
print("=" * 60)
print("测试 5: 网关是否可达")
print("=" * 60)
try:
    from database import settings
    gateway = settings.vite_api_base_url.rstrip("/")
    print(f"网关地址: {gateway}")
    req = urllib.request.Request(gateway + "/aihub/api/agents/runtimes", method="GET")
    urllib.request.urlopen(req, timeout=5)
    print("[OK] 网关可达,内部端点路由应已由 iam-service 自动发现")
except Exception as e:
    print(f"[WARN] 网关不可达或内部端点未注册: {e}")

print()
print("自测完成。")
