"""Administrator-managed variables shared by Skill script executions."""
import re

from models import PlatformGlobalSettings


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_RESERVED_NAMES = {
    "PATH", "HOME", "USERPROFILE", "USER", "LOGNAME", "SHELL",
    "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE",
    "PIP_REQUIRE_VIRTUALENV", "NODE_OPTIONS", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS",
}
_RESERVED_PREFIXES = ("AIHUB_", "ANTHROPIC_", "CLAUDE_", "DOCKER_")


def validate_runtime_environment(variables: dict[str, str]) -> dict[str, str]:
    if len(variables) > 100:
        raise ValueError("环境变量最多配置 100 项")
    size = 0
    for name, value in variables.items():
        if not _NAME.fullmatch(name):
            raise ValueError("变量名须以字母或下划线开头，仅包含字母、数字、下划线，最多 128 个字符")
        if name.upper() in _RESERVED_NAMES or name.upper().startswith(_RESERVED_PREFIXES):
            raise ValueError(f"变量 {name} 由运行环境管理，请使用其他名称")
        if "\0" in value:
            raise ValueError(f"变量 {name} 的值不能包含空字符")
        size += len(name.encode("utf-8")) + len(value.encode("utf-8")) + 2
    if size > 64 * 1024:
        raise ValueError("环境变量总大小不能超过 64 KB")
    return dict(variables)


def load_global_runtime_environment(db) -> dict[str, str]:
    # Select the column on every Run so saves/deletions take effect across workers,
    # even if the ORM session has previously loaded the settings singleton.
    variables = db.query(PlatformGlobalSettings.runtime_environment).filter(
        PlatformGlobalSettings.id == 1,
    ).scalar()
    return validate_runtime_environment(variables or {})
