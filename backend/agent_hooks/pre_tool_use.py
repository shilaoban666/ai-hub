#!/usr/bin/env python3
"""PreToolUse hook: 限制 Claude Code 的所有文件/命令操作严格在智能体工作区内。

Claude Code 在每次调用工具前以子进程执行本脚本,stdin 传入 JSON:
  {"tool_name": "Bash"|"Write"|"Edit"|"Read"|..., "tool_input": {...}, ...}

违规时 exit 2,stderr 文本作为反馈传给 Claude。
合规时 exit 0,放行。

检查维度:
1. 复合命令拆分 (&& || ; |),尊重引号
2. 命令替换提取 ($(...) 反引号),递归检查子命令
3. 危险模式黑名单 (sudo/chmod/curl|sh 等)
4. 首词限制 (bash/sh 任何参数均拒;python -c/node -e 拒)
5. 路径越界 (Bash 绝对路径/~/../盘符,以及 Write/Edit/Read/Glob/Grep 的路径参数
   必须解析到工作区内)
6. Python 包安装 (pip install 必须走工作区内 .venv)
7. 受保护的平台文件 (CLAUDE.md/.mcp.json/.claude/.claude.json/settings.json/hooks/skills):
   - 禁止删除/移动/覆盖 (rm/mv/cp/find -delete/重定向等)
   - 禁止 Write/Edit 改写 (含 .claude/settings.json、.claude/hooks/*.py,
     防止智能体改写配置关掉本钩子绕过保护)
   - 禁止 Read 读取 settings.json、.mcp.json 与 hooks/；工作区运行时目录、
     .venv、CLAUDE.md 与 .claude/skills/ 可读写

Runtime 默认使用 --permission-mode acceptEdits，本钩子在 -p 模式下作为
工作区隔离的第一道防线：① 路径越界检查 ② 危险命令拦截 ③ 受保护文件防改
④ 工具授权由 Claude Agent SDK can_use_tool 回调与 permissions.ask 处理。
本钩子仅作隔离检查；exit 0 不替代后续工具授权，危险 Bash 直接拒绝。
物理沙箱(WSL/native)作为纵深防御辅助 chattr +i 防删。
"""

import json
import os
import re
import shlex
import sys
import time


# ============= 日志（排查沙箱链路） =============

def _log_path() -> str:
    """日志写到工作区根目录的 hook_permission.log"""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return os.path.join(os.path.dirname(config_dir), "hook_permission.log")
    return os.path.join(os.getcwd(), "hook_permission.log")


def _log(msg: str) -> None:
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ============= 危险模式黑名单 =============

DANGEROUS_PATTERNS = [
    # 权限提升
    r"\bsudo\b",
    r"\bsu\b",
    # 权限修改
    r"\bchmod\b",
    r"\bchown\b",
    r"\bchgrp\b",
    # 磁盘破坏
    r"\bdd\b",
    r"\bmkfs\b",
    # 进程控制
    r"\bkillall\b",
    r"\bpkill\b",
    r"\bkill\s+-9\b",
    # 下载执行(管道到 shell)
    r"\bcurl\b.*\|\s*(?:sh|bash)\b",
    r"\bwget\b.*\|\s*(?:sh|bash)\b",
    r"\bbase64\b.*\|\s*(?:sh|bash)\b",
    # 设备直写
    r">\s*/dev/(?:sd|nvme|hd)",
    # fork bomb
    r":\s*\(\s*\)\s*\{",
    # 软链攻击(ln -s 指向根或家目录)
    r"\bln\s+-s\s+[/~]",
    # source 越界
    r"\bsource\s+[/~]",
    r"(?:^|\s)\.\s+[/~]",
    # 间接执行(防御深度,首词检查在 check_first_token；工作区 venv Python 可豁免)
    r"\bnode\s+-e\b",
    r"\bperl\s+-e\b",
    r"\bruby\s+-e\b",
    r"\bbash\s+-c\b",
    r"\bsh\s+-c\b",
    r"\bbash\s+\S+\.sh\b",
    r"\bsh\s+\S+\.sh\b",
    # eval 执行任意串
    r"\beval\b",
]

DANGEROUS_RE = [re.compile(p) for p in DANGEROUS_PATTERNS]

