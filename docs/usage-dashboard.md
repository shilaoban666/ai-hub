# 个人与全局用量

“我的用量”和“全局用量”为一级菜单，各自包含“积分用量”和“Token 用量（sub2api）”两个独立页面。头像弹窗提供两个个人用量入口。

- 个人积分：`/admin/dashboard/personal/credit-usage`
- 个人 Token：`/admin/dashboard/personal/token-usage`
- 全局积分：`/admin/dashboard/summary/credit-usage`
- 全局 Token：`/admin/dashboard/summary/token-usage`

旧 Token 地址携带 `?tab=credits` 时自动跳转至对应积分页面。全局页面继续要求超级管理员权限。

## 页面职责

四个路由分别直接加载 PersonalCreditUsage.vue、PersonalTokenUsage.vue、SummaryCreditUsage.vue 和 SummaryTokenUsage.vue，各页面独立管理接口请求、筛选条件、分页和错误状态。
全局积分页负责 IAM 姓名查询、用户筛选与排行；个人积分页只查询当前用户。两个 Token 页面保持仓库原始实现，包括原有标题、筛选、图表和最近请求的前端分页。
没有通用用量页面壳，也不通过 embedded、summaryMode 等模式参数切换业务。

## 数据口径

| 指标 | 数据来源与规则 |
| --- | --- |
| Token 用量 | sub2api `usage_logs`，沿用现有用户匹配与 Token 构成口径 |
| 期间消耗 | `agent_runs.charged_points`，仅计 `settlement_status=settled` 的运行 |
| 消耗归属日期 | 对应 `credit_ledger` 的 `run_settlement` 时间，而非运行开始或结束时间 |
| 当前余额 | `credit_accounts.available_balance`、`reserved_balance`，不随日期筛选变化 |
| 期间领取 | `initial_claim` 与 `daily_claim` 流水，分别展示赠送与每日领取 |
| 管理员调整 | `admin_adjustment` 正负金额分别汇总，不纳入消费或领取 |
| 当前未结算 | 所选用户范围内所有 `reserved`、`pending_reconciliation` 运行数量 |
| 模型消耗 | 使用运行凭证保存的模型 ID，不使用会话当前选择的模型 |

积分保留两位小数，使用已经保存的实际结算值，不按当前模型价格重新计算。
预占与解冻返还不当作消费或收入；失败、取消但已经结算的费用仍计入消耗。
未结算运行的实际消耗返回 `null`，避免显示为免费。用量事件在对账宽限期内仍未补齐时，运行会按已记录用量结算并返还剩余预占积分，缺失部分由平台承担；结算流水会记录 `incomplete_usage`。消费明细中，已结算按结算时间筛选，未结算按发起时间筛选。
待对账运行还提供“强制返还”操作：直接返还该运行的全部预占积分，按 0 积分结算，不再等待或使用未完整的用量记录；该操作通过同一运行结算流水幂等执行。
历史软删除的会话和模型仍保留费用记录。全局排行及明细按 AI Hub 用户 ID 批量查询 IAM 姓名，优先显示姓名、其次显示用户名，账号不可查询时显示用户编号。筛选支持搜索姓名或用户名，后台仍使用 AI Hub 用户 ID，不与 sub2api 用户 ID 混用。

日期按北京时间处理，查询区间为左闭右开；今日、本月截止当前时刻，近 7 天为滚动 7 天，自定义包含结束日期全天。
积分自定义范围最多 366 天。趋势可按小时、日、周汇总，周一为周起点，空时间桶补零。
Token 与积分各自加载，数据源故障互不影响，也不将两者合计。

## 接口

积分前缀为 `/api/dashboard/personal/credit-usage` 和 `/api/dashboard/summary/credit-usage`：

- `GET` 前缀：汇总、趋势、模型 Top 10。参数为 `period`、`start_date`、`end_date`、`granularity`。
- `GET /runs`：消费明细，增加 `status`、`skip`、`limit`。
- `GET /ledger`：收支流水，增加 `entry_type`、`skip`、`limit`。
- `GET /users`：仅全局，返回按消耗排序的用户排行，支持 `skip`、`limit`。

积分明细默认每页 16 条，最大 100 条。全局所有积分接口支持可选 `user_id` 筛选。
个人接口始终限定当前登录用户，显式请求其他用户返回 403。全局沿用现有超级管理员权限；积分没有公开接口。
积分统计为只读查询，不依赖 sub2api，也不要求已经发布积分策略；未开户用户返回零余额和空明细。

Token 页面沿用原有汇总和用户明细接口，以及响应中的最近 20 条请求记录；不增加完整请求分页接口。全局用户明细接口的用户 ID 属于 sub2api，严格要求超级管理员，不能因为其数字与当前 AI Hub 用户 ID 相同而放行。

## 验证

在 backend 目录运行：

```sh
python -m unittest test_credit_dashboard test_dashboard_permissions test_workbench_regressions.FailedBillingTests -v
```

设置环境变量 `AIHUB_TEST_MYSQL=1` 后运行 `test_credit_dashboard`，会额外对当前配置的 MySQL 执行个人与全局的只读集成检查，验证汇总、趋势与明细口径一致，并覆盖 ASCII 和 UTF-8 运行 ID。该检查不会改动账目或表结构。积分表和历史运行表可能使用不同字符集与排序规则，运行 ID 关联在 MySQL 上先转换为 utf8mb4，再显式指定统一排序规则，避免将 utf8mb4 排序规则直接用于 ASCII 字段导致 1253 错误。

启动前端后，在 frontend 目录运行 `npm run test:usage-browser`。
浏览器测试使用独立浏览器与模拟接口，不读取真实账号或账目，覆盖四个独立页面、侧栏与头像入口、旧链接跳转、分页、搜索、全局用户筛选、手机布局和独立错误状态。
默认访问 `http://localhost:15175`，可用 `USAGE_TEST_URL` 覆盖。测试需要 Playwright，可用 `PLAYWRIGHT_MODULE_PATH` 指定已有模块路径；默认使用 Edge，可用 `PLAYWRIGHT_CHANNEL` 覆盖。
截图保存于 `frontend/node_modules/.cache/usage-browser/`。
