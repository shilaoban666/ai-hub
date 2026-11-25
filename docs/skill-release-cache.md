# 技能持久安装与校验

安装记录决定应有的技能版本，工作区保存实际安装文件。进入对话页面、切换会话时，前端调用 `POST /api/agents/{agent_id}/skills/sync`，校验并同步当前智能体可用的技能。发送消息前再次读取最新安装和权限状态并校验，覆盖页面打开后发生的卸载、升级、撤销等变化。

同步规则：

- 缺少技能目录或文件：实际写入安装文件。
- 已卸载、撤销、不再绑定：删除该工作区对应的实际技能目录。
- 发布版本或文件内容变化：校验后替换；升级时删除旧版本多余文件。
- 文件正确：保留文件，不重装、不修改内容或修改时间。校验记录持久化，后端重启后仍可复用。
- 全局安装优先于同技能的个人安装，授权和发布状态仍每次从数据库读取。

## 安装目录与运行目录

Claude Code 的 native/container 模式使用 `USER_WORKSPACE_ROOT/{workspace_key}/managed/skill-installations/{agent_id}/{skill_name}/`。按用户工作区和智能体区分，防止不同用户或智能体的技能集合混用。每次检查当前智能体对应的目录；未进入的智能体目录在下次进入它的对话时同步。单次选择一个技能只限制运行时可见的技能，不卸载该智能体其他有效技能。

native 通过受保护的符号链接将技能接入临时运行目录 `.claude/skills/`。实际文件由 root 持有，只允许该用户组读取，普通用户不能修改。工具路径检查允许读取平台持有的技能链接目标，仍禁止修改技能及访问其他工作区。container 将选中的安装目录逐个只读挂载至 `/workspace/.claude/skills/{skill_name}`，不复制技能进临时目录。对话结束的清理只删除运行目录，不删除持久安装。

旧版 native 独立智能体工作区使用 `CLAUDE_CODE_NATIVE_WORKSPACE_ROOT/.skill-installations/{agent_id}/`。本地 directory 模式继续使用 `AGENT_WORKSPACE_ROOT/{agent_id}/.claude/skills/`，同样支持发布技能的持久校验。

进入对话的检查与运行共用数据库工作区执行租约。工作区忙时返回 `deferred`，不改动正在使用的文件；下一次进入或执行时重新检查。检查失败会显示重试提示，执行前校验仍是必经步骤。安装、卸载的文件同步在上述检查点执行，不在修改安装记录时强行打断进行中的任务。

## 校验与发布包缓存

每个实际安装目录中的 `.aihub-installed.json` 使用格式版本 2，`release` 字段明确保存 `skill_id`、`release_id`、`version` 和发布包 `content_sha256`，另外保存源文件和安装文件的校验元数据。版本信息来自数据库选定的发布记录，经发布包校验后传递至实际安装，不从目录名或 SKILL.md 推断，也不自动追踪最新发布版本。

校验先比较完整发布身份，再比较文件指纹。Linux 比对文件集合、inode、大小、纳秒级修改/变更时间、权限与所有者；一致时不读取完整技能内容。版本身份、文件元数据变化或记录缺失时比较文件内容 SHA-256：内容有效则仅更新版本记录，内容不一致才重装。升级和回滚均按此规则执行；即使版本号相同，发布 ID 或发布包哈希不同也会重新核验。Windows 的 ctime 表示创建时间，因此额外比较内容，防止同大小文件被修改后恢复 mtime 而漏检。

旧格式记录在下一次同步时自动迁移，先校验内容，再补齐版本信息；文件正确时不重装。未经过发布安装流程的旧调用仍使用文件校验，`release` 为 null，不伪造发布 ID 或版本。

发布包缓存只是安装源，不是用户的安装目录。默认位置 `backend/.cache/skill-releases/`，可通过 `SKILL_RELEASE_CACHE_ROOT` 设置。服务账号私有权限为 0700；不可将整个缓存挂载给运行环境。首次使用校验发布包 SHA-256 并解包，后续复用缓存。键包含发布 ID、发布包路径和文件元数据。缺失或校验失败时拒绝加载。包必须保存在仅服务端可写的目录。

跨进程文件锁和临时目录发布避免重复构建缓存；内存缓存最多 32 个版本、字符串估算上限 64 MiB。实际安装与缓存不使用共享硬链接，支持时使用 reflink，否则普通复制。缓存保留历史版本便于回滚，目前不自动回收；清理应在暂停工作区准备时进行。卸载会删除对应安装文件，历史发布包和缓存不属于有效安装。

## 验证

在 `backend` 目录运行：

```
python -m unittest test_skill_installation_sync test_skill_release_cache test_global_skill_installation test_asset_runtime_system_mcp test_skill_release_restore test_native_workspace_permissions test_runtime_configuration test_find_workspace_paths -q
```

覆盖跨进程复用、安装文件损坏/缺失、版本切换、实际卸载、容器多次准备与清理、单技能选择、作用域隔离、页面入口权限及忙碌处理、native 链接和工具读写保护。

`test_skill_installation_linux.py` 在 Linux root 环境的临时目录内验证真实的所有者和权限、普通用户通过链接读取技能、禁止写入、有效安装跳过内容读取和复制、清理运行目录后保留技能，以及卸载删除真实文件。已在 WSL 运行通过。容器挂载参数使用模拟验证，尚未启动实际 Claude/Docker 对话验证技能发现。