# 受限 shell 解释器:任何带参数调用都拒
RESTRICTED_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "csh", "tcsh"}

# 受限脚本解释器:仅拒 -c/-e(代码字符串),允许 script.py 文件执行
RESTRICTED_INTERPRETERS = {
    "python": ("-c", "python -c"),
    "python3": ("-c", "python3 -c"),
    "python2": ("-c", "python2 -c"),
    "node": ("-e", "node -e"),
    "perl": ("-e", "perl -e"),
    "ruby": ("-e", "ruby -e"),
}

# 复合操作符
COMPOUND_OPS_2 = ("&&", "||")
COMPOUND_OPS_1 = (";", "|")

# 命令替换嵌套最大深度
MAX_RECURSION_DEPTH = 10


# ============= 命令拆分 =============

def extract_subcommands(cmd: str) -> list[str] | None:
    """提取 $(...) 和反引号内的子命令。

    手动扫描括号深度处理嵌套。反引号用正则(POSIX 反引号不嵌套)。
    返回 None 表示括号不平衡,调用方应保守拒绝。
    """
    subs: list[str] = []
    i = 0
    n = len(cmd)
    while i < n:
        if cmd[i:i + 2] == "$(":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if cmd[j:j + 2] == "$(":
                    depth += 1
                    j += 2
                elif cmd[j] == "(":
                    depth += 1
                    j += 1
                elif cmd[j] == ")":
                    depth -= 1
                    j += 1
                else:
                    j += 1
            if depth != 0:
                return None
            subs.append(cmd[i + 2:j - 1])
            i = j
        else:
            i += 1

    for m in re.finditer(r"`([^`]+)`", cmd):
        subs.append(m.group(1))

    return subs


def _split_compound(cmd: str) -> list[tuple[str, str]] | None:
    """按 && || ; | 切段,尊重引号。

    返回 None 表示引号不平衡。
    """
    segments: list[tuple[str, str]] = []
    current: list[str] = []
    quote_char: str | None = None
    i = 0
    n = len(cmd)
    while i < n:
        c = cmd[i]
        if quote_char:
            current.append(c)
            if c == quote_char and (i == 0 or cmd[i - 1] != "\\"):
                quote_char = None
            i += 1
            continue
        if c in ('"', "'"):
            quote_char = c
            current.append(c)
            i += 1
            continue
        if cmd[i:i + 2] in COMPOUND_OPS_2:
            seg = "".join(current).strip()
            if seg:
                segments.append((seg, cmd[i:i + 2]))
            current = []
            i += 2
            continue
        if c in COMPOUND_OPS_1 or c == "\n":
            seg = "".join(current).strip()
            if seg:
                segments.append((seg, ";" if c == "\n" else c))
            current = []
            i += 1
            continue
        current.append(c)
        i += 1

    if quote_char:
        return None
    seg = "".join(current).strip()
    if seg:
        segments.append((seg, ""))
    return segments


def split_compound(cmd: str) -> list[str] | None:
    segments = _split_compound(cmd)
    return None if segments is None else [segment for segment, _ in segments]


def command_tokens(segment: str) -> list[str]:
    """Skip shell environment assignments before checking the actual command."""
    tokens = shlex.split(segment, posix=True)
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens.pop(0)
    # Shell builtins may be explicitly invoked through these wrappers. They
    # still change the parent shell's cwd and must receive the same checks.
    while tokens and tokens[0] in {"env", "command", "builtin"}:
        wrapper = tokens[0]
        tokens = tokens[1:]
        while tokens:
            if tokens[0] == "--":
                tokens = tokens[1:]
                break
            if wrapper == "env":
                if tokens[0] in {"-i", "--ignore-environment"}:
                    tokens = tokens[1:]
                    continue
                if tokens[0] in {"-u", "--unset"} and len(tokens) > 1:
                    tokens = tokens[2:]
                    continue
                if tokens[0].startswith("--unset="):
                    tokens = tokens[1:]
                    continue
            elif wrapper == "command" and tokens[0] == "-p":
                tokens = tokens[1:]
                continue
            if tokens[0].startswith("-"):
                raise ValueError("命令包装参数无法确认，请直接调用工作区内的命令")
            break
        if wrapper == "env":
            while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                tokens = tokens[1:]
    return tokens


