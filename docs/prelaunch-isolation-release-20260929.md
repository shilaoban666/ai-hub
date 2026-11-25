# 提示词隔离、运行并发与首次积分修复

## 本次行为

- 智能体安装提示词时，在关联记录中保存名称、正文、变量等独立快照。详情、运行和副本均读取快照；安装不会往 AI 工作台个人提示词列表新增记录。原模板修改、删除或改为私有不会修改既有快照；移除后重新安装才取当前版本。主提示词继续独立保存在 Agent 上。
- 旧绑定由迁移时的可用模板内容补快照，无法还原安装当时未记录的历史内容。迁移前已经删除的模板此前就不参与运行，迁移清除这类未生成快照的失效绑定，不会重新启用它们。重复迁移不覆盖已有快照。
- 共享入口继续保持现状。后端保留私有资源校验，且不能通过将原模板改公开来暴露此前安装的私有快照；需重新安装公开版本。源资源撤回后阻止继续公开分发，已安装者仍可使用本地快照。
- 发布设置中的 `max_concurrent_runs` 现在由数据库用户级互斥记录和工作区租约共同执行，工作台、自定义 Agent、网页及渠道共用。超过上限排队；同一工作区仍串行。自定义模型也受运行并发限制。
- 并发名额随租约续期，正常结束、失败和取消会释放，进程失联后到期回收。降低上限不强制中断正在执行的任务，只限制后续进入。进入聊天时的技能文件同步也使用同一租约，会短暂占用名额；忙时延后同步。
- 首次积分可从余额查询、每日领取、工作台初始化、平台模型直接运行入口触发。业务唯一键及账户锁防止重复发放、丢失余额更新；没有发布策略时不会凭空创建补贴规则。
- 自定义模型保持不检查、不预占、不扣平台积分；自身模型权限和启用状态仍校验。禁用积分账户或平台余额不足不会改变自定义模型的这条规则。
- 修正配置保存的提前提交：创建、修改、复制智能体时，工作区准备失败会回滚数据库配置及提示词绑定，不再返回失败却已保存部分配置。文件系统操作与数据库并非跨系统原子事务，运行前仍会重建有效配置。

## 部署步骤

当前仅修改本地代码，未连接业务数据库执行迁移、未部署。

1. 备份数据库，确认已完成到 043 的基线迁移。停止 API 和渠道执行进程，并排空运行任务，避免旧版本继续写入无快照绑定。
2. 使用与服务一致的环境和 `.env`，从仓库根目录执行统一入口：

   ```bash
   python backend/migrations/run_feature_0928.py --apply
   ```

3. 入口按 044～053 顺序执行全部 SQL 和数据脚本，包含提示词快照、工作台设置拆分和 Web 运行幂等字段。MySQL DDL 不可整体回滚；数据回填使用事务，失败后保持服务停止，修正原因后使用 `--from` 从失败步骤重跑。没有 `--apply` 只显示顺序，不连接数据库。
4. 用以下只读查询确认无遗漏，再启动所有新版本 API/worker；不要混跑新旧版本。

   ```sql
   SELECT COUNT(*) AS missing_prompt_snapshots
   FROM agent_prompt_templates WHERE snapshot_json IS NULL;
   SHOW TABLES LIKE 'user_execution_gates';
   SHOW TABLES LIKE 'workbench_settings';
   SHOW COLUMNS FROM agent_runs
     WHERE Field IN ('idempotency_key', 'idempotency_fingerprint');
   SHOW INDEX FROM agent_runs
     WHERE Key_name IN ('ix_agent_runs_queue_admission', 'uq_agent_runs_user_idempotency');
   ```

   第一个结果应为 0；其余查询应能找到相应表、字段和索引。`user_execution_gates` 为空是正常的，用户首次争抢运行名额时才插入记录。

5. 环境验收：首次从智能体入口运行平台模型得到初始积分；同用户工作台与智能体/渠道同时运行符合上限；源提示词改动不改变已装版本；零积分自定义模型正常；取消后后续任务可进入。

回退代码前也要停服务并排空任务。旧版本会重新读取活模板且绕过用户级并发限制，因此不具备本次隔离承诺；不要删除新快照列。若曾恢复旧版本并产生新绑定，重新上线时使用统一入口从 051 重新执行以补齐快照并复核后续字段：`python backend/migrations/run_feature_0928.py --from 051 --apply`。

## 验证记录与边界

- 16 个相关后端测试模块合计运行 131 项：127 通过、4 跳过。覆盖提示词导入/删除/复制/运行读取、失败保存回滚、模型权限与自定义模型免平台计费、积分初始化、租约等待/取消/隔离及渠道处理。
- 4 个跳过项：1 项当前 Python 缺少 fakeredis，另 3 项原有报表测试未配置其专用 MySQL 环境。路由测试隔离了 Redis 可用性探测；SQLite 测试将 BIGINT 编译为 INTEGER 以支持自增。没有将这些单元测试视为部署环境流式验证。
- `test_prelaunch_mysql.py` 在独立临时 MySQL 9.7 数据库通过：旧结构迁移、回填回滚与重复执行；失败保存回滚；8 个并发请求争抢上限 1/2；不同用户独立；租约续期、过期接管和旧持有者隔离；8 个并发首次/每日领取；已有账户的并发余额更新保留。未触碰业务库。
- 扩展检查发现仓库原有 `test_agent_workspace_settings.test_mcp_settings_enable_project_servers` 与当前权限生成行为不一致（仍要求全局 `mcp__*` 通配授权；继续检查时，无效连接器名的预授权断言也不一致）。该测试未纳入上面的通过数量，本次没有顺带修改 MCP 权限策略；完整测试集不能宣称全绿。
- 新增用例可用 `python -m unittest test_prelaunch_isolation test_resource_duplicates test_assistant_reasoning_settings test_chat_loading` 运行。真实 MySQL 用例须显式设置 `AIHUB_TEST_MYSQL_URL`，数据库名以 `test_aihub_prelaunch_` 开头且必须为空，然后运行 `python -m unittest test_prelaunch_mysql`；测试不会删除数据库。
- 没有进行生产数据库迁移、真实模型请求、渠道机器人端到端或前端浏览器验收。本次未改前端。

性能问题另见 [对话性能优化方案](chat-performance-proposal-20260929.md)，尚未实施。
