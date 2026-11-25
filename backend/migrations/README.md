# AI Hub 上线迁移统一入口

## 062：技能共用环境变量

已完成 061 的数据库在部署前执行 `python backend/migrations/run_upgrade.py --from 062 --apply`。
该迁移幂等新增 `platform_global_settings.runtime_environment` JSON 字段，不预置任何密钥。
管理员在「系统管理 → 全局设置 → 技能环境变量」中保存配置，所有用户下一次运行时自动读取，
修改和删除无需重启。用法见 [运行时配置说明](../../docs/agent-runtime-configuration.md#技能共用环境变量)。

升级范围：**`master` → 当前 `feature/1014` 的全部差异**，核对日期 2026-10-16。已通过 `git ls-remote origin refs/heads/master` 核实远端 master，与本地 master 均为 `b663a72d7e2800292ecd286715bb80263e330f6b`。

按 `git diff master` 核对整个 backend/docs 中的 SQL、迁移脚本及模型差异，完整增量为 **044～059：10 个 SQL + 6 个 Python 脚本**。本入口包含从 master 分出后各阶段累计的迁移。001～043 属于 master 已有结构，不作为本次新增迁移重复执行。

只使用 [run_upgrade.py](run_upgrade.py) 执行。SQL/Python 仍调用本目录原文件，避免维护多份副本。旧 `run_feature_0928.py` 保留为兼容入口，调用相同实现。

## 今天上线的执行顺序

命令均在**仓库根目录**执行，`python` 使用后端服务相同的环境，先安装本版本 `backend/requirements.txt`。入口自动定位 `backend` 并读取服务配置：根 `.env`，环境变量按现有 Settings 规则覆盖。目标必须是 `mysql+pymysql`。

1. 将完整版本代码和迁移目录放到目标机器，先不要启动新 API/worker。
2. 预览清单；可用只读检查确认目标库是否已经完成升级。

   ```bash
   # 离线预览：不读数据库配置、不连接数据库；列出文件顺序和摘要
   python backend/migrations/run_upgrade.py

   # 只读检查目标库：升级前缺少新增结构会返回 1，属于预期
   python backend/migrations/run_upgrade.py --check
   ```

3. 停止接收新任务，等待运行任务结束；停止所有实例的 API、渠道 Worker，并停用旧部署的独立运行时 Worker；备份数据库以及工作区/发布包目录。使用 `aihub.sh` 部署时可执行 `./aihub.sh stop`，其他部署方式由现有平台停服务。保留旧代码和原有加密密钥配置，备份不要放在公开静态目录。
4. 执行全部 SQL 和数据脚本。入口先检查基线必需表/字段，缺失时在写入前停止；成功执行后自动做结构与回填验收。

   ```bash
   python backend/migrations/run_upgrade.py --apply
   ```

5. 必须看到 `Complete: all selected migrations applied and upgrade checks passed.` 且退出码为 0，再启动**同一版本**的 API 和 Worker。也可以独立复核：

   ```bash
   python backend/migrations/run_upgrade.py --check
   ```

若本次 `--check` 已通过，说明本清单覆盖的结构与回填已到位，无需因分支名称变化重新执行迁移。检查只覆盖此增量的字段存在性、关键索引/生成列和回填结果，不代表所有字段类型、生产网络、备份恢复或业务行为均已验收。

## 完整 SQL + Python 顺序

| 顺序 | 文件 | 用途 |
| --- | --- | --- |
| 044 | [044_expert_agent_prompt_modules.sql](044_expert_agent_prompt_modules.sql) | 创建智能体提示词模块绑定表。 |
| 045 | [045_agent_scoped_workspaces.sql](045_agent_scoped_workspaces.sql) | 工作区、运行单元增加智能体范围；移除旧用户单列唯一约束。 |
| 046 | [046_agent_workspace_uniqueness.sql](046_agent_workspace_uniqueness.sql) | 增加用户/智能体唯一约束与默认助手范围生成列、唯一约束。 |
| 047 | [047_workspace_scope_keys.sql](047_workspace_scope_keys.sql) | 补齐早期 046 版本缺少的默认助手范围约束；仍按顺序执行。 |
| 048 | [048_agent_mcp_binding_status.sql](048_agent_mcp_binding_status.sql) | 智能体 MCP 绑定增加并回填独立状态。 |
| 049 | [049_agent_asset_scopes.py](049_agent_asset_scopes.py) | 技能安装、MCP、凭据增加智能体范围，复制并隔离旧绑定，按需创建工作区记录。 |
| 050 | [050_assistant_reasoning_settings.sql](050_assistant_reasoning_settings.sql) | 默认助手策略增加思考等级与推理显示设置。 |
| 051 | [051_agent_prompt_snapshots.py](051_agent_prompt_snapshots.py) | 历史结构兼容：增加快照列与用户执行互斥表、回填旧数据；当前运行时统一读取作者模板，不再使用快照。 |
| 052 | [052_split_workbench_settings.py](052_split_workbench_settings.py) | 创建默认助手设置表，复制旧设置；重复执行不覆盖已拆分配置。 |
| 053 | [053_web_run_hardening.sql](053_web_run_hardening.sql) | 增加 Web 运行幂等字段和用户排队查询索引。 |
| 054 | [054_workspace_prompt_references.py](054_workspace_prompt_references.py) | 将未修改的工作台提示词副本迁移为作者模板引用，保留已编辑副本。 |
| 055 | [055_expert_prompt_references.py](055_expert_prompt_references.py) | 将专家绑定的未编辑历史副本改为作者模板引用；合并重复绑定并保留顺序，兼容已执行旧版 054 的数据库。 |

| 056 | [056_claude_runtime.py](056_claude_runtime.py) | 将旧运行时智能体、策略和会话切换至 Claude；使用空工作区，不导入旧文件，重置恢复标识并保留消息、资产和历史运行审计。 |
| 057 | [057_noun_highlight.sql](057_noun_highlight.sql) | 默认助手设置和自定义智能体增加名词解释高亮开关（默认开启）及跳转地址；重复执行保留已保存配置。 |
| 058 | [058_skill_conversation_examples.sql](058_skill_conversation_examples.sql) | 技能增加对话示例 JSON 字段；历史记录无示例，重复执行保留配置。示例独立于 SKILL.md 和发布包，保存后在技能市场即时展示。 |
| 059 | [059_realtime_model_billing.sql](059_realtime_model_billing.sql) | 创建模型网关请求进度表，支持并发模型请求按累计 Token 实时扣费、恢复和幂等结算。 |
| 060 | [060_skill_development_mode.sql](060_skill_development_mode.sql) | 技能开发模式和工作区安装版本支持。 |
| 061 | [061_feedback_processing_details.sql](061_feedback_processing_details.sql) | 反馈处理说明和图片字段。 |
| 062 | [062_global_runtime_environment.sql](062_global_runtime_environment.sql) | 管理员共享运行环境配置。 |
| 063 | [063_agent_open_calls.sql](063_agent_open_calls.sql) | 自定义智能体开放调用密钥摘要、资源范围和持久化任务输入；只新增两张表，可重复执行。 |
| 063 | [063_knowledge_base.sql](063_knowledge_base.sql) | 创建知识库配置、钉钉绑定、上传与调用记录表，并补齐相应字段。 |

`--from 063` 按表中顺序执行两个 063 文件；两者均可重复执行。

**不能只合并执行 SQL：049、051、052 的数据处理必须运行。** 不要直接运行 `main.py`，也不要依靠 `metadata.create_all()` 给旧表补字段。所有迁移执行失败即停止；SQL 的会话变量、PREPARE 和多结果集由统一入口处理。

## 中断后的续跑与回退

入口会打印失败步骤，例如 049 失败：

```bash
python backend/migrations/run_upgrade.py --from 049
# 查清失败原因及已生效结构，保持服务停止，再续跑
python backend/migrations/run_upgrade.py --from 049 --apply
```

`--from` 包含该步骤，并一直执行到 059；不自动推断进度。已完成 053 的数据库从 `--from 054 --apply` 升级；已完成 054 的数据库从 `--from 055 --apply` 升级。已完成 055 的数据库从 `--from 056 --apply` 升级。已完成 056 的数据库执行 `python backend/migrations/run_upgrade.py --from 057 --apply`。已完成 057 的数据库执行 `python backend/migrations/run_upgrade.py --from 058 --apply`。已完成 058 的数据库执行 `python backend/migrations/run_upgrade.py --from 059 --apply`。全部迁移已完成但最终检查未通过时，按报告定位未完成的结构或回填，不能仅因最后一条 SQL 成功就启动服务。错误日志只输出步骤、对象名、数量和异常类型，避免泄露连接串、密钥或业务数据。

名词列表使用 IAM 新增认证接口 `GET /iam/api/noun-explanations/names`，返回 `{"items": ["名词名称"]}`。需配套部署 iam-service；通过现有 IAM 接口发现/路由同步流程注册新 GET 路由后再联调网关。该接口只查询名称，包含 `e_noun_check_status IN (1, 2)` 的全部名词，不分页、不返回解释正文。前端五分钟内复用名词列表。跳转地址默认使用 `https://online.fancyqube.net/Project/admin/skuapp/t_noun_explanation/?exact=1&noun_name=`，默认值定义在代码中，不使用 `.env`；默认助手和自定义智能体设置的输入框直接显示默认值，也可自行修改，跳转地址为配置的链接加命中的名词文本（名词进行 URL 编码），不自动添加参数名；例如配置 `https://example.com/?name=`，命中后得到 `https://example.com/?name=名词文本`。

MySQL DDL 隐式提交，整个升级不是单个原子事务；Python 回填各自使用事务。重跑会保留已经隔离的技能/MCP、提示词原始内容及拆分后的设置，但执行前仍须核实库的当前状态。若必须回退，应停服务，恢复配套数据库/文件备份和旧代码；不要只回滚代码或直接删除新增字段，因为旧资源绑定可能已改写。

## 自动验收范围

- 检查本次涉及表的预期字段；检查范围唯一索引和 Web 幂等/队列索引的名称、列顺序及唯一性。
- 检查工作区的 `scope_agent_id` 是持久化 `COALESCE(agent_id, 0)` 生成列，旧唯一约束不再阻止多个智能体独立安装。
- 检查技能/MCP 绑定已指向对应智能体范围，旧助手设置已在需要时复制到新表。提示词绑定允许空快照，统一从作者模板实时读取；作者取消公开或删除后不再供其他用户使用。
- `--check` 只执行元数据读取和 SELECT，不导入 FastAPI 应用，不自动建表、回填或修复。

启动后仍需走一遍：默认助手对话、自定义 Agent 对话、切换新建对话、公开智能体只读使用、技能/提示词/MCP 配置隔离；渠道已启用时补一条真实收发验收。

本轮发布包安全修复还有一项部署要求：`/releases/*` 必须代理到后端受控路由，不能由静态 alias 或共享缓存绕过权限；如曾缓存旧包，切换时清理共享缓存。详见 [生产部署说明](../../docs/production-deployment.md)。

## 基线与历史迁移

本入口用于**已有数据库增量升级**，目标库应已具备基线结构（至 043，包含 `043_agent_run_events.sql` 和 `043_feedback_processing.sql`）。不适用于空库，也不自动补齐更早迁移。

- [旧 master → 工作台 SQL 汇总](../../docs/sql/upgrade_master_to_ai_workbench.sql) 仅覆盖旧基线 `de8a590` 的 025～034（含两个 028）。
- [旧工作台中断续跑 SQL](../../docs/sql/resume_ai_workbench_from_workspace_run_views.sql) 仅用于该历史汇总的特定中断位置。
- `_migrate_agent_credentials.py` 等历史脚本不是本分支新增迁移，不应今天无条件重跑。
- 本入口不搬迁真实工作区文件，也不轮换任何加密密钥。

本地执行控制测试与隔离 MySQL 演练不等于生产库已迁移。今天实际执行以目标机器的命令退出码和验收结果为准。

## 本次验证记录（2026-10-16）

- 执行控制和只读检查的 15 项单元测试通过，覆盖离线预览、SQL 多结果集、SQL/Python 顺序、失败停止、脱敏错误、续跑、旧入口及缺失结构检测。
- 在临时目录启动独立的 MySQL 9.7.0 实例，以 `b663a72` 的实际 ORM 创建旧结构并放入测试绑定和设置：升级前检查返回未就绪；044～053 全量执行通过；再次全量执行、从 049 续跑以及最终 `--check` 均通过。
- 检查了旧技能/MCP 绑定隔离、MCP 禁用状态保留、提示词冻结，以及重跑不覆盖修改后的助手设置、MCP 认证设置，也不重复创建安装记录或工作区。
- MySQL 演练使用本地临时实例和虚构数据，未连接服务配置指向的数据库；这不代替目标 MySQL 版本与实际数据的上线验收。