def directory_target(tokens: list[str]) -> str | None:
    if not tokens or tokens[0] not in {"cd", "pushd"}:
        return None
    args = tokens[1:]
    while args and args[0] in {"--", "-L", "-P"}:
        args = args[1:]
    if len(args) != 1 or args[0] == "-" or any(c in args[0] for c in "$`*?[]{}"):
        raise ValueError("目录切换无法确认: 请指定明确的工作区内目录")
    return args[0]


def directory_destination(tokens: list[str], cwd: str, ws: str) -> str:
    """Match shell cd -L (default) versus cd -P without losing logical aliases."""
    target = directory_target(tokens)
    options = tokens[1:-1]
    physical = False
    for option in options:
        if option == "--":
            break
        if option in {"-L", "-P"}:
            physical = option == "-P"
    return _resolve_token(target, cwd, ws) if physical else _resolve_lexical(target, cwd, ws)


# ============= 检查器 =============

def check_dangerous(segment: str) -> str | None:
    """危险模式黑名单匹配。"""
    for pattern in DANGEROUS_RE:
        if pattern.search(segment):
            return f"危险命令模式: {pattern.pattern}"
    return None


def check_first_token(segment: str, cwd: str, ws: str) -> str | None:
    """检查首词是否是受限解释器。

    - bash/sh/zsh 等:任何带参数调用都拒(不允许二次调用 shell)
    - python/node/perl/ruby:仅拒 -c/-e(代码字符串),允许 script.py
    """
    try:
        tokens = command_tokens(segment)
    except ValueError:
        return None
    if not tokens:
        return None

    cmd_name = os.path.basename(tokens[0]).lower()
    if re.fullmatch(r"python\d+(?:\.\d+)*", cmd_name):
        cmd_name = "python3"
    args = tokens[1:]

    if cmd_name in RESTRICTED_SHELLS:
        if args:
            return f"间接执行受限: {cmd_name} (禁止调用 shell 解释器执行脚本或代码)"

    if cmd_name in RESTRICTED_INTERPRETERS:
        flag, label = RESTRICTED_INTERPRETERS[cmd_name]
        if flag in args:
            if cmd_name.startswith("python") and is_workspace_venv_executable(tokens[0], cwd, ws):
                return None
            return f"间接执行受限: {label}"

    return None


def check_venv_install(segment: str, cwd: str, ws: str) -> str | None:
    """Python 包安装必须使用工作区 .venv，Node 包管理器保持工作区默认行为。"""
    try:
        tokens = command_tokens(segment)
    except ValueError:
        return None
    if not tokens:
        return None

    executable = tokens[0]
    command = os.path.basename(executable).lower()
    is_pip_command = re.fullmatch(r"pip(?:\d+(?:\.\d+)*)?(?:\.exe)?", command) and any(
        token in {"install", "i"} for token in tokens[1:]
    )
    is_python_pip = (
        re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", command)
        and any(tokens[i:i + 2] == ["-m", "pip"] and any(arg in {"install", "i"} for arg in tokens[i + 2:])
                for i in range(1, len(tokens) - 1))
    )
    if not (is_pip_command or is_python_pip):
        return None

    if is_workspace_venv_executable(executable, cwd, ws):
        return None
    return "Python 包安装必须使用工作区根目录的 .venv/bin/python -m pip install；子目录中请使用对应相对路径或完整绝对路径"


def is_path_like(token: str) -> bool:
    """判断 token 是否像路径(需越界检查)。"""
    if not token:
        return False
    if token.startswith("/"):
        return True
    if token.startswith("~"):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", token):
        return True
    parts = token.replace("\\", "/").split("/")
    if ".." in parts:
        return True
    return False


def is_null_device(token: str) -> bool:
    if not token:
        return False
    return token.replace("\\", "/") == "/dev/null" or token.upper() == "NUL"


def _resolve_lexical(token: str, cwd: str, ws: str) -> str:
    """不跟随符号链接解析路径，用于识别用户实际输入的工作区路径。"""
    expanded = os.path.expanduser(token)
    base = expanded if os.path.isabs(expanded) else os.path.join(cwd or ws, expanded)
    return os.path.normcase(os.path.abspath(base))


