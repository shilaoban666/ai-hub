#!/usr/bin/env python3
"""验证 pre_tool_use.py 的工作区隔离 + 受保护文件规则逻辑(不依赖 claude -p)。

直接导入函数做单元测试 + 子进程调用 main() 做集成测试。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agent_hooks"))
import pre_tool_use as H  # noqa: E402

PASS = 0
FAIL = 0


def expect(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


# ============= 单元:受保护判定函数 =============
print("=" * 60)
print("单元测试:受保护判定函数")
print("=" * 60)
with tempfile.TemporaryDirectory() as ws:
    cwd = ws
    # 受保护条目
    expect(H.is_protected_target("CLAUDE.md", cwd, ws), "is_protected_target(CLAUDE.md)")
    expect(not H.is_protected_target(".claude", cwd, ws), "not is_protected_target(.claude runtime dir)")
    expect(H.is_protected_target(".claude/settings.json", cwd, ws), "is_protected_target(.claude/settings.json)")
    expect(H.is_protected_target(".claude/.claude.json", cwd, ws), "is_protected_target(.claude/.claude.json)")
    expect(H.is_protected_target(".claude/hooks/pre_tool_use.py", cwd, ws), "is_protected_target(.claude/hooks/pre_tool_use.py)")
    expect(not H.is_protected_target(".venv", cwd, ws), "not is_protected_target(.venv)")
    expect(not H.is_protected_target(".venv/pyvenv.cfg", cwd, ws), "not is_protected_target(.venv/pyvenv.cfg)")
    expect(not H.is_protected_target("subdir/x.txt", cwd, ws), "not is_protected_target(subdir/x.txt)")
    expect(not H.is_protected_target("myfile.txt", cwd, ws), "not is_protected_target(myfile.txt)")

    # destroys_protected(删除)
    expect(H.destroys_protected("CLAUDE.md", cwd, ws), "destroys(CLAUDE.md)")
    expect(H.destroys_protected(".claude", cwd, ws), "destroys(.claude) because it contains managed files")
    expect(not H.destroys_protected(".venv", cwd, ws), "not destroys(.venv)")
    expect(H.destroys_protected(".", cwd, ws), "destroys(.)  # rm -rf . 连带受保护")
    expect(not H.destroys_protected(".venv/Lib/site-packages/numpy", cwd, ws), "not destroys(.venv/.../numpy)")
    expect(not H.destroys_protected("myfile.txt", cwd, ws), "not destroys(myfile.txt)")
    expect(not H.destroys_protected("subdir", cwd, ws), "not destroys(subdir)")

    # is_read_protected(只保护含密钥配置和 hooks；运行时目录、skills、.venv 可读)
    expect(not H.is_read_protected(".claude", cwd, ws), "not is_read_protected(.claude runtime dir)")
    expect(H.is_read_protected(".claude/settings.json", cwd, ws), "is_read_protected(.claude/settings.json)")
    expect(H.is_read_protected(".claude/.claude.json", cwd, ws), "is_read_protected(.claude/.claude.json)")
    expect(H.is_read_protected(".claude/hooks/pre_tool_use.py", cwd, ws), "is_read_protected(.claude/hooks/...)")
    expect(not H.is_read_protected(".venv", cwd, ws), "not is_read_protected(.venv)")
    expect(not H.is_read_protected(".claude/skills/myutil/SKILL.md", cwd, ws), "not is_read_protected(.claude/skills/...)  # 技能可读")
    expect(not H.is_read_protected("CLAUDE.md", cwd, ws), "not is_read_protected(CLAUDE.md)  # 身份文件可读")
    expect(not H.is_read_protected("myfile.txt", cwd, ws), "not is_read_protected(myfile.txt)")

# ============= 单元:Bash check_command 受保护拦截 =============
print()
print("=" * 60)
print("单元测试:Bash check_command 受保护拦截")
print("=" * 60)
with tempfile.TemporaryDirectory() as ws:
    cwd = ws
    bash_deny = [
        ("rm CLAUDE.md", "rm CLAUDE.md"),
        ("rm /dev/null", "rm /dev/null outside workspace"),
        ("rm -rf .claude", "rm -rf .claude"),
        ("rm -rf .", "rm -rf .  # 连带受保护"),
        ("mv CLAUDE.md bak.md", "mv CLAUDE.md away"),
        ("mv evil.txt CLAUDE.md", "mv overwrite CLAUDE.md"),
        ("cp evil.txt CLAUDE.md", "cp overwrite CLAUDE.md"),
        ("echo x > CLAUDE.md", "redirect truncate CLAUDE.md"),
        ("echo x > .claude/settings.json", "redirect overwrite settings.json"),
        ("echo x > .claude/.claude.json", "redirect overwrite trust state"),
        ("find . -delete", "find -delete wipes workspace"),
        ("find . -name x -delete", "find -name x -delete"),
        ("truncate -s 0 CLAUDE.md", "truncate CLAUDE.md"),
    ]
    for cmd, label in bash_deny:
        reason = H.check_command(cmd, cwd, ws)
        expect(reason is not None, f"DENY bash: {label}  ({reason})")

    bash_allow = [
        ("rm myfile.txt", "rm normal file"),
        ("rm -rf subdir", "rm normal subdir"),
        ("ls", "ls"),
        ("env 2>/dev/null", "stderr redirect to /dev/null"),
        ("env 2> /dev/null", "spaced stderr redirect to /dev/null"),
        ("cat < /dev/null", "stdin redirect from /dev/null"),
        ("mv a.txt b.txt", "mv normal files"),
        ("cp a.txt b.txt", "cp normal files"),
        ("echo x > out.txt", "redirect normal file"),
        ("find subdir -delete", "find delete normal subdir"),
        ("mv a.txt .claude/b", "move into Claude runtime directory"),
        ("rm -rf .venv", "remove workspace venv"),
        ("rm -rf .venv/Lib/site-packages/numpy", "remove package inside venv"),
        (".venv/bin/pip install openpyxl pandas", "install with workspace venv pip"),
        ("./.venv/bin/pip install openpyxl pandas", "install with explicit workspace venv pip"),
        (".venv/bin/python3 -c \"print('ok')\"", "inline Python with workspace venv"),
    ]
    for cmd, label in bash_allow:
        reason = H.check_command(cmd, cwd, ws)
        expect(reason is None, f"ALLOW bash: {label}  ({reason})")

    absolute_venv_pip = os.path.join(ws, ".venv", "bin", "pip").replace("\\", "/")
    reason = H.check_command(f"{absolute_venv_pip} install openpyxl pandas", cwd, ws)
    expect(reason is None, f"ALLOW bash: absolute workspace venv pip ({reason})")
    workspace_path = ws.replace("\\", "/")
    reported_command = (
        f"cd {workspace_path} && .venv/bin/pip install openpyxl pandas "
        "2>&1 | tail -5"
    )
    reason = H.check_command(reported_command, cwd, ws)
    expect(reason is None, f"ALLOW bash: reported compound pip command ({reason})")
    reason = H.check_command(f"ls {absolute_venv_pip} 2>/dev/null", cwd, ws)
    expect(reason is None, f"ALLOW bash: inspect absolute venv executable ({reason})")
    excel_command = (
        f"cd {workspace_path} && .venv/bin/python3 -c \"\n"
        "import openpyxl\n"
        "wb = openpyxl.load_workbook('出口报关数据2026.06.xlsx', data_only=True)\n"
        "print(wb.sheetnames)\n"
        "\" 2>/dev/null || .venv/bin/python -c \"print('fallback')\""
    )
    reason = H.check_command(excel_command, cwd, ws)
    expect(reason is None, f"ALLOW bash: reported venv Python -c command ({reason})")
    reason = H.check_command("pip install openpyxl", cwd, ws)
    expect(reason is not None, "DENY bash: global pip install")
    reason = H.check_command("python3 -c \"print('outside venv')\"", cwd, ws)
    expect(reason is not None, "DENY bash: non-venv Python -c")


# ============= 集成:子进程调用 main() =============
print()
print("=" * 60)
print("集成测试:子进程调用 main()(文件路径类工具)")
print("=" * 60)
HOOK = os.path.join(HERE, "agent_hooks", "pre_tool_use.py")
PY = sys.executable


def run_hook(tool_name, tool_input, ws):
    """以子进程运行 hook,返回 (exit_code, stderr)。"""
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = os.path.join(ws, ".claude")
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    r = subprocess.run([PY, HOOK], input=payload, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=10)
    return r.returncode, (r.stderr or "").strip()


with tempfile.TemporaryDirectory() as ws:
    os.makedirs(os.path.join(ws, ".claude", "hooks"), exist_ok=True)
    os.makedirs(os.path.join(ws, ".venv"), exist_ok=True)
    open(os.path.join(ws, "CLAUDE.md"), "w").write("# test")

    # Write 平台托管文件 -> deny(2)
    for fp, label in [
        ("CLAUDE.md", "Write CLAUDE.md"),
        (".claude/settings.json", "Write .claude/settings.json"),
        (".claude/.claude.json", "Write .claude/.claude.json"),
        (".claude/hooks/pre_tool_use.py", "Write hook script"),
    ]:
        code, err = run_hook("Write", {"file_path": fp}, ws)
        expect(code == 2, f"DENY Write: {label}")

    # Write 工作区内普通文件 -> allow(0)
    code, _ = run_hook("Write", {"file_path": "subdir/new.txt"}, ws)
    expect(code == 0, "ALLOW Write subdir/new.txt")
    code, _ = run_hook("Write", {"file_path": ".claude/session-env/state"}, ws)
    expect(code == 0, "ALLOW Write .claude/session-env/state")
    code, _ = run_hook("Write", {"file_path": ".venv/pyvenv.cfg"}, ws)
    expect(code == 0, "ALLOW Write .venv/pyvenv.cfg")

    # Write 越界 -> deny(2)
    code, _ = run_hook("Write", {"file_path": os.path.join(tempfile.gettempdir(), "escape.txt")}, ws)
    expect(code == 2, "DENY Write outside workspace (abs)")
    code, _ = run_hook("Write", {"file_path": "../escape.txt"}, ws)
    expect(code == 2, "DENY Write ../escape.txt")

    # Edit 受保护 -> deny(2)
    code, _ = run_hook("Edit", {"file_path": "CLAUDE.md", "old_string": "a", "new_string": "b"}, ws)
    expect(code == 2, "DENY Edit CLAUDE.md")

    # Read CLAUDE.md -> allow(0)(身份文件可读)
    code, _ = run_hook("Read", {"file_path": "CLAUDE.md"}, ws)
    expect(code == 0, "ALLOW Read CLAUDE.md")

    # Read .claude/settings.json -> deny(2)(密钥/钩子)
    code, _ = run_hook("Read", {"file_path": ".claude/settings.json"}, ws)
    expect(code == 2, "DENY Read .claude/settings.json")

    # Read .venv/pyvenv.cfg -> allow(0)
    code, _ = run_hook("Read", {"file_path": ".venv/pyvenv.cfg"}, ws)
    expect(code == 0, "ALLOW Read .venv/pyvenv.cfg")

    # Read .claude/skills/x/SKILL.md -> allow(0)(技能内容可读)
    code, _ = run_hook("Read", {"file_path": ".claude/skills/myutil/SKILL.md"}, ws)
    expect(code == 0, "ALLOW Read .claude/skills/.../SKILL.md")

    # Read 工作区普通文件 -> allow(0)
    code, _ = run_hook("Read", {"file_path": "subdir/new.txt"}, ws)
    expect(code == 0, "ALLOW Read normal file")

    # Read 越界 -> deny(2)
    code, _ = run_hook("Read", {"file_path": os.path.join(tempfile.gettempdir(), "x.txt")}, ws)
    expect(code == 2, "DENY Read outside workspace")

    # Bash rm CLAUDE.md -> deny(2)(check_command 先于默认放行)
    code, _ = run_hook("Bash", {"command": "rm CLAUDE.md", "cwd": ws}, ws)
    expect(code == 2, "DENY Bash rm CLAUDE.md")

    # Bash rm -rf .venv -> allow(0),venv 是智能体可管理的工作区内容
    code, _ = run_hook("Bash", {"command": "rm -rf .venv", "cwd": ws}, ws)
    expect(code == 0, "ALLOW Bash rm -rf .venv")

    # Bash rm normal -> allow(0)(安全检查通过后直接 allow)
    code, _ = run_hook("Bash", {"command": "rm myfile.txt", "cwd": ws}, ws)
    expect(code == 0, "ALLOW Bash rm myfile.txt (safe Bash)")

    # Bash ls -> allow(0)
    code, _ = run_hook("Bash", {"command": "ls", "cwd": ws}, ws)
    expect(code == 0, "ALLOW Bash ls")

    # 已绑定 MCP 由 settings allow 列表控制,hook 不再发起运行时授权
    code, _ = run_hook("mcp__todo__query", {"keyword": "test"}, ws)
    expect(code == 0, "ALLOW MCP tool without runtime permission prompt")

print()
print("=" * 60)
print(f"结果: {PASS} 通过, {FAIL} 失败")
print("=" * 60)
sys.exit(1 if FAIL else 0)
