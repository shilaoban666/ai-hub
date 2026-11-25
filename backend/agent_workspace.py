"""智能体工作区目录管理

每个智能体一个固定工作区目录，结构根据 runtime_type 不同：

claude_code runtime:
  {AGENT_WORKSPACE_ROOT}/{agent_id}/
  ├── CLAUDE.md              # 智能体身份 + 执行规则
  ├── .claude/
  │   ├── .claude.json       # workspace trust state
  │   ├── settings.json      # permissions / env
  │   └── skills/
  │       └── ...            # 按技能名分目录
  ├── .mcp.json              # MCP 服务配置
  └── (用户文件)

"""

import hashlib
import json
import ntpath
import os
import posixpath
import re
import shutil
import socket
import sys
from urllib.parse import urlparse

from database import settings
from skill_utils import SKILLS_DIR
from skill_release_cache import materialize_cached_skill, remove_skill_directory


_configured_workspace_root = str(settings.agent_workspace_root or "").strip()
if _configured_workspace_root and not os.path.isabs(_configured_workspace_root):
    _configured_workspace_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", _configured_workspace_root)
    )
AGENT_WORKSPACE_ROOT = _configured_workspace_root or os.path.join(
    os.path.dirname(__file__), "agent_workspaces"
)


def legacy_workspace_roots(agent_id: int) -> list[str]:
    """Trusted host roots used by earlier workspace layouts."""
    bases = [AGENT_WORKSPACE_ROOT,
             settings.claude_code_native_workspace_root or settings.agent_native_workspace_root
             or settings.agent_linux_workspace_root]
    return list(dict.fromkeys(os.path.abspath(os.path.join(base, str(int(agent_id))))
                              for base in bases if base))


CLAUDE_CODE_MANAGED_PATHS = {
    "CLAUDE.md",
    ".mcp.json",
    ".claude",
    ".venv",
}
TEXT_PREVIEW_EXTENSIONS = {
    ".bash", ".c", ".cfg", ".conf", ".cpp", ".css", ".csv", ".go",
    ".h", ".hpp", ".htm", ".html", ".ini", ".java", ".js", ".json",
    ".jsonl", ".jsx", ".log", ".markdown", ".md", ".mjs", ".php",
    ".ps1", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}


def is_managed_workspace_path(runtime_type: str, rel_path: str) -> bool:
    """Return whether a workspace path is generated and owned by AI Hub."""
    normalized = posixpath.normpath(str(rel_path or "").replace("\\", "/")).casefold()
    managed_paths = CLAUDE_CODE_MANAGED_PATHS
    return any(
        normalized == managed_path.casefold()
        or normalized.startswith(managed_path.casefold() + "/")
        for managed_path in managed_paths
    )


def normalize_workspace_relative_path(rel_path: str) -> str:
    """Normalize a user-supplied workspace path and reject non-relative aliases."""
    raw = str(rel_path or "").replace("\\", "/")
    normalized = posixpath.normpath(raw)
    if (
        not raw
        or posixpath.isabs(raw)
        or ntpath.isabs(raw)
        or normalized in {".", ".."}
        or normalized.startswith("../")
    ):
        raise ValueError("非法路径")
    return normalized


def is_text_preview_path(rel_path: str) -> bool:
    """Return whether a workspace file type supports safe source preview."""
    return posixpath.splitext(str(rel_path or "").replace("\\", "/"))[1].casefold() in TEXT_PREVIEW_EXTENSIONS



def get_workspace_dir(agent_id: int) -> str:
    """获取智能体工作区目录路径"""
    return os.path.join(AGENT_WORKSPACE_ROOT, str(agent_id))


def ensure_workspace_dir(agent_id: int) -> str:
    """确保工作区目录存在，返回路径"""
    ws_dir = get_workspace_dir(agent_id)
    os.makedirs(ws_dir, exist_ok=True)
    os.makedirs(os.path.join(ws_dir, ".claude"), exist_ok=True)
    os.makedirs(os.path.join(ws_dir, ".claude", "skills"), exist_ok=True)
    os.makedirs(os.path.join(ws_dir, ".claude", "hooks"), exist_ok=True)
    return ws_dir