def is_workspace_venv_executable(token: str, cwd: str, ws: str) -> bool:
    """可执行路径是否明确位于当前工作区的 .venv/bin 或 .venv/Scripts。"""
    expanded = os.path.expanduser(token)
    # Unlike cd -L, executable lookup follows symlinks before processing '..'.
    executable_path = expanded if os.path.isabs(expanded) else os.path.join(cwd or ws, expanded)
    venv_root = workspace_venv_root(ws)
    if venv_root is None or not re.fullmatch(r"(?:python|pip)(?:\d+(?:\.\d+)*)?(?:\.exe)?", os.path.basename(token), re.I):
        return False
    if os.path.islink(executable_path) and not re.fullmatch(
        r"(?:python|pip)(?:\d+(?:\.\d+)*)?(?:\.exe)?", os.path.basename(os.path.realpath(executable_path)), re.I,
    ):
        return False
    parent = os.path.normcase(os.path.realpath(os.path.dirname(executable_path)))
    return any(parent == os.path.join(venv_root, name) for name in ("bin", "Scripts"))


def workspace_venv_root(ws: str) -> str | None:
    """Allow the local venv or native's shared venv, never arbitrary link targets."""
    root = os.path.normcase(os.path.realpath(ws))
    target = os.path.normcase(os.path.realpath(os.path.join(root, ".venv")))
    if target.startswith(root + os.sep):
        return target
    # Native Run views link .venv to this user's durable environment.
    run_root = os.path.dirname(root)
    runs_root = os.path.dirname(run_root)
    managed_root = os.path.dirname(runs_root)
    user_root = os.path.dirname(managed_root)
    if (os.path.basename(root) == "view" and os.path.basename(runs_root) == "runs"
            and os.path.basename(managed_root) == "managed"
            and target == os.path.join(user_root, ".venv")):
        return target
    return None


def resolve_under_ws(token: str, cwd: str, ws: str) -> bool:
    """解析 token 为绝对路径,判断是否在 ws 之下。

    相对路径以 cwd 解析,绝对路径直接用。解析后必须等于 ws 或在 ws/ 下。
    """
    # Only interpreter entry points may link to a system binary. Other venv
    # files must still resolve within the actual venv, including native's link.
    if is_workspace_venv_executable(token, cwd, ws):
        return True

    expanded = os.path.expanduser(token)
    abs_path = os.path.realpath(expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded))
    ws_norm = os.path.realpath(ws)
    if abs_path == ws_norm:
        return True
    venv_root = workspace_venv_root(ws)
    if venv_root and (abs_path == venv_root or abs_path.startswith(venv_root + os.sep)):
        return True
    return abs_path.startswith(ws_norm + os.sep) or any(
        abs_path == root or abs_path.startswith(root + os.sep)
        for root in _installed_skill_roots(ws)
    )


def _installed_skill_roots(ws: str) -> list[str]:
    """Trust only native platform-owned skill links, never arbitrary user links."""
    directory = os.path.join(os.path.realpath(ws), ".claude", "skills")
    try:
        parent = os.lstat(directory)
        if os.path.islink(directory) or parent.st_uid != 0 or parent.st_mode & 0o022:
            return []
        roots = []
        for name in os.listdir(directory):
            link = os.path.join(directory, name)
            if not os.path.islink(link) or os.lstat(link).st_uid != 0:
                continue
            target = os.path.realpath(link)
            info = os.stat(target)
            if os.path.isdir(target) and info.st_uid == 0 and not info.st_mode & 0o022:
                roots.append(target)
        return roots
    except OSError:
        return []


# ============= 受保护初始化文件/目录 =============
# 平台为每个智能体初始化的文件/目录,智能体不得删除/移动/改写,否则会破坏隔离
# 或绕过平台控制(改信任状态、.claude/settings.json / hooks/*.py)。
# Claude Code 必须能在 .claude 下创建 session-env 等运行时目录，pip 也必须能写 .venv。
# 因此只保护平台托管的控制文件，不锁定整个 .claude/.venv。
PROTECTED_FILES = (
    "CLAUDE.md",
    ".mcp.json",
    ".claude/.claude.json",
    ".claude/settings.json",
)
PROTECTED_DIRS = (".claude/hooks", ".claude/skills")


