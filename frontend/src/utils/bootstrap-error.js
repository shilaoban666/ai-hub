const text = value => typeof value === 'string' ? value.trim() : ''

export function bootstrapFailure(error) {
  const body = error?.response?.data
  const detail = body?.detail
  const code = detail?.data?.code || body?.data?.code
  const settings = {
    ASSISTANT_SETTINGS_NOT_PUBLISHED: { path: '/admin/assistant-settings', label: '智能体设置' },
    WORKBENCH_SETTINGS_NOT_PUBLISHED: { path: '/admin/workbench-settings', label: '默认助手设置' },
    DEFAULT_MODEL_UNAVAILABLE: { path: '/admin/workbench-settings', label: '默认助手设置' },
  }[code] || null

  if (['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code)) {
    return { message: '工作台初始化超时，请检查网络后重试；服务端可能仍在准备工作区。', settings: null }
  }
  if (error?.code === 'ERR_NETWORK') {
    return { message: '无法连接 AI Hub 服务，请检查网络和本地服务是否已启动后重试。', settings: null }
  }
  const message = code === 'ASSISTANT_SETTINGS_NOT_PUBLISHED'
    ? '管理员尚未发布全局智能体设置'
    : text(detail) || text(detail?.message) || text(body?.message)
      || text(error?.friendlyMessage) || text(error?.message) || '工作台初始化失败，请稍后重试。'
  return { message, settings }
}
