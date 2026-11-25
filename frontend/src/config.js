/**
 * 应用配置 - 从环境变量读取，提供默认值
 */
export const config = {
  apiTimeout: Number(import.meta.env.VITE_API_TIMEOUT) || 10000,
  skillImportTimeout: Number(import.meta.env.VITE_SKILL_IMPORT_TIMEOUT) || 120000,
  resourceDebugTimeout: Number(import.meta.env.VITE_RESOURCE_DEBUG_TIMEOUT) || 30000,
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, ''),
}