def _resolve_token(token: str, cwd: str, ws: str) -> str:
    """把 token 解析为规范化绝对路径(相对路径以 cwd 解析,cwd 缺省回退 ws)。"""
    expanded = os.path.expanduser(token)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    return os.path.realpath(os.path.join(cwd or ws, expanded))


def _protected_paths(ws: str) -> list[str]:
    ws_norm = os.path.realpath(ws)
    return [os.path.realpath(os.path.join(ws_norm, n)) for n in PROTECTED_FILES]


def _protected_dir_paths(ws: str) -> list[str]:
    ws_norm = os.path.realpath(ws)
    return [os.path.realpath(os.path.join(ws_norm, n)) for n in PROTECTED_DIRS] + _installed_skill_roots(ws)


def destroys_protected(token: str, cwd: str, ws: str) -> bool:
    """删除 token 对应路径是否会破坏受保护条目。

    True 当 token 解析为:
      - 某个受保护文件或目录本身,或
      - 受保护条目的祖先(如 . 或工作区根,删除会连带删除受保护条目),或
      - .claude/hooks 或 .claude/skills 内部的路径
    """
    prot = _protected_paths(ws)
    try:
        ap = _resolve_token(token, cwd, ws)
    except Exception:
        return False
    for p in prot:
        if ap == p or p.startswith(ap + os.sep):  # ap 是 p 或 p 的祖先
            return True
    for p in _protected_dir_paths(ws):
        if ap == p or ap.startswith(p + os.sep):  # ap 在受保护目录内
            return True
    return False


def is_protected_target(token: str, cwd: str, ws: str) -> bool:
    """token 是否指向平台托管文件或目录(用于拦截写/改)。"""
    try:
        ap = _resolve_token(token, cwd, ws)
    except Exception:
        return False
    for p in _protected_paths(ws):
        if ap == p:
            return True
    for p in _protected_dir_paths(ws):
        if ap == p or ap.startswith(p + os.sep):
            return True
    return False


def is_read_protected(token: str, cwd: str, ws: str) -> bool:
    """token 是否为智能体禁止读取的敏感路径。

    settings.json、.mcp.json 与 hooks 禁止读取，避免密钥泄漏和针对性绕过；
    .venv、Claude 运行时目录、CLAUDE.md 与 skills 可读。
    """
    try:
        ap = _resolve_token(token, cwd, ws)
    except Exception:
        return False
    ws_norm = os.path.realpath(ws)
    sensitive_files = [
        os.path.realpath(os.path.join(ws_norm, ".mcp.json")),
        os.path.realpath(os.path.join(ws_norm, ".claude", ".claude.json")),
        os.path.realpath(os.path.join(ws_norm, ".claude", "settings.json")),
    ]
    if ap in sensitive_files:
        return True
    hooks_dir = os.path.realpath(os.path.join(ws_norm, ".claude", "hooks"))
    if ap == hooks_dir or ap.startswith(hooks_dir + os.sep):
        return True
    return False


def check_find_paths(tokens: list[str], cwd: str, ws: str) -> str | None:
    """Validate explicit find roots, including plain relative names and symlink targets."""
    if not tokens or os.path.basename(tokens[0]).lower() != "find":
        return None
    args = tokens[1:]
    if "-files0-from" in args:
        return "find 搜索范围无法确认: 请直接指定工作区内的搜索路径，不使用 -files0-from"

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-L":
            return "find 禁止递归跟随符号链接: -L 可能访问工作区外，请使用默认 -P"
        if arg in ("-H", "-P") or re.fullmatch(r"-O[0-3]", arg):
            index += 1
        elif arg == "-D":
            index += 2  # GNU find debug option consumes one argument.
        elif arg == "--":
            index += 1
            break
        else:
            break

    roots = []
    for arg in args[index:]:
        if arg.startswith("-") or arg in ("!", "(", ")"):
            break
        roots.append(arg)
    ws_real = os.path.normcase(os.path.realpath(ws))
    for root in roots or ["."]:
        if any(char in root for char in "$`*?[]{}"):
            return f"find 搜索范围无法确认: {root}。请指定明确的工作区路径，文件名筛选使用 -name"
        # Traversal does not use the executable-only .venv symlink exemption.
        resolved = os.path.normcase(_resolve_token(root, cwd, ws))
        installed_root = any(resolved == path or resolved.startswith(path + os.sep)
                             for path in map(os.path.normcase, _installed_skill_roots(ws)))
        venv_root = workspace_venv_root(ws)
        in_venv = venv_root and (resolved == venv_root or resolved.startswith(venv_root + os.sep))
        if resolved != ws_real and not resolved.startswith(ws_real + os.sep) and not installed_root and not in_venv:
            return f"find 搜索路径越界: {root} (实际路径: {resolved})"
    return None


