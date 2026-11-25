-- 删除 mcp_services 表的 4 个孤儿权限字段
-- 背景：这些列此前手动加到 DB（NOT NULL 无默认值），但从未接入 ORM/API/前端
--   （MCP 级别 RBAC 功能未实现），导致 POST /api/mcps 时 INSERT 缺值报错：
--   "Field 'required_permissions' doesn't have a default value"
-- 核查结论：全仓库无代码读写这些列。iam-service / api-gateway / EndpointList.vue
--   里的 auth_required 属于另一张表 api_endpoint（iam-service 服务发现），与本项目无关。
-- 现有数据均为默认值（'[]' / 1），无实际含义，直接删除，保持 DB schema 与 ORM 一致。
ALTER TABLE mcp_services
  DROP COLUMN required_permissions,
  DROP COLUMN required_roles,
  DROP COLUMN tool_permissions,
  DROP COLUMN auth_required;
