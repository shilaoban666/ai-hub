const RUN_STATUS_META = {
  connecting: { phase: 'connecting', label: '提交中', tone: 'info' },
  queued: { phase: 'queued', label: '排队中', tone: 'info' },
  running: { phase: 'running', label: '执行中', tone: 'primary' },
  waiting_permission: { phase: 'waiting_permission', label: '等待确认', tone: 'warning' },
  stopping: { phase: 'stopping', label: '正在停止', tone: 'warning' },
}

export const getAgentRunStatusMeta = phase => RUN_STATUS_META[phase] || null

const RUN_FAILURE_PRESENTATIONS = {
  credits_exhausted: {
    title: '积分已用尽，运行已终止',
    message: '请领取积分或充值后重试，已生成的内容和用量记录已保留。',
    retryLabel: '积分恢复后重试',
  },
  credit_account_unavailable: {
    title: '积分账户不可用，运行已终止',
    message: '请联系管理员检查积分账户状态。',
    retryLabel: '账户恢复后重试',
  },
  model_balance_insufficient: {
    title: '模型服务余额不足',
    message: '请联系管理员充值，或切换其他模型后重试。',
    retryLabel: '余额恢复后重试',
  },
  model_authentication_failed: {
    title: '模型服务认证失败',
    message: '请联系管理员检查模型密钥配置。',
    retryLabel: '配置修复后重试',
  },
  workspace_not_trusted: {
    title: '工作区初始化失败',
    message: '请联系管理员重新初始化运行环境。',
    retryLabel: '重新尝试',
  },
  model_not_supported: {
    title: '当前模型不可用',
    message: '请切换其他模型，或联系管理员检查模型名称。',
    retryLabel: '切换后重试',
  },
  model_rate_limited: {
    title: '模型服务繁忙',
    message: '请求频率已受限，请稍后再试。',
    retryLabel: '稍后重试',
  },
  runtime_timeout: {
    title: '本次执行超时',
    message: '已生成的内容和已记录的用量已保留，可基于当前进度继续。',
    retryLabel: '重新尝试',
  },
  model_request_timeout: {
    title: '模型请求超时',
    message: '模型服务响应超时，已生成的内容和已记录的用量已保留，请稍后重试。',
    retryLabel: '稍后重试',
  },
  model_connection_failed: {
    title: '模型服务连接中断',
    message: '已生成的内容和已记录的用量已保留，请稍后重试。',
    retryLabel: '重新尝试',
  },
}

export const getAgentRunFailurePresentation = (message, errorCode) => {
  const known = RUN_FAILURE_PRESENTATIONS[errorCode]
  if (known) return { ...known }
  return {
    title: '本次运行未完成',
    message: message || '智能体运行失败，请稍后重试。',
    retryLabel: '重新发送',
  }
}

export const getAgentRunErrorDetails = (message, errorCode, metadata) => ({
  source: ({
    upstream: '模型上游',
    model_connection: 'AIHub 到模型上游的连接',
    runtime: 'AIHub 运行环境',
    aihub: 'AIHub',
  })[metadata?.error_origin] || '来源未确认',
  code: errorCode || '无',
  detail: metadata?.error_detail || message || '无',
})

export const applyAgentRunTerminalEvent = (state, event) => {
  if (!state || !event) return false
  if (event.type === 'error') {
    state.phase = 'failed'
    state.failed = true
    state.cancelled = false
    state.error = event.content || '智能体运行失败'
    state.errorCode = event.error_code || 'runtime_error'
    state.errorDetails = getAgentRunErrorDetails(state.error, state.errorCode, event.metadata)
    state.terminalEventReceived = true
    return true
  }
  if (event.type === 'cancelled') {
    state.phase = 'cancelled'
    state.failed = false
    state.cancelled = true
    state.error = ''
    state.errorCode = event.error_code || 'cancelled'
    state.terminalEventReceived = true
    return true
  }
  if (event.type === 'done') {
    state.terminalEventReceived = true
    if (!state.failed && !state.cancelled && state.phase !== 'stopping') {
      state.phase = 'succeeded'
    }
    return true
  }
  return false
}