def check_path_escape(segment: str, cwd: str, ws: str) -> str | None:
    """检查段内路径是否越界。

    覆盖:
    - 所有路径样 token
    - 重定向目标 (> >> < 2>)
    - cd/pushd 目标
    """
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return f"无法解析命令段: {segment[:50]}"

    if not tokens:
        return None

    executable_tokens = command_tokens(segment)
    reason = check_find_paths(executable_tokens, cwd, ws)
    if reason:
        return reason

    # cd/pushd 无参数 → cd 到 $HOME,越界
    try:
        target = directory_target(executable_tokens)
    except ValueError as exc:
        return str(exc)
    if target is not None and not resolve_under_ws(directory_destination(executable_tokens, cwd, ws), cwd, ws):
        return f"目录越界: {executable_tokens[0]} {target}"

    # 重定向目标
    redirect_ops = {">", ">>", "<", "2>", "2>>"}
    null_redirect_targets = set()
    for idx, tok in enumerate(tokens):
        if tok in redirect_ops and idx + 1 < len(tokens):
            tgt = tokens[idx + 1]
            if is_null_device(tgt):
                null_redirect_targets.add(tgt)
                continue
            if is_path_like(tgt) and not resolve_under_ws(tgt, cwd, ws):
                return f"重定向越界: {tgt}"
        elif tok.startswith((">", "<", "2>")) and len(tok) > 1:
            tgt = re.sub(r"^(?:2>>|>>|2>|>|<)", "", tok)
            if tgt and is_null_device(tgt):
                continue
            if tgt and is_path_like(tgt) and not resolve_under_ws(tgt, cwd, ws):
                return f"重定向越界: {tgt}"

    # 所有路径样 token
    for tok in tokens:
        if tok in null_redirect_targets:
            continue
        # Environment values and --option=/path must use the same boundary
        # checks as positional paths. PYTHONPATH/PATH may contain several paths.
        values = [tok]
        if "=" in tok and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok) or tok.startswith("--")):
            key, value = tok.split("=", 1)
            values = value.split(os.pathsep) if key in {"PATH", "PYTHONPATH"} else [value]
        for value in values:
            if is_path_like(value) and not resolve_under_ws(value, cwd, ws):
                return f"路径越界: {value} (解析基准目录: {cwd})"

    return None


def _operands(args: list[str]) -> list[str]:
    """从参数列表中提取非 flag 操作数(跳过 - 开头,尊重 -- 终止符)。"""
    out: list[str] = []
    skip_flags = True
    for t in args:
        if skip_flags and t == "--":
            skip_flags = False
            continue
        if skip_flags and t.startswith("-") and len(t) > 1:
            continue
        out.append(t)
    return out