def delete_workspace(agent_id: int) -> None:
    """删除整个工作区目录（软删智能体时调用）"""
    ws_dir = get_workspace_dir(agent_id)
    if os.path.exists(ws_dir):
        shutil.rmtree(ws_dir, ignore_errors=True)


def _load_skill_content(skill) -> str | None:
    """加载技能内容，依次尝试：content 字段 → 文件树 JSON → 磁盘文件"""
    if skill.content:
        return skill.content

    if skill.files:
        try:
            file_data = json.loads(skill.files)
            file_tree = file_data.get("tree", file_data) if isinstance(file_data, dict) else file_data
            if isinstance(file_tree, list):
                content = _find_skill_md_in_tree(file_tree)
                if content:
                    return content
        except (json.JSONDecodeError, TypeError):
            pass

    skill_md_path = os.path.join(SKILLS_DIR, str(skill.id), "SKILL.md")
    if os.path.exists(skill_md_path):
        try:
            with open(skill_md_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass

    return None


def _load_skill_files(skill) -> dict[str, str] | None:
    """加载技能的完整文件列表 {relative_path: content}"""
    files = {}

    # 1. 从 skill.files JSON 解析文件树
    if skill.files:
        try:
            file_data = json.loads(skill.files)
            file_tree = file_data.get("tree", file_data) if isinstance(file_data, dict) else file_data
            if isinstance(file_tree, list):
                _flatten_tree(file_tree, "", files)
                if files:
                    return files
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 从磁盘读取
    skill_dir = os.path.join(SKILLS_DIR, str(skill.id))
    if os.path.isdir(skill_dir):
        for root, _dirs, filenames in os.walk(skill_dir):
            for filename in filenames:
                full = os.path.join(root, filename)
                rel = os.path.relpath(full, skill_dir).replace("\\", "/")
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        files[rel] = f.read()
                except (UnicodeDecodeError, Exception):
                    pass
        if files:
            return files

    # 3. 只有纯文本内容，作为 SKILL.md
    if skill.content:
        return {"SKILL.md": skill.content}

    return None


def _flatten_tree(nodes: list, parent_path: str, out: dict[str, str]) -> None:
    """递归展平文件树到 {path: content}"""
    for node in nodes:
        label = node.get("label", "")
        path = f"{parent_path}/{label}" if parent_path else label
        if node.get("type") == "file":
            out[path] = node.get("content", "")
        elif node.get("type") == "folder" and node.get("children"):
            _flatten_tree(node["children"], path, out)


def _find_skill_md_in_tree(nodes: list) -> str | None:
    """在文件树中递归查找 SKILL.md"""
    for node in nodes:
        if node.get("type") == "file" and node.get("label", "").upper() == "SKILL.MD":
            return node.get("content", "")
        if node.get("type") == "folder" and node.get("children"):
            result = _find_skill_md_in_tree(node["children"])
            if result:
                return result
    return None


# hook 脚本源目录
HOOKS_SRC_DIR = os.path.join(os.path.dirname(__file__), "agent_hooks")

# 需要安装到工作区的 hook 脚本
HOOK_SCRIPTS = [
    "post_tool_use.py",
    "pre_tool_use.py",
]


def install_hooks(ws_dir: str) -> list[str]:
    """将 hook 脚本复制到工作区 .claude/hooks/ 目录，返回已安装的 hook 名列表"""
    hooks_dir = os.path.join(ws_dir, ".claude", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    installed = []
    for script_name in HOOK_SCRIPTS:
        src = os.path.join(HOOKS_SRC_DIR, script_name)
        dst = os.path.join(hooks_dir, script_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            installed.append(script_name)
        else:
            print(f"[Agent] Hook 脚本不存在: {src}")

    return installed


def install_skills(ws_dir: str, skills, *, cached_copies=None) -> list[str]:
    """将技能安装到 .claude/skills/ 目录，返回已安装的技能名列表

    每个技能创建独立子目录，写入完整文件树。
    """
    skills_dir = os.path.join(ws_dir, ".claude", "skills")
    if os.path.islink(os.path.join(ws_dir, ".claude")) or os.path.islink(skills_dir):
        raise ValueError("skill installation directory must not be a symlink")
    skills = list(skills or [])
    desired_names = {_claude_skill_name(skill) for skill in skills}

    # Remove uninstalled skills, but preserve unchanged cached versions.
    if os.path.exists(skills_dir):
        for item in os.listdir(skills_dir):
            if item not in desired_names:
                remove_skill_directory(os.path.join(skills_dir, item))

    installed = []
    for skill in skills:
        name = _claude_skill_name(skill)
        skill_dir = os.path.join(skills_dir, name)
        cached_dir = getattr(skill, "cached_files_dir", None)
        if cached_dir:
            source = _skill_installation_source(skill)
            if cached_copies is None:
                materialize_cached_skill(source, skill_dir)
            else:
                cached_copies.append((source, os.path.join(".claude", "skills", name)))
            installed.append(name)
            continue
        remove_skill_directory(skill_dir)
        os.makedirs(skill_dir, exist_ok=True)

        skill_files = _load_skill_files(skill)
        if skill_files:
            for rel_path, content in skill_files.items():
                # 安全检查：防止路径穿越
                safe_path = os.path.normpath(rel_path)
                if safe_path.startswith(".."):
                    continue
                full_path = os.path.join(skill_dir, safe_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
            installed.append(name)

    return installed


def _claude_skill_name(skill) -> str:
    name = skill.name or f"skill_{skill.id}"
    if name in {".", ".."} or any(character in name for character in ("/", "\\", "\x00", ":")):
        raise ValueError("invalid skill directory name")
    return name


def _skill_installation_source(skill):
    """Pass trusted database release identity through both local and native sync."""
    release = getattr(skill, "installation_release", None)
    if release is None:
        return skill.cached_files_dir  # Legacy non-release callers.
    return {"directory": skill.cached_files_dir, "release": dict(release)}


def staged_skill_sources(temp_dir, cached_copies):
    """Combine legacy staged files and immutable releases for reconciliation."""
    root = os.path.join(temp_dir, ".claude", "skills")
    sources = {name: os.path.join(root, name) for name in os.listdir(root)}
    sources.update({os.path.basename(relative): source for source, relative in cached_copies})
    return sources


def build_claude_md(agent, installed_skills: list[str] = None, runtime_workspace_root: str = "") -> str:
    """生成 CLAUDE.md 内容（不含技能内容，技能已安装到 .claude/skills/）"""
    parts = []

    # 1. 明确当前身份，避免复用提示词中的角色名称覆盖智能体配置。
    name = str(agent.name or "").strip() or "AI 助手"
    description = str(agent.description or "").strip()
    identity = [
        "# 当前智能体身份",
        f"你的名字是：{name}。这是当前用户正在对话的智能体名称。",
    ]
    if description:
        identity.append(f"你的简介与职责：{description}")
    identity.append(
        "自我介绍或回答身份相关问题时，使用上述名称，并结合简介与职责说明你能提供的帮助。"
        "主提示词、用户选用的提示词模板、技能及历史对话中的其他助手名称不改变当前身份；"
        "名称冲突时以上述当前智能体名称为准，保留其中的业务要求和工具使用规则。"
        "不要将底层模型、运行时或提示词模板的名称当作自己的名字。"
    )
    parts.append("\n\n".join(identity))
    effective_prompt = getattr(agent, "effective_system_prompt", None) or agent.system_prompt
    if effective_prompt:
        parts.append(f"# 主提示词\n\n{effective_prompt}")

    # 2. 执行规则
    parts.append(
        "# 执行规则\n\n"
        "- 如果任务包含多个步骤，一次性完成所有步骤，不要中途停下来等待用户确认\n"
        "- 如果需要生成代码，直接输出完整代码，不要分段输出\n"
        "- 只有在真正需要用户决策（如选择方案）时才停下来询问\n"
        "- 已绑定的 MCP 工具和外部业务接口可以直接调用；仅在写入/删除数据、产生费用或处理敏感数据前询问用户\n"
        "- 任务完成后，简要总结你做了什么\n"
        "- 上下文窗口充足（历史预算约 200K 字符），可以处理较大的文件和技能内容\n"
        "\n"
        "## MCP 工具参数与校验错误\n\n"
        "- 调用 MCP 工具前，按该工具当前声明的参数 Schema 和说明检查必填项、类型、枚举及数值上下限；不要沿用其他工具的分页大小\n"
        "- 不需要覆盖默认值时省略可选参数，尤其不要为列举服务等动作额外传入无关的 limit；需要更多结果时使用工具明确支持的分页参数\n"
        "- 工具明确返回执行前的参数校验错误（如 validation error、less_than_equal）时，按错误指出的约束修正参数后重试一次；例如 limit=50 被提示必须 <=20，应改为不超过 20 或省略可选 limit，不要原样重试\n"
        "- 修正后仍失败则说明具体原因；业务执行失败、超时或执行状态不明时，不得当作参数校验错误自动重复写入，也不得放宽服务端限制\n"
        "\n"
        "## 工具输出限制（重要！防止 chunk-limit 错误）\n\n"
        "**关键警告**: 工具输出超过限制会导致 'chunk is longer than limit' 错误，必须严格遵守：\n\n"
        "- **Read 工具**：单次读取不超过 300 行，大文件必须分页读取（offset/limit 参数）\n"
        "  - 先用 `wc -l file` 确认总行数，然后分段读取\n"
        "  - 示例：`Read(file, offset=0, limit=300)` → `Read(file, offset=300, limit=300)`\n"
        "- **Grep 工具**：必须设置 head_limit=50（最多 100），output_mode 优先用 files_with_matches\n"
        "  - 如需查看内容，先用 files_with_matches 找文件，再 Read 具体文件\n"
        "- **Bash 命令**：所有可能长输出的命令必须加 `| head -100` 或 `| tail -100`\n"
        "  - 避免直接 `cat` 大文件，用 `head -n 100` 或 `tail -n 100`\n"
        "  - 避免无限制的 `find` / `ls -R` / `grep -r`，必须限制输出行数\n"
        "- **如果遇到截断错误**：立即缩小范围（减少行数/分批处理），不要重试相同参数\n"
        "- **Grep 前置过滤**：先用 Glob 定位文件，缩小搜索范围，再精准 Grep\n"
        "\n"
        "# Python 环境（重要）\n\n"
        "- 运行 Python 脚本、执行 Python 代码、安装依赖统一使用当前工作区根目录的 .venv\n"
        "- 运行脚本：`.venv/bin/python script.py`；安装依赖：`.venv/bin/python -m pip install <pkg>`\n"
        "- Windows 使用 `.venv\\Scripts\\python.exe` 和 `-m pip`；不要混用不同解释器的 pip\n"
        "- 切换到子目录后，相对路径以切换后的目录为准。例如 `cd out && ../.venv/bin/python script.py`\n"
        "- 也可以使用工作区根目录下解释器的完整绝对路径，避免多次 cd 导致解释器或文件路径错误\n"
        "- PATH 已优先指向工作区 .venv；不要显式改用 /usr/bin/python3 或系统 pip 来绕过依赖问题\n"
        "- 不要在系统 Python 环境中安装包，所有依赖安装在 .venv 中\n"
        "- 仅当 .venv 损坏或缺失时才执行 `python -m venv .venv` 重建\n"
        "\n"
        "# 工作区\n\n"
        "- 所有文件操作和命令执行在当前工作区目录内完成\n"
        "- 绝对路径不因 /var、/tmp 等前缀而越界；应以规范化并解析符号链接后是否属于当前工作区判断\n"
        "- current 别名与本轮 view 目录指向同一工作区时等价，不要改用其他用户或其他运行的目录\n"
        "- 可以自由读写文件、执行脚本、安装依赖\n"
        "- 禁止使用 sudo/su 提权\n"
    )
    if runtime_workspace_root:
        parts.append(f"当前工作区根目录（运行环境内）：{runtime_workspace_root}")

    # 3. 已安装技能
    if installed_skills:
        parts.append("# 已加载技能\n\n" + "\n".join(f"- {s}" for s in installed_skills))

    return "\n\n".join(parts)


def _check_http_mcp(url: str, timeout: float = 2.0) -> bool:
    """快速 TCP 连接检查 HTTP MCP 服务是否可达"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def _mcp_runtime_server_names(mcps) -> dict[str, str]:
    """Give display names stable CLI identifiers without permission collisions.

    Claude replaces non-ASCII tool-name characters with underscores. Distinct
    display names can therefore become the same tool namespace. Use the same
    unique ASCII names in .mcp.json and the permission rules instead.
    """
    names = {(getattr(service, "name", "") or "").strip() for service in mcps}
    names.discard("")
    aliases = {name: name for name in names if re.fullmatch(r"[a-zA-Z0-9_-]+", name)}
    used = set(aliases.values())
    for name in sorted(names - aliases.keys()):
        readable = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_-")[:32] or "mcp"
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        base = f"{readable}_{digest}"
        alias = base
        suffix = 2
        while alias in used:
            alias = f"{base}_{suffix}"
            suffix += 1
        aliases[name] = alias
        used.add(alias)
    return aliases


def build_mcp_json(
    mcps,
    check_connectivity: bool = False,
    overrides: list[dict] | None = None,
) -> tuple[dict, list[str]]:
    """从数据库 MCP 服务构建 claude code .mcp.json 格式

    Args:
        mcps: MCP 服务 ORM 列表
        check_connectivity: 是否检查 HTTP 类 MCP 的连通性

    Returns:
        (mcp_config, warnings): MCP 配置 dict + 警告消息列表
    """
    servers = {}
    warnings = []
    runtime_names = _mcp_runtime_server_names(mcps)
    override_map = {
        int(item.get("mcp_id")): item
        for item in (overrides or [])
        if isinstance(item, dict) and item.get("mcp_id")
    }

    for svc in mcps:
        name = (svc.name or "").strip()
        if not name:
            continue
        runtime_name = runtime_names[name]
        try:
            cfg = json.loads(svc.config) if svc.config else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(cfg, dict):
            continue

        override = override_map.get(getattr(svc, "id", None), {})
        for field in ("env", "headers"):
            values = override.get(field) if isinstance(override, dict) else None
            if not isinstance(values, dict):
                continue
            merged = dict(cfg.get(field) or {})
            for key, value in values.items():
                if value == "":
                    merged.pop(key, None)
                else:
                    merged[key] = value
            cfg[field] = merged

        if svc.type == "stdio":
            command = cfg.get("command", "").strip()
            if not command:
                continue
            entry = {
                "command": command,
                "args": cfg.get("args", []),
            }
            if cfg.get("env"):
                entry["env"] = cfg["env"]
            servers[runtime_name] = entry

        elif svc.type in ("sse", "http", "streamable_http", "streamable-http"):
            url = cfg.get("url", "").strip()
            if not url:
                continue
            if check_connectivity and not _check_http_mcp(url):
                warnings.append(f"MCP 服务 [{name}] 不可达 ({url})，已跳过。请确认服务是否已启动。")
                continue
            entry = {
                "type": "http",
                "url": url,
            }
            if cfg.get("headers"):
                entry["headers"] = cfg["headers"]
            servers[runtime_name] = entry

        elif svc.type == "json":
            if cfg:
                servers[runtime_name] = cfg

    return {"mcpServers": servers}, warnings


def get_mcp_server_names(mcps) -> list[str]:
    """Return the effective project MCP server names written to .mcp.json."""
    if not mcps:
        return []
    mcp_config, _ = build_mcp_json(mcps, check_connectivity=False)
    servers = mcp_config.get("mcpServers", {})
    return list(servers.keys()) if isinstance(servers, dict) else []


def get_mcp_tool_permissions(mcps) -> dict:
    """Use identical tool scopes for CLI settings and SDK approval validation."""
    server_names = set(get_mcp_server_names(mcps))
    runtime_names = _mcp_runtime_server_names(mcps)
    permissions = {"allow": [], "ask": []}
    for service in mcps:
        name = runtime_names.get((getattr(service, "name", "") or "").strip())
        if name not in server_names:
            continue
        tools = getattr(service, "allowed_tools", None) or ["*"]
        target = permissions["ask" if getattr(service, "require_confirmation", False) else "allow"]
        target.extend(f"mcp__{name}__{re.sub(r'[^a-zA-Z0-9_*-]', '_', tool)}" for tool in tools)
    return permissions


def _hook_command(command) -> str:
    """Claude hook settings require command hooks to be strings."""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def build_claude_state_json(project_paths) -> dict:
    """Build Claude Code's per-project trust state for managed workspaces."""
    projects = {}
    for value in project_paths or []:
        path = str(value or "").strip()
        if not path:
            continue
        if path.startswith("/"):
            normalized = posixpath.normpath(path)
        elif ntpath.isabs(path):
            normalized = ntpath.normpath(path)
        else:
            normalized = os.path.normpath(os.path.abspath(path))
        projects[normalized] = {"hasTrustDialogAccepted": True}
    return {"projects": projects}


def build_settings_json(
    agent,
    model,
    mcps=None,
    include_secrets: bool = True,
    sandbox_type: str = "directory",
    runtime_workspace_root: str = "",
) -> dict:
    """生成 .claude/settings.json

    - allow: 全部工具开放，MCP 绑定即授权
    - deny: 仅拦截真正破坏性命令
    - defaultMode: acceptEdits。托管会话通过 Agent SDK 回调处理 ask；
      逐次确认模式由运行器追加 ask 规则，覆盖此处的 allow。
    - env: 注入 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL
    - include_secrets: native 沙箱下置 False，密码不落 settings.json(由 runtime env 注入)
    - sandbox_type: directory 用 sys.executable 跑 hook；native(Linux)
      用系统 python3(hook 脚本仅依赖标准库)
    """
    if mcps is None:
        mcps = getattr(agent, "mcps", []) or []
    mcp_server_names = get_mcp_server_names(mcps)
    # Bound MCPs are allowed unless their policy requires SDK confirmation.
    mcp_permissions = get_mcp_tool_permissions(mcps)

    allow_tools = [
        "Bash",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
        "Task",
        "NotebookEdit",
    ] + mcp_permissions["allow"]

    # 危险命令黑名单：仅拦截真正破坏性的操作
    deny_patterns = [
        # 删除根
        "Bash(rm -rf /*)",
        "Bash(rm -rf /)",
        "Bash(rm -rf ~)",
        # 权限提升
        "Bash(sudo *)",
        "Bash(su *)",
        "Bash(su)",
        # 磁盘破坏
        "Bash(dd if=* of=/*)",
        "Bash(> /dev/sd*)",
        "Bash(> /dev/nvme*)",
        "Bash(> /dev/hd*)",
        "Bash(mkfs.*)",
        # fork bomb
        "Bash(:(){ :|:& };:)",
    ]

    env = {}
    if model:
        is_platform_model = getattr(model, "scope", "user") == "platform"
        if include_secrets and not is_platform_model:
            env["ANTHROPIC_AUTH_TOKEN"] = model.api_key or ""
        if model.api_proxy_url and not is_platform_model:
            env["ANTHROPIC_BASE_URL"] = model.api_proxy_url
        env["ANTHROPIC_MODEL"] = model.name or ""

    # PreToolUse hook: 工作区隔离检查 + 危险命令拦截（.* 匹配所有工具含 MCP）
    # PostToolUse hook: 截断过大的工具返回结果，防止 API chunk-limit 错误
    # directory 使用宿主解释器；native/container 使用运行环境内的解释器。
    # 仅当路径含空格时加引号:Claude Code 可能按空格拆分命令,无空格路径加引号反而会让
    # 首个 token 带字面引号导致命令找不到。
    agent_id = getattr(agent, "id", None)
    if sandbox_type in ("native", "linux_user", "container"):
        python_exe = "/usr/bin/python3"
        if sandbox_type == "container":
            agent_home = "/workspace"
        elif runtime_workspace_root:
            agent_home = os.path.normpath(runtime_workspace_root).replace("\\", "/")
        elif sandbox_type in ("native", "linux_user") and agent_id:
            from database import settings as app_settings

            linux_root = (
                getattr(app_settings, "claude_code_native_workspace_root", "")
                or getattr(app_settings, "agent_native_workspace_root", "")
                or getattr(app_settings, "agent_linux_workspace_root", "/var/lib/aihub/agent_workspaces")
            )
            agent_home = os.path.join(linux_root, str(agent_id)).replace("\\", "/")
        else:
            agent_home = f"/home/agent_{agent_id}" if agent_id else ""
        hook_dir = f"{agent_home}/.claude/hooks" if agent_home else ".claude/hooks"
        # Linux: 数组格式，claude 直接 exec 不经过 shell，避免命令解析差异
        pre_hook_cmd = [python_exe, f"{hook_dir}/pre_tool_use.py"]
        post_hook_cmd = [python_exe, f"{hook_dir}/post_tool_use.py"]
    else:
        python_exe = sys.executable
        hook_dir = ".claude/hooks"
        quote = '"' if ' ' in python_exe else ''
        pre_hook_cmd = f"{quote}{python_exe}{quote} {hook_dir}/pre_tool_use.py"
        post_hook_cmd = f"{quote}{python_exe}{quote} {hook_dir}/post_tool_use.py"
    hooks = {
        "PreToolUse": [
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": _hook_command(pre_hook_cmd),
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Read|Grep|Bash|WebFetch|WebSearch",
                "hooks": [
                    {
                        "type": "command",
                        "command": _hook_command(post_hook_cmd),
                    }
                ],
            }
        ],
    }

    return {
        "permissions": {
            "allow": allow_tools,
            "ask": mcp_permissions["ask"],
            "deny": deny_patterns,
            "defaultMode": "acceptEdits",
        },
        "env": env,
        "enableAllProjectMcpServers": True,
        "enabledMcpjsonServers": mcp_server_names,
        "disabledMcpjsonServers": [],
        "hooks": hooks,
    }


def sync_workspace(agent, model, filter_skills=None) -> str:
    """同步智能体配置到工作区目录

    根据 agent.runtime_type 生成不同的配置：
    - claude_code: CLAUDE.md + .claude/settings.json + .mcp.json

    Args:
        agent: Agent ORM 对象
        model: AIModel ORM 对象
        filter_skills: 可选，过滤后的技能列表；None 表示使用全部绑定技能

    Returns:
        工作区目录路径
    """
    runtime_type = (getattr(agent, "runtime_type", None) or "claude_code")

    ws_dir = ensure_workspace_dir(agent.id)

    # 1. 安装技能（所有 runtime 共用 .claude/skills/）
    skills_to_install = filter_skills if filter_skills is not None else (
        agent.runtime_skills if hasattr(agent, "runtime_skills") else agent.skills
    )
    installed = install_skills(ws_dir, skills_to_install)

    # 1.5. 安装 hooks（截断大工具结果等）
    installed_hooks = install_hooks(ws_dir)

    # 2. CLAUDE.md（所有 runtime 都支持）
    claude_md = build_claude_md(agent, installed, runtime_workspace_root=ws_dir)
    with open(os.path.join(ws_dir, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write(claude_md)

    # 3. .mcp.json（所有 runtime 共用 MCP 配置，跳过不可达的 HTTP MCP）
    mcp_json, mcp_warnings = build_mcp_json(
        agent.mcps,
        overrides=getattr(agent, "mcp_overrides", []),
    )
    for w in mcp_warnings:
        print(f"[Agent] MCP 警告: {w}")
    with open(os.path.join(ws_dir, ".mcp.json"), "w", encoding="utf-8") as f:
        json.dump(mcp_json, f, ensure_ascii=False, indent=2)

    # 4. Runtime 特定配置
    if runtime_type == "claude_code":
        # Claude Code ignores project settings until the workspace is trusted.
        with open(os.path.join(ws_dir, ".claude", ".claude.json"), "w", encoding="utf-8") as f:
            json.dump(build_claude_state_json([ws_dir]), f, ensure_ascii=False, indent=2)
        # .claude/settings.json
        settings_json = build_settings_json(agent, model, mcps=agent.mcps)
        with open(os.path.join(ws_dir, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings_json, f, ensure_ascii=False, indent=2)
    return ws_dir


def init_workspace(agent, model, filter_skills=None) -> str:
    """创建智能体时初始化工作区（sync_workspace 的别名，语义更清晰）"""
    return sync_workspace(agent, model, filter_skills=filter_skills)