def check_protected_destructive(segment: str, cwd: str, ws: str) -> str | None:
    """拦截会破坏受保护初始化文件/目录的 Bash 命令。

    覆盖: rm/rmdir/unlink/shred(删)、mv(移走/覆盖)、cp(覆盖)、find -delete、
    truncate(截断)、tee(写入),以及重定向覆盖(> >> 2>)。
    """
    try:
        tokens = command_tokens(segment)
    except ValueError:
        return None
    if not tokens:
        return None
    cmd = os.path.basename(tokens[0]).lower()
    args = tokens[1:]

    if cmd in ("rm", "rmdir", "unlink", "shred"):
        for t in _operands(args):
            if destroys_protected(t, cwd, ws):
                return f"受保护初始化文件/目录禁止删除: {t}"

    elif cmd == "mv":
        ops = _operands(args)
        if len(ops) >= 2:
            for t in ops:  # 源端移走=删除受保护,目标端覆盖受保护
                if is_protected_target(t, cwd, ws) or destroys_protected(t, cwd, ws):
                    return f"受保护初始化文件/目录禁止移动/覆盖: {t}"

    elif cmd == "cp":
        ops = _operands(args)
        if len(ops) >= 2:
            dst = ops[-1]
            if is_protected_target(dst, cwd, ws):
                return f"受保护初始化文件/目录禁止覆盖: {dst}"

    elif cmd == "truncate":
        for t in _operands(args):
            if is_protected_target(t, cwd, ws):
                return f"受保护初始化文件禁止截断: {t}"

    elif cmd == "tee":
        for t in _operands(args):
            if is_protected_target(t, cwd, ws):
                return f"受保护初始化文件禁止写入: {t}"

    elif cmd == "find":
        # 路径操作数(find 后、首个 flag 前);-delete / -exec 表示删除动作
        has_delete = "-delete" in args or "-ok" in args or "-exec" in args
        path_ops: list[str] = []
        for a in args:
            if a.startswith("-"):
                break
            path_ops.append(a)
        if has_delete:
            targets = path_ops if path_ops else ["."]  # 无路径则默认 cwd
            for t in targets:
                if destroys_protected(t, cwd, ws):
                    return f"find 删除范围含受保护初始化文件/目录: {t}"

    # 重定向覆盖受保护文件(> CLAUDE.md / >> .claude/settings.json 等)
    redirect_ops = {">", ">>", "2>", "2>>"}
    for idx, tok in enumerate(tokens):
        tgt = None
        if tok in redirect_ops and idx + 1 < len(tokens):
            tgt = tokens[idx + 1]
        elif tok.startswith((">", "2>")) and len(tok) > 1:
            tgt = re.sub(r"^(?:2>>|>>|2>|>)", "", tok)
        if tgt and is_protected_target(tgt, cwd, ws):
            return f"受保护初始化文件禁止重定向覆盖: {tgt}"

    return None


def check_segment(segment: str, cwd: str, ws: str) -> str | None:
    """检查单个命令段(已不含复合操作符)。"""
    reason = check_dangerous(segment)
    if reason:
        return reason
    reason = check_first_token(segment, cwd, ws)
    if reason:
        return reason
    reason = check_venv_install(segment, cwd, ws)
    if reason:
        return reason
    reason = check_protected_destructive(segment, cwd, ws)
    if reason:
        return reason
    return check_path_escape(segment, cwd, ws)


def check_command(cmd: str, cwd: str, ws: str, depth: int = 0) -> str | None:
    """递归检查命令(含命令替换)。

    返回拒绝原因字符串,或 None 表示放行。
    """
    if depth > MAX_RECURSION_DEPTH:
        return "命令替换嵌套过深"

    # 整条命令的危险模式检查(覆盖跨管道的模式,如 curl|sh、wget|bash)
    reason = check_dangerous(cmd)
    if reason:
        return reason

    segments = _split_compound(cmd)
    if segments is None:
        return "复合命令引号不平衡,无法解析"

    # Track both successful and failed cd branches. In `cd out && python ...`
    # Python runs in out; after || it may instead run in the original directory.
    succeeded = {cwd}
    failed: set[str] = set()
    previous_op = ";"
    for seg, operator in segments:
        active = succeeded if previous_op == "&&" else failed if previous_op == "||" else succeeded | failed
        skipped_success = succeeded if previous_op == "||" else set()
        skipped_failure = failed if previous_op == "&&" else set()
        next_success = set(skipped_success)
        next_failure = set(skipped_failure)
        try:
            tokens = command_tokens(seg)
            target = directory_target(tokens)
        except ValueError as exc:
            return f"无法解析命令段: {exc}"
        if target is not None and (previous_op == "|" or operator == "|"):
            return "管道中的目录切换无法确认，请使用 cd <工作区目录> && <命令>"
        if tokens and tokens[0] == "popd":
            return "目录栈切换无法确认，请使用 cd <工作区目录>"
        subs = extract_subcommands(seg)
        if subs is None:
            return "无法解析命令替换($() 或反引号嵌套不平衡)"
        for current in active:
            for sub in subs:
                reason = check_command(sub, current, ws, depth + 1)
                if reason:
                    return f"命令替换内: {reason}"
            reason = check_segment(seg, current, ws)
            if reason:
                return reason
            next_success.add(directory_destination(tokens, current, ws) if target is not None else current)
            next_failure.add(current)
        succeeded, failed = next_success, next_failure
        previous_op = operator

    return None


# ============= 入口 =============

def get_workspace_root() -> str:
    """从 CLAUDE_CONFIG_DIR 推断工作区根目录。

    agent_runner.py 设置 CLAUDE_CONFIG_DIR = {workspace}/.claude,
    其父目录即工作区根。即使 Claude cd 到子目录,ws 仍是原始根。
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return os.path.realpath(os.path.dirname(config_dir))
    return os.path.realpath(os.getcwd())


def main() -> None:
    _log(f"=== hook invoked pid={os.getpid()} ===")
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        _log(f"hook parse FAIL: {e}")
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    _log(f"hook tool={tool_name} input_keys={list(tool_input.keys()) if isinstance(tool_input, dict) else '?'}")

    # Bash:先做工作区隔离安全检查(越界/危险命令自动拒绝,不询问)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if not cmd:
            sys.exit(0)
        cwd = data.get("cwd") or tool_input.get("cwd") or os.getcwd()
        ws = get_workspace_root()
        reason = check_command(cmd, cwd, ws)
        if reason:
            _log(f"hook Bash DENY (workspace_isolation): {reason}")
            sys.stderr.write(
                f"[workspace_isolation] 拒绝:{reason}。"
                f"所有路径与命令必须在工作区内:{ws}\n"
            )
            sys.exit(2)
        _log("hook AUTO-ALLOW (safe Bash after workspace isolation)")
        sys.exit(0)

    # 文件路径类工具:强制工作区隔离 + 平台托管文件不可删改/不可读取密钥
    # Write/Edit/Read 取 file_path;NotebookEdit 取 notebook_path;Glob/Grep 取可选 path
    FILE_PATH_KEYS = {
        "Write": "file_path", "Edit": "file_path", "Read": "file_path",
        "NotebookEdit": "notebook_path", "Glob": "path", "Grep": "path",
    }
    if tool_name in FILE_PATH_KEYS:
        target = (tool_input or {}).get(FILE_PATH_KEYS[tool_name])
        if target:
            ws = get_workspace_root()
            cwd = data.get("cwd") or (tool_input or {}).get("cwd") or ws
            # 1) 工作区越界:所有文件操作必须在 ws 内
            if not resolve_under_ws(target, cwd, ws):
                _log(f"hook {tool_name} DENY (workspace_escape): {target}")
                sys.stderr.write(
                    f"[workspace_isolation] 拒绝:{tool_name} 路径越界:{target}。"
                    f"所有文件操作必须在工作区内:{ws}\n"
                )
                sys.exit(2)
            # 2) 写/改类工具禁止改写平台托管的控制文件(防绕过钩子)
            if tool_name in ("Write", "Edit", "NotebookEdit") and is_protected_target(target, cwd, ws):
                _log(f"hook {tool_name} DENY (protected_init_file): {target}")
                sys.stderr.write(
                    f"[workspace_isolation] 拒绝:{tool_name} 平台托管文件禁止修改或覆盖:{target}\n"
                )
                sys.exit(2)
            # 3) 禁止读取含密钥的配置和 hooks 源码；运行时目录、skills、.venv 可读
            if tool_name == "Read" and is_read_protected(target, cwd, ws):
                _log(f"hook {tool_name} DENY (read_protected): {target}")
                sys.stderr.write(
                    f"[workspace_isolation] 拒绝:{tool_name} 受保护敏感路径"
                    f"(配置/钩子)禁止读取:{target}\n"
                )
                sys.exit(2)
        _log(f"hook AUTO-ALLOW (file tool in-workspace) tool={tool_name}")
        sys.exit(0)

    # MCP 由绑定关系及 permissions allow/ask 控制，需询问时交给 SDK 回调。
    _log(f"hook AUTO-ALLOW (allowed tool) tool={tool_name}")
    sys.exit(0)


if __name__ == "__main__":
    main()
